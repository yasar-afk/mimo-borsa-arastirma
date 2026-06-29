# -*- coding: utf-8 -*-
# ============================================================
# dashboard/data_provider.py — Veri Sağlayıcı
#
# AMAÇ:
#   Bot'un ürettiği tüm veri kaynaklarını okur,
#   temizler ve Plotly'ye hazır formatta sunar.
#
# KAYNAKLAR:
#   - logs/portfolio_state.json  → Portföy & pozisyonlar
#   - logs/signals.jsonl         → Sinyal geçmişi
#   - logs/trading-bot.log       → İşlem logları
#   - ccxt (Binance)             → Canlı OHLCV verisi
# ============================================================

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

# Proje kök dizini
ROOT_DIR = Path(__file__).parent.parent
LOGS_DIR = ROOT_DIR / "logs"
PORTFOLIO_STATE_PATH = LOGS_DIR / "portfolio_state.json"
PORTFOLIO_STATE_PATH_V61 = LOGS_DIR / "portfolio_state_v61.json"
SIGNALS_JSONL_PATH = LOGS_DIR / "signals.jsonl"
SIGNALS_JSONL_PATH_V61 = LOGS_DIR / "signals_v61.jsonl"
LOG_PATH = LOGS_DIR / "trading-bot.log"

# signals.jsonl'dan okunan sembol listesini önbellekle
_symbols_cache: List[str] = []
_symbols_cache_time: float = 0.0


