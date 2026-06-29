# -*- coding: utf-8 -*-
# ============================================================
# live_v6mr.py — V6 Mean Reversion LIVE Trading Bot
#
# AMAÇ:
#   V6 Mean Reversion stratejisini canlı borsada çalıştırır.
#   10 sembolü tarar, sinyal üretir ve emir iletir.
#
# ÇALIŞTIRMA:
#   python live_v6mr.py                    # Paper trade modu
#   python live_v6mr.py --live             # Canlı mod
#   python live_v6mr.py --single-run       # Tek seferlik tarama
#
# ⚠️  UYARI: Canlı modda gerçek para kullanılır!
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

# Windows stdout encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.data.historical import HistoricalDataFetcher
from src.strategy.v6_mean_rev import V6MeanReversion
from src.backtest.engine import BacktestEngine, TradeRecord
from src.utils.telegram_notifier import send_telegram_notification
from src.utils.logger import get_logger

logger = get_logger("live_v6mr")


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


class LiveV6MRBot:
    """V6 Mean Reversion canlı trading botu."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_positions: int = 5,
        position_pct: float = 0.10,
        is_live: bool = False,
        top_n: int = 100,
    ) -> None:
        """LiveV6MRBot başlatır.

        Args:
            initial_capital: Başlangıç sermayesi.
            max_positions: Maksimum açık pozisyon.
            position_pct: Pozisyon başına sermaye oranı.
            is_live: True ise canlı trading, False ise paper trade.
            top_n: En yüksek hacimli N sembol.
        """
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.position_pct = position_pct
        self.is_live = is_live
        self.top_n = top_n

        self.fetcher = HistoricalDataFetcher()
        self.strategy = V6MeanReversion()
        self.balance = initial_capital
        self.positions: Dict[str, dict] = {}
        self.trades: List[TradeRecord] = []
        self.cycle_events: List[str] = []

        # Kayıtlı durumu yükle
        self._load_state()

        logger.info(f"LiveV6MRBot başlatıldı | Sermaye: ${initial_capital:,.2f} | Mod: {'LIVE' if is_live else 'PAPER'} | Top {top_n}")

        # Telegram bildirimi
        mod = '🔴 CANLI' if is_live else '🟢 PAPER'
        msg = (
            f"🤖 V6 Mean Reversion Bot Başlatıldı\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Sermaye: ${initial_capital:,.2f}\n"
            f"📊 Mod: {mod}\n"
            f"🎯 Max Pozisyon: {max_positions}\n"
            f"📏 Pozisyon Büyüklüğü: %{position_pct*100:.0f}\n"
            f"📋 Semboller: Top {top_n} (hacme göre)"
        )
        send_telegram_notification(msg)

    def run_single_scan(self) -> List[dict]:
        """Tek seferlik tarama yapar.
        

        Returns:
            Bulunan sinyaller listesi.
        """
        self.fetcher.clear_cache()
        logger.info("=" * 60)
        logger.info("TARAMA BAŞLIYOR")
        logger.info("=" * 60)

        # En yüksek hacimli sembolleri çek
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
                # Veri çek
                df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=500)
                if df.empty or len(df) < 200:
                    logger.warning(f"{symbol}: Yetersiz veri")
                    continue

                # İndikatörleri hesapla
                df = self._add_indicators(df)

                # Sinyal kontrolü (son 5 barda)
                for i in range(max(0, len(df) - 5), len(df)):
                    signal = self.strategy.generate_signal(df, i)
                    if signal:
                        price = float(df.iloc[i]["close"])
                        atr = float(df.iloc[i].get("atr", price * 0.02))

                        sl = self.strategy.get_stop_loss(price, atr, signal)
                        tp = self.strategy.get_take_profit(price, atr, signal)

                        signals.append({
                            "symbol": symbol,
                            "signal": signal,
                            "price": price,
                            "stop_loss": sl,
                            "take_profit": tp,
                            "atr": atr,
                            "time": df.index[i],
                        })
                        logger.info(f"SİNYAL: {signal} {symbol} @ {format_price(price)} | SL: {format_price(sl)} | TP: {format_price(tp)}")

            except Exception as e:
                logger.error(f"{symbol} tarama hatası: {e}")

        logger.info(f"Tarama tamamlandı: {len(signals)} sinyal bulundu")
        return signals

    def run_loop(self, interval_minutes: int = 60) -> None:
        """Periyodik döngü modu.

        Args:
            interval_minutes: Tarama aralığı (dakika).
        """
        logger.info("=" * 60)
        logger.info("PERİYODİK DÖNGÜ BAŞLADI")
        logger.info(f"Tarama aralığı: {interval_minutes} dakika")
        logger.info("Durdurmak için Ctrl+C")
        logger.info("=" * 60)

        # Başlangıçta durum dosyasını oluştur/güncelle
        self._save_state()

        try:
            while True:
                self.cycle_events = []

                # Açık pozisyonları kontrol et
                self._check_positions()

                # Yeni sinyalleri tara
                signals = self.run_single_scan()

                # Sinyalleri değerlendir
                self._rotation_done_this_cycle = False  # Her döngüde rotasyon sayacını sıfırla
                for sig in signals:
                    self._evaluate_signal(sig)

                # Durum raporu
                self._print_status()

                # Durumu kaydet (kalp atışı güncellemesi için)
                self._save_state()

                # Bekle
                logger.info(f"Sonraki tarama: {interval_minutes} dakika sonra")
                time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            logger.info("Durduruldu (Ctrl+C)")
            self._print_final_report()

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame'e indikatörleri ekler."""
        df = df.copy()

        # Bollinger Bands
        df["bb_mid"] = df["close"].rolling(window=20).mean()
        bb_std = df["close"].rolling(window=20).std()
        df["bb_upper"] = df["bb_mid"] + 2.0 * bb_std
        df["bb_lower"] = df["bb_mid"] - 2.0 * bb_std
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
        df["bb_width_ma"] = df["bb_width"].rolling(window=20).mean()

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))

        # ATR
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=14).mean()

        # Hacim
        df["volume_ma"] = df["volume"].rolling(window=20).mean()

        return df

    def _calculate_stagnation_score(self, pos: dict) -> float:
        """Bir pozisyonun durgunluk skorunu hesaplar (0-100).

        Kriter 1 (ağırlık %40): Kaç saattir açık (max 4 saat üzerinde tam puan)
        Kriter 2 (ağırlık %35): TP'ye ilerleme eksikliği (hiç ilerlememiş = tam puan)
        Kriter 3 (ağırlık %25): Negatif momentum (zarar yazıyorsa tam puan)

        Returns:
            0-100 arası skor. Yüksek skor = daha durgun, kapatılmaya daha uygun.
        """
        score = 0.0

        # Kriter 1 — Zaman durgunluğu (max 4 saatte tam puan)
        # Not: 15 dk = 2.5 puan, 1 sa = 10 puan — genç pozisyonlar doğal olarak korunur
        entry_time = pos.get("entry_time")
        if entry_time is not None:
            try:
                geçen_saat = (pd.Timestamp.now() - pd.Timestamp(entry_time)).total_seconds() / 3600
                score += min((geçen_saat / 4.0) * 40.0, 40.0)
            except Exception:
                score += 20.0  # varsayılan: orta seviye

        # Kriter 2 — TP'ye ilerleme eksikliği
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

        # Kriter 3 — Negatif momentum
        pnl_u = pos.get("pnl_usdt", 0.0)
        if pnl_u < 0:
            score += 25.0

        return min(score, 100.0)

    def _find_worst_position(self) -> tuple[str, float]:
        """Açık pozisyonlar arasında en durgun olanı bulur.

        Returns:
            (sembol, skor) tuple'ı. Pozisyon yoksa ("", 0.0).
        """
        if not self.positions:
            return "", 0.0
        worst_sym = ""
        worst_score = -1.0
        for sym, pos in self.positions.items():
            s = self._calculate_stagnation_score(pos)
            logger.debug(f"  Durgunluk skoru {sym}: {s:.1f}/100")
            if s > worst_score:
                worst_score = s
                worst_sym = sym
        return worst_sym, worst_score

    def _evaluate_signal(self, signal: dict) -> None:
        """Sinyali değerlendirir ve pozisyon açar. Limit doluysa rotasyon dener."""
        symbol = signal["symbol"]
        sig_type = signal["signal"]
        ROTATION_THRESHOLD = 65.0   # Döngü başına 1 rotasyon, min 2 saat yaş + bu eşik

        # Aynı sembolde zaten pozisyon var mı?
        if symbol in self.positions:
            logger.info(f"{symbol} zaten açık pozisyonda")
            return

        # Açık pozisyon limiti doluysa → rotasyon dene
        if len(self.positions) >= self.max_positions:
            # BU DÖNGÜDE ZATEN ROTASYON YAPILDIYSA ATLA
            if getattr(self, "_rotation_done_this_cycle", False):
                logger.info(f"Bu döngüde zaten 1 rotasyon yapıldı → {symbol} atlanıyor")
                return

            worst_sym, worst_score = self._find_worst_position()
            if worst_score >= ROTATION_THRESHOLD:
                logger.info(
                    f"🔄 ROTASYON tetiklendi: {worst_sym} → skor={worst_score:.1f} "
                    f">= eşik={ROTATION_THRESHOLD} → kapatılıyor"
                )
                # Güncel fiyatı çek ve rotasyonla kapat
                try:
                    df_rot = self.fetcher.fetch_ohlcv(worst_sym, "1h", limit=1)
                    rot_price = float(df_rot.iloc[-1]["close"]) if not df_rot.empty else self.positions[worst_sym]["current_price"]
                except Exception:
                    rot_price = self.positions[worst_sym].get("current_price", self.positions[worst_sym]["entry_price"])
                self._close_position(worst_sym, rot_price, "ROTATION")
                del self.positions[worst_sym]
                self._rotation_done_this_cycle = True  # Bu döngüde bir daha rotasyon yok
            else:
                logger.warning(
                    f"Pozisyon limiti dolu ({self.max_positions}) | "
                    f"En kötü pozisyon {worst_sym} skoru {worst_score:.1f} < {ROTATION_THRESHOLD} (eşik) → rotasyon yapılmadı"
                )
                return

        # Pozisyon büyüklüğü
        position_value = self.balance * self.position_pct
        if position_value < 10:
            logger.warning(f"Yetersiz bakiye: ${self.balance:,.2f}")
            return

        # Pozisyon aç
        entry_price = signal["price"]
        amount = position_value / entry_price
        commission = position_value * 0.001

        self.positions[symbol] = {
            "side": "LONG" if sig_type == "BUY" else "SHORT",
            "entry_price": entry_price,
            "amount": amount,
            "stop_loss": signal["stop_loss"],
            "take_profit": signal["take_profit"],
            "entry_time": signal["time"],
        }

        self.balance -= (position_value + commission)

        logger.info(f"POZİSYON AÇILDI: {sig_type} {symbol}")
        logger.info(f"  Giriş: {format_price(entry_price)} | Miktar: {amount:.6f}")
        logger.info(f"  SL: {format_price(signal['stop_loss'])} | TP: {format_price(signal['take_profit'])}")

        # Döngü olayı olarak kaydet
        yon = 'LONG' if sig_type == 'BUY' else 'SHORT'
        self.cycle_events.append(
            f"📈 {symbol} ({yon}) | Yeni Pozisyon\n"
            f"   Giriş: {format_price(entry_price)} | TP: {format_price(signal['take_profit'])}"
        )
        self._save_state()

    def _check_positions(self) -> None:
        """Açık pozisyonları kontrol eder."""
        closed = []

        for symbol, pos in self.positions.items():
            try:
                # Güncel fiyatı çek
                df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=1)
                if df.empty:
                    continue

                current_price = float(df.iloc[-1]["close"])
                pos["current_price"] = current_price

                # PnL hesapla
                side_up = str(pos["side"]).upper()
                if "LONG" in side_up or side_up == "BUY":
                    pnl_u = (current_price - pos["entry_price"]) * pos["amount"]
                else:
                    pnl_u = (pos["entry_price"] - current_price) * pos["amount"]

                cost = pos["entry_price"] * pos["amount"]
                pnl_p = (pnl_u / cost) if cost > 0 else 0.0

                pos["pnl_usdt"] = pnl_u
                pos["pnl_pct"] = pnl_p

                # Kâr Takip için En Yüksek/En Düşük Fiyat Güncelleme
                if "LONG" in side_up or side_up == "BUY":
                    pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), current_price)
                else:
                    pos["lowest_price"] = min(pos.get("lowest_price", pos["entry_price"]), current_price)

                # Breakeven Stop Loss (Maliyete Çekme) Kontrolü
                if not pos.get("sl_to_breakeven", False):
                    entry_price = pos["entry_price"]
                    tp_price = pos["take_profit"]
                    
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
                                    logger.info(f"🛡️ {symbol} TP hedefine %{progress_pct*100:.1f} yaklaştı. SL maliyete çekildi: {format_price(new_sl)}")
                                    self.cycle_events.append(f"🛡️ {symbol} | SL maliyete çekildi: {format_price(new_sl)}")
                            else:  # SHORT
                                new_sl = entry_price * 0.998
                                if pos["stop_loss"] > new_sl:
                                    pos["stop_loss"] = new_sl
                                    pos["sl_to_breakeven"] = True
                                    logger.info(f"🛡️ {symbol} TP hedefine %{progress_pct*100:.1f} yaklaştı. SL maliyete çekildi: {format_price(new_sl)}")
                                    self.cycle_events.append(f"🛡️ {symbol} | SL maliyete çekildi: {format_price(new_sl)}")

                # Trailing Take Profit (Akıllı Kâr Takip) Kontrolü
                tp_closed = False
                if "LONG" in side_up or side_up == "BUY":
                    tp_target = pos["take_profit"] - pos["entry_price"]
                    if tp_target > 0:
                        max_progress = (pos["highest_price"] - pos["entry_price"]) / tp_target
                        if max_progress >= 0.70:
                            trigger_price = pos["highest_price"] - 0.20 * tp_target
                            if current_price <= trigger_price:
                                self._close_position(symbol, current_price, "EARLY_TP")
                                closed.append(symbol)
                                tp_closed = True
                else:  # SHORT
                    tp_target = pos["entry_price"] - pos["take_profit"]
                    if tp_target > 0:
                        max_progress = (pos["entry_price"] - pos["lowest_price"]) / tp_target
                        if max_progress >= 0.70:
                            trigger_price = pos["lowest_price"] + 0.20 * tp_target
                            if current_price >= trigger_price:
                                self._close_position(symbol, current_price, "EARLY_TP")
                                closed.append(symbol)
                                tp_closed = True

                if tp_closed:
                    continue

                # SL/TP kontrolü
                if "LONG" in side_up or side_up == "BUY":
                    if current_price <= pos["stop_loss"]:
                        self._close_position(symbol, current_price, "STOP_LOSS")
                        closed.append(symbol)
                    elif current_price >= pos["take_profit"]:
                        self._close_position(symbol, current_price, "TAKE_PROFIT")
                        closed.append(symbol)
                else:  # SHORT
                    if current_price >= pos["stop_loss"]:
                        self._close_position(symbol, current_price, "STOP_LOSS")
                        closed.append(symbol)
                    elif current_price <= pos["take_profit"]:
                        self._close_position(symbol, current_price, "TAKE_PROFIT")
                        closed.append(symbol)

            except Exception as e:
                logger.error(f"{symbol} pozisyon kontrol hatası: {e}")

        for sym in closed:
            del self.positions[sym]

    def _close_position(self, symbol: str, exit_price: float, reason: str) -> None:
        """Pozisyonu kapatır."""
        pos = self.positions[symbol]

        if pos["side"] == "LONG":
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
            pnl_pct=net_pnl / (pos["entry_price"] * pos["amount"]),
            commission=commission,
            hold_duration_hours=(pd.Timestamp.now() - pos["entry_time"]).total_seconds() / 3600,
            exit_reason=reason,
        )
        self.trades.append(trade)

        emoji = "✅" if net_pnl > 0 else "❌"
        logger.info(f"{emoji} POZİSYON KAPATILDI: {symbol} | {reason}")
        logger.info(f"  Kâr/Zarar: ${net_pnl:+,.2f} ({trade.pnl_pct * 100:+.2f}%)")

        # Döngü olayı olarak kaydet
        if reason == "TAKE_PROFIT":
            emoji_tg = "✅"
        elif reason == "STOP_LOSS":
            emoji_tg = "🛑"
        elif reason == "ROTATION":
            emoji_tg = "🔄"
        elif reason == "EARLY_TP":
            emoji_tg = "💵"
        else:
            emoji_tg = "✅" if net_pnl > 0 else "❌"
        yon = 'LONG' if pos['side'] in ('LONG', 'BUY') else 'SHORT'
        pnl_pct_formatted = f"+%{trade.pnl_pct * 100:.2f}" if trade.pnl_pct >= 0 else f"-%{abs(trade.pnl_pct * 100):.2f}"
        self.cycle_events.append(
            f"{emoji_tg} {symbol} ({yon}) | {reason} ile kapandı\n"
            f"   Çıkış: {format_price(exit_price)} | PnL: {net_pnl:+,.2f} USDT ({pnl_pct_formatted})"
        )
        self._save_state()

    def _print_status(self) -> None:
        """Durum raporu yazdırır ve tek Telegram mesajı gönderir."""
        total_pnl = sum(t.pnl_usdt for t in self.trades)
        win_trades = sum(1 for t in self.trades if t.pnl_usdt > 0)
        total_trades = len(self.trades)
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

        logger.info("\n" + "=" * 60)
        logger.info("DURUM RAPORU")
        logger.info("=" * 60)
        logger.info(f"  Bakiye:      ${self.balance:,.2f}")
        logger.info(f"  Toplam PnL:  ${total_pnl:+,.2f}")
        logger.info(f"  Açık Pozisyon: {len(self.positions)}")
        logger.info(f"  Toplam İşlem: {total_trades}")
        logger.info(f"  Kazanma Oranı: %{win_rate:.1f}")
        logger.info("=" * 60)

        # Birleşik Telegram raporu
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        now = pd.Timestamp.now().strftime("%d.%m.%Y %H:%M")
        mod = '🔴 CANLI' if self.is_live else '🟢 PAPER'

        lines = [
            f"📊 V6 Mean Reversion Durum Raporu",
            f"🕐 {now} | {mod}",
            f"----------------------------------",
            f"",
            f"💰 Boştaki Nakit: ${self.balance:,.2f} USDT",
            f"📈 Başlangıç Sermayesi: ${self.initial_capital:,.2f} USDT",
            f"{pnl_emoji} Toplam Net Kâr: {total_pnl:+,.2f} USDT",
            f"📊 Açık Pozisyon: {len(self.positions)} adet",
            f"🔢 Toplam İşlem: {total_trades} | Kazanma: %{win_rate:.1f}",
        ]

        # Döngü olayları
        if self.cycle_events:
            lines.append(f"")
            lines.append(f"🔔 Bu Döngüdeki İşlemler:")
            lines.extend(self.cycle_events)

        # Açık pozisyonlar
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
                lines.append(f"  💵 Maliyet: ${cost:,.2f} USDT")
                lines.append(f"  🛡️ SL: {format_price(pos.get('stop_loss', 0))} | TP: {format_price(pos.get('take_profit', 0))}")

            total_unrealized_pct = (total_unrealized / total_cost) if total_cost > 0 else 0.0
            total_unrealized_pct_formatted = f"+%{total_unrealized_pct * 100:.2f}" if total_unrealized_pct >= 0 else f"-%{abs(total_unrealized_pct * 100):.2f}"
            sign_u = "+" if total_unrealized >= 0 else "-"
            val_abs_u = abs(total_unrealized)

            lines.append(f"")
            lines.append(f"----------------------------------")
            lines.append(f"📐 Toplam Pozisyon Maliyeti: ${total_cost:,.2f} USDT")
            lines.append(f"📊 Toplam Açık PnL: {sign_u}${val_abs_u:,.2f} USDT ({total_unrealized_pct_formatted})")
            lines.append(f"💵 Toplam Portföy Değeri: ${self.balance + total_cost + total_unrealized:,.2f} USDT")
        else:
            lines.append(f"")
            lines.append(f"📂 Açık pozisyon yok.")

        send_telegram_notification("\n".join(lines))

    def _print_final_report(self) -> None:
        """Son raporu yazdırır."""
        self._print_status()

        if self.trades:
            logger.info("\nİŞLEM LİSTESİ:")
            for t in self.trades:
                emoji = "✅" if t.pnl_usdt > 0 else "❌"
                logger.info(f"  {emoji} {t.symbol} | {t.side} | ${t.pnl_usdt:+,.2f} | {t.exit_reason}")

    def _save_state(self) -> None:
        """Durumu logs/portfolio_state.json dosyasına kaydeder."""
        try:
            Path("logs").mkdir(exist_ok=True)

            # Pozisyonları watch.py formatına çevir
            formatted_positions = {}
            for sym, pos in self.positions.items():
                cost = pos["entry_price"] * pos["amount"]
                formatted_positions[sym] = {
                    "side": pos["side"],
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
                }

            # İşlem geçmişini orders formatına çevir
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

            state = {
                "usdt_balance": self.balance,
                "open_positions": formatted_positions,
                "orders": orders,
                "total_pnl": sum(t.pnl_usdt for t in self.trades),
                "total_trades": len(self.trades),
                "win_rate": (sum(1 for t in self.trades if t.pnl_usdt > 0) / len(self.trades) * 100) if self.trades else 0,
                "last_updated": pd.Timestamp.now(tz="UTC").isoformat(),
            }
            with open("logs/portfolio_state.json", "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            logger.debug(f"Durum kaydedildi: logs/portfolio_state.json")
        except Exception as e:
            logger.error(f"Durum kaydetme hatası: {e}")

    def _load_state(self) -> None:
        """Kayıtlı durumu logs/portfolio_state.json dosyasından geri yükler."""
        try:
            state_path = Path("logs/portfolio_state.json")
            if state_path.exists():
                with open(state_path, encoding="utf-8") as f:
                    state = json.load(f)
                
                self.balance = state.get("usdt_balance", self.initial_capital)
                
                # Pozisyonları yükle
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
                    }
                
                # İşlemleri yükle
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
                logger.info(f"Kayıtlı durum başarıyla yüklendi | Bakiye: ${self.balance:,.2f} | Açık Pozisyonlar: {list(self.positions.keys())}")
        except Exception as e:
            logger.error(f"Durum geri yükleme hatası: {e}")


