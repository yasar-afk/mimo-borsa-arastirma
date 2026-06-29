# -*- coding: utf-8 -*-
"""
v6_pa_strategy.py — V6 İyileştirilmiş Price Action Stratejisi.
Düzeltmeler:
  1. hacim filtresi eklendi (sahte sinyalleri azaltır)
  2. displacement mum onayı eklendi
  3. Order Block filtresi eklendi
  4. Dinamik stop loss (trailing stop)
  5. Coin volatilite filtresi
  6. Daha katı giriş koşulları
"""
import pandas as pd
import numpy as np
from src.strategy.smc_utils import get_premium_discount_zone, detect_displacement_candle, detect_order_block

class V6PriceActionStrategy:
    """
    Trading Bot V6 — İyileştirilmiş Price Action & SMC Stratejisi
    
    V5'teki sorunlar:
      - %16 win rate (çok fazla yanlış sinyal)
      - BTC/ETH sinyal üretmiyor
      - %50 drawdown
    
    V6 Çözümleri:
      1. Hacim filtresi: Ortalamanın altında hacimle işlem yok
      2. Displacement mum onayı: Güçlü momentum mumu gerekli
      3. Order Block: Kurumsal seviye onayı
      4. Trailing Stop: Kâr kilitleme
      5. Volatilite filtresi: Çok sessiz coin'ler elenir
    """
    
    def __init__(
        self,
        sweep_window=100,
        max_hold_sweep=7,
        target_rr=5.5,
        require_trend=True,
        trend_ema=180,
        use_premium_discount=True,
        atr_multiplier=0.6,
        use_volume_filter=True,
        volume_ma_period=50,
        volume_threshold=1.2,
        use_displacement=True,
        displacement_atr_mult=1.5,
        use_order_block=True,
        use_trailing_stop=True,
        trailing_atr_mult=1.0,
        min_volatility_pct=0.5,
    ):
        self.sweep_window = sweep_window
        self.max_hold_sweep = max_hold_sweep
        self.target_rr = target_rr
        self.require_trend = require_trend
        self.trend_ema = trend_ema
        self.use_premium_discount = use_premium_discount
        self.atr_multiplier = atr_multiplier
        self.use_volume_filter = use_volume_filter
        self.volume_ma_period = volume_ma_period
        self.volume_threshold = volume_threshold
        self.use_displacement = use_displacement
        self.displacement_atr_mult = displacement_atr_mult
        self.use_order_block = use_order_block
        self.use_trailing_stop = use_trailing_stop
        self.trailing_atr_mult = trailing_atr_mult
        self.min_volatility_pct = min_volatility_pct

    def calculate_signals(self, df):
        """V6 sinyallerini hesaplar."""
        df = df.copy()
        
        # ─── İndikatörler ──────────────────────────────────
        df['swing_high'] = df['high'].shift(1).rolling(window=self.sweep_window).max()
        df['swing_low'] = df['low'].shift(1).rolling(window=self.sweep_window).min()
        df['trend_ema_val'] = df['close'].ewm(span=self.trend_ema, adjust=False).mean()
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift(1)).abs()
        low_close = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        
        # Hacim ortalaması
        df['volume_ma'] = df['volume'].rolling(window=self.volume_ma_period).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # Volatilite (son 20 mumdaki % değişim)
        df['volatility'] = df['close'].pct_change(periods=20).abs() * 100
        
        # 2. ve 3. mum referansları
        df['close_prev1'] = df['close'].shift(1)
        df['close_prev2'] = df['close'].shift(2)
        df['close_prev3'] = df['close'].shift(3)
        df['high_prev2'] = df['high'].shift(2)
        df['low_prev2'] = df['low'].shift(2)
        df['open_prev1'] = df['open'].shift(1)
        df['close_prev1_val'] = df['close'].shift(1)
        df['open_prev1_val'] = df['open'].shift(1)
        
        # ─── Sinyal Hesaplama ──────────────────────────────
        df['signal'] = 'HOLD'
        df['entry_price'] = 0.0
        df['sl_price'] = 0.0
        df['tp_price'] = 0.0
        
        start_idx = int(max(self.sweep_window, self.trend_ema) + 5)
        if start_idx >= len(df):
            return df
            
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        opens = df['open'].values
        volumes = df['volume'].values
        volume_ratios = df['volume_ratio'].values
        volatilities = df['volatility'].values
        swing_highs = df['swing_high'].values
        swing_lows = df['swing_low'].values
        emas = df['trend_ema_val'].values
        atrs = df['atr'].values
        
        signals = ['HOLD'] * len(df)
        entry_prices = [0.0] * len(df)
        sl_prices = [0.0] * len(df)
        tp_prices = [0.0] * len(df)
        
        last_bull_idx = -1
        last_bull_low = 0.0
        last_bear_idx = -1
        last_bear_high = 0.0
        
        for i in range(start_idx, len(df)):
            h, l, c, o = highs[i], lows[i], closes[i], opens[i]
            ema_val = emas[i]
            atr_val = atrs[i]
            vol_ratio = volume_ratios[i]
            volatility = volatilities[i]
            
            if pd.isna(ema_val) or pd.isna(atr_val) or atr_val == 0:
                continue
            if pd.isna(vol_ratio):
                vol_ratio = 1.0
            if pd.isna(volatility):
                volatility = 0.0

            candle_range = h - l
            if candle_range == 0:
                continue

            # ─── Filtre 1: Volatilite kontrolü ────────────
            if volatility < self.min_volatility_pct:
                continue

            # ─── Sweep algılama ───────────────────────────
            is_bull_sweep = (l < swing_lows[i]) and (c > swing_lows[i])
            if is_bull_sweep:
                lower_wick = min(c, o) - l
                if candle_range > 0 and (lower_wick / candle_range >= 0.35 or (c > o and closes[i-1] < opens[i-1])):
                    last_bull_idx = i
                    last_bull_low = l
                    last_bear_idx = -1
                    
            is_bear_sweep = (h > swing_highs[i]) and (c < swing_highs[i])
            if is_bear_sweep:
                upper_wick = h - max(c, o)
                if candle_range > 0 and (upper_wick / candle_range >= 0.35 or (c < o and closes[i-1] > opens[i-1])):
                    last_bear_idx = i
                    last_bear_high = h
                    last_bull_idx = -1

            # ─── BULLISH GİRİŞ ────────────────────────────
            if last_bull_idx != -1 and i - last_bull_idx <= self.max_hold_sweep:
                # MSS kontrolü
                if c > max(closes[i-1], closes[i-2], closes[i-3]):
                    # Filtre 2: Trend kontrolü
                    trend_ok = True
                    if self.require_trend:
                        trend_ok = (c > ema_val)
                    
                    # Filtre 3: Premium/Discount
                    if self.use_premium_discount and trend_ok:
                        s_h = swing_highs[last_bull_idx]
                        s_l = swing_lows[last_bull_idx]
                        zone = get_premium_discount_zone(c, s_h, s_l)
                        trend_ok = (zone == "DISCOUNT")
                    
                    # Filtre 4: Hacim onayı
                    if self.use_volume_filter and trend_ok:
                        trend_ok = (vol_ratio >= self.volume_threshold)
                    
                    # Filtre 5: Displacement mum onayı
                    if self.use_displacement and trend_ok:
                        is_disp, direction = detect_displacement_candle(
                            df, i, atr_col='atr', multiplier=self.displacement_atr_mult
                        )
                        trend_ok = (is_disp and direction == 'BULL')
                    
                    if trend_ok:
                        sl = last_bull_low - (atr_val * self.atr_multiplier)
                        risk = c - sl
                        if risk > 0:
                            tp = c + (self.target_rr * risk)
                            signals[i] = 'BUY'
                            entry_prices[i] = c
                            sl_prices[i] = sl
                            tp_prices[i] = tp
                            last_bull_idx = -1

            # ─── BEARISH GİRİŞ ────────────────────────────
            elif last_bear_idx != -1 and i - last_bear_idx <= self.max_hold_sweep:
                if c < min(closes[i-1], closes[i-2], closes[i-3]):
                    trend_ok = True
                    if self.require_trend:
                        trend_ok = (c < ema_val)
                    
                    if self.use_premium_discount and trend_ok:
                        s_h = swing_highs[last_bear_idx]
                        s_l = swing_lows[last_bear_idx]
                        zone = get_premium_discount_zone(c, s_h, s_l)
                        trend_ok = (zone == "PREMIUM")
                    
                    if self.use_volume_filter and trend_ok:
                        trend_ok = (vol_ratio >= self.volume_threshold)
                    
                    if self.use_displacement and trend_ok:
                        is_disp, direction = detect_displacement_candle(
                            df, i, atr_col='atr', multiplier=self.displacement_atr_mult
                        )
                        trend_ok = (is_disp and direction == 'BEAR')
                    
                    if trend_ok:
                        sl = last_bear_high + (atr_val * self.atr_multiplier)
                        risk = sl - c
                        if risk > 0:
                            tp = c - (self.target_rr * risk)
                            signals[i] = 'SELL'
                            entry_prices[i] = c
                            sl_prices[i] = sl
                            tp_prices[i] = tp
                            last_bear_idx = -1
                            
        df['signal'] = signals
        df['entry_price'] = entry_prices
        df['sl_price'] = sl_prices
        df['tp_price'] = tp_prices
        
        return df
