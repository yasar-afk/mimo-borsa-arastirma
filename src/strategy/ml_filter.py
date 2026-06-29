# -*- coding: utf-8 -*-
# ============================================================
# src/strategy/ml_filter.py — Yapay Zeka Sinyal Onay Katmanı
# ============================================================

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import joblib

from src.utils.logger import get_logger

logger = get_logger("ml_filter")


class MLSignalFilter:
    """Yapay Zeka (ML) tabanlı sinyal onay ve güven skoru hesaplama katmanı."""

    FEATURE_NAMES = [
        "signal_direction",  # BUY/LONG: 1, SELL/SHORT: 0
        "rsi",
        "bb_width",
        "bb_width_ratio",    # bb_width / bb_width_ma
        "atr_price_ratio",   # atr / close
        "atr_ma_ratio",      # atr_ma / close
        "adx",
        "plus_di",
        "minus_di",
        "volume_ratio",      # volume / volume_ma
        "macd_line_ratio",   # macd_line / close
        "macd_signal_ratio", # macd_signal / close
        "macd_hist_ratio",   # macd_hist / close
        "vwap_price_ratio",  # vwap / close
        "stoch_rsi_k",
        "stoch_rsi_d",
        "ema_fast_ratio",    # close / ema_fast
        "ema_slow_ratio",    # close / ema_slow
        "ema_trend_ratio",   # close / ema_trend
    ]

    def __init__(self, model_path: str = "models/signal_classifier.pkl") -> None:
        self.model_path = Path(model_path)
        self.model = None
        self.is_trained = False
        self.load_model()

    def load_model(self) -> bool:
        """Kayıtlı modeli yükler."""
        if self.model_path.exists():
            try:
                self.model = joblib.load(self.model_path)
                self.is_trained = True
                logger.info(f"🤖 ML Modeli başarıyla yüklendi: {self.model_path}")
                return True
            except Exception as e:
                logger.error(f"❌ ML Modeli yükleme hatası: {e}")
                self.is_trained = False
        else:
            logger.info(f"ℹ️ ML Modeli bulunamadı: {self.model_path} (Eğitim bekleniyor)")
            self.is_trained = False
        return False

    def extract_features_at_idx(self, df: pd.DataFrame, idx: int, signal_type: str) -> Optional[dict]:
        """Belirtilen indekste modelin girdisi olacak özellikleri (features) çıkarır."""
        try:
            if idx < 0 or idx >= len(df):
                return None

            row = df.iloc[idx]
            close = float(row["close"])
            if close <= 0:
                return None

            # Oranlar ve Metrikler
            bb_width = float(row.get("bb_width", 0))
            bb_width_ma = float(row.get("bb_width_ma", bb_width))
            bb_width_ratio = bb_width / bb_width_ma if bb_width_ma > 0 else 1.0

            atr = float(row.get("atr", 0))
            atr_ma = float(row.get("atr_ma", atr))
            atr_price_ratio = atr / close
            atr_ma_ratio = atr_ma / close

            volume = float(row.get("volume", 0))
            volume_ma = float(row.get("volume_ma", volume))
            volume_ratio = volume / volume_ma if volume_ma > 0 else 1.0

            macd_line = float(row.get("macd_line", 0))
            macd_signal = float(row.get("macd_signal", 0))
            macd_hist = float(row.get("macd_hist", 0))
            macd_line_ratio = macd_line / close
            macd_signal_ratio = macd_signal / close
            macd_hist_ratio = macd_hist / close

            vwap = float(row.get("vwap", close))
            vwap_price_ratio = vwap / close

            ema_fast = float(row.get("ema_fast", close))
            ema_slow = float(row.get("ema_slow", close))
            ema_trend = float(row.get("ema_trend", close))
            ema_fast_ratio = close / ema_fast if ema_fast > 0 else 1.0
            ema_slow_ratio = close / ema_slow if ema_slow > 0 else 1.0
            ema_trend_ratio = close / ema_trend if ema_trend > 0 else 1.0

            feature_dict = {
                "signal_direction": 1 if signal_type in ("BUY", "LONG") else 0,
                "rsi": float(row.get("rsi", 50.0)),
                "bb_width": bb_width,
                "bb_width_ratio": bb_width_ratio,
                "atr_price_ratio": atr_price_ratio,
                "atr_ma_ratio": atr_ma_ratio,
                "adx": float(row.get("adx", 20.0)),
                "plus_di": float(row.get("plus_di", 20.0)),
                "minus_di": float(row.get("minus_di", 20.0)),
                "volume_ratio": volume_ratio,
                "macd_line_ratio": macd_line_ratio,
                "macd_signal_ratio": macd_signal_ratio,
                "macd_hist_ratio": macd_hist_ratio,
                "vwap_price_ratio": vwap_price_ratio,
                "stoch_rsi_k": float(row.get("stoch_rsi_k", 50.0)),
                "stoch_rsi_d": float(row.get("stoch_rsi_d", 50.0)),
                "ema_fast_ratio": ema_fast_ratio,
                "ema_slow_ratio": ema_slow_ratio,
                "ema_trend_ratio": ema_trend_ratio,
            }
            
            # None/NaN değerleri temizle/varsayılan ata
            for k, v in feature_dict.items():
                if pd.isna(v) or np.isnan(v) or np.isinf(v):
                    feature_dict[k] = 0.0

            return feature_dict

        except Exception as e:
            logger.error(f"❌ Özellik çıkarım hatası: {e}")
            return None

    def predict_probability(self, df: pd.DataFrame, idx: int, signal_type: str) -> float:
        """Sinyalin başarılı olma (TP'ye ulaşma) olasılığını hesaplar.
        
        Returns:
            0.0 ile 1.0 arasında olasılık puanı. Model yüklü değilse 0.50 döner.
        """
        if not self.is_trained or self.model is None:
            return 0.50

        features_dict = self.extract_features_at_idx(df, idx, signal_type)
        if features_dict is None:
            return 0.50

        try:
            # Feature DataFrame oluştur ve doğru sırada olduğundan emin ol
            features = [features_dict[name] for name in self.FEATURE_NAMES]
            features_df = pd.DataFrame([features], columns=self.FEATURE_NAMES)

            # Sadece 1 (Başarılı) sınıfının olasılığını döndür
            proba = self.model.predict_proba(features_df)[0][1]
            return float(proba)
        except Exception as e:
            logger.error(f"❌ ML Model tahmin hatası: {e}")
            return 0.50
