# -*- coding: utf-8 -*-
"""
src/strategy/v3_pa_strategy.py — Stateful Price Action & SMC Strategy.
"""
import pandas as pd
import numpy as np
from src.strategy.smc_utils import get_premium_discount_zone, is_kill_zone

class V3PriceActionStrategy:
    """Trading Bot V3 Price Action & Smart Money Concepts Strategy.
    
    Karar Mantığı (Stateful Model):
      1. Likidite Temizliği (Liquidity Sweep) oluştuğunda bu durum max_hold_sweep mum boyunca saklanır.
      2. Bu süreçte Market Structure Shift (MSS/CHoCH) gerçekleşirse sinyal tetiklenir.
      3. Trend kontrolü EMA 200 ile yapılabilir veya Premium/Discount Zone kullanılarak daha esnek hale getirilebilir.
      4. FVG (Fair Value Gap) MSS mumunda aranır ve limit giriş için kullanılır.
    """
    
    def __init__(self, sweep_window=30, max_hold_sweep=5, target_rr=3.0, partial_rr=1.5, require_trend=False, displacement_atr_mult=1.5, use_premium_discount=True, fvg_wait=3):
        self.sweep_window = sweep_window
        self.max_hold_sweep = max_hold_sweep
        self.target_rr = target_rr
        self.partial_rr = partial_rr
        self.require_trend = require_trend
        self.displacement_atr_mult = displacement_atr_mult
        self.use_premium_discount = use_premium_discount
        self.fvg_wait = fvg_wait

    def calculate_signals(self, df):
        """Calculates indicators and entry setups. Returns a df with signals."""
        df = df.copy()
        
        # 1. Swing Highs & Lows (excluding current candle to avoid future bias)
        df["swing_high"] = df["high"].shift(1).rolling(window=self.sweep_window).max()
        df["swing_low"] = df["low"].shift(1).rolling(window=self.sweep_window).min()
        
        # EMA 200 (for trend detection)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        
        # ATR (for volatility context)
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df["atr"] = true_range.rolling(window=14).mean()
        
        # Signals
        df["signal"] = "HOLD" # default
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
            timestamp_val = df.get("timestamp", pd.Series([0]*len(df))).iloc[i]
            
            h = df["high"].iloc[i]
            l = df["low"].iloc[i]
            c = df["close"].iloc[i]
            o = df["open"].iloc[i]
            
            candle_range = h - l
            if candle_range == 0:
                continue
                
            # ── A. SWEEP TESPİTLERİ (Mevcut Mumda Süpürme Var Mı?) ──
            
            # 1. Bullish Sweep (Fiyat Swing Low'u süpürdü)
            is_bull_sweep_now = (l < low_prev) and (c > low_prev)
            if is_bull_sweep_now:
                lower_wick = min(c, o) - l
                # Wick oranı %35 ve üzeri veya yutan boğa gibi güçlü dönüşler
                is_bull_rejection = (lower_wick / candle_range >= 0.35) or (c > o and df["close"].iloc[i-1] < df["open"].iloc[i-1])
                if is_bull_rejection:
                    last_bull_sweep_idx = i
                    last_bull_sweep_low = l
                    # Bearish sweep durumunu sıfırla ki çelişki olmasın
                    last_bear_sweep_idx = -1
                    
            # 2. Bearish Sweep (Fiyat Swing High'ı süpürdü)
            is_bear_sweep_now = (h > high_prev) and (c < high_prev)
            if is_bear_sweep_now:
                upper_wick = h - max(c, o)
                is_bear_rejection = (upper_wick / candle_range >= 0.35) or (c < o and df["close"].iloc[i-1] > df["open"].iloc[i-1])
                if is_bear_rejection:
                    last_bear_sweep_idx = i
                    last_bear_sweep_high = h
                    last_bull_sweep_idx = -1
                    
            # ── B. DURUMSAL SİNYAL DEĞERLENDİRME (Stateful Logic) ──
            
            # 1. BULLISH SETUP TAKİBİ
            if last_bull_sweep_idx != -1:
                # Sweep eskidiyse iptal et
                if i - last_bull_sweep_idx > self.max_hold_sweep:
                    last_bull_sweep_idx = -1
                else:
                    # Yapı kırılması (MSS) aranıyor
                    is_bullish_mss = c > max(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                    
                    if is_bullish_mss:
                        # Trend Filtreleri
                        trend_ok = True
                        if self.require_trend:
                            trend_ok = (c > ema200_val)
                            
                        # Premium/Discount Filtresi (EMA yerine tercih edilir)
                        if self.use_premium_discount and trend_ok:
                            # Süpürmenin yapıldığı andaki swing aralığına göre discount kontrolü
                            swing_h = df["swing_high"].iloc[last_bull_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bull_sweep_idx]
                            zone = get_premium_discount_zone(c, swing_h, swing_l)
                            trend_ok = (zone == "DISCOUNT")
                            
                        if trend_ok:
                            df.at[df.index[i], "signal"] = "BUY"
                            sl = last_bull_sweep_low - (atr_val * 0.5)
                            
                            # Bullish FVG Kontrolü (Breakout mumu ile)
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
                            
                            # Sinyal oluştuktan sonra sweep durumunu sıfırla
                            last_bull_sweep_idx = -1
                            
            # 2. BEARISH SETUP TAKİBİ
            if last_bear_sweep_idx != -1:
                # Sweep eskidiyse iptal et
                if i - last_bear_sweep_idx > self.max_hold_sweep:
                    last_bear_sweep_idx = -1
                else:
                    # Yapı kırılması (MSS) aranıyor
                    is_bearish_mss = c < min(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                    
                    if is_bearish_mss:
                        # Trend Filtreleri
                        trend_ok = True
                        if self.require_trend:
                            trend_ok = (c < ema200_val)
                            
                        # Premium/Discount Filtresi
                        if self.use_premium_discount and trend_ok:
                            swing_h = df["swing_high"].iloc[last_bear_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bear_sweep_idx]
                            zone = get_premium_discount_zone(c, swing_h, swing_l)
                            trend_ok = (zone == "PREMIUM")
                            
                        if trend_ok:
                            df.at[df.index[i], "signal"] = "SELL"
                            sl = last_bear_sweep_high + (atr_val * 0.5)
                            
                            # Bearish FVG Kontrolü
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
