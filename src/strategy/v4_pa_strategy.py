# -*- coding: utf-8 -*-
"""
src/strategy/v4_pa_strategy.py — Stateful Price Action & SMC Strategy V4.
"""
import pandas as pd
import numpy as np
import ta
import datetime
from src.strategy.smc_utils import get_premium_discount_zone, detect_order_block

def check_v4_session(timestamp):
    if not timestamp or np.isnan(timestamp):
        return False
    if timestamp > 1e11:
        timestamp = timestamp / 1000.0
    try:
        dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        hour = dt.hour
        return (7 <= hour < 10) or (12 <= hour < 16)
    except Exception:
        return False

def check_ote_condition(entry_price, swing_h, swing_l, side):
    swing_range = swing_h - swing_l
    if swing_range <= 0:
        return False
    if side == "BUY":
        retracement = (swing_h - entry_price) / swing_range
    else: # SELL
        retracement = (entry_price - swing_l) / swing_range
    return 0.62 <= retracement <= 0.79

class V4PriceActionStrategy:
    """Trading Bot V4 Price Action & Smart Money Concepts Strategy.
    
    Optimized confluences:
      1. Refined Session Kill Zone Filtering (London 07-10 UTC, NY 12-16 UTC).
      2. Fibonacci OTE (Optimal Trade Entry 0.62 - 0.79) pullback validation.
      3. High Volume breakout confirmation.
      4. Funding & Open Interest institutional flow tracking.
    """
    
    def __init__(
        self, 
        sweep_window=120, 
        max_hold_sweep=5, 
        target_rr=3.0, 
        partial_rr=1.5, 
        require_trend=True, 
        displacement_atr_mult=1.5, 
        use_premium_discount=True, 
        fvg_wait=3,
        use_session_filter=True,
        use_ote_filter=False,     # Optional OTE check
        use_volume_filter=False,  # Optional volume check
        use_funding_oi_filter=False, # Optional funding/OI check
    ):
        self.sweep_window = sweep_window
        self.max_hold_sweep = max_hold_sweep
        self.target_rr = target_rr
        self.partial_rr = partial_rr
        self.require_trend = require_trend
        self.displacement_atr_mult = displacement_atr_mult
        self.use_premium_discount = use_premium_discount
        self.fvg_wait = fvg_wait
        self.use_session_filter = use_session_filter
        self.use_ote_filter = use_ote_filter
        self.use_volume_filter = use_volume_filter
        self.use_funding_oi_filter = use_funding_oi_filter

    def calculate_signals(self, df):
        """Calculates indicators and entry setups. Returns a df with signals."""
        df = df.copy()
        
        # Base Swing High/Low & Trend Indicators
        df["swing_high"] = df["high"].shift(1).rolling(window=self.sweep_window).max()
        df["swing_low"] = df["low"].shift(1).rolling(window=self.sweep_window).min()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df["atr"] = true_range.rolling(window=14).mean()
        
        # Optional Volume Confirmation Indicator
        if self.use_volume_filter:
            df["vol_sma"] = df["volume"].rolling(window=20).mean()
            
        # Ensure Funding and Open Interest columns exist
        if "funding_rate" not in df.columns:
            df["funding_rate"] = 0.0
        if "open_interest" not in df.columns:
            df["open_interest"] = 0.0
            
        df["signal"] = "HOLD"
        df["entry_price"] = 0.0
        df["sl_price"] = 0.0
        df["tp_price"] = 0.0
        df["has_fvg"] = False
        
        last_bull_sweep_idx = -1
        last_bull_sweep_low = 0.0
        last_bear_sweep_idx = -1
        last_bear_sweep_high = 0.0
        
        start_idx = int(max(self.sweep_window, 200) + 2)
        if start_idx >= len(df):
            return df
            
        for i in range(start_idx, len(df)):
            high_prev = df["swing_high"].iloc[i]
            low_prev = df["swing_low"].iloc[i]
            ema200_val = df["ema200"].iloc[i]
            atr_val = df["atr"].iloc[i]
            
            h = df["high"].iloc[i]
            l = df["low"].iloc[i]
            c = df["close"].iloc[i]
            o = df["open"].iloc[i]
            
            candle_range = h - l
            if candle_range == 0:
                continue
                
            # Sweep Detection
            is_bull_sweep_now = (l < low_prev) and (c > low_prev)
            if is_bull_sweep_now:
                lower_wick = min(c, o) - l
                is_bull_rejection = (lower_wick / candle_range >= 0.35) or (c > o and df["close"].iloc[i-1] < df["open"].iloc[i-1])
                if is_bull_rejection:
                    last_bull_sweep_idx = i
                    last_bull_sweep_low = l
                    last_bear_sweep_idx = -1
                    
            is_bear_sweep_now = (h > high_prev) and (c < high_prev)
            if is_bear_sweep_now:
                upper_wick = h - max(c, o)
                is_bear_rejection = (upper_wick / candle_range >= 0.35) or (c < o and df["close"].iloc[i-1] > df["open"].iloc[i-1])
                if is_bear_rejection:
                    last_bear_sweep_idx = i
                    last_bear_sweep_high = h
                    last_bull_sweep_idx = -1
                    
            # Stateful Signal Evaluation
            # 1. BULLISH SETUP
            if last_bull_sweep_idx != -1:
                if i - last_bull_sweep_idx > self.max_hold_sweep:
                    last_bull_sweep_idx = -1
                else:
                    is_bullish_mss = c > max(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                    if is_bullish_mss:
                        trend_ok = True
                        if self.require_trend:
                            trend_ok = (c > ema200_val)
                            
                        if self.use_premium_discount and trend_ok:
                            swing_h = df["swing_high"].iloc[last_bull_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bull_sweep_idx]
                            zone = get_premium_discount_zone(c, swing_h, swing_l)
                            trend_ok = (zone == "DISCOUNT")
                            
                        # V4 Confluence Filters
                        if trend_ok:
                            # A. Session Filter
                            if self.use_session_filter:
                                timestamp_val = df.index[i].timestamp() if hasattr(df.index[i], 'timestamp') else df.index[i]
                                if not check_v4_session(timestamp_val):
                                    trend_ok = False
                                    
                            # B. Fibonacci OTE Filter
                            if trend_ok and self.use_ote_filter:
                                fvg_gap = df["low"].iloc[i] - df["high"].iloc[i-2]
                                entry_price_check = (df["low"].iloc[i] + df["high"].iloc[i-2]) / 2.0 if fvg_gap > 0 else c
                                swing_h = df["swing_high"].iloc[last_bull_sweep_idx]
                                swing_l = df["swing_low"].iloc[last_bull_sweep_idx]
                                if not check_ote_condition(entry_price_check, swing_h, swing_l, "BUY"):
                                    trend_ok = False
                                    
                            # C. Volume Filter
                            if trend_ok and self.use_volume_filter:
                                vol_sma_val = df["vol_sma"].iloc[i]
                                if not pd.isna(vol_sma_val) and vol_sma_val > 0:
                                    if df["volume"].iloc[i] / vol_sma_val <= 1.5:
                                        trend_ok = False
                                        
                            # D. Funding & OI Filter
                            if trend_ok and self.use_funding_oi_filter:
                                funding_rate_val = df["funding_rate"].iloc[i]
                                if funding_rate_val > 0.0005:
                                    trend_ok = False
                                if trend_ok:
                                    oi_sweep = df["open_interest"].iloc[last_bull_sweep_idx]
                                    oi_mss = df["open_interest"].iloc[i]
                                    if oi_sweep > 0 and oi_mss > 0 and oi_mss <= oi_sweep:
                                        trend_ok = False
                                        
                        if trend_ok:
                            df.at[df.index[i], "signal"] = "BUY"
                            sl = last_bull_sweep_low - (atr_val * 0.5)
                            
                            fvg_gap = df["low"].iloc[i] - df["high"].iloc[i-2]
                            if fvg_gap > 0:
                                df.at[df.index[i], "has_fvg"] = True
                                fvg_mid = (df["low"].iloc[i] + df["high"].iloc[i-2]) / 2.0
                                df.at[df.index[i], "entry_price"] = fvg_mid
                            else:
                                df.at[df.index[i], "entry_price"] = c
                                
                            risk = df["entry_price"].iloc[i] - sl
                            if risk <= 0:
                                risk = atr_val * 0.5
                                sl = df["entry_price"].iloc[i] - risk
                                
                            df.at[df.index[i], "sl_price"] = sl
                            df.at[df.index[i], "tp_price"] = df["entry_price"].iloc[i] + (self.target_rr * risk)
                            last_bull_sweep_idx = -1
                            
            # 2. BEARISH SETUP
            if last_bear_sweep_idx != -1:
                if i - last_bear_sweep_idx > self.max_hold_sweep:
                    last_bear_sweep_idx = -1
                else:
                    is_bearish_mss = c < min(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                    if is_bearish_mss:
                        trend_ok = True
                        if self.require_trend:
                            trend_ok = (c < ema200_val)
                            
                        if self.use_premium_discount and trend_ok:
                            swing_h = df["swing_high"].iloc[last_bear_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bear_sweep_idx]
                            zone = get_premium_discount_zone(c, swing_h, swing_l)
                            trend_ok = (zone == "PREMIUM")
                            
                        # V4 Confluence Filters
                        if trend_ok:
                            # A. Session Filter
                            if self.use_session_filter:
                                timestamp_val = df.index[i].timestamp() if hasattr(df.index[i], 'timestamp') else df.index[i]
                                if not check_v4_session(timestamp_val):
                                    trend_ok = False
                                    
                            # B. Fibonacci OTE Filter
                            if trend_ok and self.use_ote_filter:
                                fvg_gap = df["low"].iloc[i-2] - df["high"].iloc[i]
                                entry_price_check = (df["high"].iloc[i] + df["low"].iloc[i-2]) / 2.0 if fvg_gap > 0 else c
                                swing_h = df["swing_high"].iloc[last_bear_sweep_idx]
                                swing_l = df["swing_low"].iloc[last_bear_sweep_idx]
                                if not check_ote_condition(entry_price_check, swing_h, swing_l, "SELL"):
                                    trend_ok = False
                                    
                            # C. Volume Filter
                            if trend_ok and self.use_volume_filter:
                                vol_sma_val = df["vol_sma"].iloc[i]
                                if not pd.isna(vol_sma_val) and vol_sma_val > 0:
                                    if df["volume"].iloc[i] / vol_sma_val <= 1.5:
                                        trend_ok = False
                                        
                            # D. Funding & OI Filter
                            if trend_ok and self.use_funding_oi_filter:
                                funding_rate_val = df["funding_rate"].iloc[i]
                                if funding_rate_val < -0.0005:
                                    trend_ok = False
                                if trend_ok:
                                    oi_sweep = df["open_interest"].iloc[last_bear_sweep_idx]
                                    oi_mss = df["open_interest"].iloc[i]
                                    if oi_sweep > 0 and oi_mss > 0 and oi_mss <= oi_sweep:
                                        trend_ok = False
                                        
                        if trend_ok:
                            df.at[df.index[i], "signal"] = "SELL"
                            sl = last_bear_sweep_high + (atr_val * 0.5)
                            
                            fvg_gap = df["low"].iloc[i-2] - df["high"].iloc[i]
                            if fvg_gap > 0:
                                df.at[df.index[i], "has_fvg"] = True
                                fvg_mid = (df["high"].iloc[i] + df["low"].iloc[i-2]) / 2.0
                                df.at[df.index[i], "entry_price"] = fvg_mid
                            else:
                                df.at[df.index[i], "entry_price"] = c
                                
                            risk = sl - df["entry_price"].iloc[i]
                            if risk <= 0:
                                risk = atr_val * 0.5
                                sl = df["entry_price"].iloc[i] + risk
                                
                            df.at[df.index[i], "sl_price"] = sl
                            df.at[df.index[i], "tp_price"] = df["entry_price"].iloc[i] - (self.target_rr * risk)
                            last_bear_sweep_idx = -1
                            
        return df