def get_available_symbols(force_refresh: bool = False) -> List[str]:
    """Bot'un taradığı tüm USDT çiftlerini döndürür.

    Öncelik sırası:
      1. signals.jsonl'daki tüm benzersiz semboller (hızlı, API gerekmez)
      2. Hata durumunda sabit temel liste
    """
    import time
    global _symbols_cache, _symbols_cache_time

    # 10 dakikada bir yenile
    if not force_refresh and _symbols_cache and (time.time() - _symbols_cache_time) < 600:
        return _symbols_cache

    symbols: set = set()

    # ── Yöntem 1: signals.jsonl'dan oku (en güncel) ──
    if SIGNALS_JSONL_PATH.exists():
        try:
            with open(SIGNALS_JSONL_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        sym = obj.get("symbol", "")
                        if sym and sym.endswith("/USDT") and len(sym) <= 20:
                            symbols.add(sym)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

    # ── Yöntem 2: portfolio_state.json'dan açık/kapalı pozisyonlar ──
    try:
        state = load_portfolio_state()
        for sym in state.get("open_positions", {}).keys():
            symbols.add(sym)
        for order in state.get("orders", []):
            sym = order.get("symbol", "")
            if sym:
                symbols.add(sym)
    except Exception:
        pass

    # ── Geri dönüş: temel liste ──
    if not symbols:
        symbols = {
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
            "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
            "LTC/USDT", "NEAR/USDT", "TON/USDT", "SUI/USDT", "INJ/USDT",
        }

    result = sorted(symbols)
    _symbols_cache = result
    _symbols_cache_time = time.time()
    return result




# ─── Portföy Verisi ────────────────────────────────────────

def _load_single_state(path: Path) -> dict:
    if not path.exists():
        return {
            "usdt_balance": 10000.0,
            "open_positions": {},
            "orders": [],
            "total_pnl": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "last_updated": datetime.now().isoformat(),
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except Exception:
        return {}


def load_portfolio_state() -> dict:
    """portfolio_state.json ve portfolio_state_v61.json dosyalarını okur ve birleştirir."""
    state65 = _load_single_state(PORTFOLIO_STATE_PATH)
    state61 = _load_single_state(PORTFOLIO_STATE_PATH_V61)

    balance = state65.get("usdt_balance", 10000.0) + state61.get("usdt_balance", 10000.0)
    
    open_positions = {}
    open_positions.update(state65.get("open_positions", {}))
    open_positions.update(state61.get("open_positions", {}))
    
    orders = []
    orders.extend(state65.get("orders", []))
    orders.extend(state61.get("orders", []))
    
    total_pnl = state65.get("total_pnl", 0.0) + state61.get("total_pnl", 0.0)
    total_trades = state65.get("total_trades", 0) + state61.get("total_trades", 0)
    
    win_rate = 0.0
    if total_trades > 0:
        closed_orders = [o for o in orders if o.get("close_reason") and o.get("status") == "filled"]
        if closed_orders:
            wins = sum(1 for o in closed_orders if o.get("pnl_usdt", 0.0) > 0)
            win_rate = wins / len(closed_orders)

    return {
        "usdt_balance": balance,
        "open_positions": open_positions,
        "orders": orders,
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "last_updated": datetime.now().isoformat(),
    }


def get_open_positions_df() -> pd.DataFrame:
    """Açık pozisyonları DataFrame olarak döndürür."""
    state = load_portfolio_state()
    positions = state.get("open_positions", {})
    if not positions:
        return pd.DataFrame()

    rows = []
    for sym, pos in positions.items():
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", entry)
        sl = pos.get("stop_loss", 0)
        tp = pos.get("take_profit", 0)
        pnl_usdt = pos.get("pnl_usdt", 0)
        pnl_pct = pos.get("pnl_pct", 0)
        opened_at = pos.get("opened_at", "")

        # SL/TP mesafeleri
        sl_dist = abs(entry - sl) / entry * 100 if entry > 0 else 0
        tp_dist = abs(tp - entry) / entry * 100 if entry > 0 else 0

        rows.append({
            "Sembol": sym,
            "Yön": pos.get("side", "long").upper(),
            "Kategori": pos.get("category", "SAFE"),
            "Giriş": entry,
            "Anlık": current,
            "PnL ($)": round(pnl_usdt, 2),
            "PnL (%)": round(pnl_pct * 100, 2),
            "SL": sl,
            "TP": tp,
            "SL Mesafe": f"{sl_dist:.1f}%",
            "TP Mesafe": f"{tp_dist:.1f}%",
            "Açılış": opened_at[:16] if opened_at else "",
        })

    return pd.DataFrame(rows)


def get_closed_trades_df() -> pd.DataFrame:
    """Kapanmış işlemleri DataFrame olarak döndürür."""
    state = load_portfolio_state()
    orders = state.get("orders", [])

    exit_orders = [o for o in orders if o.get("close_reason") and o.get("status") == "filled"]
    entry_orders = [o for o in orders if not o.get("close_reason") and o.get("status") == "filled"]

    rows = []
    for exit_ord in exit_orders:
        expected_entry_side = "buy" if exit_ord["side"] == "sell" else "sell"
        matching_entry = None
        for entry_ord in reversed(entry_orders):
            if (entry_ord["symbol"] == exit_ord["symbol"]
                    and entry_ord["side"] == expected_entry_side
                    and entry_ord["timestamp"] < exit_ord["timestamp"]):
                matching_entry = entry_ord
                break

        if not matching_entry:
            continue

        b_price = matching_entry["price"]
        s_price = exit_ord["price"]
        b_amount = matching_entry.get("amount", 0.0)
        direction = "LONG" if expected_entry_side == "buy" else "SHORT"

        pnl_usdt = exit_ord.get("pnl_usdt")
        pnl_pct = exit_ord.get("pnl_pct")
        if pnl_usdt is None:
            if expected_entry_side == "buy":
                pnl_usdt = (s_price - b_price) * b_amount
                pnl_pct = (s_price - b_price) / b_price if b_price > 0 else 0
            else:
                pnl_usdt = (b_price - s_price) * b_amount
                pnl_pct = (b_price - s_price) / b_price if b_price > 0 else 0

        try:
            entry_dt = datetime.fromisoformat(matching_entry["timestamp"])
            exit_dt = datetime.fromisoformat(exit_ord["timestamp"])
            duration_h = (exit_dt - entry_dt).total_seconds() / 3600
        except Exception:
            entry_dt = exit_dt = None
            duration_h = 0

        rows.append({
            "Sembol": exit_ord["symbol"],
            "Yön": direction,
            "Giriş Tarihi": entry_dt,
            "Çıkış Tarihi": exit_dt,
            "Giriş ($)": round(b_price, 6),
            "Çıkış ($)": round(s_price, 6),
            "PnL ($)": round(pnl_usdt, 2),
            "PnL (%)": round(pnl_pct * 100, 2),
            "Süre (saat)": round(duration_h, 1),
            "Kapanış Sebebi": exit_ord.get("close_reason", "KAPANDI"),
        })

    df = pd.DataFrame(rows)
    if not df.empty and "Çıkış Tarihi" in df.columns:
        df = df.sort_values("Çıkış Tarihi", ascending=False)
    return df


def get_portfolio_metrics() -> dict:
    """Temel portföy metriklerini hesaplar."""
    state = load_portfolio_state()
    closed = get_closed_trades_df()

    balance = state.get("usdt_balance", 10000.0)
    total_pnl = state.get("total_pnl", 0)
    total_trades = state.get("total_trades", 0)
    win_rate = state.get("win_rate", 0)

    # Kapalı işlemlerden hesapla
    if not closed.empty:
        wins = len(closed[closed["PnL ($)"] > 0])
        total_trades = len(closed)
        win_rate = wins / total_trades if total_trades > 0 else 0
        total_pnl = closed["PnL ($)"].sum()

    # Drawdown
    max_drawdown = 0.0
    if not closed.empty and "PnL ($)" in closed.columns:
        cumulative = closed["PnL ($)"].iloc[::-1].cumsum()
        running_max = cumulative.cummax()
        drawdown = (running_max - cumulative)
        max_drawdown = float(drawdown.max()) if len(drawdown) > 0 else 0.0

    # Sharpe (basit)
    sharpe = 0.0
    if not closed.empty and len(closed) > 1:
        returns = closed["PnL (%)"].values
        if returns.std() != 0:
            sharpe = round(returns.mean() / returns.std() * (252 ** 0.5) / 100, 2)

    return {
        "balance": round(balance, 2),
        "total_pnl": round(total_pnl, 2),
        "total_trades": total_trades,
        "win_rate": round(win_rate * 100, 1),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": sharpe,
        "open_count": len(state.get("open_positions", {})),
    }


def get_equity_curve() -> pd.DataFrame:
    """Equity curve için zaman serisi üretir."""
    closed = get_closed_trades_df()
    state = load_portfolio_state()
    start_balance = 10000.0

    if closed.empty:
        # Veri yoksa düz çizgi
        now = datetime.now()
        dates = [now - timedelta(hours=i) for i in range(24, 0, -1)]
        return pd.DataFrame({"Tarih": dates, "Bakiye": [start_balance] * 24})

    closed_sorted = closed.sort_values("Çıkış Tarihi")
    dates = [closed_sorted["Çıkış Tarihi"].iloc[0] - timedelta(hours=1)]
    balances = [start_balance]

    cumulative = start_balance
    for _, row in closed_sorted.iterrows():
        cumulative += row["PnL ($)"]
        dates.append(row["Çıkış Tarihi"])
        balances.append(round(cumulative, 2))

    # Şimdiki bakiyeyi ekle
    dates.append(datetime.now())
    balances.append(round(state.get("usdt_balance", cumulative), 2))

    return pd.DataFrame({"Tarih": dates, "Bakiye": balances})


# ─── Sinyal Verisi ─────────────────────────────────────────

def _load_single_signals(path: Path, limit: int = 500) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                rows.append(obj)
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return rows


def load_signals(limit: int = 500) -> pd.DataFrame:
    """signals.jsonl ve signals_v61.jsonl dosyalarından son N sinyali okur ve birleştirir."""
    rows65 = _load_single_signals(SIGNALS_JSONL_PATH, limit)
    rows61 = _load_single_signals(SIGNALS_JSONL_PATH_V61, limit)
    
    all_rows = rows65 + rows61
    if not all_rows:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_rows)
    
    # Tarihe göre sırala
    if "generated_at" in df.columns:
        df["generated_at"] = pd.to_datetime(df["generated_at"], errors="coerce")
        df = df.sort_values("generated_at")
        
    return df.tail(limit)


def get_signal_summary() -> dict:
    """Sinyal istatistiklerini döndürür."""
    df = load_signals(limit=2000)
    if df.empty:
        return {"buy": 0, "sell": 0, "hold": 0, "no_signal": 0, "total": 0}

    counts = df["signal_type"].value_counts().to_dict() if "signal_type" in df.columns else {}
    return {
        "buy": counts.get("BUY", 0),
        "sell": counts.get("SELL", 0),
        "hold": counts.get("HOLD", 0),
        "no_signal": counts.get("NO_SIGNAL", 0),
        "total": len(df),
    }


# ─── Canlı OHLCV (ccxt) ────────────────────────────────────

def fetch_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 200) -> pd.DataFrame:
    """ccxt Binance'ten OHLCV verisi çeker."""
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")
        return df
    except Exception as e:
        # Hata durumunda dummy veri
        return _generate_dummy_ohlcv(limit)


