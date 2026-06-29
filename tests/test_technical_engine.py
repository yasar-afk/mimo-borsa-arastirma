# ============================================================
# tests/test_technical_engine.py — Trading Bot Trading Bot
#
# AMAÇ:
#   TechnicalEngine ve indikatör modellerinin birim testleri.
#   Gerçek API çağrısı yapılmaz; sentetik OHLCV verisi üretilir.
#
# ÇALIŞTIRMA:
#   pytest tests/test_technical_engine.py -v
#   pytest tests/ -v  (tüm testler)
#
# MİMARİ NOT:
#   Sentetik veri üretiminde deterministik (tekrarlanabilir) veri
#   kullanılır. Rastgele veri testleri kırılgan yapar.
# ============================================================

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.technical.engine import TechnicalEngine
from src.technical.indicators import (
    BBPosition,
    BollingerResult,
    EMAAlignment,
    EMAResult,
    IndicatorSet,
    MACDCrossType,
    MACDResult,
    RSIResult,
    RSIZone,
    SignalDirection,
    VolumeResult,
)


# ─── Ortak Fixtures ──────────────────────────────────────────

@pytest.fixture
def engine() -> TechnicalEngine:
    """Varsayılan parametreli TechnicalEngine."""
    return TechnicalEngine()


@pytest.fixture
def synthetic_bullish_df() -> pd.DataFrame:
    """Yükselen trend sentetik OHLCV verisi (300 bar)."""
    np.random.seed(42)
    n = 300
    base = 30000.0
    timestamps = [1_700_000_000_000 + i * 14_400_000 for i in range(n)]

    # Yükselen trend: her bar yaklaşık +0.1% artış
    closes = [base * (1 + 0.001 * i + np.random.normal(0, 0.003)) for i in range(n)]
    highs  = [c * (1 + abs(np.random.normal(0, 0.002))) for c in closes]
    lows   = [c * (1 - abs(np.random.normal(0, 0.002))) for c in closes]
    opens  = [closes[max(0, i-1)] for i in range(n)]
    vols   = [100 + np.random.exponential(50) for _ in range(n)]

    return pd.DataFrame({
        "timestamp": timestamps,
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": vols,
    })


@pytest.fixture
def synthetic_bearish_df() -> pd.DataFrame:
    """Düşen trend sentetik OHLCV verisi (300 bar)."""
    np.random.seed(7)
    n = 300
    base = 50000.0
    timestamps = [1_700_000_000_000 + i * 14_400_000 for i in range(n)]

    closes = [base * (1 - 0.001 * i + np.random.normal(0, 0.003)) for i in range(n)]
    highs  = [c * (1 + abs(np.random.normal(0, 0.002))) for c in closes]
    lows   = [c * (1 - abs(np.random.normal(0, 0.002))) for c in closes]
    opens  = [closes[max(0, i-1)] for i in range(n)]
    vols   = [100 + np.random.exponential(30) for _ in range(n)]

    return pd.DataFrame({
        "timestamp": timestamps,
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": vols,
    })


@pytest.fixture
def insufficient_df() -> pd.DataFrame:
    """Çok az bar içeren DataFrame (min_bars altında)."""
    n = 10
    closes = [30000.0 + i * 10 for i in range(n)]
    return pd.DataFrame({
        "timestamp": list(range(n)),
        "open":   closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.99 for c in closes],
        "close":  closes,
        "volume": [100.0] * n,
    })


# ─── TechnicalEngine Başlatma Testleri ───────────────────────

class TestTechnicalEngineInit:
    """TechnicalEngine başlatma ve konfigürasyon testleri."""

    def test_default_params(self, engine):
        """Varsayılan parametreler doğru set edilmeli."""
        assert engine.rsi_period == 14
        assert engine.macd_fast == 12
        assert engine.macd_slow == 26
        assert engine.macd_signal == 9
        assert engine.ema_periods == [20, 50, 200]
        assert engine.atr_period == 14
        assert engine.bb_period == 20

    def test_custom_params(self):
        """Özel parametreler doğru atanmalı."""
        eng = TechnicalEngine(rsi_period=21, macd_fast=8, ema_periods=[10, 30, 100])
        assert eng.rsi_period == 21
        assert eng.macd_fast == 8
        assert eng.ema_periods == [10, 30, 100]

    def test_min_bars_calculated(self, engine):
        """Minimum bar sayısı hesaplanmış olmalı."""
        assert engine.min_bars > 0
        assert engine.min_bars >= max(engine.ema_periods)


