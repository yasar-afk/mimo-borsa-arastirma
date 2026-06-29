# ============================================================
# src/strategy/v6_mean_rev.py — V6 Mean Reversion Stratejisi
#
# AMAÇ:
#   RSI divergence + Bollinger Bands squeeze ile ortalama
#   dönüş stratejisi. Range-bound piyasalarda çalışır.
#
# SİNYAL MANTĞI:
#   ALIŞ: Fiyat BB lower altına düştü + RSI < 30 + Bullish divergence
#   SATIŞ: Fiyat BB upper üstüne çıktı + RSI > 70 + Bearish divergence
# ============================================================

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class V6MeanReversion:
    """RSI/Bollinger tabanlı mean reversion stratejisi."""

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        atr_period: int = 14,
        volume_ma_period: int = 20,
        divergence_lookback: int = 10,
        atr_sl_multiplier: float = 1.5,
        atr_tp_multiplier: float = 2.5,
    ) -> None:
        """V6MeanReversion başlatır.

        Args:
            bb_period: Bollinger Bands periyodu.
            bb_std: Bollinger Bands standart sapması.
            rsi_period: RSI periyodu.
            rsi_oversold: RSI aşırı satım eşiği.
            rsi_overbought: RSI aşırı alım eşiği.
            atr_period: ATR periyodu.
            volume_ma_period: Hacim ortalaması periyodu.
            divergence_lookback: Divergence arama penceresi.
            atr_sl_multiplier: ATR stop loss çarpanı.
            atr_tp_multiplier: ATR take profit çarpanı.
        """
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period = atr_period
        self.volume_ma_period = volume_ma_period
        self.divergence_lookback = divergence_lookback
        self.atr_sl_multiplier = atr_sl_multiplier
        self.atr_tp_multiplier = atr_tp_multiplier

    def generate_signal(self, df: pd.DataFrame, idx: int) -> Optional[dict]:
        """Sinyal üretir.

        Args:
            df: İndikatörlü DataFrame.
            idx: Mevcut bardaki indeks.

        Returns:
            {"type": "BUY"|"SELL", "category": "SAFE"|"RELAXED"} veya None.
        """
        if idx < self.divergence_lookback:
            return None

        row = df.iloc[idx]

        # Fiyat ve Bollinger Bands
        close = float(row["close"])
        bb_lower = float(row.get("bb_lower", 0))
        bb_upper = float(row.get("bb_upper", 1))
        bb_mid = float(row.get("bb_mid", close))
        bb_width = float(row.get("bb_width", 0))

        # RSI
        rsi = float(row.get("rsi", 50))

        # Hacim
        volume = float(row["volume"])
        volume_ma = float(row.get("volume_ma", volume))
        vol_ratio = volume / volume_ma if volume_ma > 0 else 0

        # Squeeze tespiti (BB daralması)
        bb_width_ma = float(row.get("bb_width_ma", bb_width))
        is_squeeze = bb_width < bb_width_ma * 0.8 if bb_width_ma > 0 else False

        # Divergence kontrolü
        has_bullish_div = self._check_bullish_divergence(df, idx)
        has_bearish_div = self._check_bearish_divergence(df, idx)

        # ═══ ALIŞ SİNYALİ (SAFE) ═══
        # Fiyat BB lower'ın altında + RSI < 30 + Bullish divergence
        # veya Squeeze sonrası yukarı kırılım
        if (close <= bb_lower and rsi <= self.rsi_oversold
                and has_bullish_div and vol_ratio > 0.8):
            return {"type": "BUY", "category": "SAFE"}

        if (is_squeeze and close > bb_mid and rsi > 40 and rsi < 60
                and vol_ratio > 1.5):
            return {"type": "BUY", "category": "SAFE"}

        # ═══ ALIŞ SİNYALİ (RELAXED) ═══
        # Uyumsuzluk yok ama RSI<35 ve fiyat BB altında
        if (close <= bb_lower and rsi <= 35 and vol_ratio > 0.5):
            return {"type": "BUY", "category": "RELAXED"}

        # ═══ SATIŞ SİNYALİ (SAFE) ═══
        # Fiyat BB upper'ın üstünde + RSI > 70 + Bearish divergence
        if (close >= bb_upper and rsi >= self.rsi_overbought
                and has_bearish_div and vol_ratio > 0.8):
            return {"type": "SELL", "category": "SAFE"}

        # ═══ SATIŞ SİNYALİ (RELAXED) ═══
        if (close >= bb_upper and rsi >= 65 and vol_ratio > 0.5):
            return {"type": "SELL", "category": "RELAXED"}

        return None

    def _check_bullish_divergence(
        self,
        df: pd.DataFrame,
        idx: int,
    ) -> bool:
        """Bullish RSI divergence kontrolü.

        Fiyat yeni dip yaparken RSI yeni dip yapmıyorsa divergence var.

        Args:
            df: DataFrame.
            idx: Mevcut indeks.

        Returns:
            Bullish divergence varsa True.
        """
        lookback = min(self.divergence_lookback, idx)
        prices = df["close"].iloc[idx - lookback:idx + 1].values
        rsis = df.get("rsi", pd.Series([50] * len(df))).iloc[idx - lookback:idx + 1].values

        if len(prices) < 3 or np.any(np.isnan(rsis)):
            return False

        # Son iki dip noktası bul
        price_min_idx = np.argmin(prices[:-1])
        recent_price = prices[-1]
        recent_rsi = rsis[-1]

        if recent_price < prices[price_min_idx] and recent_rsi > rsis[price_min_idx]:
            return True

        return False

    def _check_bearish_divergence(
        self,
        df: pd.DataFrame,
        idx: int,
    ) -> bool:
        """Bearish RSI divergence kontrolü.

        Fiyat yeni tepe yaparken RSI yeni tepe yapmıyorsa divergence var.

        Args:
            df: DataFrame.
            idx: Mevcut indeks.

        Returns:
            Bearish divergence varsa True.
        """
        lookback = min(self.divergence_lookback, idx)
        prices = df["close"].iloc[idx - lookback:idx + 1].values
        rsis = df.get("rsi", pd.Series([50] * len(df))).iloc[idx - lookback:idx + 1].values

        if len(prices) < 3 or np.any(np.isnan(rsis)):
            return False

        price_max_idx = np.argmax(prices[:-1])
        recent_price = prices[-1]
        recent_rsi = rsis[-1]

        if recent_price > prices[price_max_idx] and recent_rsi < rsis[price_max_idx]:
            return True

        return False

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """İndikatörleri hesaplar.

        Args:
            df: Ham OHLCV DataFrame.

        Returns:
            İndikatörler eklenmiş DataFrame.
        """
        df = df.copy()

        # Bollinger Bands
        df["bb_mid"] = df["close"].rolling(window=self.bb_period).mean()
        bb_std = df["close"].rolling(window=self.bb_period).std()
        df["bb_upper"] = df["bb_mid"] + self.bb_std * bb_std
        df["bb_lower"] = df["bb_mid"] - self.bb_std * bb_std
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
        df["bb_width_ma"] = df["bb_width"].rolling(window=self.bb_period).mean()

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

        return df

    def get_stop_loss(
        self,
        entry_price: float,
        atr: float,
        side: str,
    ) -> float:
        """Stop loss fiyatını hesaplar."""
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
        """Take profit fiyatını hesaplar."""
        if side == "BUY":
            return entry_price + self.atr_tp_multiplier * atr
        else:
            return entry_price - self.atr_tp_multiplier * atr