def main():
    """Ana fonksiyon."""
    parser = argparse.ArgumentParser(description="V6 Mean Reversion LIVE Bot")
    parser.add_argument("--live", action="store_true", help="Canlı mod (gerçek para)")
    parser.add_argument("--single-run", action="store_true", help="Tek seferlik tarama")
    parser.add_argument("--capital", type=float, default=10000.0, help="Başlangıç sermayesi")
    parser.add_argument("--max-positions", type=int, default=5, help="Maks pozisyon")
    parser.add_argument("--top", type=int, default=100, help="En yüksek hacimli N sembol")
    parser.add_argument("--interval", type=int, default=15, help="Tarama aralığı (dk)")
    args = parser.parse_args()

    # Mükerrer çalışmayı engellemek için port kilidi (sadece ana döngü için)
    if not args.single_run:
        import socket
        try:
            lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lock_socket.bind(("127.0.0.1", 28384))
            globals()["_bot_lock_socket"] = lock_socket
        except socket.error:
            print("\n❌ HATA: Bot zaten arka planda çalışıyor! İkinci bir kopya başlatılamaz.\n")
            sys.exit(0)

    print("=" * 60)
    print("V6 MEAN REVERSION LIVE BOT")
    print("=" * 60)
    print(f"  Sermaye:    ${args.capital:,.2f}")
    print(f"  Max Pozisyon: {args.max_positions}")
    print(f"  Mod:        {'LIVE' if args.live else 'PAPER'}")
    print(f"  Semboller:  Top {args.top} (hacme göre)")
    print("=" * 60)

    if args.live:
        print("\n⚠️  UYARI: CANLI MOD AKTİF! GERÇEK PARA KULLANILACAK!")
        print("Devam etmek için 'yes' yazın:")
        confirm = input("> ")
        if confirm.lower() != "yes":
            print("İptal edildi.")
            sys.exit(0)

    bot = LiveV6MRBot(
        initial_capital=args.capital,
        max_positions=args.max_positions,
        position_pct=0.10,
        is_live=args.live,
        top_n=args.top,
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
