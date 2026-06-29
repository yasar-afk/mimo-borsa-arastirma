# -*- coding: utf-8 -*-
# ============================================================
# train_ml.py — Yapay Zeka Model Eğitim Scripti
# ============================================================

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score, precision_score, recall_score
import joblib

# Windows UTF-8 Düzeltmesi
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.data.historical import HistoricalDataFetcher
from src.strategy.v6_mean_rev import V6MeanReversion
from src.strategy.ml_filter import MLSignalFilter
from run_backtest import prepare_data
from src.utils.logger import get_logger

logger = get_logger("train_ml")


def calculate_dynamic_sl_tp(entry_price: float, atr: float, side: str, df_slice: pd.DataFrame) -> Tuple[float, float]:
    """live_v65.py içindeki dinamik SL/TP mantığının aynısı."""
    if "atr" in df_slice.columns and len(df_slice) >= 50:
        atr_series = df_slice["atr"].dropna()
        if len(atr_series) >= 50:
            atr_ma = atr_series.iloc[-50:].mean()
        else:
            atr_ma = atr_series.mean()
    else:
        atr_ma = atr

    if atr_ma > 0:
        vol_ratio = atr / atr_ma
    else:
        vol_ratio = 1.0

    if vol_ratio < 0.8:
        sl_mult = 1.5
    elif vol_ratio < 1.2:
        sl_mult = 2.0
    elif vol_ratio < 1.8:
        sl_mult = 2.5
    else:
        sl_mult = 3.0

    tp_mult = 2.5

    if side == "BUY":
        sl = entry_price - sl_mult * atr
        tp = entry_price + tp_mult * atr
    else:
        sl = entry_price + sl_mult * atr
        tp = entry_price - tp_mult * atr

    return sl, tp


def label_signal_outcome(df: pd.DataFrame, idx: int, signal_type: str, sl: float, tp: float, hold_bars: int = 72) -> int:
    """Sinyalin sonrasındaki fiyat hareketini inceleyerek TP=1, SL=0 olarak etiketler."""
    entry_price = float(df.iloc[idx]["close"])
    end_idx = min(idx + hold_bars, len(df) - 1)
    
    for i in range(idx + 1, end_idx + 1):
        row = df.iloc[i]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        
        if signal_type == "BUY":
            # SL tetiklendi mi?
            if low <= sl:
                return 0
            # TP tetiklendi mi?
            if high >= tp:
                return 1
        else: # SELL
            # SL tetiklendi mi?
            if high >= sl:
                return 0
            # TP tetiklendi mi?
            if low <= tp:
                return 1
                
    # Belirlenen mum süresince (hold_bars) ikisi de tetiklenmediyse son fiyata bakılır
    final_close = float(df.iloc[end_idx]["close"])
    if signal_type == "BUY":
        return 1 if final_close > entry_price else 0
    else: # SELL
        return 1 if final_close < entry_price else 0


def build_dataset(symbols: List[str], days: int) -> Tuple[pd.DataFrame, pd.Series]:
    """Geçmiş verileri çekip sinyalleri çıkarır ve etiketli veri setini oluşturur."""
    fetcher = HistoricalDataFetcher()
    strategy = V6MeanReversion()
    ml_filter = MLSignalFilter()
    
    limit = days * 24
    features_list = []
    labels_list = []
    
    logger.info(f"⏳ {len(symbols)} sembol için son {days} günlük veriler çekilerek veri seti toplanıyor...")
    
    for i, symbol in enumerate(symbols, 1):
        logger.info(f"[{i}/{len(symbols)}] {symbol} verileri işleniyor...")
        try:
            # 1. Veri çek
            df = fetcher.fetch_ohlcv(symbol, "1h", limit=limit)
            if df.empty or len(df) < 200:
                logger.warning(f"  ⚠️ {symbol} için yeterli veri yok, atlanıyor.")
                continue
                
            # 2. İndikatörleri zenginleştir
            df = prepare_data(df)
            
            # 3. Sinyalleri tarama
            signals_count = 0
            for idx in range(50, len(df) - 75):
                sig_dict = strategy.generate_signal(df, idx)
                if sig_dict:
                    sig_type = sig_dict["type"]
                    price = float(df.iloc[idx]["close"])
                    atr = float(df.iloc[idx].get("atr", price * 0.02))
                    
                    # Dinamik SL/TP hesapla
                    sl, tp = calculate_dynamic_sl_tp(price, atr, sig_type, df.iloc[:idx+1])
                    
                    # Etiket belirle (TP=1, SL=0)
                    label = label_signal_outcome(df, idx, sig_type, sl, tp)
                    
                    # Özellikleri çıkar
                    features = ml_filter.extract_features_at_idx(df, idx, sig_type)
                    if features:
                        features_list.append(features)
                        labels_list.append(label)
                        signals_count += 1
                        
            logger.info(f"  ✅ {symbol} | {signals_count} sinyal toplandı.")
            
        except Exception as e:
            logger.error(f"❌ {symbol} işlenirken hata oluştu: {e}")
            
    if not features_list:
        raise ValueError("Hiç sinyal verisi toplanamadı! Gün sayısını artırmayı deneyin veya borsa bağlantısını kontrol edin.")
        
    X = pd.DataFrame(features_list)
    y = pd.Series(labels_list)
    
    # Modelin beklediği sıralamayı koru
    X = X[ml_filter.FEATURE_NAMES]
    
    return X, y


