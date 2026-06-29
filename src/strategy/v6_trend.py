# ============================================================
# src/strategy/v6_trend.py — V6 Trend Following Stratejisi
#
# AMAÇ:
#   EMA crossover + MACD onayı + Volume filtresi ile trend
#   takip eden strateji. Freqtrade ve Jesse'den öğrenilen
#   en iyi uygulamalar.
#
# SİNYAL MANTĞI:
#   ALIŞ: EMA21 > EMA55 + MACD pozitif + Hacim artışı
#   SATIŞ: EMA21 < EMA55 + MACD negatif + Hacim artışı
# ============================================================

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class V6TrendFollowing:
    """EMA/MACD tabanlı trend takip stratejisi."""

    def __init__(
        self,
        ema_fast: int = 21,
        ema_slow: int = 55,
        ema_trend: int = 200,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 14,
        atr_period: int = 14,
        volume_ma_period: int = 20,
        volume_threshold: float = 1.2,
        atr_sl_multiplier: float = 1.5,
        atr_tp_multiplier: float = 3.0,
    ) -> None:
        """V6TrendFollowing başlatır.

        Args:
            ema_fast: Hızlı EMA periyodu.
            ema_slow: Yavaş EMA periyodu.
            ema_trend: Trend EMA periyodu (200-bar).
            macd_fast: MACD hızlı periyodu.
            macd_slow: MACD yavaş periyodu.
            macd_signal: MACD sinyal periyodu.
            rsi_period: RSI periyodu.
            atr_period: ATR periyodu.
            volume_ma_period: Hacim hareketli ortalaması periyodu.
            volume_threshold: Minimum hacim oranı.
            atr_sl_multiplier: ATR stop loss çarpanı.
            atr_tp_multiplier: ATR take profit çarpanı.
        """
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.ema_trend = ema_trend
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.volume_ma_period = volume_ma_period
        self.volume_threshold = volume_threshold
        self.atr_sl_multiplier = atr_sl_multiplier
        self.atr_tp_multiplier = atr_tp_multiplier

    def generate_signal(self, df: pd.DataFrame, idx: int) -> Optional[str]:
        """Sinyal üretir.

        Args:
            df: OHLCV DataFrame (indikatörler hesaplanmış).
            idx: Mevcut bardaki indeks.

        Returns:
            "BUY", "SELL", veya None.
        """
        if idx < self.ema_trend:
            return None

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        # EMA crossover kontrolü
        ema_fast_now = float(row.get("ema_fast", 0))
        ema_slow_now = float(row.get("ema_slow", 0))
        ema_fast_prev = float(prev.get("ema_fast", 0))
        ema_slow_prev = float(prev.get("ema_slow", 0))
        ema_trend_now = float(row.get("ema_trend", 0))
        close = float(row["close"])

        # MACD kontrolü
        macd_line = float(row.get("macd_line", 0))
        macd_signal = float(row.get("macd_signal", 0))
        macd_hist = float(row.get("macd_hist", 0))
        macd_hist_prev = float(prev.get("macd_hist", 0))

        # Hacim kontrolü
        volume = float(row["volume"])
        volume_ma = float(row.get("volume_ma", volume))
        vol_ratio = volume / volume_ma if volume_ma > 0 else 0

        # RSI kontrolü
        rsi = float(row.get("rsi", 50))

        # ═══ ALIŞ SİNYALİ ═══
        # EMA21 EMA55'i yukarı kesiyor + MACD histogram pozitife dönüyor
        # + Fiyat EMA200'ün üstünde + Hacim artışı
        if (ema_fast_prev <= ema_slow_prev and ema_fast_now > ema_slow_now
                and macd_hist > 0 and macd_hist > macd_hist_prev
                and close > ema_trend_now
                and vol_ratio >= self.volume_threshold
                and rsi < 70):
            return "BUY"

        # ═══ SATIŞ SİNYALİ ═══
        # EMA21 EMA55'i aşağı kesiyor + MACD histogram negatife dönüyor
        # + Fiyat EMA200'ün altında + Hacim artışı
        if (ema_fast_prev >= ema_slow_prev and ema_fast_now < ema_slow_now
                and macd_hist < 0 and macd_hist < macd_hist_prev
                and close < ema_trend_now
                and vol_ratio >= self.volume_threshold
                and rsi > 30):
            return "SELL"

        return None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """İndikatörleri hesaplar.

        Args:
            df: Ham OHLCV DataFrame.

        Returns:
            İndikatörler eklenmiş DataFrame.
        """
        df = df.copy()

        # EMA'lar
        df["ema_fast"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()
        df["ema_trend"] = df["close"].ewm(span=self.ema_trend, adjust=False).mean()

        # MACD
        ema_f = df["close"].ewm(span=self.macd_fast, adjust=False).mean()
        ema_s = df["close"].ewm(span=self.macd_slow, adjust=False).mean()
        df["macd_line"] = ema_f - ema_s
        df["macd_signal"] = df["macd_line"].ewm(span=self.macd_signal, adjust=False).mean()
        df["macd_hist"] = df["macd_line"] - df["macd_signal"]

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=self.rsi_period).mean()
        avg_loss = loss.rolling(window=self.rsi_period).mean()
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))

        # ATR
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()

        # Hacim ortalaması
        df["volume_ma"] = df["volume"].rolling(window=self.volume_ma_period).mean()
        df["volume_ratio"] = df["volume"] / df["volume_ma"]

        return df

    def get_stop_loss(
        self,
        entry_price: float,
        atr: float,
        side: str,
    ) -> float:
        """Stop loss fiyatını hesaplar.

        Args:
            entry_price: Giriş fiyatı.
            atr: Mevcut ATR değeri.
            side: "BUY" veya "SELL".

        Returns:
            Stop loss fiyatı.
        """
        if side == "BUY":
            return entry_price - self.atr_sl_multiplier * atr
        else:
            return entry_price + self.atr_sl_multiplier * atr

    def get_take_profit(
        self,
        entry_price: float,
        atr: float,
        side: str,
    ) -> float:
        """Take profit fiyatını hesaplar.

        Args:
            entry_price: Giriş fiyatı.
            atr: Mevcut ATR değeri.
            side: "BUY" veya "SELL".

        Returns:
            Take profit fiyatı.
        """
        if side == "BUY":
            return entry_price + self.atr_tp_multiplier * atr
        else:
            return entry_price - self.atr_tp_multiplier * atr
