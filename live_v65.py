# -*- coding: utf-8 -*-
# ============================================================
# live_v65.py — V6.5 Enhanced Mean Reversion LIVE Trading Bot
#
# V6'DAN DERSLER:
#   1. Aynı pozisyona tekrar tekrar girme → Cooldown sistemi
#   2. Rotasyon çok agresif → Eşik 65→80, majör çiftlerde 90
#   3. SL çok dar (1.5x ATR) → Dinamik SL (volatilite bazlı)
#   4. Rejim filtresi yok → Trending piyasada ters sinyal engeli
#   5. Korelasyon kontrolü yok → Aynı sektör max 2 pozisyon
#   6. Kademeli kâr alma yok → Partial TP (3 seviye)
#   7. Sembol kalite filtresi yok → Aşırı hareketli/stabilcoin engeli
#
# ÇALIŞTIRMA:
#   python live_v65.py                    # Paper trade modu
#   python live_v65.py --live             # Canlı mod
#   python live_v65.py --single-run       # Tek seferlik tarama
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from src.data.historical import HistoricalDataFetcher
from src.strategy.v6_mean_rev import V6MeanReversion
from src.strategy.regime_detector import RegimeDetector, MarketRegime
from src.strategy.ml_filter import MLSignalFilter
from src.backtest.engine import BacktestEngine, TradeRecord
from src.utils.telegram_notifier import send_telegram_notification
from src.utils.logger import get_logger
from src.config.settings import get_settings
from src.utils.telegram_listener import start_telegram_listener

logger = get_logger("live_v65")


def format_price(price: float) -> str:
    if price is None or price == 0:
        return "-"
    if price >= 100:
        return f"${price:,.2f}"
    elif price >= 1.0:
        return f"${price:,.4f}"
    elif price >= 0.0001:
        return f"${price:,.6f}"
    else:
        return f"${price:,.8f}"


