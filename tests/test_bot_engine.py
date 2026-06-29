# ============================================================
# tests/test_bot_engine.py — Trading Bot Trading Bot
#
# AMAÇ:
#   BotEngine (Orkestratör) ve CandleScheduler için pytest testleri.
#   Gerçek ağ çağrıları ve API bağlantıları mock ile taklit edilir.
#
# ÇALIŞTIRMA:
#   pytest tests/test_bot_engine.py -v
# ============================================================

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from src.bot.scheduler import CandleScheduler, TIMEFRAME_SECONDS
from src.bot.engine import BotEngine
from src.config.settings import get_settings
from src.data.models import DataFetchResult, OHLCVCandle, OHLCVSeries


# ─── CandleScheduler Testleri ─────────────────────────────────

class TestCandleScheduler:
    """CandleScheduler sınıfının işlevlerini test eder."""

    def test_init_and_timeframe_validation(self):
        """Scheduler doğru şekilde başlatılmalı ve bilinmeyen timeframe uyarılmalıdır."""
        scheduler = CandleScheduler(["4h", "1d", "invalid_tf"])
        assert "4h" in scheduler.timeframes
        assert "1d" in scheduler.timeframes
        assert "invalid_tf" in scheduler.timeframes

    def test_is_due_initial_state(self):
        """Hiç veri çekilmemişken is_due True dönmeli."""
        scheduler = CandleScheduler(["4h", "1d"])
        assert scheduler.is_due("4h") is True
        assert scheduler.is_due("1d") is True

    def test_mark_fetched_and_due_logic(self):
        """mark_fetched çağrısından sonra bekleme süresi dolana kadar is_due False dönmeli."""
        scheduler = CandleScheduler(["1m"])
        
        # İlk durumda due olmalı
        assert scheduler.is_due("1m") is True
        
        # Mark et
        scheduler.mark_fetched("1m")
        
        # Şimdi due olmamalı (çünkü son çekim 0 saniye önceydi, interval 60 saniye)
        assert scheduler.is_due("1m") is False
        
        # Geri kalan saniyeyi sorgula
        secs = scheduler.seconds_until_next_candle("1m")
        assert 0.0 < secs <= 60.0

    def test_get_due_timeframes(self):
        """Due olan timeframe listesini döner."""
        scheduler = CandleScheduler(["4h", "1d"])
        assert set(scheduler.get_due_timeframes()) == {"4h", "1d"}
        
        scheduler.mark_fetched("4h")
        assert scheduler.get_due_timeframes() == ["1d"]

    def test_next_candle_time(self):
        """Sonraki mum zamanını UTC olarak döndürür."""
        scheduler = CandleScheduler(["4h"])
        
        # Çekilmemiş durum
        t_before = time.time()
        next_time = scheduler.next_candle_time("4h")
        assert next_time is not None
        assert next_time.tzinfo == timezone.utc
        assert next_time.timestamp() >= t_before + 14400 - 5.0

    def test_status_report(self):
        """status_report hata fırlatmadan bir string rapor döndürmeli."""
        scheduler = CandleScheduler(["4h", "1d"])
        report = scheduler.status_report()
        assert isinstance(report, str)
        assert "4h" in report
        assert "1d" in report


# ─── BotEngine Entegrasyon Testleri ───────────────────────────

@pytest.fixture
def large_ohlcv_series() -> OHLCVSeries:
    """TechnicalEngine için yeterli sayıda (min_bars ~ 210) mum içeren mock OHLCVSeries."""
    base_ts = 1_700_000_000_000
    candles = [
        OHLCVCandle(
            timestamp=base_ts + i * 14400000,
            open=30000.0 + i * 10,
            high=30100.0 + i * 10,
            low=29900.0 + i * 10,
            close=30050.0 + i * 10,
            volume=100.0 + (i % 5) * 10,
        )
        for i in range(220)  # Min bars 205'ten büyük
    ]
    return OHLCVSeries(symbol="BTC/USDT", timeframe="4h", candles=candles)


