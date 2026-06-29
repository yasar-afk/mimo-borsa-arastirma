# ============================================================
# tests/test_collector.py — Trading Bot Trading Bot
# Amaç : DataCollector ve OHLCVValidator için pytest birim testleri.
#         Her kritik fonksiyon; gerçek API çağrısı YAPMADAN
#         mock ile test edilir (hızlı, deterministic, güvenli).
# Tarih: 2026-06-03
#
# ÇALIŞTIRMA:
#   pip install pytest pytest-mock
#   pytest tests/ -v
#   pytest tests/ -v --tb=short    (kısa hata çıktısı)
#
# MİMARİ NOT:
#   Mock kullanan testler gerçek Binance'a bağlanmaz → CI/CD'de
#   API key gerektirmez. Entegrasyon testi için ayrı test dosyası
#   açılacak (tests/integration/).
# ============================================================

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.collector import DataCollector, _CacheEntry
from src.data.models import (
    DataFetchResult,
    DataSource,
    OHLCVCandle,
    OHLCVSeries,
)
from src.data.validator import OHLCVValidator, ValidationResult


# ─── Ortak Fixtures ──────────────────────────────────────────

@pytest.fixture
def sample_raw_ohlcv() -> list:
    """CCXT'nin döndürdüğü formatında örnek ham veri."""
    base_ts = 1_700_000_000_000  # Örnek timestamp (ms)
    return [
        [base_ts + i * 14400000, 30000 + i, 31000 + i, 29000 + i, 30500 + i, 100 + i]
        for i in range(10)
    ]


@pytest.fixture
def sample_dataframe(sample_raw_ohlcv) -> pd.DataFrame:
    """Örnek OHLCV DataFrame."""
    return DataCollector._raw_to_dataframe(sample_raw_ohlcv)


@pytest.fixture
def sample_series() -> OHLCVSeries:
    """Test için örnek OHLCVSeries nesnesi."""
    candles = [
        OHLCVCandle(
            timestamp=1_700_000_000_000 + i * 14400000,
            open=30000.0 + i,
            high=31000.0 + i,
            low=29000.0 + i,
            close=30500.0 + i,
            volume=100.0 + i,
        )
        for i in range(5)
    ]
    return OHLCVSeries(symbol="BTC/USDT", timeframe="4h", candles=candles)


@pytest.fixture
def collector() -> DataCollector:
    """Paper trade modunda DataCollector nesnesi."""
    return DataCollector(is_paper_trade=True)


# ─── OHLCVCandle Testleri ────────────────────────────────────

class TestOHLCVCandle:
    """OHLCVCandle model doğrulama testleri."""

    def test_valid_candle_creation(self):
        """Geçerli verilerle mum oluşturulabilmeli."""
        candle = OHLCVCandle(
            timestamp=1_700_000_000_000,
            open=30000.0,
            high=31000.0,
            low=29000.0,
            close=30500.0,
            volume=100.0,
        )
        assert candle.open == 30000.0
        assert candle.is_bullish is True  # close > open
        assert candle.body_size == 500.0  # |30500 - 30000|
        assert candle.range_size == 2000.0  # 31000 - 29000

    def test_bearish_candle(self):
        """Düşüşçü mum doğru algılanmalı."""
        candle = OHLCVCandle(
            timestamp=1_700_000_000_000,
            open=31000.0,
            high=31500.0,
            low=29000.0,
            close=29500.0,
            volume=200.0,
        )
        assert candle.is_bullish is False

    def test_invalid_high_less_than_low(self):
        """high < low ise hata fırlatmalı."""
        with pytest.raises(Exception):
            OHLCVCandle(
                timestamp=1_700_000_000_000,
                open=30000.0,
                high=28000.0,   # high < low → GEÇERSİZ
                low=29000.0,
                close=30000.0,
                volume=100.0,
            )

    def test_zero_price_rejected(self):
        """Sıfır fiyat reddedilmeli."""
        with pytest.raises(Exception):
            OHLCVCandle(
                timestamp=1_700_000_000_000,
                open=0.0,       # Geçersiz
                high=1000.0,
                low=0.0,
                close=500.0,
                volume=100.0,
            )


# ─── OHLCVSeries Testleri ────────────────────────────────────

