# -*- coding: utf-8 -*-
"""
backtest_v5_10k.py — V5 Price Action stratejisi ile 1 yıllık backtest.
$10,000 başlangıç sermayesi ile tüm coin'lerde test.
"""
import pandas as pd
import numpy as np
import os
import sys
import glob

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = r"C:\Users\52tuz\Desktop\deneme borsa\data\historical_1y_15m_all"
INITIAL_CAPITAL = 10000.0
LEVERAGE = 5
COMMISSION_RATE = 0.00063
RISK_PER_TRADE = 0.02
TARGET_RR = 5.5
SWEEP_WINDOW = 100
MAX_HOLD_SWEEP = 7
TREND_EMA = 180
ATR_MULT = 0.6

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def run_backtest_single(df, symbol):
    """Tek coin üzerinde backtest çalıştır."""
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)

    df['swing_high'] = df['high'].shift(1).rolling(window=SWEEP_WINDOW).max()
    df['swing_low'] = df['low'].shift(1).rolling(window=SWEEP_WINDOW).min()
    df['trend_ema'] = df['close'].ewm(span=TREND_EMA, adjust=False).mean()
    df['atr'] = calculate_atr(df)

    capital = INITIAL_CAPITAL
    position = None  # {type, entry, sl, tp, size, entry_time}
    trades = []
    equity_curve = []

    start_idx = int(max(SWEEP_WINDOW, TREND_EMA) + 2)
    last_bull_idx = -1
    last_bull_low = 0.0
    last_bear_idx = -1
    last_bear_high = 0.0

    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    opens_arr = df['open'].values
    swing_highs = df['swing_high'].values
    swing_lows = df['swing_low'].values
    emas = df['trend_ema'].values
    atrs = df['atr'].values
    times = df['datetime'].values

    for i in range(start_idx, len(df)):
        h, l, c, o = highs[i], lows[i], closes[i], opens_arr[i]
        ema_val = emas[i]
        atr_val = atrs[i]

        if pd.isna(ema_val) or pd.isna(atr_val) or atr_val == 0:
            equity_curve.append(capital)
            continue

        candle_range = h - l
        if candle_range == 0:
            equity_curve.append(capital)
            continue

        # Pozisyon varsa k kontrolü
        if position is not None:
            hit_sl = False
            hit_tp = False

            if position['type'] == 'LONG':
                if l <= position['sl']:
                    hit_sl = True
                elif h >= position['tp']:
                    hit_tp = True
            else:
                if h >= position['sl']:
                    hit_sl = True
                elif l <= position['tp']:
                    hit_tp = True

            if hit_sl or hit_tp:
                if hit_sl:
                    exit_price = position['sl']
                else:
                    exit_price = position['tp']

                if position['type'] == 'LONG':
                    pnl_pct = (exit_price - position['entry']) / position['entry']
                else:
                    pnl_pct = (position['entry'] - exit_price) / position['entry']

                pnl_usd = pnl_pct * position['size'] * LEVERAGE
                commission = position['size'] * COMMISSION_RATE * LEVERAGE * 2
                net_pnl = pnl_usd - commission
                capital += net_pnl

                trades.append({
                    'symbol': symbol,
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl_pct': pnl_pct * 100,
                    'pnl_usd': net_pnl,
                    'entry_time': position['entry_time'],
                    'exit_time': times[i],
                    'result': 'WIN' if net_pnl > 0 else 'LOSS'
                })
                position = None

        # Yeni sinyal kontrolü (pozisyon yoksa)
        if position is None:
            # Bullish sweep
            is_bull_sweep = (l < swing_lows[i]) and (c > swing_lows[i])
            if is_bull_sweep:
                lower_wick = min(c, o) - l
                if candle_range > 0 and (lower_wick / candle_range >= 0.35 or (c > o and closes[i-1] < opens_arr[i-1])):
                    last_bull_idx = i
                    last_bull_low = l
                    last_bear_idx = -1

            # Bearish sweep
            is_bear_sweep = (h > swing_highs[i]) and (c < swing_highs[i])
            if is_bear_sweep:
                upper_wick = h - max(c, o)
                if candle_range > 0 and (upper_wick / candle_range >= 0.35 or (c < o and closes[i-1] > opens_arr[i-1])):
                    last_bear_idx = i
                    last_bear_high = h
                    last_bull_idx = -1

            # Bullish entry
            if last_bull_idx != -1 and i - last_bull_idx <= MAX_HOLD_SWEEP:
                if c > max(closes[i-1], closes[i-2], closes[i-3]):
                    if c > ema_val:
                        sl = last_bull_low - (atr_val * ATR_MULT)
                        risk = c - sl
                        if risk > 0:
                            tp = c + (TARGET_RR * risk)
                            size = (capital * RISK_PER_TRADE) / (risk / c * LEVERAGE)
                            if size > 0 and size * LEVERAGE <= capital:
                                position = {
                                    'type': 'LONG',
                                    'entry': c,
                                    'sl': sl,
                                    'tp': tp,
                                    'size': size,
                                    'entry_time': times[i]
                                }
                                last_bull_idx = -1

            # Bearish entry
            elif last_bear_idx != -1 and i - last_bear_idx <= MAX_HOLD_SWEEP:
                if c < min(closes[i-1], closes[i-2], closes[i-3]):
                    if c < ema_val:
                        sl = last_bear_high + (atr_val * ATR_MULT)
                        risk = sl - c
                        if risk > 0:
                            tp = c - (TARGET_RR * risk)
                            size = (capital * RISK_PER_TRADE) / (risk / c * LEVERAGE)
                            if size > 0 and size * LEVERAGE <= capital:
                                position = {
                                    'type': 'SHORT',
                                    'entry': c,
                                    'sl': sl,
                                    'tp': tp,
                                    'size': size,
                                    'entry_time': times[i]
                                }
                                last_bear_idx = -1

        equity_curve.append(capital)

    # Açık pozisyon varsa kapat
    if position is not None:
        exit_price = closes[-1]
        if position['type'] == 'LONG':
            pnl_pct = (exit_price - position['entry']) / position['entry']
        else:
            pnl_pct = (position['entry'] - exit_price) / position['entry']
        pnl_usd = pnl_pct * position['size'] * LEVERAGE
        commission = position['size'] * COMMISSION_RATE * LEVERAGE * 2
        net_pnl = pnl_usd - commission
        capital += net_pnl
        trades.append({
            'symbol': symbol,
            'type': position['type'],
            'entry': position['entry'],
            'exit': exit_price,
            'pnl_pct': pnl_pct * 100,
            'pnl_usd': net_pnl,
            'entry_time': position['entry_time'],
            'exit_time': times[-1],
            'result': 'WIN' if net_pnl > 0 else 'LOSS'
        })

    return trades, capital, equity_curve