class TestBotEngine:
    """BotEngine entegrasyon ve akış testleri (Mock veriyle)."""

    @patch("src.bot.engine.DataCollector")
    def test_bot_engine_initialization(self, mock_collector_class):
        """BotEngine doğru bileşenlerle başlatılabilmeli."""
        cfg = get_settings()
        bot = BotEngine(settings=cfg, is_paper_trade=True)
        
        assert bot.is_paper_trade is True
        assert bot.collector is not None
        assert bot.technical_engine is not None
        assert bot.signal_generator is not None
        assert bot.journal is not None
        assert bot.scheduler is not None

    @patch("src.bot.engine.DataCollector")
    def test_single_run_failure_on_connect(self, mock_collector_class):
        """Borsaya bağlanılamadığında run() erken çıkmalı."""
        mock_collector = MagicMock()
        mock_collector.connect.return_value = False
        mock_collector_class.return_value = mock_collector

        bot = BotEngine()
        bot.run(single_run=True)

        mock_collector.connect.assert_called_once()
        mock_collector.validate_symbol.assert_not_called()

    @patch("src.bot.engine.DataCollector")
    def test_single_run_failure_on_symbol_validation(self, mock_collector_class):
        """Sembol geçersiz olduğunda run() erken çıkmalı."""
        mock_collector = MagicMock()
        mock_collector.connect.return_value = True
        mock_collector.validate_symbol.return_value = False
        mock_collector_class.return_value = mock_collector

        bot = BotEngine()
        bot.run(single_run=True)

        mock_collector.connect.assert_called_once()
        mock_collector.validate_symbol.assert_called_once()
        mock_collector.disconnect.assert_called_once()

    @patch("src.bot.engine.DataCollector")
    @patch("src.bot.engine.SignalJournal")
    def test_single_run_success_flow(self, mock_journal_class, mock_collector_class, large_ohlcv_series, tmp_path):
        """Başarılı bir single_run veri akışı, indikatör, sinyal ve günlük kaydı adımlarını tamamlamalı."""
        mock_collector = MagicMock()
        mock_collector.connect.return_value = True
        mock_collector.validate_symbol.return_value = True
        
        # Fetch metodunun başarılı sonuç dönmesini sağla
        mock_fetch_result = DataFetchResult(
            success=True,
            symbol="BTC/USDT",
            timeframe="4h",
            data=large_ohlcv_series
        )
        mock_collector.fetch.return_value = mock_fetch_result
        
        # to_dataframe dönüştürücüsünü taklit et
        # Fixture verilerini DataFrame yapalım
        candles_dict = [c.model_dump() for c in large_ohlcv_series.candles]
        df = pd.DataFrame(candles_dict)
        mock_collector.to_dataframe.return_value = df
        
        mock_collector_class.return_value = mock_collector

        # Journal mockla
        mock_journal = MagicMock()
        mock_journal_class.return_value = mock_journal

        # BotEngine'i kur ve çalıştır
        cfg = get_settings()
        original_log_dir = cfg.logging.log_dir
        original_strategy_version = cfg.strategy.version
        cfg.logging.log_dir = str(tmp_path)
        cfg.strategy.version = "v1"
        cfg.data.timeframes = ["4h"]  # Testi hızlandırmak için tek timeframe
        
        try:
            bot = BotEngine(settings=cfg)
            bot.journal = mock_journal  # Mock journal'ı enjekte et
            
            bot.run(single_run=True)

            # Doğrulamalar
            mock_collector.connect.assert_called_once()
            mock_collector.validate_symbol.assert_called_once_with("BTC/USDT")
            mock_collector.fetch.assert_called_once_with(symbol="BTC/USDT", timeframe="4h", limit=cfg.data.limit)
            mock_collector.to_dataframe.assert_called_once_with(large_ohlcv_series)
            
            # Sinyal journal'a kaydedildi mi?
            mock_journal.record.assert_called_once()
            # Kaydedilen sinyal TradeSignal nesnesi olmalı
            recorded_signal = mock_journal.record.call_args[0][0]
            assert recorded_signal.symbol == "BTC/USDT"
            assert recorded_signal.timeframe == "4h"
            
            # Bağlantı kesildi mi?
            mock_collector.disconnect.assert_called_once()
        finally:
            cfg.logging.log_dir = original_log_dir
            cfg.strategy.version = original_strategy_version



# TDD Test: Cache Clearing

def test_run_single_scan_clears_cache():
    from live_v6mr import LiveV6MRBot
    from unittest.mock import MagicMock, patch
    bot = LiveV6MRBot()
    bot.fetcher = MagicMock()
    bot.fetcher.fetch_top_symbols.return_value = []
    bot.run_single_scan()
    bot.fetcher.clear_cache.assert_called_once()