def main():
    parser = argparse.ArgumentParser(description="Yapay Zeka Model Eğiticisi")
    parser.add_argument("--days", type=int, default=150, help="Eğitim için geçmiş gün sayısı")
    parser.add_argument("--top", type=int, default=40, help="Eğitimde kullanılacak en yüksek hacimli sembol sayısı")
    args = parser.parse_args()
    
    logger.info("="*60)
    logger.info("🤖 YAPAY ZEKA SİNYAL ONAY MODELİ EĞİTİMİ BAŞLIYOR")
    logger.info("="*60)
    
    # En yüksek hacimli sembolleri çek
    fetcher = HistoricalDataFetcher()
    try:
        fetcher.exchange.load_markets()
        symbols = fetcher.fetch_top_symbols(top_n=args.top, quote="USDT")
        # Hariç tutulan stabilcoin vb. temizle
        excluded = {"PAXG/USDT", "RLUSD/USDT", "FDUSD/USDT", "USDC/USDT", "USDT/USDT"}
        symbols = [s for s in symbols if s not in excluded]
    except Exception as e:
        logger.error(f"Sembol listesi alınamadı: {e}")
        sys.exit(1)
        
    # Veri setini oluştur
    try:
        X, y = build_dataset(symbols, args.days)
    except Exception as e:
        logger.error(f"Veri seti oluşturulamadı: {e}")
        sys.exit(1)
        
    logger.info(f"📊 Toplam Toplanan Sinyal Sayısı: {len(X)}")
    logger.info(f"📈 Başarılı Sinyal (TP) Oranı: {y.mean() * 100:.2f}% ({y.sum()} adet)")
    logger.info(f"📉 Başarısız Sinyal (SL) Oranı: {(1 - y.mean()) * 100:.2f}% ({len(y) - y.sum()} adet)")
    
    # Train / Test Ayrımı
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    # Model Tanımlama & Eğitme
    # Aşırı uyumun (overfitting) önüne geçmek için max_depth ve min_samples_leaf sınırlandırılmıştır
    model = RandomForestClassifier(
        n_estimators=150,
        max_depth=6,
        min_samples_leaf=5,
        random_state=42,
        class_weight="balanced"
    )
    
    logger.info("⚙️ Model eğitiliyor...")
    model.fit(X_train, y_train)
    
    # Tahminler ve Değerlendirme
    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred)
    rec = recall_score(y_test, y_pred)
    
    logger.info("\n📊 TEST SETİ DEĞERLENDİRME SONUÇLARI:")
    logger.info(f"  Accuracy  (Doğruluk) : {acc:.4f}")
    logger.info(f"  Precision (Hassasiyet): {prec:.4f} (Başarı tahmini ne kadar doğru?)")
    logger.info(f"  Recall    (Duyarlılık): {rec:.4f} (Başarılıların ne kadarı yakalandı?)")
    
    logger.info("\n📋 Sınıflandırma Raporu:")
    report = classification_report(y_test, y_pred)
    print(report)
    
    # Özellik Önem Dereceleri (Feature Importances)
    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1]
    
    logger.info("\n📈 En Önemli Özellikler (Top 10):")
    for rank in range(min(10, len(indices))):
        idx = indices[rank]
        logger.info(f"  {rank+1}. {X.columns[idx]:<25}: {importances[idx]:.4f}")
        
    # Modeli Kaydet
    Path("models").mkdir(exist_ok=True)
    model_path = "models/signal_classifier.pkl"
    joblib.dump(model, model_path)
    logger.info(f"\n💾 Model kaydedildi: {model_path}")
    logger.info("🎉 Eğitim süreci başarıyla tamamlandı!")


if __name__ == "__main__":
    main()
