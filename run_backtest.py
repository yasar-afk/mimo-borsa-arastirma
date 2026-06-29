# ============================================================
# run_backtest.py — 100 Günlük Backtest Çalıştırıcı
#
# AMAÇ:
#   Top 100 USDT çifti üzerinde 100 günlük backtest çalıştırır,
#   tüm stratejileri test eder ve kapsamlı rapor üretir.
#
# ÇALIŞTIRMA:
#   python run_backtest.py
#   python run_backtest.py --days 100 --top 100 --capital 10000
# ============================================================

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.data.historical import HistoricalDataFetcher
from src.backtest.engine import BacktestEngine, MultiSymbolBacktest, BacktestResult
from src.backtest.report import BacktestReporter
from src.strategy.v6_trend import V6TrendFollowing
from src.strategy.v6_mean_rev import V6MeanReversion
from src.strategy.v6_grid import V6GridTrading
from src.strategy.regime_detector import RegimeDetector, MarketRegime
from src.strategy.ml_filter import MLSignalFilter
from src.technical.indicators import enrich_with_new_indicators
from src.utils.logger import get_logger

logger = get_logger("backtest_runner")


def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame'e tüm indikatörleri ekler.

    Args:
        df: Ham OHLCV DataFrame.

        Returns:
            Tüm indikatörler eklenmiş DataFrame.
    """
    df = df.copy()

    # Mevcut indikatörler (TechnicalEngine'den)
    close = df["close"]
    df["ema_fast"] = close.ewm(span=21, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=55, adjust=False).mean()
    df["ema_trend"] = close.ewm(span=200, adjust=False).mean()

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd_line"] = ema12 - ema26
    df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd_line"] - df["macd_signal"]

    # RSI
    delta = close.diff()
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
    df["atr_ma"] = df["atr"].rolling(window=14).mean()

    # Bollinger Bands
    df["bb_mid"] = close.rolling(window=20).mean()
    bb_std = close.rolling(window=20).std()
    df["bb_upper"] = df["bb_mid"] + 2.0 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2.0 * bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_width_ma"] = df["bb_width"].rolling(window=20).mean()

    # Hacim
    df["volume_ma"] = df["volume"].rolling(window=20).mean()

    # ADX
    plus_dm = df["high"].diff()
    minus_dm = -df["low"].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    atr14 = tr.rolling(window=14).mean()
    smooth_plus = plus_dm.rolling(window=14).mean()
    smooth_minus = minus_dm.rolling(window=14).mean()
    plus_di = 100 * smooth_plus / atr14
    minus_di = 100 * smooth_minus / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    df["adx"] = dx.rolling(window=14).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di

    # Yeni indikatörler
    df = enrich_with_new_indicators(df)

    return df


def run_strategy_backtest(
    data: pd.DataFrame,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    engine: BacktestEngine,
) -> Optional[BacktestResult]:
    """Tek bir strateji için backtest çalıştırır.

    Args:
        data: İndikatörlü DataFrame.
        strategy_name: Strateji adı.
        symbol: Sembol.
        timeframe: Timeframe.
        engine: BacktestEngine instance'ı.

        Returns:
            BacktestResult veya None.
    """
    if strategy_name == "trend_following":
        strategy = V6TrendFollowing()
        
        def signal_fn(df, idx):
            sig = strategy.generate_signal(df, idx)
            if isinstance(sig, dict):
                return sig.get("type")
            return sig
            
    elif strategy_name == "mean_reversion":
        strategy = V6MeanReversion()
        
        def signal_fn(df, idx):
            sig = strategy.generate_signal(df, idx)
            if isinstance(sig, dict):
                return sig.get("type")
            return sig
            
    elif strategy_name == "mean_reversion_ai":
        strategy = V6MeanReversion()
        ml_filter = MLSignalFilter()
        
        def signal_fn(df, idx):
            sig = strategy.generate_signal(df, idx)
            if isinstance(sig, dict):
                sig_type = sig.get("type")
            else:
                sig_type = sig
                
            if sig_type and ml_filter.is_trained:
                prob = ml_filter.predict_probability(df, idx, sig_type)
                if prob < 0.60:
                    return None
            return sig_type
            
    elif strategy_name == "grid_trading":
        strategy = V6GridTrading()
        
        def signal_fn(df, idx):
            sig = strategy.generate_signal(df, idx)
            if isinstance(sig, dict):
                return sig.get("type")
            return sig
            
    elif strategy_name == "regime_adaptive":
        regime_detector = RegimeDetector()
        trend_strat = V6TrendFollowing()
        mean_rev_strat = V6MeanReversion()

        def signal_fn(df, idx):
            regime = regime_detector.detect(df, idx)
            if regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
                sig = trend_strat.generate_signal(df, idx)
            else:
                sig = mean_rev_strat.generate_signal(df, idx)
                
            if isinstance(sig, dict):
                return sig.get("type")
            return sig

    elif strategy_name == "regime_adaptive_ai":
        regime_detector = RegimeDetector()
        trend_strat = V6TrendFollowing()
        mean_rev_strat = V6MeanReversion()
        ml_filter = MLSignalFilter()
        
        def signal_fn(df, idx):
            regime = regime_detector.detect(df, idx)
            if regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
                sig = trend_strat.generate_signal(df, idx)
            else:
                sig = mean_rev_strat.generate_signal(df, idx)
                
            if isinstance(sig, dict):
                sig_type = sig.get("type")
            else:
                sig_type = sig
                
            if sig_type and ml_filter.is_trained:
                prob = ml_filter.predict_probability(df, idx, sig_type)
                if prob < 0.60:
                    return None
            return sig_type

    else:
        return None

    return engine.run(
        data=data,
        strategy_fn=signal_fn,
        symbol=symbol,
        strategy_name=strategy_name,
        timeframe=timeframe,
    )


def main():
    """Ana fonksiyon."""
    parser = argparse.ArgumentParser(description="Trading Bot 100-Day Backtest")
    parser.add_argument("--days", type=int, default=100, help="Backtest süresi (gün)")
    parser.add_argument("--top", type=int, default=100, help="Top N sembol")
    parser.add_argument("--capital", type=float, default=10000.0, help="Başlangıç sermayesi")
    parser.add_argument("--timeframe", type=str, default="1h", help="Ana timeframe")
    parser.add_argument("--max-positions", type=int, default=10, help="Max pozisyon")
    args = parser.parse_args()

    print("=" * 80)
    print("🚀 Trading Bot V6 — 100 GÜNLÜK BACKTEST")
    print("=" * 80)
    print(f"  Sermaye     : ${args.capital:,.2f}")
    print(f"  Süre        : {args.days} gün")
    print(f"  Semboller   : Top {args.top} USDT çifti")
    print(f"  Timeframe   : {args.timeframe}")
    print(f"  Max Pozisyon: {args.max_positions}")
    print("=" * 80)

    # 1. Veri çekiciyi başlat
    fetcher = HistoricalDataFetcher()
    print("\n📡 Binance'a bağlanılıyor...")
    try:
        fetcher.exchange.load_markets()
    except Exception as e:
        print(f"❌ Bağlantı hatası: {e}")
        sys.exit(1)

    # 2. Top N sembolü çek
    print(f"\n🔍 Top {args.top} USDT çifti aranıyor...")
    symbols = fetcher.fetch_top_symbols(top_n=args.top, quote="USDT")
    print(f"  {len(symbols)} sembol bulundu")

    # 3. Verileri çek
    print(f"\n📥 Son {args.days} günlük veriler çekiliyor...")
    limit = args.days * 24  # 1h için yaklaşık
    all_data: Dict[str, pd.DataFrame] = {}
    done = 0

    for symbol in symbols:
        done += 1
        print(f"  [{done}/{len(symbols)}] {symbol}...", end=" ", flush=True)
        try:
            df = fetcher.fetch_ohlcv(symbol, args.timeframe, limit=limit)
            if not df.empty and len(df) >= 200:
                all_data[symbol] = df
                print(f"✅ {len(df)} mum")
            else:
                print(f"❌ Yetersiz veri ({len(df)} mum)")
        except Exception as e:
            print(f"❌ Hata: {e}")
        time.sleep(0.2)

    print(f"\n✅ {len(all_data)} sembol için veri hazır")

    if not all_data:
        print("❌ Hiç sembol kalamadı! Çıkılıyor.")
        sys.exit(1)

    # 4. Backtest motorunu başlat
    engine = BacktestEngine(
        initial_capital=args.capital,
        commission_rate=0.001,
        slippage_pct=0.0005,
        max_positions=args.max_positions,
        max_position_pct=0.10,
    )

    reporter = BacktestReporter()

    # 5. Tüm stratejileri çalıştır
    strategies = [
        "trend_following",
        "mean_reversion",
        "mean_reversion_ai",
        "grid_trading",
        "regime_adaptive",
        "regime_adaptive_ai"
    ]
    all_results: Dict[str, List[BacktestResult]] = {s: [] for s in strategies}

    for strategy_name in strategies:
        print(f"\n{'=' * 60}")
        print(f"📊 Strateji: {strategy_name.upper()}")
        print(f"{'=' * 60}")

        strategy_results = []
        for symbol, data in all_data.items():
            # Veriyi hazırla
            prepared = prepare_data(data)

            # Backtest çalıştır
            result = run_strategy_backtest(
                data=prepared,
                strategy_name=strategy_name,
                symbol=symbol,
                timeframe=args.timeframe,
                engine=engine,
            )

            if result and result.metrics.total_trades > 0:
                strategy_results.append(result)
                all_results[strategy_name].append(result)

        # Strateji özeti
        if strategy_results:
            total_pnl = sum(r.metrics.total_pnl for r in strategy_results)
            total_trades = sum(r.metrics.total_trades for r in strategy_results)
            avg_win_rate = np.mean([r.metrics.win_rate for r in strategy_results])
            avg_sharpe = np.mean([r.metrics.sharpe_ratio for r in strategy_results])

            print(f"\n  📈 {strategy_name.upper()} SONUÇLARI:")
            print(f"  Test edilen sembol   : {len(strategy_results)}")
            print(f"  Toplam işlem         : {total_trades}")
            print(f"  Toplam kâr/zarar     : ${total_pnl:+,.2f}")
            print(f"  Ortalama win rate    : %{avg_win_rate:.2f}")
            print(f"  Ortalama Sharpe      : {avg_sharpe:.3f}")

    # 6. Genel karşılaştırma
    print(f"\n{'=' * 80}")
    print("📊 GENEL STRATEJİ KARŞILAŞTIRMASI")
    print(f"{'=' * 80}")
    print(f"{'Strateji':<20} {'Sembol':>8} {'Toplam İşlem':>12} {'Toplam Kâr':>14} {'Ort. Win%':>10} {'Ort. Sharpe':>12}")
    print("-" * 80)

    best_strategy = None
    best_pnl = -float("inf")

    for strategy_name in strategies:
        results = all_results[strategy_name]
        if results:
            total_pnl = sum(r.metrics.total_pnl for r in results)
            total_trades = sum(r.metrics.total_trades for r in results)
            avg_win = np.mean([r.metrics.win_rate for r in results])
            avg_sharpe = np.mean([r.metrics.sharpe_ratio for r in results])

            emoji = "🟢" if total_pnl > 0 else "🔴"
            print(f"{emoji} {strategy_name:<18} {len(results):>8} {total_trades:>12} ${total_pnl:>+12,.2f} {avg_win:>9.2f}% {avg_sharpe:>11.3f}")

            if total_pnl > best_pnl:
                best_pnl = total_pnl
                best_strategy = strategy_name

    print("-" * 80)
    if best_strategy:
        print(f"\n🏆 EN İYİ STRATEJİ: {best_strategy.upper()} (${best_pnl:+,.2f})")

    # 7. Her strateji için HTML raporları kaydet
    print(f"\n📄 HTML raporları kaydediliyor...")
    for strategy_name in strategies:
        results = all_results[strategy_name]
        if results:
            # En iyi 5 sembolü raporla
            top_results = sorted(results, key=lambda r: r.metrics.total_pnl, reverse=True)[:5]
            for r in top_results:
                safe_sym = r.symbol.replace("/", "_")
                filepath = reporter.save_html_report(
                    r,
                    filename=f"{strategy_name}_{safe_sym}.html",
                )
                print(f"  📄 {filepath}")

    # 8. Portföy özeti
    print(f"\n{'=' * 80}")
    print("💼 PORTFÖY ÖZETİ")
    print(f"{'=' * 80}")

    for strategy_name in strategies:
        results = all_results[strategy_name]
        if results:
            multi = MultiSymbolBacktest(engine)
            multi.results = results
            summary = multi.get_portfolio_summary()
            reporter.print_portfolio_summary(summary)

    print(f"\n✅ Backtest tamamlandı! Raporlar: raporlar/backtest/")


if __name__ == "__main__":
    main()
