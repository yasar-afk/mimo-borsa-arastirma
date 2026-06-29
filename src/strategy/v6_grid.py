# ============================================================
# src/strategy/v6_grid.py — V6 Grid Trading Stratejisi
#
# AMAÇ:
#   Belirli bir fiyat aralığında al-sat grid'i kuran
#   range-bound strateji. Fiyat hareketlerine göre
#   dinamik grid seviyeleri üretir.
#
# SİNYAL MANTĞI:
#   Her bar'da fiyatın grid'e göre konumunu kontrol eder.
#   Fiyat bir grid seviyesinin altına düşerse ALIŞ
#   Fiyat bir grid seviyesinin üstüne çıkarsa SATIŞ
# ============================================================

from __future__ import annotations

from typing import List, Optional, Set

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class V6GridTrading:
    """Dinamik grid trading stratejisi."""

    def __init__(
        self,
        grid_count: int = 20,
        atr_period: int = 14,
        grid_spread_pct: float = 0.05,
        lookback_period: int = 50,
    ) -> None:
        """V6GridTrading başlatır.

        Args:
            grid_count: Grid seviye sayısı.
            atr_period: ATR periyodu.
            grid_spread_pct: Grid yayılım yüzdesi (fiyatın %5'i).
            lookback_period: Geçmiş fiyat aralığı penceresi.
        """
        self.grid_count = grid_count
        self.atr_period = atr_period
        self.grid_spread_pct = grid_spread_pct
        self.lookback_period = lookback_period
        self.grid_levels: List[float] = []
        self.last_grid_idx: int = -1
        self.bought_levels: Set[float] = set()
        self.sold_levels: Set[float] = set()

    def generate_signal(self, df: pd.DataFrame, idx: int) -> Optional[str]:
        """Sinyal üretir.

        Args:
            df: İndikatörlü DataFrame.
            idx: Mevcut bardaki indeks.

        Returns:
            "BUY", "SELL", veya None.
        """
        if idx < self.lookback_period:
            return None

        close = float(df.iloc[idx]["close"])
        high = float(df.iloc[idx]["high"])
        low = float(df.iloc[idx]["low"])

        # Grid'i yeniden hesapla (her 50 barda bir)
        if idx - self.last_grid_idx > 50 or not self.grid_levels:
            self._recalculate_grid(df, idx)
            self.last_grid_idx = idx
            self.bought_levels.clear()
            self.sold_levels.clear()

        if not self.grid_levels:
            return None

        prev_close = float(df.iloc[idx - 1]["close"])

        # Her grid seviyesini kontrol et
        for level in self.grid_levels:
            # ALIŞ: Fiyat seviyenin altına düştüyse ve henüz almadıysak
            if level not in self.bought_levels:
                if low <= level and prev_close > level:
                    self.bought_levels.add(level)
                    return "BUY"

            # SATIŞ: Fiyat seviyenin üstüne çıktıysa ve henüz satmadıysak
            if level not in self.sold_levels and level in self.bought_levels:
                if high >= level and prev_close < level:
                    self.sold_levels.add(level)
                    self.bought_levels.discard(level)
                    return "SELL"

        return None

    def _recalculate_grid(self, df: pd.DataFrame, idx: int) -> None:
        """Grid seviyelerini yeniden hesaplar.

        Args:
            df: DataFrame.
            idx: Mevcut indeks.
        """
        lookback = min(self.lookback_period, idx)
        window = df.iloc[idx - lookback:idx + 1]

        high = float(window["high"].max())
        low = float(window["low"].min())
        mid_price = (high + low) / 2

        # Fiyat aralığının %5'i kadar spread ile grid oluştur
        spread = mid_price * self.grid_spread_pct
        grid_start = mid_price - spread
        grid_end = mid_price + spread

        self.grid_levels = np.linspace(grid_start, grid_end, self.grid_count).tolist()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """İndikatörleri hesaplar.

        Args:
            df: Ham OHLCV DataFrame.

        Returns:
            İndikatörler eklenmiş DataFrame.
        """
        df = df.copy()

        # ATR
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()

        return df

    def get_grid_levels(self) -> List[float]:
        """Mevcut grid seviyelerini döndürür."""
        return self.grid_levels.copy()