# ─── Ana Çalıştırma ──────────────────────────────────────────
print("=" * 70)
print("  Trading Bot V5 — 1 YILLIK BACKTEST ($10,000 Sermaye)")
print("  15 Dakikalık Veri · 20 Coin · 5x Kaldıraç")
print("=" * 70)
print()

csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
all_trades = []
results_summary = []

for csv_path in csv_files:
    symbol = os.path.basename(csv_path).replace("_15m_all.csv", "")
    print(f"  {symbol} işleniyor...", end=" ")

    try:
        df = pd.read_csv(csv_path)
        trades, final_capital, equity = run_backtest_single(df, symbol)
        all_trades.extend(trades)

        total_pnl = sum(t['pnl_usd'] for t in trades)
        win_trades = [t for t in trades if t['result'] == 'WIN']
        loss_trades = [t for t in trades if t['result'] == 'LOSS']
        win_rate = len(win_trades) / len(trades) * 100 if trades else 0

        results_summary.append({
            'symbol': symbol,
            'trades': len(trades),
            'wins': len(win_trades),
            'losses': len(loss_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'final_capital': final_capital
        })
        print(f"{len(trades)} işlem, PnL: ${total_pnl:+.2f}, Win: %{win_rate:.1f}")
    except Exception as e:
        print(f"HATA: {e}")

# ─── Genel Sonuçlar ──────────────────────────────────────────
print()
print("=" * 70)
print("  GENEL SONUÇLAR")
print("=" * 70)

total_trades = len(all_trades)
total_wins = len([t for t in all_trades if t['result'] == 'WIN'])
total_losses = len([t for t in all_trades if t['result'] == 'LOSS'])
overall_win_rate = total_wins / total_trades * 100 if total_trades else 0

total_pnl_all = sum(t['pnl_usd'] for t in all_trades)
final_capital_total = INITIAL_CAPITAL + total_pnl_all
roi = (final_capital_total / INITIAL_CAPITAL - 1) * 100

avg_win = np.mean([t['pnl_usd'] for t in all_trades if t['result'] == 'WIN']) if total_wins else 0
avg_loss = np.mean([t['pnl_usd'] for t in all_trades if t['result'] == 'LOSS']) if total_losses else 0
profit_factor = abs(avg_win * total_wins / (avg_loss * total_losses)) if total_losses and avg_loss != 0 else float('inf')

# Max drawdown
if all_trades:
    cumulative = np.cumsum([t['pnl_usd'] for t in all_trades])
    peak = np.maximum.accumulate(cumulative + INITIAL_CAPITAL)
    drawdown = (peak - (cumulative + INITIAL_CAPITAL)) / peak * 100
    max_drawdown = np.max(drawdown)
else:
    max_drawdown = 0

print(f"""
  Başlangıç Sermayesi:  ${INITIAL_CAPITAL:,.2f}
  Toplam İşlem:         {total_trades}
  Kazanma Oranı:        %{overall_win_rate:.1f} ({total_wins}W / {total_losses}L)
  Ortalama Kazanç:      ${avg_win:+.2f}
  Ortalama Kayıp:       ${avg_loss:+.2f}
  Profit Factor:        {profit_factor:.2f}
  Maksimum Drawdown:    %{max_drawdown:.1f}
  
  ─── NET SONUÇ ───
  Toplam Kâr/Zarar:     ${total_pnl_all:+,.2f}
  Final Sermaye:        ${final_capital_total:,.2f}
  Getiri (ROI):         %{roi:+.1f}
""")

# ─── En İyi/Kötü Coin'ler ──────────────────────────────────
if results_summary:
    sorted_by_pnl = sorted(results_summary, key=lambda x: x['total_pnl'], reverse=True)
    print("  EN İYİ 5 COIN:")
    for r in sorted_by_pnl[:5]:
        print(f"    {r['symbol']:15s} {r['trades']:3d} işlem  %{r['win_rate']:.0f} win  ${r['total_pnl']:+.2f}")
    print()
    print("  EN KÖTÜ 5 COIN:")
    for r in sorted_by_pnl[-5:]:
        print(f"    {r['symbol']:15s} {r['trades']:3d} işlem  %{r['win_rate']:.0f} win  ${r['total_pnl']:+.2f}")