def _generate_dummy_ohlcv(n: int = 200) -> pd.DataFrame:
    """API bağlantısı yoksa demo veri üretir."""
    np.random.seed(42)
    dates = pd.date_range(end=datetime.now(), periods=n, freq="1h")
    price = 65000.0
    prices = []
    for _ in range(n):
        price *= 1 + np.random.normal(0, 0.005)
        prices.append(price)

    opens = prices
    closes = [p * (1 + np.random.normal(0, 0.003)) for p in prices]
    highs = [max(o, c) * (1 + abs(np.random.normal(0, 0.002))) for o, c in zip(opens, closes)]
    lows = [min(o, c) * (1 - abs(np.random.normal(0, 0.002))) for o, c in zip(opens, closes)]
    volumes = [np.random.uniform(1e6, 5e6) for _ in range(n)]

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes
    }, index=dates)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Bollinger Bantları ve RSI ekler."""
    if df.empty or len(df) < 20:
        return df

    close = df["close"]

    # Bollinger Bands (20, 2)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df = df.copy()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_mid"] = sma20
    df["bb_lower"] = sma20 - 2 * std20

    # RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # EMA 20/50
    df["ema20"] = close.ewm(span=20).mean()
    df["ema50"] = close.ewm(span=50).mean()

    return df


def get_daily_pnl() -> pd.DataFrame:
    """Günlük PnL hesaplar."""
    closed = get_closed_trades_df()
    if closed.empty or "Çıkış Tarihi" not in closed.columns:
        return pd.DataFrame()

    df = closed.copy()
    df["Gün"] = pd.to_datetime(df["Çıkış Tarihi"]).dt.date
    daily = df.groupby("Gün")["PnL ($)"].sum().reset_index()
    daily.columns = ["Gün", "PnL ($)"]
    return daily