class TestOHLCVSeries:
    """OHLCVSeries koleksiyon testleri."""

    def test_latest_candle(self, sample_series):
        """En son mum doğru döndürülmeli."""
        latest = sample_series.latest_candle
        assert latest is not None
        assert latest.close == 30504.0  # 30500 + 4

    def test_empty_series(self):
        """Boş seri için latest_candle None döndürmeli."""
        empty = OHLCVSeries(symbol="ETH/USDT", timeframe="1d", candles=[])
        assert empty.latest_candle is None
        assert empty.latest_close is None
        assert empty.candle_count == 0


# ─── OHLCVValidator Testleri ─────────────────────────────────

class TestOHLCVValidator:
    """Veri doğrulayıcı testleri."""

    @pytest.fixture
    def validator(self):
        return OHLCVValidator(
            max_missing_candles=5,
            min_volume_threshold=0.0,
            price_spike_factor=0.10,
        )

    def test_valid_dataframe_passes(self, validator, sample_dataframe):
        """Geçerli DataFrame doğrulamadan geçmeli."""
        cleaned, result = validator.validate(sample_dataframe, "BTC/USDT", "4h")
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_empty_dataframe_fails(self, validator):
        """Boş DataFrame doğrulamayı geçememeli."""
        empty_df = pd.DataFrame()
        _, result = validator.validate(empty_df, "BTC/USDT", "4h")
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_missing_column_fails(self, validator):
        """Eksik sütun doğrulamayı geçememeli."""
        bad_df = pd.DataFrame({
            "timestamp": [1_700_000_000_000],
            "open": [30000.0],
            "high": [31000.0],
            # "low" eksik!
            "close": [30500.0],
            "volume": [100.0],
        })
        _, result = validator.validate(bad_df, "BTC/USDT", "4h")
        assert result.is_valid is False

    def test_nan_values_within_limit_filled(self, validator, sample_dataframe):
        """Limit dahilindeki NaN değerler forward-fill ile doldurulmalı."""
        sample_dataframe.loc[sample_dataframe.index[2], "close"] = float("nan")
        cleaned, result = validator.validate(sample_dataframe, "BTC/USDT", "4h")
        # Uyarı olmalı ama hata değil
        assert result.is_valid is True
        assert any("NaN" in w for w in result.warnings)
        assert cleaned["close"].isna().sum() == 0

    def test_price_spike_detected(self, validator):
        """%50 fiyat sıçraması uyarı üretmeli."""
        data = {
            "timestamp": [1_700_000_000_000 + i * 14400000 for i in range(5)],
            "open":  [30000.0, 30100.0, 45000.0, 30300.0, 30400.0],  # %50 sıçrama
            "high":  [31000.0, 31100.0, 46000.0, 31300.0, 31400.0],
            "low":   [29000.0, 29100.0, 44000.0, 29300.0, 29400.0],
            "close": [30500.0, 30600.0, 45500.0, 30700.0, 30800.0],
            "volume":[100.0, 110.0, 120.0, 130.0, 140.0],
        }
        df = pd.DataFrame(data)
        _, result = validator.validate(df, "BTC/USDT", "4h")
        assert any("sıçrama" in w for w in result.warnings)

    def test_duplicate_timestamps_removed(self, validator):
        """Tekrarlayan timestamp'ler temizlenmeli."""
        ts = 1_700_000_000_000
        data = {
            "timestamp": [ts, ts, ts + 14400000],  # İlk ikisi aynı!
            "open":  [30000.0, 30000.0, 30100.0],
            "high":  [31000.0, 31000.0, 31100.0],
            "low":   [29000.0, 29000.0, 29100.0],
            "close": [30500.0, 30500.0, 30600.0],
            "volume":[100.0, 100.0, 110.0],
        }
        df = pd.DataFrame(data)
        cleaned, result = validator.validate(df, "BTC/USDT", "4h")
        assert len(cleaned) == 2  # Tekrar eden kaldırılmalı


# ─── DataCollector Testleri ──────────────────────────────────