# ─── DataFrame Validasyon Testleri ───────────────────────────

class TestDataFrameValidation:
    """_validate_dataframe() testi."""

    def test_empty_df_fails(self, engine):
        """Boş DataFrame reddedilmeli."""
        result = engine._validate_dataframe(pd.DataFrame())
        assert result is False

    def test_missing_column_fails(self, engine):
        """Eksik sütun reddedilmeli."""
        bad_df = pd.DataFrame({"open": [1], "high": [2], "low": [0.5], "close": [1.5]})
        # "volume" eksik
        result = engine._validate_dataframe(bad_df)
        assert result is False

    def test_insufficient_bars_fails(self, engine, insufficient_df):
        """Min bar altında reddedilmeli."""
        result = engine._validate_dataframe(insufficient_df)
        assert result is False

    def test_valid_df_passes(self, engine, synthetic_bullish_df):
        """Geçerli DataFrame kabul edilmeli."""
        result = engine._validate_dataframe(synthetic_bullish_df)
        assert result is True


# ─── enrich_dataframe() Testleri ─────────────────────────────

class TestEnrichDataframe:
    """enrich_dataframe() testi."""

    def test_rsi_column_added(self, engine, synthetic_bullish_df):
        """RSI sütunu eklenmeli."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        assert "rsi" in df.columns

    def test_macd_columns_added(self, engine, synthetic_bullish_df):
        """MACD sütunları eklenmeli."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        assert "macd" in df.columns
        assert "macd_signal" in df.columns
        assert "macd_hist" in df.columns

    def test_ema_columns_added(self, engine, synthetic_bullish_df):
        """EMA sütunları eklenmeli."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        assert "ema20" in df.columns
        assert "ema50" in df.columns
        assert "ema200" in df.columns

    def test_atr_columns_added(self, engine, synthetic_bullish_df):
        """ATR sütunları eklenmeli."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        assert "atr" in df.columns
        assert "atr_pct" in df.columns

    def test_bollinger_columns_added(self, engine, synthetic_bullish_df):
        """Bollinger sütunları eklenmeli."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        assert "bb_upper" in df.columns
        assert "bb_lower" in df.columns
        assert "bb_pct_b" in df.columns

    def test_volume_columns_added(self, engine, synthetic_bullish_df):
        """Hacim analizi sütunları eklenmeli."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        assert "volume_avg" in df.columns
        assert "volume_ratio" in df.columns

    def test_original_df_not_modified(self, engine, synthetic_bullish_df):
        """Orijinal DataFrame değiştirilmemeli (kopya döndürülmeli)."""
        original_cols = list(synthetic_bullish_df.columns)
        engine.enrich_dataframe(synthetic_bullish_df)
        assert list(synthetic_bullish_df.columns) == original_cols

    def test_row_count_preserved(self, engine, synthetic_bullish_df):
        """Satır sayısı korunmalı."""
        n_before = len(synthetic_bullish_df)
        df = engine.enrich_dataframe(synthetic_bullish_df)
        assert len(df) == n_before

    def test_rsi_values_in_range(self, engine, synthetic_bullish_df):
        """RSI değerleri 0–100 arasında olmalı."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        valid = df["rsi"].dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_atr_positive(self, engine, synthetic_bullish_df):
        """ATR warmup sonrası değerleri pozitif olmalı."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        # ATR ilk N barda warmup nedeniyle 0 olur; sadece dolu değerleri kontrol et
        valid = df["atr"].dropna()
        positive = valid[valid > 0]
        assert len(positive) > 0, "Hiç pozitif ATR değeri yok"
        # Toplam değerlerin %90'ından fazlası pozitif olmalı
        assert len(positive) / len(valid) > 0.90

    def test_bb_upper_above_lower(self, engine, synthetic_bullish_df):
        """BB üst bant > alt bant olmalı."""
        df = engine.enrich_dataframe(synthetic_bullish_df)
        valid = df[["bb_upper", "bb_lower"]].dropna()
        assert (valid["bb_upper"] > valid["bb_lower"]).all()


# ─── get_latest_indicators() Testleri ────────────────────────

