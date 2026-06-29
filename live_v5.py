# -*- coding: utf-8 -*-
"""
live_v5.py — V5 Price Action LIVE Bot (Filtresiz, %2 Risk)
"""
import sys
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

from src.data.historical import HistoricalDataFetcher
from src.strategy.v5_pa_strategy import V5PriceActionStrategy
from src.strategy.regime_detector import RegimeDetector, MarketRegime
from src.utils.telegram_notifier import send_telegram_notification
from src.utils.logger import get_logger
from src.config.settings import get_settings
from src.utils.telegram_listener import start_telegram_listener

logger = get_logger("live_v5")


def format_price(price):
    if price is None or price == 0: return "-"
    if price >= 100: return f"${price:,.2f}"
    elif price >= 1.0: return f"${price:,.4f}"
    elif price >= 0.0001: return f"${price:,.6f}"
    else: return f"${price:,.8f}"


class LiveV5Bot:
    """V5 Price Action — Filtresiz, %2 risk, 50 coin."""

    EXCLUDED = {"PAXG/USDT", "RLUSD/USDT", "FDUSD/USDT", "USDC/USDT"}

    def __init__(self, initial_capital=10000.0, max_positions=5, position_pct=0.02,
                 is_live=False, top_n=50):
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.position_pct = position_pct
        self.is_live = is_live
        self.top_n = top_n

        self.fetcher = HistoricalDataFetcher()
        self.strategy = V5PriceActionStrategy()
        self.balance = initial_capital
        self.positions = {}
        self._symbol_stats = {}
        self._cooldown_map = {}
        self._load_state()

        self.settings = get_settings()
        self.settings.strategy.version = "v5"

        print(f"[V5] Baslatildi | ${initial_capital:,.0f} | {'LIVE' if is_live else 'PAPER'} | Top {top_n}")
        send_telegram_notification(
            f"🤖 V5 PA Bot Başlatıldı\n"
            f"💰 Sermaye: ${initial_capital:,.2f}\n"
            f"📊 Mod: {'🔴 CANLI' if is_live else '🟢 PAPER'}\n"
            f"🎯 Max Pozisyon: {max_positions}\n"
            f"📏 Risk: %{position_pct*100:.0f}\n"
            f"📋 Semboller: Top {top_n}\n"
            f"🛡️ RR: 5.5 | ATR Stop: 0.6x\n"
            f"⚙️ Filtre: YOK (filtresiz)"
        )

        try:
            start_telegram_listener(self)
        except Exception:
            pass

    def _send_portfolio_summary(self, msg=""):
        self._print_status()

    def _load_state(self):
        try:
            p = Path("logs/portfolio_state_v5.json")
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    s = json.load(f)
                self.balance = s.get("balance", self.initial_capital)
                self.positions = s.get("positions", {})
                self._symbol_stats = s.get("symbol_stats", {})
        except Exception:
            pass

    def _save_state(self):
        try:
            Path("logs").mkdir(exist_ok=True)
            with open("logs/portfolio_state_v5.json", "w", encoding="utf-8") as f:
                json.dump({"balance": self.balance, "positions": self.positions,
                           "symbol_stats": self._symbol_stats}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _is_in_cooldown(self, symbol):
        if symbol not in self._cooldown_map: return False, ""
        cd = self._cooldown_map[symbol]
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        if now < cd["until"]:
            return True, f"Cooldown: {cd['reason']}"
        del self._cooldown_map[symbol]
        return False, ""

    def _set_cooldown(self, symbol, reason, hours=2):
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        self._cooldown_map[symbol] = {"until": now + timedelta(hours=hours), "reason": reason}

    def run_cycle(self):
        print(f"\n[V5] Tarama | Bakiye: {format_price(self.balance)} | Pozisyon: {len(self.positions)}")

        # Pozisyon izle
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            try:
                ticker = self.fetcher.exchange.fetch_ticker(sym)
                price = ticker["last"]
                hit_sl = (pos["t"]=="LONG" and price<=pos["sl"]) or (pos["t"]=="SHORT" and price>=pos["sl"])
                hit_tp = (pos["t"]=="LONG" and price>=pos["tp"]) or (pos["t"]=="SHORT" and price<=pos["tp"])
                if hit_sl or hit_tp:
                    self._close(sym, price, "SL" if hit_sl else "TP")
            except Exception:
                pass

        # Tarama
        try:
            symbols = self.fetcher.fetch_top_symbols(top_n=self.top_n, quote="USDT")
            if not symbols:
                return

            for sym in symbols:
                if sym in self.EXCLUDED: continue
                if sym in self.positions: continue
                if len(self.positions) >= self.max_positions: break
                cd_ok, _ = self._is_in_cooldown(sym)
                if not cd_ok: continue

                try:
                    # 3 zaman diliminde tara: 15m, 1h, 4h
                    for tf in ["15m", "1h", "4h"]:
                        df = self.fetcher.fetch_ohlcv(sym, tf, limit=500)
                        if df.empty or len(df) < 200: continue

                        df_sig = self.strategy.calculate_signals(df)
                        for i in range(max(0, len(df_sig)-5), len(df_sig)):
                            sig = df_sig.iloc[i]["signal"]
                            if sig in ("BUY", "SELL"):
                                self._open(sym, sig, float(df_sig.iloc[i]["close"]),
                                           float(df_sig.iloc[i]["sl_price"]),
                                           float(df_sig.iloc[i]["tp_price"]))
                                break
                        if sym in self.positions: break
                except Exception:
                    pass

        except Exception as e:
            print(f"[V5] Tarama hatasi: {e}")

        self._save_state()

    def _open(self, sym, direction, price, sl, tp):
        risk_pct = self.position_pct
        if direction == "BUY":
            risk = price - sl
        else:
            risk = sl - price
        if risk <= 0: return

        sz = (self.balance * risk_pct) / (risk / price * 5)
        notional = sz * price
        if notional > self.balance * 0.1: return

        self.positions[sym] = {"t": direction, "e": price, "sl": sl, "tp": tp, "sz": sz, "n": notional}
        self.balance -= notional * 0.001

        emoji = "🟢" if direction == "BUY" else "🔴"
        send_telegram_notification(
            f"{emoji} YENİ POZİSYON — {sym}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Yön: {direction}\n"
            f"💰 Giriş: {format_price(price)}\n"
            f"🛑 Stop: {format_price(sl)}\n"
            f"🎯 Hedef: {format_price(tp)}\n"
            f"💵 Değer: {format_price(notional)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye: {format_price(self.balance)}"
        )
        print(f"[V5] {sym} {direction} @ {format_price(price)}")

    def _close(self, sym, exit_price, reason):
        pos = self.positions.pop(sym)
        entry = pos["e"]
        if pos["t"] == "BUY":
            pnl_pct = (exit_price - entry) / entry
        else:
            pnl_pct = (entry - exit_price) / entry
        pnl = pnl_pct * pos["sz"] * 5 - pos["n"] * 0.00063 * 5 * 2
        self.balance += pos["n"] + pnl

        if sym not in self._symbol_stats:
            self._symbol_stats[sym] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
        self._symbol_stats[sym]["total_pnl"] += pnl
        if pnl > 0:
            self._symbol_stats[sym]["wins"] += 1
        else:
            self._symbol_stats[sym]["losses"] += 1
            self._set_cooldown(sym, "SL")

        cs = self._symbol_stats[sym]
        ct = cs["wins"] + cs["losses"]
        cwr = cs["wins"] / ct * 100 if ct else 0

        emoji = "✅" if pnl > 0 else "❌"
        send_telegram_notification(
            f"{emoji} POZİSYON KAPATILDI — {sym}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Yön: {pos['t']}\n"
            f"💰 Giriş: {format_price(entry)}\n"
            f"💵 Çıkış: {format_price(exit_price)}\n"
            f"📈 K/Z: {format_price(pnl)} (%{pnl_pct*100:+.1f})\n"
            f"📋 Neden: {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {sym}: {ct} işlem, %{cwr:.0f} WR, {format_price(cs['total_pnl'])}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye: {format_price(self.balance)}"
        )
        print(f"[V5] {sym} KAPATILDI {reason} | {format_price(pnl)}")

    def _print_status(self):
        print(f"[V5] Bakiye: {format_price(self.balance)} | Pozisyon: {len(self.positions)}")


import json

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--paper", action="store_true")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--top-n", type=int, default=50)
    args = parser.parse_args()

    bot = LiveV5Bot(initial_capital=args.capital, max_positions=5,
                    position_pct=0.02, is_live=args.live and not args.paper, top_n=args.top_n)
    while True:
        try:
            bot.run_cycle()
        except Exception as e:
            print(f"[V5] Hata: {e}")
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