class TestDataCollector:
    """DataCollector işlevsellik testleri."""

    def test_initialization(self, collector):
        """DataCollector doğru başlamalı."""
        assert collector.is_paper_trade is True
        assert collector.is_connected is False
        assert collector.exchange is None

    def test_fetch_without_connection_fails(self, collector):
        """Bağlantı olmadan fetch başarısız olmalı."""
        result = collector.fetch("BTC/USDT", "4h")
        assert result.success is False
        assert "bağlantı" in result.error_message.lower()

    def test_raw_to_dataframe_conversion(self, sample_raw_ohlcv):
        """Ham CCXT verisi doğru DataFrame'e dönüşmeli."""
        df = DataCollector._raw_to_dataframe(sample_raw_ohlcv)
        assert len(df) == 10
        assert "open" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_to_dataframe_from_series(self, collector, sample_series):
        """OHLCVSeries DataFrame'e doğru dönüşmeli."""
        df = collector.to_dataframe(sample_series)
        assert len(df) == 5
        assert "close" in df.columns
        assert df["close"].iloc[0] == 30500.0

    def test_cache_set_and_get(self, collector, sample_series):
        """Önbellek yazma ve okuma çalışmalı."""
        from src.data.collector import _CacheEntry
        key = "BTC/USDT:4h"
        collector._cache[key] = _CacheEntry(sample_series, ttl_seconds=3600)

        assert key in collector._cache
        assert not collector._cache[key].is_expired

    def test_cache_expiry(self, collector, sample_series):
        """Süresi dolan önbellek expired olarak işaretlenmeli."""
        from src.data.collector import _CacheEntry
        key = "BTC/USDT:4h"
        # TTL = -1 saniye → anında süresi dolmuş
        entry = _CacheEntry(sample_series, ttl_seconds=-1)
        collector._cache[key] = entry

        assert collector._cache[key].is_expired

    def test_clear_cache_all(self, collector, sample_series):
        """clear_cache() tüm önbelleği silmeli."""
        from src.data.collector import _CacheEntry
        collector._cache["BTC/USDT:4h"] = _CacheEntry(sample_series, 3600)
        collector._cache["ETH/USDT:1d"] = _CacheEntry(sample_series, 3600)
        collector.clear_cache()
        assert len(collector._cache) == 0

    def test_clear_cache_specific_symbol(self, collector, sample_series):
        """Belirli sembol önbelleği silinmeli, diğerleri kalmalı."""
        from src.data.collector import _CacheEntry
        collector._cache["BTC/USDT:4h"] = _CacheEntry(sample_series, 3600)
        collector._cache["ETH/USDT:1d"] = _CacheEntry(sample_series, 3600)
        collector.clear_cache("BTC/USDT")
        assert "ETH/USDT:1d" in collector._cache
        assert "BTC/USDT:4h" not in collector._cache

    @patch("ccxt.binance")
    def test_connect_success(self, mock_binance_class, collector):
        """Başarılı bağlantı is_connected=True yapmalı."""
        mock_exchange = MagicMock()
        mock_exchange.markets = {"BTC/USDT": {}, "ETH/USDT": {}}
        mock_exchange.load_markets.return_value = mock_exchange.markets
        mock_binance_class.return_value = mock_exchange

        with patch("src.data.collector.ccxt.binance", return_value=mock_exchange):
            result = collector.connect()
            # Not: sandbox set_sandbox_mode çağrısı olur
            assert collector._is_connected is True or result is True

    def test_repr(self, collector):
        """__repr__ hata vermeden çalışmalı."""
        s = repr(collector)
        assert "DataCollector" in s
        assert "Paper Trade" in s


# ─── DataFetchResult Testleri ────────────────────────────────

class TestDataFetchResult:
    """DataFetchResult model testleri."""

    def test_successful_result(self, sample_series):
        """Başarılı sonuç doğru candle_count döndürmeli."""
        result = DataFetchResult(
            success=True,
            symbol="BTC/USDT",
            timeframe="4h",
            data=sample_series,
        )
        assert result.candle_count == 5

    def test_failed_result(self):
        """Başarısız sonuç candle_count=0 döndürmeli."""
        result = DataFetchResult(
            success=False,
            symbol="BTC/USDT",
            timeframe="4h",
            error_message="Test hatası",
        )
        assert result.candle_count == 0
        assert result.data is None