class TestGetLatestIndicators:
    """get_latest_indicators() entegrasyon testi."""

    def test_returns_indicator_set(self, engine, synthetic_bullish_df):
        """IndicatorSet nesnesi döndürülmeli."""
        result = engine.get_latest_indicators(
            synthetic_bullish_df, "BTC/USDT", "4h"
        )
        assert result is not None
        assert isinstance(result, IndicatorSet)

    def test_symbol_and_timeframe_set(self, engine, synthetic_bullish_df):
        """Symbol ve timeframe doğru set edilmeli."""
        result = engine.get_latest_indicators(
            synthetic_bullish_df, "BTC/USDT", "4h"
        )
        assert result.symbol == "BTC/USDT"
        assert result.timeframe == "4h"

    def test_all_indicators_present(self, engine, synthetic_bullish_df):
        """Tüm indikatörler hesaplanmış olmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        assert result.rsi is not None
        assert result.macd is not None
        assert result.ema is not None
        assert result.atr is not None
        assert result.bollinger is not None
        assert result.volume is not None

    def test_weighted_score_in_range(self, engine, synthetic_bullish_df):
        """Ağırlıklı puan 0.0–1.0 arasında olmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        assert 0.0 <= result.weighted_score <= 1.0

    def test_score_breakdown_populated(self, engine, synthetic_bullish_df):
        """Puan dökümü dolu olmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        assert len(result.score_breakdown) > 0

    def test_insufficient_data_returns_none(self, engine, insufficient_df):
        """Yetersiz veri varsa None döndürülmeli."""
        result = engine.get_latest_indicators(insufficient_df)
        assert result is None

    def test_summary_method_works(self, engine, synthetic_bullish_df):
        """summary() metodu hatasız çalışmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        summary = result.summary()
        assert isinstance(summary, str)
        assert len(summary) > 0


# ─── RSI Yorumlama Testleri ──────────────────────────────────

class TestRSIInterpretation:
    """RSI değer yorumlama testleri."""

    def test_bullish_trend_rsi_not_oversold(self, engine, synthetic_bullish_df):
        """Yükselen trendde RSI genellikle oversold olmamalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        # Uzun yükselen trendde RSI yüksek olur
        assert result.rsi is not None
        assert result.rsi.value > 30, "Yükselen trendde RSI 30 altında olmamalı"

    def test_bearish_trend_rsi_not_overbought(self, engine, synthetic_bearish_df):
        """Düşen trendde RSI genellikle overbought olmamalı."""
        result = engine.get_latest_indicators(synthetic_bearish_df)
        assert result.rsi is not None
        assert result.rsi.value < 70, "Düşen trendde RSI 70 üstünde olmamalı"

    def test_rsi_effective_weight_normal(self, engine, synthetic_bullish_df):
        """Normal durumda RSI efektif ağırlığı 0.70 olmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        if result.rsi and not result.rsi.has_divergence:
            assert result.rsi.effective_weight == 0.70

    def test_rsi_effective_weight_divergence(self):
        """Divergence durumunda RSI efektif ağırlığı 0.85 olmalı."""
        rsi = RSIResult(
            value=35.0,
            zone=RSIZone.NEAR_OVERSOLD,
            signal=SignalDirection.STRONG_BUY,
            signal_strength=0.95,
            is_bullish_divergence=True,
        )
        assert rsi.effective_weight == 0.85


# ─── ATR Stop-Loss Testleri ──────────────────────────────────

class TestATRStopLoss:
    """ATR stop-loss hesaplama testleri."""

    def test_stop_loss_below_price_for_long(self, engine, synthetic_bullish_df):
        """Long stop-loss fiyatın altında olmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        assert result.atr is not None
        assert result.atr.stop_loss_long < result.atr.current_price

    def test_stop_loss_above_price_for_short(self, engine, synthetic_bullish_df):
        """Short stop-loss fiyatın üstünde olmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        assert result.atr is not None
        assert result.atr.stop_loss_short > result.atr.current_price

    def test_rr_ratio_satisfied(self, engine, synthetic_bullish_df):
        """Risk/Ödül oranı minimum 2.0 olmalı."""
        result = engine.get_latest_indicators(synthetic_bullish_df)
        assert result.atr is not None
        risk   = result.atr.current_price - result.atr.stop_loss_long
        reward = result.atr.take_profit_long - result.atr.current_price
        if risk > 0:
            actual_rr = reward / risk
            assert actual_rr >= engine.rr_ratio - 0.01  # Küçük float tolerans


