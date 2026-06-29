# -*- coding: utf-8 -*-
"""
live_v7.py — V7 Price Action LIVE Trading Bot
Backtest Optimized: 100 coin, %114 ROI, %26.6 win rate.

Çalıştırma:
  python live_v7.py                    # Paper trade modu
  python live_v7.py --live             # Canlı mod
  python live_v7.py --single-run       # Tek seferlik tarama
"""

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
from src.strategy.v7_pa_strategy import V7PriceActionStrategy
from src.strategy.adaptive_learner import AdaptiveLearner
from src.strategy.regime_detector import RegimeDetector, MarketRegime
from src.backtest.engine import BacktestEngine, TradeRecord
from src.utils.telegram_notifier import send_telegram_notification
from src.utils.logger import get_logger
from src.config.settings import get_settings
from src.utils.telegram_listener import start_telegram_listener

logger = get_logger("live_v7")


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


class LiveV7Bot:
    """V7 Price Action canlı trading botu — backtest optimized."""

    MAJOR_PAIRS = {"BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"}
    EXCLUDED_SYMBOLS = {"PAXG/USDT", "RLUSD/USDT", "FDUSD/USDT", "USDC/USDT"}
    SECTORS = {
        "l1": {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT", "NEAR/USDT", "DOT/USDT", "ADA/USDT"},
        "l2": {"ARB/USDT", "OP/USDT", "MATIC/USDT", "IMX/USDT"},
        "defi": {"UNI/USDT", "AAVE/USDT", "LINK/USDT", "LDO/USDT", "MKR/USDT"},
        "meme": {"DOGE/USDT", "PEPE/USDT", "SHIB/USDT", "LUNC/USDT"},
        "ai": {"FET/USDT", "RENDER/USDT", "TAO/USDT"},
    }

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_positions: int = 10,
        position_pct: float = 0.02,
        is_live: bool = False,
        top_n: int = 100,
    ) -> None:
        self.portfolio_state_path = "logs/portfolio_state_v7.json"
        self.signals_jsonl_path = "logs/signals_v7.jsonl"
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.position_pct = position_pct
        self.is_live = is_live
        self.top_n = top_n

        self.fetcher = HistoricalDataFetcher()
        self.strategy = V7PriceActionStrategy()
        self.regime_detector = RegimeDetector()
        self.balance = initial_capital
        self.positions: Dict[str, dict] = {}
        self.trades: List[TradeRecord] = []
        self.cycle_events: List[str] = []

        # Cooldown
        self._cooldown_map: Dict[str, dict] = {}
        self.COOLDOWN_SL_HOURS = 2

        # Win rate takibi (pozisyon boyutlandırma için)
        self._symbol_stats: Dict[str, Dict] = {}  # {sym: {"wins": int, "losses": int, "total_pnl": float}}

        self._load_state()
        
        # Adaptif öğrenme
        self.learner = AdaptiveLearner()
        self._last_daily_optimize = None
        
        # Settings (telegram_listener için gerekli)
        self.settings = get_settings()
        self.settings.strategy.version = "v7"

        logger.info(f"LiveV7Bot başlatıldı | Sermaye: ${initial_capital:,.2f} | {'LIVE' if is_live else 'PAPER'} | Top {top_n}")

        mod = '🔴 CANLI' if is_live else '🟢 PAPER'
        version = self.learner.get_version()
        msg = (
            f"🤖 V{version} Price Action Bot Başlatıldı\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Sermaye: ${initial_capital:,.2f}\n"
            f"📊 Mod: {mod}\n"
            f"🎯 Max Pozisyon: {max_positions}\n"
            f"📏 Risk/Trade: %{position_pct*100:.0f}\n"
            f"📋 Semboller: Top {top_n} (hacme göre)\n"
            f"🛡️ RR Hedefi: 5.5 | ATR Stop: 0.6x\n"
            f"📈 Backtest ROI: %+114.6\n"
            f"🧠 Günlük Otomatik Öğrenme: Aktif"
        )
        send_telegram_notification(msg)

        try:
            start_telegram_listener(self)
        except Exception as e:
            logger.error(f"Telegram listener başlatılamadı: {e}")

    def _send_portfolio_summary(self, trigger_message: str = "") -> None:
        self._print_status()

    # ═══════════════════════════════════════════════════════════
    # STATE MANAGEMENT
    # ═══════════════════════════════════════════════════════════

    def _load_state(self) -> None:
        try:
            path = Path(self.portfolio_state_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self.balance = state.get("balance", self.initial_capital)
                self.positions = state.get("positions", {})
                self._symbol_stats = state.get("symbol_stats", {})
                logger.info(f"State yüklendi: ${self.balance:,.2f} bakiye, {len(self.positions)} pozisyon")
        except Exception as e:
            logger.warning(f"State yüklenemedi: {e}")

    def _save_state(self) -> None:
        try:
            Path("logs").mkdir(exist_ok=True)
            state = {
                "balance": self.balance,
                "positions": self.positions,
                "symbol_stats": self._symbol_stats,
                "updated_at": pd.Timestamp.now().isoformat(),
            }
            with open(self.portfolio_state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"State kayıt hatası: {e}")

    # ═══════════════════════════════════════════════════════════
    # COOLDOWN
    # ═══════════════════════════════════════════════════════════

    def _is_in_cooldown(self, symbol: str) -> Tuple[bool, str]:
        if symbol not in self._cooldown_map:
            return False, ""
        cd = self._cooldown_map[symbol]
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        if now < cd["until"]:
            remaining = (cd["until"] - now).total_seconds() / 3600
            return True, f"Cooldown: {cd['reason']} ({remaining:.1f}h kaldı)"
        if now >= cd["until"]:
            del self._cooldown_map[symbol]
        return False, ""

    def _set_cooldown(self, symbol: str, reason: str, hours: float) -> None:
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        self._cooldown_map[symbol] = {"until": now + timedelta(hours=hours), "reason": reason}

    # ═══════════════════════════════════════════════════════════
    # POZİSYON BOYUTLANDIRMA (Win Rate Bazlı)
    # ═══════════════════════════════════════════════════════════

    def _get_position_size_multiplier(self, symbol: str) -> float:
        """Win rate'e göre pozisyon boyutu çarpanı."""
        stats = self._symbol_stats.get(symbol, {"wins": 0, "losses": 0})
        total = stats["wins"] + stats["losses"]
        if total < 5:
            return 1.0  # Yeterli veri yok, normal boyut
        wr = stats["wins"] / total
        if wr > 0.30:
            return 1.5  # Yüksek win rate → daha büyük
        elif wr > 0.20:
            return 1.0  # Normal
        else:
            return 0.5  # Düşük win rate → daha küçük

    # ═══════════════════════════════════════════════════════════
    # FİLTRELER
    # ═══════════════════════════════════════════════════════════

    def _check_symbol_quality(self, symbol: str) -> Tuple[bool, str]:
        if symbol in self.EXCLUDED_SYMBOLS:
            return False, f"Hariç tutulan: {symbol}"
        # Adaptif öğrenme黒listesi
        if self.learner.is_symbol_blacklisted(symbol):
            return False, f"Öğrenme黒listesinde: {symbol}"
        # Volatilite kontrolü
        try:
            df = self.fetcher.fetch_ohlcv(symbol, "1h", limit=50)
            if df.empty or len(df) < 20:
                return False, "Yeterli veri yok"
            volatility = df["close"].pct_change(20).abs().iloc[-1] * 100
            if pd.isna(volatility) or volatility < 0.3:
                return False, f"Volatilite çok düşük: %{volatility:.2f}"
        except Exception:
            pass
        return True, ""

    def _check_sector_limit(self, symbol: str) -> Tuple[bool, str]:
        for sector, syms in self.SECTORS.items():
            if symbol in syms:
                count = sum(1 for s in self.positions if s in syms)
                if count >= 2:
                    return False, f"Sektör limiti: {sector}'da {count} pozisyon"
        return True, ""

    def _check_regime(self, symbol: str, signal: str) -> Tuple[bool, str, float]:
        try:
            df_4h = self.fetcher.fetch_ohlcv(symbol, "4h", limit=200)
            if df_4h.empty or len(df_4h) < 50:
                return True, "", 1.0
            df_4h = self.regime_detector.calculate_indicators(df_4h)
            regime = self.regime_detector.detect(df_4h, len(df_4h) - 1)
            # gevşet: sadece çok belirgin trend'leri engelle
            if regime == MarketRegime.TREND_UP and signal == "SELL":
                # VOLATILE veya RANGE'de SHORT'a izin ver
                return True, "TREND_UP ama SHORT'a izin verildi", 0.7
            if regime == MarketRegime.TREND_DOWN and signal == "BUY":
                return True, "TREND_DOWN ama LONG'a izin verildi", 0.7
            if regime == MarketRegime.VOLATILE:
                return True, "VOLATILE — pozisyon küçültüldü", 0.5
            return True, f"Rejim: {regime.value}", 1.0
        except Exception:
            return True, "", 1.0

    # ═══════════════════════════════════════════════════════════
    # TARAMA
    # ═══════════════════════════════════════════════════════════

    def run_single_scan(self) -> List[dict]:
        self.fetcher.clear_cache()
        logger.info("=" * 60)
        logger.info("V7 TARAMA BAŞLIYOR")
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
                quality_ok, quality_reason = self._check_symbol_quality(symbol)
                if not quality_ok:
                    continue

                # 3 zaman diliminde tara: 15m, 1h, 4h
                for tf in ["15m", "1h", "4h"]:
                    df = self.fetcher.fetch_ohlcv(symbol, tf, limit=500)
                    if df.empty or len(df) < 200:
                        continue

                    df_signals = self.strategy.calculate_signals(df)

                    for i in range(max(0, len(df_signals) - 5), len(df_signals)):
                        sig = df_signals.iloc[i]["signal"]
                        if sig in ("BUY", "SELL"):
                            price = float(df_signals.iloc[i]["close"])
                            sl = float(df_signals.iloc[i]["sl_price"])
                            tp = float(df_signals.iloc[i]["tp_price"])
                            atr = float(df_signals.iloc[i].get("atr", price * 0.02))

                            signals.append({
                                "symbol": symbol,
                                "signal": sig,
                                "price": price,
                                "stop_loss": sl,
                                "take_profit": tp,
                                "atr": atr,
                                "time": df.index[i] if hasattr(df.index[i], 'isoformat') else str(df.index[i]),
                            })
                            logger.info(f"SİNYAL: {sig} {symbol} @ {format_price(price)} | SL: {format_price(sl)} | TP: {format_price(tp)}")
                            break
                    if symbol in [s["symbol"] for s in signals]:
                        break

            except Exception as e:
                logger.error(f"{symbol} tarama hatası: {e}")

        # Sinyal loglama
        try:
            Path("logs").mkdir(exist_ok=True)
            with open(self.signals_jsonl_path, "a", encoding="utf-8") as f:
                now_str = pd.Timestamp.now().isoformat()
                for s in signals:
                    f.write(json.dumps({
                        "generated_at": now_str,
                        "symbol": s["symbol"],
                        "signal_type": s["signal"],
                        "price": s["price"],
                        "stop_loss": s["stop_loss"],
                        "take_profit": s["take_profit"],
                    }) + "\n")
        except Exception as e:
            logger.error(f"Sinyal loglama hatası: {e}")

        logger.info(f"Tarama tamamlandı: {len(signals)} sinyal")
        return signals

    # ═══════════════════════════════════════════════════════════
    # İŞLEM AÇMA
    # ═══════════════════════════════════════════════════════════

    def open_position(self, signal: dict) -> bool:
        symbol = signal["symbol"]
        direction = signal["signal"]
        price = signal["price"]
        sl = signal["stop_loss"]
        tp = signal["take_profit"]

        # Kontroller
        if symbol in self.positions:
            print(f"[V7] {symbol} zaten acik")
            return False

        if len(self.positions) >= self.max_positions:
            print(f"[V7] Max pozisyon dolu ({self.max_positions})")
            return False

        cooldown_ok, cooldown_reason = self._is_in_cooldown(symbol)
        if not cooldown_ok:
            print(f"[V7] {symbol} cooldown: {cooldown_reason}")
            return False

        sector_ok, sector_reason = self._check_sector_limit(symbol)
        if not sector_ok:
            print(f"[V7] {symbol} sektor: {sector_reason}")
            return False

        regime_ok, regime_reason, regime_mult = self._check_regime(symbol, direction)
        if not regime_ok:
            print(f"[V7] {symbol} rejim: {regime_reason}")
            return False

        # Pozisyon boyutu
        size_mult = self._get_position_size_multiplier(symbol)
        risk_amount = self.balance * self.position_pct * size_mult * regime_mult

        if direction == "BUY":
            risk_per_unit = price - sl
        else:
            risk_per_unit = sl - price

        if risk_per_unit <= 0:
            print(f"[V7] {symbol} risk <= 0: price={price}, sl={sl}")
            return False

        position_size = risk_amount / risk_per_unit
        notional = position_size * price

        if notional > self.balance * 0.1:  # Max %10 sermaye
            notional = self.balance * 0.1
            position_size = notional / price

        # Pozisyon kaydı
        self.positions[symbol] = {
            "direction": direction,
            "entry_price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "size": position_size,
            "notional": notional,
            "opened_at": pd.Timestamp.now().isoformat(),
        }

        self.balance -= notional * 0.001  # Komisyon

        # Telegram bildirimi
        emoji = "🟢" if direction == "BUY" else "🔴"
        msg = (
            f"{emoji} YENİ POZİSYON — {symbol}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Yön: {direction}\n"
            f"💰 Giriş Fiyatı: {format_price(price)}\n"
            f"🛑 Stop Loss: {format_price(sl)}\n"
            f"🎯 Take Profit: {format_price(tp)}\n"
            f"📏 Pozisyon: {position_size:.4f} adet\n"
            f"💵 Değer: {format_price(notional)}\n"
            f"⚖️ Kaldıraç: 5x\n"
            f"🎯 RR: 5.5\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye: {format_price(self.balance)}"
        )
        send_telegram_notification(msg)

        self._save_state()
        return True

    # ═══════════════════════════════════════════════════════════
    # POZİSYON İZLEME
    # ═══════════════════════════════════════════════════════════

    def monitor_positions(self) -> None:
        if not self.positions:
            return

        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            try:
                ticker = self.fetcher.exchange.fetch_ticker(symbol)
                current_price = ticker["last"]

                if pos["direction"] == "BUY":
                    if current_price <= pos["stop_loss"]:
                        self._close_position(symbol, current_price, "STOP_LOSS")
                    elif current_price >= pos["take_profit"]:
                        self._close_position(symbol, current_price, "TAKE_PROFIT")
                else:
                    if current_price >= pos["stop_loss"]:
                        self._close_position(symbol, current_price, "STOP_LOSS")
                    elif current_price <= pos["take_profit"]:
                        self._close_position(symbol, current_price, "TAKE_PROFIT")

            except Exception as e:
                logger.error(f"{symbol} fiyat kontrolü hatası: {e}")

    def _close_position(self, symbol: str, exit_price: float, reason: str) -> None:
        pos = self.positions.pop(symbol)
        entry = pos["entry_price"]
        size = pos["size"]

        if pos["direction"] == "BUY":
            pnl_pct = (exit_price - entry) / entry
        else:
            pnl_pct = (entry - exit_price) / entry

        pnl_usd = pnl_pct * size * 5  # 5x kaldıraç
        commission = size * 0.00063 * 5 * 2
        net_pnl = pnl_usd - commission

        self.balance += pos["notional"] + net_pnl

        # Win rate takibi
        if symbol not in self._symbol_stats:
            self._symbol_stats[symbol] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
        self._symbol_stats[symbol]["total_pnl"] += net_pnl
        if net_pnl > 0:
            self._symbol_stats[symbol]["wins"] += 1
        else:
            self._symbol_stats[symbol]["losses"] += 1
            self._set_cooldown(symbol, "STOP_LOSS", self.COOLDOWN_SL_HOURS)

        # Adaptif öğrenmeye de kaydet
        self.learner.update_symbol_stats(symbol, net_pnl)

        # Telegram — Coin özel K/Z
        emoji = "✅" if net_pnl > 0 else "❌"
        
        # Bu coin'in toplam istatistiği
        coin_stats = self._symbol_stats.get(symbol, {"wins": 0, "losses": 0, "total_pnl": 0.0})
        coin_total_pnl = coin_stats["total_pnl"]
        coin_trades = coin_stats["wins"] + coin_stats["losses"]
        coin_wr = coin_stats["wins"] / coin_trades * 100 if coin_trades else 0
        
        msg = (
            f"{emoji} POZİSYON KAPATILDI — {symbol}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Yön: {pos['direction']}\n"
            f"💰 Giriş: {format_price(entry)}\n"
            f"💵 Çıkış: {format_price(exit_price)}\n"
            f"📈 İşlem K/Z: {format_price(net_pnl)} (%{pnl_pct*100:+.1f})\n"
            f"📋 Neden: {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {symbol} Özeti:\n"
            f"   İşlem: {coin_trades} | WR: %{coin_wr:.0f}\n"
            f"   Toplam K/Z: {format_price(coin_total_pnl)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye: {format_price(self.balance)}"
        )
        send_telegram_notification(msg)

        self._save_state()

    # ═══════════════════════════════════════════════════════════
    # ANA DÖNGÜ
    # ═══════════════════════════════════════════════════════════

    def run_cycle(self) -> None:
        logger.info(f"Döngü başlıyor | Bakiye: {format_price(self.balance)} | Pozisyon: {len(self.positions)}")

        # Pozisyon izle
        self.monitor_positions()

        # Tarama yap
        signals = self.run_single_scan()

        # Sinyalleri işle
        for signal in signals:
            if len(self.positions) >= self.max_positions:
                break
            self.open_position(signal)

        # Günlük optimizasyon kontrolü
        now = datetime.now()
        if self._last_daily_optimize is None or (now - self._last_daily_optimize).total_seconds() > 86400:
            self._run_daily_optimization()
            self._last_daily_optimize = now

        self._print_status()

    def _run_daily_optimization(self) -> None:
        """Günlük optimizasyon — adaptif öğrenme."""
        try:
            # İşlemleri learner'a aktar
            for trade in self.trades:
                self.learner.update_symbol_stats(trade.symbol, trade.pnl_usdt)

            # Optimizasyonu çalıştır
            result = self.learner.daily_optimize(self._get_portfolio_state())

            if result.get("optimized"):
                logger.info(f"Günlük optimizasyon tamamlandı: {result.get('changes', [])}")
            else:
                logger.info(f"Günlük optimizasyon atlandı: {result.get('reason')}")

        except Exception as e:
            logger.error(f"Günlük optimizasyon hatası: {e}")

    def _get_portfolio_state(self) -> dict:
        """Portföy durumunu döndür."""
        return {
            "balance": self.balance,
            "positions": self.positions,
            "symbol_stats": self._symbol_stats,
        }

    def _send_hourly_summary(self) -> None:
        """Saatlik Telegram özeti."""
        now = datetime.now()
        total_pnl = sum(
            self._symbol_stats.get(s, {}).get("total_pnl", 0)
            for s in self._symbol_stats
        )
        total_wins = sum(self._symbol_stats.get(s, {}).get("wins", 0) for s in self._symbol_stats)
        total_losses = sum(self._symbol_stats.get(s, {}).get("losses", 0) for s in self._symbol_stats)
        total_trades = total_wins + total_losses
        wr = total_wins / total_trades * 100 if total_trades else 0

        version = self.learner.get_version()
        msg = (
            f"📊 SAATLIK ÖZET — V{version} Bot\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye: {format_price(self.balance)}\n"
            f"📈 Toplam K/Z: {format_price(total_pnl)}\n"
            f"📊 İşlemler: {total_trades} (%{wr:.1f} WR)\n"
            f"🔓 Açık Pozisyon: {len(self.positions)}\n"
            f"⏰ {now.strftime('%H:%M')}"
        )
        send_telegram_notification(msg)

    def _print_status(self) -> None:
        logger.info(f"Bakiye: {format_price(self.balance)} | Pozisyon: {len(self.positions)}")
        for sym, pos in self.positions.items():
            logger.info(f"  {sym}: {pos['direction']} @ {format_price(pos['entry_price'])}")

    def run(self, interval_minutes: int = 15) -> None:
        """Ana döngü."""
        logger.info(f"V7 Bot döngüsü başlatıldı — {interval_minutes} dakika aralıkla")

        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                logger.info("Bot durduruldu (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Döngü hatası: {e}")
                send_telegram_notification(f"⚠️ V7 Bot HATA: {e}")

            time.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="ANTIGRAVITI V7 Price Action Bot")
    parser.add_argument("--live", action="store_true", help="Canlı mod")
    parser.add_argument("--paper", action="store_true", help="Paper trade modu (varsayılan)")
    parser.add_argument("--single-run", action="store_true", help="Tek seferlik tarama")
    parser.add_argument("--interval", type=int, default=15, help="Tarama aralığı (dakika)")
    parser.add_argument("--capital", type=float, default=10000.0, help="Başlangıç sermayesi")
    parser.add_argument("--top-n", type=int, default=100, help="Taranacak sembol sayısı")
    args = parser.parse_args()

    is_live = args.live and not args.paper

    bot = LiveV7Bot(
        initial_capital=args.capital,
        max_positions=10,
        position_pct=0.01,
        is_live=is_live,
        top_n=args.top_n,
    )

    if args.single_run:
        signals = bot.run_single_scan()
        bot._print_status()
    else:
        bot.run(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