class LiveV65Bot:
    """V6.5 Enhanced Mean Reversion canlı trading botu."""

    # Sabitler
    MAJOR_PAIRS = {"BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"}
    EXCLUDED_SYMBOLS = {"PAXG/USDT", "RLUSD/USDT", "FDUSD/USDT", "USDC/USDT"}
    SECTORS = {
        "l1": {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT", "NEAR/USDT", "DOT/USDT", "ADA/USDT"},
        "l2": {"ARB/USDT", "OP/USDT", "MATIC/USDT", "IMX/USDT"},
        "defi": {"UNI/USDT", "AAVE/USDT", "LINK/USDT", "LDO/USDT", "MKR/USDT"},
        "meme": {"DOGE/USDT", "PEPE/USDT", "SHIB/USDT", "LUNC/USDT"},
        "ai": {"FET/USDT", "RENDER/USDT", "TAO/USDT"},
    }
    MAX_DAILY_MOVE_PCT = 15.0   # 10'dan 15'e — daha az filtre
    MAX_CONSECUTIVE_LOSSES = 5   # 3'ten 5'e — daha esnek
    LOSS_COOLDOWN_HOURS = 12     # 24'ten 12'ye

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_positions: int = 5,
        position_pct: float = 0.10,
        is_live: bool = False,
        top_n: int = 100,
        mode: str = "v6.5",
    ) -> None:
        self.mode = mode
        self.portfolio_state_path = "logs/portfolio_state_v61.json" if mode == "v6.1" else "logs/portfolio_state.json"
        self.signals_jsonl_path = "logs/signals_v61.jsonl" if mode == "v6.1" else "logs/signals.jsonl"
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.position_pct = position_pct
        self.is_live = is_live
        self.top_n = top_n

        self.fetcher = HistoricalDataFetcher()
        self.strategy = V6MeanReversion()
        self.regime_detector = RegimeDetector()
        self.balance = initial_capital
        self.positions: Dict[str, dict] = {}
        self.trades: List[TradeRecord] = []
        self.cycle_events: List[str] = []

        # V6.5: Cooldown haritası {symbol: {"until": timestamp, "direction": str, "reason": str}}
        self._cooldown_map: Dict[str, dict] = {}
        self.COOLDOWN_SL_HOURS = 2       # 4'ten 2'ye düşürüldü — daha az engelleyici
        self.COOLDOWN_ROTATION_HOURS = 0.5  # 1'den 0.5'e düşürüldü
        self.SAME_PRICE_TOLERANCE = 0.02

        # V6.5: Sembol kayıp sayacı {symbol: consecutive_losses}
        self._loss_counter: Dict[str, int] = {}
        self.MAX_CONSECUTIVE_LOSSES = 5     # 3'ten 5'e
        self.LOSS_COOLDOWN_HOURS = 12       # 24'ten 12'ye

        # V6.5: Rotasyon eşiği
        self.ROTATION_THRESHOLD = 70.0       # 80'den 70'e — daha aktif rotasyon
        self.MAJOR_ROTATION_THRESHOLD = 80.0 # 90'dan 80'e
        self.MAX_ROTATION_LOSS = 25.0        # 20'den 25'e — biraz daha esnek

        self._load_state()
        self.ml_filter = MLSignalFilter()

        self.settings = get_settings()
        self.settings.strategy.version = "v6.1" if mode == "v6.1" else "v6.5"

        logger.info(f"LiveV65Bot başlatıldı (Mod: {self.mode}) | Sermaye: ${initial_capital:,.2f} | Mod: {'LIVE' if is_live else 'PAPER'} | Top {top_n}")

        mod = '🔴 CANLI' if is_live else '🟢 PAPER'
        bot_name = "V6.1 Bot" if self.mode == "v6.1" else "V6.5 Enhanced Bot"
        features_str = "Kademeli Kâr + Cooldown" if self.mode == "v6.1" else "Cooldown + Rejim + DinamikSL + Korelasyon"
        msg = (
            f"🤖 {bot_name} Başlatıldı\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Sermaye: ${initial_capital:,.2f}\n"
            f"📊 Mod: {mod}\n"
            f"🎯 Max Pozisyon: {max_positions}\n"
            f"📏 Pozisyon Büyüklüğü: %{position_pct*100:.0f}\n"
            f"📋 Semboller: Top {top_n} (hacme göre)\n"
            f"🛡️ Özellikler: {features_str}"
        )
        send_telegram_notification(msg)

        # Telegram command listener'ı başlat
        try:
            start_telegram_listener(self)
        except Exception as e:
            logger.error(f"Telegram listener başlatılamadı: {e}")

    def _send_portfolio_summary(self, trigger_message: str = "") -> None:
        """Telegram'dan gelen durum isteğine cevap olarak anlık durumu gönderir."""
        logger.info(f"Telegram status query received: {trigger_message}")
        self._print_status()

    # ═══════════════════════════════════════════════════════════
    # V6.5 YENİ: COOLDOWN SİSTEMİ
    # ═══════════════════════════════════════════════════════════

    def _is_in_cooldown(self, symbol: str, direction: str) -> Tuple[bool, str]:
        """Sembol cooldown'da mı kontrol eder."""
        if symbol not in self._cooldown_map:
            return False, ""

        cd = self._cooldown_map[symbol]
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)

        if now < cd["until"]:
            remaining = (cd["until"] - now).total_seconds() / 3600
            if cd.get("direction") == direction:
                return True, f"Cooldown: {cd['reason']} ({remaining:.1f}h kaldı)"

        # Cooldown süresi dolmuşsa temizle
        if now >= cd["until"]:
            del self._cooldown_map[symbol]

        return False, ""

    def _set_cooldown(self, symbol: str, direction: str, reason: str, hours: float) -> None:
        """Sembol için cooldown ayarlar."""
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        self._cooldown_map[symbol] = {
            "until": now + timedelta(hours=hours),
            "direction": direction,
            "reason": reason,
        }
        logger.info(f"⏱️ {symbol} cooldown'a alındı: {reason} ({hours}h)")

    def _check_same_price_reentry(self, symbol: str, new_entry: float, direction: str) -> bool:
        """Aynı fiyattan tekrar giriş kontrolü."""
        orders = [t for t in self.trades if t.symbol == symbol]
        if not orders:
            return False

        last_trade = orders[-1]
        if last_trade.exit_reason != "STOP_LOSS":
            return False

        price_diff = abs(new_entry - last_trade.entry_price) / last_trade.entry_price
        if price_diff < self.SAME_PRICE_TOLERANCE:
            if last_trade.pnl_usdt < 0:
                return True
        return False

    # ═══════════════════════════════════════════════════════════
    # V6.5 YENİ: PİYASA REJİMİ FİLTRESİ
    # ═══════════════════════════════════════════════════════════

    def _check_regime_filter(self, symbol: str, signal: str) -> Tuple[bool, str, float]:
        """Piyasa rejimine göre sinyal filtreleme.

        Returns:
            (allowed, reason, size_multiplier)
        """
        try:
            df_4h = self.fetcher.fetch_ohlcv(symbol, "4h", limit=200)
            if df_4h.empty or len(df_4h) < 50:
                return True, "", 1.0

            df_4h = self.regime_detector.calculate_indicators(df_4h)
            regime = self.regime_detector.detect(df_4h, len(df_4h) - 1)

            if regime == MarketRegime.TREND_UP and signal == "SELL":
                return False, f"TREND_UP rejiminde SHORT engellendi", 1.0

            if regime == MarketRegime.TREND_DOWN and signal == "BUY":
                return False, f"TREND_DOWN rejiminde LONG engellendi", 1.0

            if regime == MarketRegime.VOLATILE:
                return True, "VOLATILE rejim — pozisyon küçültüldü", 0.50

            return True, f"Rejim: {regime.value}", 1.0

        except Exception as e:
            logger.warning(f"{symbol} rejim tespiti hatası: {e}")
            return True, "", 1.0

    # ═══════════════════════════════════════════════════════════
    # V6.5 YENİ: DİNAMİK STOP-LOSS
    # ═══════════════════════════════════════════════════════════

    def _calculate_dynamic_sl(self, entry_price: float, atr: float, side: str, df: pd.DataFrame) -> Tuple[float, float]:
        """Volatilite bazlı dinamik SL/TP hesaplar.

        Returns:
            (stop_loss, take_profit)
        """
        if self.mode == "v6.1":
            sl_mult = self.strategy.atr_sl_multiplier  # 1.5
            tp_mult = self.strategy.atr_tp_multiplier  # 2.5
            if side == "BUY":
                sl = entry_price - sl_mult * atr
                tp = entry_price + tp_mult * atr
            else:
                sl = entry_price + sl_mult * atr
                tp = entry_price - tp_mult * atr
            return sl, tp

        # ATR'nin uzun vadeli ortalamasını hesapla
        if "atr" in df.columns and len(df) >= 50:
            atr_series = df["atr"].dropna()
            if len(atr_series) >= 50:
                atr_ma = atr_series.iloc[-50:].mean()
            else:
                atr_ma = atr_series.mean()
        else:
            atr_ma = atr

        # Volatilite oranına göre SL çarpanı belirle
        if atr_ma > 0:
            vol_ratio = atr / atr_ma
        else:
            vol_ratio = 1.0

        if vol_ratio < 0.8:
            sl_mult = 1.5  # Düşük volatilite
        elif vol_ratio < 1.2:
            sl_mult = 2.0  # Normal
        elif vol_ratio < 1.8:
            sl_mult = 2.5  # Yüksek volatilite
        else:
            sl_mult = 3.0  # Aşırı volatilite

        tp_mult = 2.5  # TP her zaman 2.5x ATR

        if side == "BUY":
            sl = entry_price - sl_mult * atr
            tp = entry_price + tp_mult * atr
        else:
            sl = entry_price + sl_mult * atr
            tp = entry_price - tp_mult * atr

        return sl, tp

    # ═══════════════════════════════════════════════════════════
    # V6.5 YENİ: KORELASYON FİLTRESİ
    # ═══════════════════════════════════════════════════════════

    def _get_sector(self, symbol: str) -> Optional[str]:
        """Sembolün sektörünü döndürür."""
        for sector, symbols in self.SECTORS.items():
            if symbol in symbols:
                return sector
        return None

    def _check_sector_limit(self, symbol: str) -> Tuple[bool, str]:
        """Aynı sektörde max pozisyon sayısını kontrol eder."""
        sector = self._get_sector(symbol)
        if sector is None:
            return True, ""

        count = 0
        for pos_sym in self.positions:
            if self._get_sector(pos_sym) == sector:
                count += 1

        if count >= 2:
            return False, f"Sektör limiti: {sector}'da zaten {count} pozisyon var"

        return True, ""

    def _check_price_correlation(self, symbol: str) -> Tuple[bool, str]:
        """Fiyat korelasyonu kontrolü."""
        if not self.positions:
            return True, ""

        try:
            new_df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=100)
            if new_df.empty or len(new_df) < 30:
                return True, ""

            new_returns = new_df["close"].pct_change().dropna()

            for pos_sym in self.positions:
                pos_df = self.fetcher.fetch_ohlcv(pos_sym, "1h", limit=100)
                if pos_df.empty or len(pos_df) < 30:
                    continue

                pos_returns = pos_df["close"].pct_change().dropna()
                min_len = min(len(new_returns), len(pos_returns))
                if min_len < 20:
                    continue

                corr = np.corrcoef(
                    new_returns.iloc[-min_len:].values,
                    pos_returns.iloc[-min_len:].values,
                )[0, 1]

                if abs(corr) >= 0.70:
                    return False, f"Korelasyon: {symbol}↔{pos_sym} = {corr:.2f} (limit: 0.70)"

            return True, ""

        except Exception as e:
            logger.warning(f"{symbol} korelasyon kontrolü hatası: {e}")
            return True, ""

    # ═══════════════════════════════════════════════════════════
    # V6.5 YENİ: SEMBOL KALİTE FİLTRESİ
    # ═══════════════════════════════════════════════════════════

    def _check_symbol_quality(self, symbol: str) -> Tuple[bool, str]:
        """Sembol kalite kontrolü."""
        # Hariç tutulan semboller
        if symbol in self.EXCLUDED_SYMBOLS:
            return False, f"Hariç tutulan sembol: {symbol}"

        # Ardışık kayıp kontrolü
        losses = self._loss_counter.get(symbol, 0)
        if losses >= self.MAX_CONSECUTIVE_LOSSES:
            return False, f"Ardışık {losses} kayıp — {self.LOSS_COOLDOWN_HOURS}h bekleme"

        # Günlük hareket kontrolü
        try:
            df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=24)
            if not df.empty and len(df) >= 2:
                high_24h = float(df["high"].max())
                low_24h = float(df["low"].min())
                current = float(df.iloc[-1]["close"])
                if current > 0:
                    daily_range_pct = (high_24h - low_24h) / current * 100
                    if daily_range_pct > self.MAX_DAILY_MOVE_PCT:
                        return False, f"24h hareket %{daily_range_pct:.1f} > %{self.MAX_DAILY_MOVE_PCT} limit"
        except Exception:
            pass

        return True, ""

    # ═══════════════════════════════════════════════════════════
    # MEVCUT: Tarama ve İndikatörler (V6 ile aynı)
    # ═══════════════════════════════════════════════════════════

    def run_single_scan(self) -> List[dict]:
        self.fetcher.clear_cache()
        logger.info("=" * 60)
        logger.info("V6.5 TARAMA BAŞLIYOR")
        logger.info("=" * 60)

        try:
            symbols = self.fetcher.fetch_top_symbols(top_n=self.top_n, quote="USDT")
            if not symbols:
                logger.error("Sembol listesi alınamadı")
                return []
            logger.info(f"Top {len(symbols)} USDT çifti taranacak")
        except Exception as e:
            logger.error(f"Sembol listesi hatası: {e}")
            return []

        signals = []

        for symbol in symbols:
            try:
                # V6.5: Sembol kalite filtresi
                quality_ok, quality_reason = self._check_symbol_quality(symbol)
                if not quality_ok:
                    logger.debug(f"{symbol} atlandı: {quality_reason}")
                    continue

                df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=500)
                if df.empty or len(df) < 200:
                    continue

                df = self._add_indicators(df)

                for i in range(max(0, len(df) - 5), len(df)):
                    signal_dict = self.strategy.generate_signal(df, i)
                    if signal_dict:
                        signal_type = signal_dict["type"]
                        category = signal_dict["category"]
                        
                        # V6.1 modunda sadece SAFE sinyallerini işle ve kategorisini v6.1 yap
                        if self.mode == "v6.1":
                            if category != "SAFE":
                                continue
                            category = "v6.1"
                            
                        price = float(df.iloc[i]["close"])
                        atr = float(df.iloc[i].get("atr", price * 0.02))

                        # V6.5: Dinamik SL/TP
                        sl, tp = self._calculate_dynamic_sl(price, atr, signal_type, df.iloc[:i+1])

                        # Sinyal Güven Puanı hesapla
                        confidence = self._calculate_confidence_score(df, i, signal_type)

                        signals.append({
                            "symbol": symbol,
                            "signal": signal_type,
                            "category": category,
                            "price": price,
                            "stop_loss": sl,
                            "take_profit": tp,
                            "atr": atr,
                            "time": df.index[i],
                            "confidence": confidence,
                        })
                        logger.info(f"SİNYAL: {signal_type} ({category}) {symbol} @ {format_price(price)} | SL: {format_price(sl)} | TP: {format_price(tp)} | Güven: %{confidence:.1f}")

            except Exception as e:
                logger.error(f"{symbol} tarama hatası: {e}")

        # V6.5: Güven puanına göre azalan sırada sırala
        signals.sort(key=lambda x: x.get("confidence", 50.0), reverse=True)
        
        # Dashboard için signals.jsonl'e kaydet
        try:
            Path("logs").mkdir(exist_ok=True)
            with open(self.signals_jsonl_path, "a", encoding="utf-8") as f:
                now_str = pd.Timestamp.now().isoformat()
                if not signals:
                    f.write(json.dumps({"generated_at": now_str, "signal_type": "NO_SIGNAL", "symbol": "ALL", "confidence": 0.0}) + "\n")
                else:
                    for s in signals:
                        f.write(json.dumps({
                            "generated_at": now_str,
                            "symbol": s["symbol"],
                            "signal_type": s["signal"],
                            "category": s.get("category", "SAFE"),
                            "price": s["price"],
                            "confidence": s.get("confidence", 0.0),
                            "stop_loss": s.get("stop_loss", 0.0),
                            "take_profit": s.get("take_profit", 0.0)
                        }) + "\n")
        except Exception as e:
            logger.error(f"Sinyal loglama hatası: {e}")

        logger.info(f"Tarama tamamlandı: {len(signals)} sinyal bulundu (Güven puanına göre sıralandı)")
        return signals

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["bb_mid"] = df["close"].rolling(window=20).mean()
        bb_std = df["close"].rolling(window=20).std()
        df["bb_upper"] = df["bb_mid"] + 2.0 * bb_std
        df["bb_lower"] = df["bb_mid"] - 2.0 * bb_std
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
        df["bb_width_ma"] = df["bb_width"].rolling(window=20).mean()

        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))

        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=14).mean()

        df["volume_ma"] = df["volume"].rolling(window=20).mean()

        return df

    # ═══════════════════════════════════════════════════════════
    # MEVCUT: Stagnation Scoring (V6 ile aynı)
    # ═══════════════════════════════════════════════════════════

    def _calculate_stagnation_score(self, pos: dict) -> float:
        score = 0.0

        entry_time = pos.get("entry_time")
        if entry_time is not None:
            try:
                gecen_saat = (pd.Timestamp.now() - pd.Timestamp(entry_time)).total_seconds() / 3600
                score += min((gecen_saat / 4.0) * 40.0, 40.0)
            except Exception:
                score += 20.0

        entry_price = pos.get("entry_price", 0)
        tp_price = pos.get("take_profit", 0)
        current_price = pos.get("current_price", entry_price)
        if entry_price > 0 and tp_price > 0:
            side_up = str(pos.get("side", "")).upper()
            if "LONG" in side_up or side_up == "BUY":
                tp_hedef = tp_price - entry_price
                tp_gercek = current_price - entry_price
            else:
                tp_hedef = entry_price - tp_price
                tp_gercek = entry_price - current_price
            if tp_hedef > 0:
                ilerleme_oran = tp_gercek / tp_hedef
                score += max((1.0 - ilerleme_oran) * 35.0, 0.0)
            else:
                score += 35.0
        else:
            score += 35.0

        pnl_u = pos.get("pnl_usdt", 0.0)
        if pnl_u < 0:
            score += 25.0

        return min(score, 100.0)

    def _find_worst_position(self) -> tuple[str, float]:
        if not self.positions:
            return "", 0.0
        worst_sym = ""
        worst_score = -1.0
        for sym, pos in self.positions.items():
            s = self._calculate_stagnation_score(pos)
            if s > worst_score:
                worst_score = s
                worst_sym = sym
        return worst_sym, worst_score

    # ═══════════════════════════════════════════════════════════
    # V6.5: GELİŞMİŞ SİNYAL DEĞERLENDİRME
    # ═══════════════════════════════════════════════════════════

    def _calculate_confidence_score(self, df: pd.DataFrame, idx: int, signal: str) -> float:
        """Sinyalin güven/başarı olasılığı puanını hesaplar (Maks 100)."""
        try:
            if idx < 0 or idx >= len(df):
                return 50.0

            row = df.iloc[idx]
            close = float(row["close"])
            rsi = float(row.get("rsi", 50.0))
            volume = float(row.get("volume", 0.0))
            volume_ma = float(row.get("volume_ma", volume))
            atr = float(row.get("atr", close * 0.02))

            bb_lower = float(row.get("bb_lower", 0.0))
            bb_upper = float(row.get("bb_upper", 999999.0))

            rsi_score = 0.0
            bb_score = 0.0
            vol_score = 0.0
            div_score = 0.0

            # 1. RSI Ekstremite Puanı (Maks 30)
            if signal == "BUY":
                if rsi <= 30.0:
                    rsi_score = min((30.0 - rsi) * 2.0, 30.0)
            elif signal == "SELL":
                if rsi >= 70.0:
                    rsi_score = min((rsi - 70.0) * 2.0, 30.0)

            # 2. Bollinger Bandı Sapma Puanı (Maks 30)
            if atr > 0:
                if signal == "BUY" and close < bb_lower:
                    dev_atr = (bb_lower - close) / atr
                    bb_score = min(dev_atr * 30.0, 30.0)
                elif signal == "SELL" and close > bb_upper:
                    dev_atr = (close - bb_upper) / atr
                    bb_score = min(dev_atr * 30.0, 30.0)

            # 3. Hacim Patlaması Puanı (Maks 20)
            if volume_ma > 0:
                vol_ratio = volume / volume_ma
                if vol_ratio > 1.0:
                    vol_score = min((vol_ratio - 1.0) * 10.0, 20.0)

            # 4. Uyumsuzluk (Divergence) Puanı (Maks 20)
            is_div = False
            if signal == "BUY":
                is_div = self.strategy._check_bullish_divergence(df, idx)
            elif signal == "SELL":
                is_div = self.strategy._check_bearish_divergence(df, idx)

            if is_div:
                div_score = 20.0
            else:
                bb_width = float(row.get("bb_width", 0.0))
                bb_width_ma = float(row.get("bb_width_ma", bb_width))
                is_squeeze = bb_width < bb_width_ma * 0.8 if bb_width_ma > 0 else False
                if is_squeeze:
                    div_score = 10.0

            total_score = rsi_score + bb_score + vol_score + div_score
            return float(np.clip(total_score, 0.0, 100.0))

        except Exception as e:
            logger.error(f"Güven puanı hesaplama hatası: {e}")
            return 50.0

    def _evaluate_signal(self, signal: dict) -> None:
        symbol = signal["symbol"]
        sig_type = signal["signal"]
        direction = "LONG" if sig_type == "BUY" else "SHORT"

        # V6.5: Cooldown kontrolü
        in_cd, cd_reason = self._is_in_cooldown(symbol, direction)
        if in_cd:
            logger.info(f"⏱️ {symbol} atlandı: {cd_reason}")
            return

        # Aynı sembolde zaten pozisyon var mı?
        if symbol in self.positions:
            logger.info(f"{symbol} zaten açık pozisyonda")
            return

        # V6.5: Aynı fiyattan tekrar giriş kontrolü
        if self._check_same_price_reentry(symbol, signal["price"], direction):
            logger.warning(f"🚫 {symbol} aynı fiyattan tekrar giriş engellendi (önceki SL)")
            self._set_cooldown(symbol, direction, "Aynı fiyat SL tekrarı", self.COOLDOWN_SL_HOURS)
            return

        # V6.5: Sembol kalite filtresi
        if self.mode != "v6.1":
            quality_ok, quality_reason = self._check_symbol_quality(symbol)
            if not quality_ok:
                logger.info(f"🚫 {symbol} atlandı: {quality_reason}")
                return

        # V6.5: Piyasa rejimi filtresi
        if self.mode != "v6.1":
            regime_ok, regime_reason, size_mult = self._check_regime_filter(symbol, sig_type)
            if not regime_ok:
                logger.info(f"🚫 {symbol} atlandı: {regime_reason}")
                self.cycle_events.append(f"🚫 {symbol} | {regime_reason}")
                return
        else:
            regime_reason = ""
            size_mult = 1.0

        # V6.5: Sektör limiti kontrolü
        if self.mode != "v6.1":
            sector_ok, sector_reason = self._check_sector_limit(symbol)
            if not sector_ok:
                logger.info(f"🚫 {symbol} atlandı: {sector_reason}")
                return

        # V6.5: Korelasyon kontrolü
        if self.mode != "v6.1":
            corr_ok, corr_reason = self._check_price_correlation(symbol)
            if not corr_ok:
                logger.info(f"🚫 {symbol} atlandı: {corr_reason}")
                return

        # V6.5: Gelişmiş rotasyon (limit doluysa)
        if len(self.positions) >= self.max_positions:
            if self.mode == "v6.1":
                logger.warning(f"Pozisyon limiti dolu ({self.max_positions})")
                return

            if getattr(self, "_rotation_done_this_cycle", False):
                logger.info(f"Bu döngüde zaten 1 rotasyon yapıldı → {symbol} atlanıyor")
                return

            worst_sym, worst_score = self._find_worst_position()

            # V6.5: Majör çiftlerde daha yüksek eşik
            is_major = worst_sym in self.MAJOR_PAIRS
            threshold = self.MAJOR_ROTATION_THRESHOLD if is_major else self.ROTATION_THRESHOLD

            if worst_score >= threshold:
                # V6.5: Rotasyon zarar limiti kontrolü
                worst_pos = self.positions[worst_sym]
                worst_pnl = worst_pos.get("pnl_usdt", 0.0)
                if worst_pnl < -self.MAX_ROTATION_LOSS:
                    logger.warning(f"🔄 Rotasyon engellendi: {worst_sym} zararı ${worst_pnl:.2f} > limit ${self.MAX_ROTATION_LOSS}")
                    return

                logger.info(f"🔄 ROTASYON: {worst_sym} → skor={worst_score:.1f} >= eşik={threshold}")
                try:
                    df_rot = self.fetcher.fetch_ohlcv(worst_sym, "1h", limit=1)
                    rot_price = float(df_rot.iloc[-1]["close"]) if not df_rot.empty else self.positions[worst_sym]["current_price"]
                except Exception:
                    rot_price = self.positions[worst_sym].get("current_price", self.positions[worst_sym]["entry_price"])

                # Rotasyon yönlü
                rot_dir = "LONG" if self.positions[worst_sym]["side"] in ("LONG", "BUY") else "SHORT"
                self._close_position(worst_sym, rot_price, "ROTATION")
                del self.positions[worst_sym]
                self._set_cooldown(worst_sym, rot_dir, "Rotasyon", self.COOLDOWN_ROTATION_HOURS)
                self._rotation_done_this_cycle = True
            else:
                logger.warning(f"Pozisyon limiti dolu | En kötü: {worst_sym} skor={worst_score:.1f} < {threshold}")
                return

        # V6.5 YENİ: Yapay Zeka (ML) Sinyal Filtresi ve Dinamik Boyutlandırma
        if self.mode != "v6.1" and self.ml_filter.is_trained:
            try:
                df_ml = self.fetcher.fetch_ohlcv(symbol, "1h", limit=200)
                if not df_ml.empty and len(df_ml) >= 50:
                    from run_backtest import prepare_data
                    df_ml = prepare_data(df_ml)
                    
                    ml_prob = self.ml_filter.predict_probability(df_ml, len(df_ml) - 1, sig_type)
                    logger.info(f"🤖 [ML Analizi] {symbol} {direction} Sinyali Kazanma Olasılığı: %{ml_prob*100:.1f}")
                    
                    signal["confidence"] = ml_prob * 100
                    
                    if ml_prob < 0.60:
                        logger.warning(f"🚫 {symbol} atlandı: ML Kazanma Olasılığı %{ml_prob*100:.1f} < %60 limit")
                        self.cycle_events.append(f"🚫 {symbol} | ML Olasılık Düşük (%{ml_prob*100:.1f})")
                        return
                        
                    if ml_prob >= 0.80:
                        size_mult *= 1.5
                        logger.info(f"🔥 Yüksek ML Güveni: Pozisyon boyutu 1.5x yapıldı (Yeni çarpan: {size_mult:.2f})")
                    elif ml_prob >= 0.70:
                        size_mult *= 1.2
                        logger.info(f"✨ İyi ML Güveni: Pozisyon boyutu 1.2x yapıldı (Yeni çarpan: {size_mult:.2f})")
                    elif ml_prob < 0.65:
                        size_mult *= 0.8
                        logger.info(f"⚠️ Düşük ML Güveni: Pozisyon boyutu 0.8x yapıldı (Yeni çarpan: {size_mult:.2f})")
            except Exception as e:
                logger.error(f"ML onay filtreleme aşamasında hata: {e}")

        # Pozisyon büyüklüğü (V6.5: rejime göre ayarla)
        position_value = self.balance * self.position_pct * size_mult
        if position_value < 10:
            logger.warning(f"Yetersiz bakiye: ${self.balance:,.2f}")
            return

        # Pozisyon aç
        entry_price = signal["price"]
        amount = position_value / entry_price
        commission = position_value * 0.001

        # V6.5: Giriş RSI'sını kaydet (yapı kırılma kontrolü için)
        entry_rsi = 50.0
        try:
            df_entry = self.fetcher.fetch_ohlcv(symbol, "1h", limit=20)
            if not df_entry.empty and len(df_entry) >= 15:
                df_entry = self._add_indicators(df_entry)
                entry_rsi = float(df_entry.iloc[-1].get("rsi", 50))
        except Exception:
            pass

        confidence = signal.get("confidence", 50.0)
        category = signal.get("category", "SAFE")
        
        self.positions[symbol] = {
            "side": direction,
            "category": category,
            "entry_price": entry_price,
            "amount": amount,
            "stop_loss": signal["stop_loss"],
            "take_profit": signal["take_profit"],
            "entry_time": signal["time"],
            "partial_tp_level": 0,
            "original_amount": amount,
            "entry_rsi": entry_rsi,
            "confidence": confidence,
        }

        self.balance -= (position_value + commission)

        logger.info(f"POZİSYON AÇILDI: {sig_type} {symbol} ({category} | Güven: %{confidence:.1f})")
        logger.info(f"  Giriş: {format_price(entry_price)} | Miktar: {amount:.6f}")
        logger.info(f"  SL: {format_price(signal['stop_loss'])} | TP: {format_price(signal['take_profit'])}")
        if regime_reason:
            logger.info(f"  Rejim: {regime_reason}")

        yon = direction
        emoji_cat = "⚙️" if category == "v6.1" else ("✅" if category == "SAFE" else "⚠️")
        cat_str = "V6.1" if category == "v6.1" else ("Güvenli (SAFE)" if category == "SAFE" else "Esnetilmiş (RELAXED)")
        
        # Telegram anında bildirim
        msg = (
            f"{emoji_cat} YENİ POZİSYON AÇILDI\n"
            f"Kategori: {cat_str}\n"
            f"Parite: {symbol} ({yon})\n"
            f"Giriş: {format_price(entry_price)}\n"
            f"Hedef (TP): {format_price(signal['take_profit'])}\n"
            f"Zarar Kes (SL): {format_price(signal['stop_loss'])}\n"
            f"Güven: %{confidence:.1f}"
        )
        send_telegram_notification(msg)
        
        self.cycle_events.append(
            f"📈 {symbol} ({yon}) | {cat_str} Pozisyon (Güven: %{confidence:.1f})\n"
            f"   Giriş: {format_price(entry_price)} | TP: {format_price(signal['take_profit'])}"
        )
        self._save_state()

    # ═══════════════════════════════════════════════════════════
    # V6.5: GELİŞMİŞ POZİSYON KONTROLÜ
    # ═══════════════════════════════════════════════════════════

    def _check_positions(self) -> None:
        closed = []

        for symbol, pos in self.positions.items():
            try:
                df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=1)
                if df.empty:
                    continue

                current_price = float(df.iloc[-1]["close"])
                pos["current_price"] = current_price

                side_up = str(pos["side"]).upper()
                if "LONG" in side_up or side_up == "BUY":
                    pnl_u = (current_price - pos["entry_price"]) * pos["amount"]
                else:
                    pnl_u = (pos["entry_price"] - current_price) * pos["amount"]

                cost = pos["entry_price"] * pos["amount"]
                pnl_p = (pnl_u / cost) if cost > 0 else 0.0

                pos["pnl_usdt"] = pnl_u
                pos["pnl_pct"] = pnl_p

                if "LONG" in side_up or side_up == "BUY":
                    pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), current_price)
                else:
                    pos["lowest_price"] = min(pos.get("lowest_price", pos["entry_price"]), current_price)

                # V6.5: Kademeli Kâr Alma (Partial TP)
                tp_closed = self._check_partial_tp(symbol, pos, current_price)
                if tp_closed:
                    closed.append(symbol)
                    continue

                # V6.5: Gelişmiş Breakeven SL
                self._check_breakeven_sl(symbol, pos, current_price)

                # V6.5: Grafik yapısı kırılma kontrolü (en az 1 saat açık pozisyonlar için)
                entry_time = pos.get("entry_time")
                if entry_time is not None:
                    try:
                        hours_open = (pd.Timestamp.now() - pd.Timestamp(entry_time)).total_seconds() / 3600
                        if hours_open >= 1.0:
                            if self._check_structure_break(symbol, pos, current_price):
                                closed.append(symbol)
                                continue
                    except Exception:
                        pass

                # Trailing TP (V6 ile aynı)
                tp_closed = self._check_trailing_tp(symbol, pos, current_price)
                if tp_closed:
                    closed.append(symbol)
                    continue

                # SL/TP kontrolü
                if "LONG" in side_up or side_up == "BUY":
                    if current_price <= pos["stop_loss"]:
                        self._close_position(symbol, current_price, "STOP_LOSS")
                        closed.append(symbol)
                    elif current_price >= pos["take_profit"]:
                        self._close_position(symbol, current_price, "TAKE_PROFIT")
                        closed.append(symbol)
                else:
                    if current_price >= pos["stop_loss"]:
                        self._close_position(symbol, current_price, "STOP_LOSS")
                        closed.append(symbol)
                    elif current_price <= pos["take_profit"]:
                        self._close_position(symbol, current_price, "TAKE_PROFIT")
                        closed.append(symbol)

            except Exception as e:
                logger.error(f"{symbol} pozisyon kontrol hatası: {e}")

        for sym in closed:
            if sym in self.positions:
                del self.positions[sym]

    def _check_partial_tp(self, symbol: str, pos: dict, current_price: float) -> bool:
        """V6.5: Kademeli kâr alma kontrolü."""
        entry_price = pos["entry_price"]
        tp_price = pos["take_profit"]
        side_up = str(pos["side"]).upper()

        if "LONG" in side_up or side_up == "BUY":
            tp_target = tp_price - entry_price
            tp_progress = current_price - entry_price
        else:
            tp_target = entry_price - tp_price
            tp_progress = entry_price - current_price

        if tp_target <= 0:
            return False

        progress_pct = tp_progress / tp_target
        current_level = pos.get("partial_tp_level", 0)

        # Seviye 1: %50 progress → %30 kapat, SL maliyete çek
        if progress_pct >= 0.50 and current_level < 1:
            close_amount = pos["original_amount"] * 0.30
            if close_amount > 0 and pos["amount"] > close_amount:
                partial_pnl = self._calculate_partial_pnl(pos, current_price, close_amount)
                pos["amount"] -= close_amount
                self.balance += close_amount * current_price - partial_pnl * 0.001
                pos["partial_tp_level"] = 1

                # SL'yi maliyete çek
                if "LONG" in side_up or side_up == "BUY":
                    pos["stop_loss"] = max(pos["stop_loss"], entry_price * 1.002)
                else:
                    pos["stop_loss"] = min(pos["stop_loss"], entry_price * 0.998)
                pos["sl_to_breakeven"] = True

                logger.info(f"💰 {symbol} Partial TP-1: %30 kapatıldı, SL maliyete çekildi")
                self.cycle_events.append(f"💰 {symbol} | Partial TP-1: %30 kapatıldı")
                self._save_state()
                return False

        # Seviye 2: %70 progress → %30 daha kapat, trailing başlat
        if progress_pct >= 0.70 and current_level < 2:
            close_amount = pos["original_amount"] * 0.30
            if close_amount > 0 and pos["amount"] > close_amount:
                pos["amount"] -= close_amount
                pos["partial_tp_level"] = 2

                logger.info(f"💰 {symbol} Partial TP-2: %30 daha kapatıldı, trailing başlatıldı")
                self.cycle_events.append(f"💰 {symbol} | Partial TP-2: trailing aktif")
                self._save_state()
                return False

        # Seviye 3: %100 progress → tamamlandı
        if progress_pct >= 1.0 and current_level < 3:
            self._close_position(symbol, current_price, "TAKE_PROFIT")
            return True

        return False

    def _calculate_partial_pnl(self, pos: dict, exit_price: float, amount: float) -> float:
        """Partial close için PnL hesaplar."""
        if pos["side"] in ("LONG", "BUY"):
            return (exit_price - pos["entry_price"]) * amount
        else:
            return (pos["entry_price"] - exit_price) * amount

    def _check_breakeven_sl(self, symbol: str, pos: dict, current_price: float) -> None:
        """V6.5: Breakeven SL kontrolü."""
        if pos.get("sl_to_breakeven", False):
            return

        entry_price = pos["entry_price"]
        tp_price = pos["take_profit"]
        side_up = str(pos["side"]).upper()

        if "LONG" in side_up or side_up == "BUY":
            tp_target = tp_price - entry_price
            tp_progress = current_price - entry_price
        else:
            tp_target = entry_price - tp_price
            tp_progress = entry_price - current_price

        if tp_target > 0:
            progress_pct = tp_progress / tp_target
            if progress_pct >= 0.50:
                if "LONG" in side_up or side_up == "BUY":
                    new_sl = entry_price * 1.002
                    if pos["stop_loss"] < new_sl:
                        pos["stop_loss"] = new_sl
                        pos["sl_to_breakeven"] = True
                        logger.info(f"🛡️ {symbol} SL maliyete çekildi: {format_price(new_sl)}")
                        self.cycle_events.append(f"🛡️ {symbol} | SL maliyete çekildi")
                else:
                    new_sl = entry_price * 0.998
                    if pos["stop_loss"] > new_sl:
                        pos["stop_loss"] = new_sl
                        pos["sl_to_breakeven"] = True
                        logger.info(f"🛡️ {symbol} SL maliyete çekildi: {format_price(new_sl)}")
                        self.cycle_events.append(f"🛡️ {symbol} | SL maliyete çekildi")

    def _check_trailing_tp(self, symbol: str, pos: dict, current_price: float) -> bool:
        """Trailing TP kontrolü (V6 ile aynı mantık)."""
        side_up = str(pos["side"]).upper()

        if "LONG" in side_up or side_up == "BUY":
            tp_target = pos["take_profit"] - pos["entry_price"]
            if tp_target > 0:
                max_progress = (pos.get("highest_price", pos["entry_price"]) - pos["entry_price"]) / tp_target
                if max_progress >= 0.70:
                    trigger_price = pos.get("highest_price", pos["entry_price"]) - 0.20 * tp_target
                    if current_price <= trigger_price:
                        self._close_position(symbol, current_price, "EARLY_TP")
                        return True
        else:
            tp_target = pos["entry_price"] - pos["take_profit"]
            if tp_target > 0:
                max_progress = (pos["entry_price"] - pos.get("lowest_price", pos["entry_price"])) / tp_target
                if max_progress >= 0.70:
                    trigger_price = pos.get("lowest_price", pos["entry_price"]) + 0.20 * tp_target
                    if current_price >= trigger_price:
                        self._close_position(symbol, current_price, "EARLY_TP")
                        return True

        return False

    # ═══════════════════════════════════════════════════════════
    # V6.5 YENİ: GRAFİK YAPISI KIRILMA KONTROLÜ
    # Pozisyon açıkken teknik yapıyı izler, bozulursa kapatır
    # ═══════════════════════════════════════════════════════════

    def _check_structure_break(self, symbol: str, pos: dict, current_price: float) -> bool:
        """Açık pozisyonun teknik yapısını kontrol eder.

        Giriş sinyali veren koşullar bozulduysa pozisyonu kapatır:
        - LONG: RSI tekrar aşırı satıma döndü, fiyat BB altına düştü, hacim çöktü
        - SHORT: RSI tekrar aşırı alıma döndü, fiyat BB üstüne çıktı, hacim çöktü
        - Her iki yön: 4h trend ters döndü

        Returns:
            True ise pozisyon kapatıldı.
        """
        try:
            df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=50)
            if df.empty or len(df) < 30:
                return False

            df = self._add_indicators(df)
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else last

            rsi = float(last.get("rsi", 50))
            prev_rsi = float(prev.get("rsi", 50))
            bb_mid = float(last.get("bb_mid", current_price))
            bb_lower = float(last.get("bb_lower", 0))
            bb_upper = float(last.get("bb_upper", 999999))
            volume = float(last.get("volume", 0))
            volume_ma = float(last.get("volume_ma", volume))

            side_up = str(pos["side"]).upper()
            reasons = []

            if "LONG" in side_up or side_up == "BUY":
                # Yapı kırılma 1: RSI toparlandıktan sonra tekrar çöktü (45'in altına)
                entry_rsi = pos.get("entry_rsi", 30)
                if entry_rsi < 35 and rsi > 40 and prev_rsi > 40:
                    # RSI bir toparlanma yaşadı, ama şimdi tekrar düşüyor
                    pass
                if rsi < 25 and rsi < prev_rsi:
                    reasons.append(f"RSI çöküşü: {rsi:.1f} (düşüyor)")

                # Yapı kırılma 2: Fiyat BB ortasının belirgin şekilde altına düştü
                if bb_mid > 0 and current_price < bb_mid * 0.98:
                    reasons.append(f"BB orta altında: {format_price(current_price)} < {format_price(bb_mid)}")

                # Yapı kırılma 3: Hacim çöktü (alım baskısı yok)
                if volume_ma > 0 and volume < volume_ma * 0.4:
                    reasons.append(f"Hacim çöküşü: {volume:.0f} / ort {volume_ma:.0f}")

                # Yapı kırılma 4: Fiyat girişten beri en düşük seviyede ve SL'a yaklaşıyor
                sl_distance = abs(pos["stop_loss"] - current_price) / current_price if current_price > 0 else 0
                if current_price <= pos.get("lowest_price", current_price) and sl_distance < 0.005:
                    reasons.append("Fiyat dip + SL'a çok yakın")

            else:  # SHORT
                # Yapı kırılma 1: RSI tekrar aşırı alıma döndü
                if rsi > 75 and rsi > prev_rsi:
                    reasons.append(f"RSI aşırı alım: {rsi:.1f} (yükseliyor)")

                # Yapı kırılma 2: Fiyat BB ortasının belirgin şekilde üstüne çıktı
                if bb_mid > 0 and current_price > bb_mid * 1.02:
                    reasons.append(f"BB orta üstünde: {format_price(current_price)} > {format_price(bb_mid)}")

                # Yapı kırılma 3: Hacim çöktü
                if volume_ma > 0 and volume < volume_ma * 0.4:
                    reasons.append(f"Hacim çöküşü: {volume:.0f} / ort {volume_ma:.0f}")

                # Yapı kırılma 4: Fiyat girişten beri en yüksek seviyede ve SL'a yaklaşıyor
                sl_distance = abs(pos["stop_loss"] - current_price) / current_price if current_price > 0 else 0
                if current_price >= pos.get("highest_price", current_price) and sl_distance < 0.005:
                    reasons.append("Fiyat tepe + SL'a çok yakın")

            # 4h trend kontrolü (her iki yön için)
            try:
                df_4h = self.fetcher.fetch_ohlcv(symbol, "4h", limit=50)
                if not df_4h.empty and len(df_4h) >= 20:
                    df_4h = self._add_indicators(df_4h)
                    rsi_4h = float(df_4h.iloc[-1].get("rsi", 50))

                    if "LONG" in side_up or side_up == "BUY":
                        if rsi_4h < 35:
                            reasons.append(f"4h trend düşüş: RSI={rsi_4h:.1f}")
                    else:
                        if rsi_4h > 65:
                            reasons.append(f"4h trend yükseliş: RSI={rsi_4h:.1f}")
            except Exception:
                pass

            # En az 2 koşul sağlanırsa yapısal kırılma var
            if len(reasons) >= 2:
                logger.warning(f"📉 {symbol} YAPI KIRILMASI ({len(reasons)} koşul): {' | '.join(reasons)}")
                self._close_position(symbol, current_price, "STRUCTURE_BREAK")
                return True

            # Tek güçlü sinyal de tetikleyebilir (RSI çöküşü veya 4h trend)
            if len(reasons) == 1:
                strong_signals = ["RSI çöküşü", "4h trend"]
                if any(s in reasons[0] for s in strong_signals):
                    # Ama sadece kârdaysa veya zarar küçükse erken kapat
                    pnl = pos.get("pnl_usdt", 0)
                    if pnl >= 0 or pnl > -15:
                        logger.warning(f"📉 {symbol} YAPI KIRILMASI (güçlü sinyal): {reasons[0]}")
                        self._close_position(symbol, current_price, "STRUCTURE_BREAK")
                        return True

            return False

        except Exception as e:
            logger.error(f"{symbol} yapı kontrolü hatası: {e}")
            return False

    # ═══════════════════════════════════════════════════════════
    # POZİSYON KAPATMA (V6 ile aynı + V6.5 ekleri)
    # ═══════════════════════════════════════════════════════════

    def _close_position(self, symbol: str, exit_price: float, reason: str) -> None:
        pos = self.positions[symbol]

        if pos["side"] in ("LONG", "BUY"):
            pnl = (exit_price - pos["entry_price"]) * pos["amount"]
        else:
            pnl = (pos["entry_price"] - exit_price) * pos["amount"]

        commission = (pos["entry_price"] * pos["amount"] + exit_price * pos["amount"]) * 0.001
        net_pnl = pnl - commission

        self.balance += pos["entry_price"] * pos["amount"] + net_pnl

        trade = TradeRecord(
            symbol=symbol,
            side=pos["side"],
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            entry_time=pos["entry_time"],
            exit_time=pd.Timestamp.now(),
            amount=pos["amount"],
            pnl_usdt=net_pnl,
            pnl_pct=net_pnl / (pos["entry_price"] * pos["amount"]) if pos["entry_price"] * pos["amount"] > 0 else 0,
            commission=commission,
            hold_duration_hours=(pd.Timestamp.now() - pos["entry_time"]).total_seconds() / 3600,
            exit_reason=reason,
        )
        self.trades.append(trade)

        # V6.5: Ardışık kayıp sayacı güncelle
        if net_pnl < 0:
            self._loss_counter[symbol] = self._loss_counter.get(symbol, 0) + 1
            if self._loss_counter[symbol] >= self.MAX_CONSECUTIVE_LOSSES:
                self._set_cooldown(symbol, pos["side"], f"Ardışık {self._loss_counter[symbol]} kayıp", self.LOSS_COOLDOWN_HOURS)
        else:
            self._loss_counter[symbol] = 0

        emoji = "✅" if net_pnl > 0 else "❌"
        logger.info(f"{emoji} POZİSYON KAPATILDI: {symbol} | {reason}")
        logger.info(f"  Kâr/Zarar: ${net_pnl:+,.2f} ({trade.pnl_pct * 100:+.2f}%)")

        if reason == "TAKE_PROFIT":
            emoji_tg = "✅"
        elif reason == "STOP_LOSS":
            emoji_tg = "🛑"
        elif reason == "ROTATION":
            emoji_tg = "🔄"
        elif reason == "EARLY_TP":
            emoji_tg = "💵"
        elif reason == "STRUCTURE_BREAK":
            emoji_tg = "📉"
        else:
            emoji_tg = "✅" if net_pnl > 0 else "❌"

        yon = 'LONG' if pos['side'] in ('LONG', 'BUY') else 'SHORT'
        pnl_pct_formatted = f"+%{trade.pnl_pct * 100:.2f}" if trade.pnl_pct >= 0 else f"-%{abs(trade.pnl_pct * 100):.2f}"
        
        # Telegram anında bildirim
        category = pos.get("category", "SAFE")
        cat_str = "V6.1" if category == "v6.1" else ("Güvenli (SAFE)" if category == "SAFE" else "Esnetilmiş (RELAXED)")
        msg = (
            f"{emoji_tg} POZİSYON KAPANDI ({reason})\n"
            f"Kategori: {cat_str}\n"
            f"Parite: {symbol} ({yon})\n"
            f"Çıkış Fiyatı: {format_price(exit_price)}\n"
            f"Kâr/Zarar: {net_pnl:+,.2f} USDT ({pnl_pct_formatted})"
        )
        send_telegram_notification(msg)
        
        self.cycle_events.append(
            f"{emoji_tg} {symbol} ({yon}) | {reason} ile kapandı\n"
            f"   Çıkış: {format_price(exit_price)} | PnL: {net_pnl:+,.2f} USDT ({pnl_pct_formatted})"
        )
        self._save_state()

    # ═══════════════════════════════════════════════════════════
    # DÖNGÜ VE DURUM RAPORU (V6 ile aynı)
    # ═══════════════════════════════════════════════════════════

    def run_loop(self, interval_minutes: int = 60) -> None:
        logger.info("=" * 60)
        logger.info("V6.5 PERİYODİK DÖNGÜ BAŞLADI")
        logger.info(f"Tarama aralığı: {interval_minutes} dakika")
        logger.info("=" * 60)

        self._save_state()

        try:
            while True:
                self.cycle_events = []
                self._check_positions()

                signals = self.run_single_scan()

                self._rotation_done_this_cycle = False
                for sig in signals:
                    self._evaluate_signal(sig)

                self._print_status()
                self._save_state()

                logger.info(f"Sonraki tarama: {interval_minutes} dakika sonra")
                time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            logger.info("Durduruldu (Ctrl+C)")
            self._print_final_report()

    def _print_status(self) -> None:
        total_pnl = sum(t.pnl_usdt for t in self.trades)
        win_trades = sum(1 for t in self.trades if t.pnl_usdt > 0)
        total_trades = len(self.trades)
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

        logger.info("\n" + "=" * 60)
        logger.info("V6.5 DURUM RAPORU")
        logger.info("=" * 60)
        logger.info(f"  Bakiye:      ${self.balance:,.2f}")
        logger.info(f"  Toplam PnL:  ${total_pnl:+,.2f}")
        logger.info(f"  Açık Pozisyon: {len(self.positions)}")
        logger.info(f"  Toplam İşlem: {total_trades}")
        logger.info(f"  Kazanma Oranı: %{win_rate:.1f}")
        logger.info(f"  Cooldown: {len(self._cooldown_map)} sembol")
        logger.info("=" * 60)

        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        now = pd.Timestamp.now().strftime("%d.%m.%Y %H:%M")
        mod = '🔴 CANLI' if self.is_live else '🟢 PAPER'

        lines = [
            f"📊 V6.5 Enhanced Durum Raporu",
            f"🕐 {now} | {mod}",
            f"----------------------------------",
            f"",
            f"💰 Boştaki Nakit: ${self.balance:,.2f} USDT",
            f"📈 Başlangıç Sermayesi: ${self.initial_capital:,.2f} USDT",
            f"{pnl_emoji} Toplam Net Kâr: {total_pnl:+,.2f} USDT",
            f"📊 Açık Pozisyon: {len(self.positions)} adet",
            f"🔢 Toplam İşlem: {total_trades} | Kazanma: %{win_rate:.1f}",
        ]

        if self._cooldown_map:
            lines.append(f"⏱️ Cooldown: {len(self._cooldown_map)} sembol beklemede")

        if self.cycle_events:
            lines.append(f"")
            lines.append(f"🔔 Bu Döngüdeki İşlemler:")
            lines.extend(self.cycle_events)

        if self.positions:
            lines.append(f"")
            lines.append(f"📂 Açık Pozisyonlar:")
            total_cost = 0.0
            total_unrealized = 0.0
            for sym, pos in self.positions.items():
                side_emoji = "🟢" if pos["side"] in ('LONG', 'BUY') else "🔴"
                side_label = "LONG" if pos["side"] in ('LONG', 'BUY') else "SHORT"

                cost = pos["entry_price"] * pos["amount"]
                total_cost += cost

                pnl_u = pos.get("pnl_usdt", 0.0)
                pnl_p = pos.get("pnl_pct", 0.0)
                total_unrealized += pnl_u

                pnl_pct_formatted = f"+%{pnl_p * 100:.2f}" if pnl_p >= 0 else f"-%{abs(pnl_p * 100):.2f}"

                lines.append(f"")
                lines.append(f"• {sym} ({side_emoji} {side_label})")
                lines.append(f"  💰 Giriş: {format_price(pos['entry_price'])}")
                lines.append(f"  🔍 Güncel: {format_price(pos.get('current_price', pos['entry_price']))}")
                lines.append(f"  📊 PnL: {pnl_u:+,.2f} USDT ({pnl_pct_formatted})")
                lines.append(f"  🛡️ SL: {format_price(pos.get('stop_loss', 0))} | TP: {format_price(pos.get('take_profit', 0))}")

                # V6.5: Partial TP seviyesi göster
                ptl = pos.get("partial_tp_level", 0)
                if ptl > 0:
                    lines.append(f"  💰 Partial TP: Seviye {ptl}/3 tamamlandı")

            total_unrealized_pct = (total_unrealized / total_cost) if total_cost > 0 else 0.0
            total_unrealized_pct_formatted = f"+%{total_unrealized_pct * 100:.2f}" if total_unrealized_pct >= 0 else f"-%{abs(total_unrealized_pct * 100):.2f}"

            lines.append(f"")
            lines.append(f"----------------------------------")
            lines.append(f"📐 Toplam Pozisyon Maliyeti: ${total_cost:,.2f} USDT")
            lines.append(f"📊 Toplam Açık PnL: {total_unrealized:+,.2f} USDT ({total_unrealized_pct_formatted})")
            lines.append(f"💵 Toplam Portföy Değeri: ${self.balance + total_cost + total_unrealized:,.2f} USDT")
        else:
            lines.append(f"")
            lines.append(f"📂 Açık pozisyon yok.")
            
        # Önceden burada send_telegram_notification vardı, 15 dakikalık periyodik mesajları kapatmak için kaldırıldı.
        # logger.debug("\n".join(lines))

    def _print_final_report(self) -> None:
        self._print_status()
        if self.trades:
            logger.info("\nİŞLEM LİSTESİ:")
            for t in self.trades:
                emoji = "✅" if t.pnl_usdt > 0 else "❌"
                logger.info(f"  {emoji} {t.symbol} | {t.side} | ${t.pnl_usdt:+,.2f} | {t.exit_reason}")

    # ═══════════════════════════════════════════════════════════
    # DURUM KAYDETME / YÜKLEME (V6.5 genişletilmiş)
    # ═══════════════════════════════════════════════════════════

    def _save_state(self) -> None:
        try:
            Path("logs").mkdir(exist_ok=True)

            formatted_positions = {}
            for sym, pos in self.positions.items():
                cost = pos["entry_price"] * pos["amount"]
                formatted_positions[sym] = {
                    "side": pos["side"],
                    "category": pos.get("category", "SAFE"),
                    "entry_price": pos["entry_price"],
                    "current_price": pos.get("current_price", pos["entry_price"]),
                    "amount": pos["amount"],
                    "cost_usdt": cost,
                    "stop_loss": pos.get("stop_loss", 0),
                    "take_profit": pos.get("take_profit", 0),
                    "sl_to_breakeven": pos.get("sl_to_breakeven", False),
                    "highest_price": pos.get("highest_price", pos["entry_price"]),
                    "lowest_price": pos.get("lowest_price", pos["entry_price"]),
                    "pnl_usdt": pos.get("pnl_usdt", 0.0),
                    "pnl_pct": pos.get("pnl_pct", 0.0),
                    "status": "active",
                    "entry_time": pos.get("entry_time", pd.Timestamp.now()).isoformat() if hasattr(pos.get("entry_time", ""), "isoformat") else str(pos.get("entry_time", "")),
                    "partial_tp_level": pos.get("partial_tp_level", 0),
                    "original_amount": pos.get("original_amount", pos["amount"]),
                }

            orders = []
            for t in self.trades:
                orders.append({
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "amount": t.amount,
                    "pnl_usdt": t.pnl_usdt,
                    "pnl_pct": t.pnl_pct,
                    "close_reason": t.exit_reason,
                    "status": "filled",
                    "timestamp": t.exit_time.isoformat(),
                })

            # V6.5: Cooldown ve kayıp sayacı da kaydet
            cooldown_data = {}
            for sym, cd in self._cooldown_map.items():
                cooldown_data[sym] = {
                    "until": cd["until"].isoformat() if hasattr(cd["until"], "isoformat") else str(cd["until"]),
                    "direction": cd.get("direction", ""),
                    "reason": cd.get("reason", ""),
                }

            state = {
                "usdt_balance": self.balance,
                "open_positions": formatted_positions,
                "orders": orders,
                "total_pnl": sum(t.pnl_usdt for t in self.trades),
                "total_trades": len(self.trades),
                "win_rate": (sum(1 for t in self.trades if t.pnl_usdt > 0) / len(self.trades) * 100) if self.trades else 0,
                "last_updated": pd.Timestamp.now(tz="UTC").isoformat(),
                "version": "v6.5",
                "cooldown_map": cooldown_data,
                "loss_counter": self._loss_counter,
            }
            with open(self.portfolio_state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Durum kaydetme hatası: {e}")

    def _load_state(self) -> None:
        try:
            state_path = Path(self.portfolio_state_path)
            if state_path.exists():
                with open(state_path, encoding="utf-8") as f:
                    state = json.load(f)

                self.balance = state.get("usdt_balance", self.initial_capital)

                open_pos = state.get("open_positions", {})
                self.positions = {}
                for sym, pos in open_pos.items():
                    self.positions[sym] = {
                        "side": pos.get("side"),
                        "entry_price": pos.get("entry_price"),
                        "current_price": pos.get("current_price", pos.get("entry_price")),
                        "amount": pos.get("amount"),
                        "cost_usdt": pos.get("cost_usdt", pos.get("entry_price") * pos.get("amount")),
                        "stop_loss": pos.get("stop_loss"),
                        "take_profit": pos.get("take_profit"),
                        "sl_to_breakeven": pos.get("sl_to_breakeven", False),
                        "highest_price": pos.get("highest_price", pos.get("entry_price")),
                        "lowest_price": pos.get("lowest_price", pos.get("entry_price")),
                        "pnl_usdt": pos.get("pnl_usdt", 0.0),
                        "pnl_pct": pos.get("pnl_pct", 0.0),
                        "status": pos.get("status", "active"),
                        "entry_time": pd.Timestamp(pos.get("entry_time")) if pos.get("entry_time") else pd.Timestamp.now(),
                        "partial_tp_level": pos.get("partial_tp_level", 0),
                        "original_amount": pos.get("original_amount", pos.get("amount")),
                    }

                orders = state.get("orders", [])
                self.trades = []
                for o in orders:
                    self.trades.append(TradeRecord(
                        symbol=o.get("symbol"),
                        side=o.get("side"),
                        entry_price=o.get("entry_price"),
                        exit_price=o.get("exit_price"),
                        entry_time=pd.Timestamp(o.get("timestamp")) - pd.Timedelta(hours=1),
                        exit_time=pd.Timestamp(o.get("timestamp")),
                        amount=o.get("amount"),
                        pnl_usdt=o.get("pnl_usdt"),
                        pnl_pct=o.get("pnl_pct"),
                        commission=0.0,
                        hold_duration_hours=1.0,
                        exit_reason=o.get("close_reason"),
                    ))

                # V6.5: Cooldown ve kayıp sayacı yükle
                cooldown_data = state.get("cooldown_map", {})
                for sym, cd in cooldown_data.items():
                    self._cooldown_map[sym] = {
                        "until": pd.Timestamp(cd["until"]),
                        "direction": cd.get("direction", ""),
                        "reason": cd.get("reason", ""),
                    }

                self._loss_counter = state.get("loss_counter", {})

                logger.info(f"Kayıtlı durum yüklendi | Bakiye: ${self.balance:,.2f} | Açık: {list(self.positions.keys())} | Cooldown: {len(self._cooldown_map)}")
        except Exception as e:
            logger.error(f"Durum geri yükleme hatası: {e}")


def main():
    parser = argparse.ArgumentParser(description="V6.5 / V6.1 Mean Reversion Bot")
    parser.add_argument("--live", action="store_true", help="Canlı mod (gerçek para)")
    parser.add_argument("--single-run", action="store_true", help="Tek seferlik tarama")
    parser.add_argument("--capital", type=float, default=10000.0, help="Başlangıç sermayesi")
    parser.add_argument("--max-positions", type=int, default=5, help="Maks pozisyon")
    parser.add_argument("--top", type=int, default=100, help="En yüksek hacimli N sembol")
    parser.add_argument("--interval", type=int, default=15, help="Tarama aralığı (dk)")
    parser.add_argument("--mode", type=str, default="v6.5", choices=["v6.5", "v6.1"], help="Bot çalışma modu")
    args = parser.parse_args()

    if not args.single_run:
        import socket
        port = 28386 if args.mode == "v6.1" else 28385
        try:
            lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lock_socket.bind(("127.0.0.1", port))
            globals()["_bot_lock_socket"] = lock_socket
        except socket.error:
            print(f"\n❌ HATA: Bot ({args.mode}) zaten arka planda çalışıyor! İkinci bir kopya başlatılamaz.\n")
            sys.exit(0)

    print("=" * 60)
    bot_title = "V6.1 MEAN REVERSION BOT" if args.mode == "v6.1" else "V6.5 ENHANCED MEAN REVERSION BOT"
    print(bot_title)
    print("=" * 60)
    print(f"  Sermaye:    ${args.capital:,.2f}")
    print(f"  Max Pozisyon: {args.max_positions}")
    print(f"  Mod:        {'LIVE' if args.live else 'PAPER'}")
    print(f"  Semboller:  Top {args.top} (hacme göre)")
    features_desc = "Kademeli Kâr + Cooldown" if args.mode == "v6.1" else "Cooldown + Rejim + DinamikSL + Korelasyon + PartialTP"
    print(f"  Özellikler: {features_desc}")
    print("=" * 60)

    if args.live:
        print("\n⚠️  UYARI: CANLI MOD AKTİF! GERÇEK PARA KULLANILACAK!")
        print("Devam etmek için 'yes' yazın:")
        confirm = input("> ")
        if confirm.lower() != "yes":
            print("İptal edildi.")
            sys.exit(0)

    bot = LiveV65Bot(
        initial_capital=args.capital,
        max_positions=args.max_positions,
        position_pct=0.10,
        is_live=args.live,
        top_n=args.top,
        mode=args.mode,
    )

    if args.single_run:
        signals = bot.run_single_scan()
        if signals:
            print(f"\n{len(signals)} sinyal bulundu:")
            for s in signals:
                print(f"  {s['signal']} {s['symbol']} @ ${s['price']:,.4f}")
        else:
            print("\nSinyal bulunamadı.")
    else:
        bot.run_loop(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