# ─── Ağırlıklı Puanlama Testleri ─────────────────────────────

class TestWeightedScoring:
    """IndicatorSet.calculate_weighted_score() testleri."""

    def test_score_with_all_buy_signals(self):
        """Tüm sinyaller alış ise puan yüksek olmalı."""
        rsi = RSIResult(
            value=28.0, zone=RSIZone.OVERSOLD,
            signal=SignalDirection.STRONG_BUY, signal_strength=0.90
        )
        macd = MACDResult(
            macd_line=0.01, signal_line=-0.01, histogram=0.02,
            cross_type=MACDCrossType.BULLISH_CROSS,
            signal=SignalDirection.STRONG_BUY, signal_strength=0.85
        )
        ind_set = IndicatorSet(
            symbol="BTC/USDT", timeframe="4h",
            timestamp=0, current_price=30000.0,
            rsi=rsi, macd=macd,
        )
        score = ind_set.calculate_weighted_score()
        assert score > 0.70, f"Tüm alış sinyallerinde puan düşük: {score}"

    def test_score_with_all_sell_signals(self):
        """Tüm sinyaller satış ise puan düşük olmalı."""
        # Yönlü skor (direction-aware) mantığına göre, STRONG_SELL ve yüksek
        # signal_strength (örn. 0.90) olduğunda, directional_score 0.05'e yaklaşır.
        # Bu yüzden güçlü satış durumunda puan düşük olmalıdır.
        rsi = RSIResult(
            value=78.0, zone=RSIZone.OVERBOUGHT,
            signal=SignalDirection.STRONG_SELL, signal_strength=0.90
        )
        macd = MACDResult(
            macd_line=-0.01, signal_line=0.01, histogram=-0.02,
            cross_type=MACDCrossType.BEARISH_CROSS,
            signal=SignalDirection.STRONG_SELL, signal_strength=0.85
        )
        ind_set = IndicatorSet(
            symbol="BTC/USDT", timeframe="4h",
            timestamp=0, current_price=50000.0,
            rsi=rsi, macd=macd,
        )
        score = ind_set.calculate_weighted_score()
        assert score < 0.30, f"Tüm satış sinyallerinde puan yüksek: {score}"

    def test_empty_indicator_set_score(self):
        """İndikatörsüz set 0.0 puan üretmeli."""
        ind_set = IndicatorSet(
            symbol="BTC/USDT", timeframe="4h",
            timestamp=0, current_price=30000.0,
        )
        score = ind_set.calculate_weighted_score()
        assert score == 0.0

    def test_signal_direction_scores(self):
        """SignalDirection.score değerleri doğru olmalı."""
        assert SignalDirection.STRONG_BUY.score  == 1.00
        assert SignalDirection.BUY.score          == 0.75
        assert SignalDirection.NEUTRAL.score      == 0.50
        assert SignalDirection.SELL.score         == 0.25
        assert SignalDirection.STRONG_SELL.score  == 0.00


# ─── Fibonacci Hesaplama Testleri ────────────────────────────

class TestFibonacciCalculations:
    """Fibonacci seviye hesaplama testleri."""

    def test_fibonacci_calculation_values(self, engine):
        """Hesaplanan Fibonacci seviyelerinin doğruluğu kontrol edilmeli."""
        n = 505
        closes = [100.0] * n
        highs = [100.0] * n
        lows = [100.0] * n
        
        # 250. mumu high=200 yapalım (swing_high = 200.0)
        highs[250] = 200.0
        
        df = pd.DataFrame({
            "timestamp": list(range(n)),
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n
        })
        
        fib = engine._interpret_fibonacci(df)
        assert fib is not None
        assert fib.swing_high == 200.0
        assert fib.swing_low == 100.0
        
        # Seviye doğrulamaları ( swing_high - x * diff )
        # diff = 100.0
        # fib_236 = 200.0 - 0.236 * 100 = 176.4
        # fib_382 = 200.0 - 0.382 * 100 = 161.8
        # fib_500 = 200.0 - 0.500 * 100 = 150.0
        # fib_618 = 200.0 - 0.618 * 100 = 138.2
        # fib_786 = 200.0 - 0.786 * 100 = 121.4
        
        assert abs(fib.fib_236 - 176.4) < 0.01
        assert abs(fib.fib_382 - 161.8) < 0.01
        assert abs(fib.fib_500 - 150.0) < 0.01
        assert abs(fib.fib_618 - 138.2) < 0.01
        assert abs(fib.fib_786 - 121.4) < 0.01

    def test_fibonacci_insufficient_lookback(self, engine):
        """10 mumdan az veri için None dönmeli."""
        df = pd.DataFrame({
            "timestamp": list(range(5)),
            "open": [10.0]*5,
            "high": [12.0]*5,
            "low": [8.0]*5,
            "close": [10.0]*5,
            "volume": [100.0]*5
        })
        fib = engine._interpret_fibonacci(df)
        assert fib is None

    def test_fibonacci_flat_price(self, engine):
        """Swing High ve Swing Low eşit ise None dönmeli."""
        n = 20
        df = pd.DataFrame({
            "timestamp": list(range(n)),
            "open": [100.0]*n,
            "high": [100.0]*n,
            "low": [100.0]*n,
            "close": [100.0]*n,
            "volume": [100.0]*n
        })
        fib = engine._interpret_fibonacci(df)
        assert fib is None


# ─── Formasyon Tespit Testleri ───────────────────────────────

class TestPatternDetection:
    """Mum ve grafik formasyon tespiti testleri."""

    def test_hammer_detection(self, engine):
        """Çekiç (Hammer) mum formasyonu tespiti kontrol edilmeli."""
        n = 20
        # Düşen trend
        closes = [100.0 - i for i in range(n)]
        opens = [100.0 - i + 0.5 for i in range(n)]
        highs = [100.0 - i + 1.0 for i in range(n)]
        lows = [100.0 - i - 1.0 for i in range(n)]
        
        # Son mumu çekiç yapalım:
        # open = 80, close = 81 (küçük gövde, bullish)
        # high = 81.1 (çok küçük üst gölge)
        # low = 75 (uzun alt gölge)
        # range = 6.1, body = 1, upper_shadow = 0.1, lower_shadow = 5
        # lower_shadow >= 2 * body (5 >= 2), upper_shadow <= 0.1 * range (0.1 <= 0.61)
        opens[-1] = 80.0
        closes[-1] = 81.0
        highs[-1] = 81.1
        lows[-1] = 75.0
        
        df = pd.DataFrame({
            "timestamp": list(range(n)),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0]*n
        })
        
        res = engine._detect_patterns(df)
        assert res is not None
        assert res.hammer is True
        assert "Çekiç (Hammer)" in res.active_patterns

    def test_bullish_engulfing_detection(self, engine):
        """Yutan Boğa (Bullish Engulfing) mum formasyonu tespiti kontrol edilmeli."""
        n = 20
        closes = [100.0]*n
        opens = [100.0]*n
        highs = [101.0]*n
        lows = [99.0]*n
        
        # Sondan önceki mum: Bearish (open=100, close=98)
        opens[-2] = 100.0
        closes[-2] = 98.0
        
        # Son mum: Bullish ve engulfing (open=97.5, close=101)
        opens[-1] = 97.5
        closes[-1] = 101.0
        
        df = pd.DataFrame({
            "timestamp": list(range(n)),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0]*n
        })
        
        res = engine._detect_patterns(df)
        assert res is not None
        assert res.bullish_engulfing is True
        assert "Yutan Boğa (Bullish Engulfing)" in res.active_patterns

    def test_double_bottom_detection(self, engine):
        """İkili Dip (Double Bottom) grafik formasyonu tespiti kontrol edilmeli."""
        n = 100
        # Fiyat genel olarak 100 civarında gitsin
        closes = [100.0] * n
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        
        # Birinci Dip (20. mum civarı): 90.0
        lows[20] = 90.0
        closes[20] = 91.0
        
        # İkinci Dip (70. mum civarı): 90.2 (%0.22 fark, %1.5 limitinin altında)
        lows[70] = 90.2
        closes[70] = 91.2
        
        # Son mumun fiyatı (sekme teyidi için, örn: 93.0)
        # avg_dip = 90.1. 90.1 < 93.0 <= 90.1 * 1.04 = 93.7. Doğru!
        closes[-1] = 93.0
        opens[-1] = 92.5
        highs[-1] = 93.5
        lows[-1] = 92.0
        
        df = pd.DataFrame({
            "timestamp": list(range(n)),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0]*n
        })
        
        res = engine._detect_patterns(df)
        assert res is not None
        assert res.double_bottom is True
        assert "İkili Dip (Double Bottom)" in res.active_patterns


