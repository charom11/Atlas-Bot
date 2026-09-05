#!/usr/bin/env python3
"""
INSTITUTIONAL 8-STEP SMART MONEY CONCEPTS (SMC) MULTI-TIMEFRAME ENGINE
======================================================================
Strategy Rules:
1. 4H Macro Bias: Up = Buys only, Down = Sells only (EMA 50/200 + 4H Swing HH/HL vs LH/LL)
2. 30m Mode Decision: 30m against 4H = Pullback Mode | 30m with 4H = Continuation Mode
3. Mark 30m Area: 30m Demand/HL (for Buys) or 30m Supply/LH (for Sells)
4. POI Tap: Wait for price to tap the 30m POI zone
5. 5m Timeframe: Drop to 5m execution
6. Filter: Ignore the initial 5m counter-trend shift into the zone
7. Entry Trigger: Enter on the FIRST 5m Market Structure Shift (MSS / CHoCH) aligning back WITH 4H
8. Risk Management: Stop Loss beyond 5m swing extreme | Take Profit @ next 30m level or 1:2.5 RR
"""

import os
import sys
import time
import math
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

class SmartMoneyStructureEngine:
    def __init__(self, symbol="XRPUSDT", rr_ratio=2.5):
        self.symbol = symbol
        self.rr_ratio = rr_ratio
        self.poi_tap_threshold = 0.003 # 0.3% zone proximity
        
    def fetch_klines(self, interval="5m", limit=100):
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": interval, "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=5)
            if r.status_code == 200:
                raw = r.json()
                data = []
                for k in raw:
                    data.append({
                        'time': k[0],
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5])
                    })
                return pd.DataFrame(data)
        except Exception:
            pass
        return None

    @staticmethod
    def identify_swings(df, window=3):
        """Identifies Fractal Swing Highs and Swing Lows"""
        highs = df['high'].values
        lows = df['low'].values
        n = len(df)
        
        swing_highs = [] # (index, price)
        swing_lows = []  # (index, price)
        
        for i in range(window, n - window):
            # Swing High
            is_sh = True
            for w in range(1, window + 1):
                if highs[i] <= highs[i - w] or highs[i] <= highs[i + w]:
                    is_sh = False
                    break
            if is_sh:
                swing_highs.append((i, highs[i]))
                
            # Swing Low
            is_sl = True
            for w in range(1, window + 1):
                if lows[i] >= lows[i - w] or lows[i] >= lows[i + w]:
                    is_sl = False
                    break
            if is_sl:
                swing_lows.append((i, lows[i]))
                
        return swing_highs, swing_lows

    def get_4h_bias(self, df_4h):
        """
        Step 1: Check 4H bias: Up = Buys only, Down = Sells only
        """
        if df_4h is None or len(df_4h) < 20:
            return 'NEUTRAL'
        
        closes = df_4h['close'].values
        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().values
        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().values
        
        sh, sl = self.identify_swings(df_4h, window=2)
        
        # Trend evaluation
        bullish = (closes[-1] > ema20[-1] and ema20[-1] >= ema50[-1])
        bearish = (closes[-1] < ema20[-1] and ema20[-1] <= ema50[-1])
        
        if len(sh) >= 2 and len(sl) >= 2:
            hh_hl = (sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1])
            lh_ll = (sh[-1][1] < sh[-2][1] and sl[-1][1] < sl[-2][1])
            if hh_hl:
                bullish = True
            elif lh_ll:
                bearish = True

        if bullish and not bearish:
            return 'BULLISH' # BUYS ONLY
        elif bearish and not bullish:
            return 'BEARISH' # SELLS ONLY
        return 'BULLISH' if closes[-1] >= ema50[-1] else 'BEARISH'

    def get_30m_poi_and_mode(self, df_30m, bias_4h):
        """
        Step 2 & 3: Decide 30m mode (Pullback vs Continuation) & Mark 30m POI Area
        """
        if df_30m is None or len(df_30m) < 20:
            return None, 'UNKNOWN'
        
        closes = df_30m['close'].values
        highs = df_30m['high'].values
        lows = df_30m['low'].values
        
        sh_30m, sl_30m = self.identify_swings(df_30m, window=2)
        current_price = closes[-1]
        
        poi_zone = None
        mode = 'CONTINUATION'
        
        if bias_4h == 'BULLISH': # Look for 30m Demand (Higher Low / Order Block)
            if sl_30m:
                last_sl_price = sl_30m[-1][1]
                # If price is retracing downwards toward the 30m demand
                if current_price < highs[-5:].max() and current_price >= last_sl_price * 0.995:
                    mode = 'PULLBACK'
                    poi_zone = {
                        'type': 'DEMAND',
                        'top': last_sl_price * 1.006,
                        'bottom': last_sl_price * 0.994,
                        'target_level': highs[-20:].max()
                    }
                else:
                    mode = 'CONTINUATION'
                    poi_zone = {
                        'type': 'DEMAND_BREAKOUT',
                        'top': current_price * 1.002,
                        'bottom': last_sl_price,
                        'target_level': current_price * 1.03
                    }
        else: # BEARISH: Look for 30m Supply (Lower High / Order Block)
            if sh_30m:
                last_sh_price = sh_30m[-1][1]
                if current_price > lows[-5:].min() and current_price <= last_sh_price * 1.005:
                    mode = 'PULLBACK'
                    poi_zone = {
                        'type': 'SUPPLY',
                        'top': last_sh_price * 1.006,
                        'bottom': last_sh_price * 0.994,
                        'target_level': lows[-20:].min()
                    }
                else:
                    mode = 'CONTINUATION'
                    poi_zone = {
                        'type': 'SUPPLY_BREAKOUT',
                        'top': last_sh_price,
                        'bottom': current_price * 0.998,
                        'target_level': current_price * 0.97
                    }
                    
        return poi_zone, mode

    def evaluate_5m_mss(self, df_5m, bias_4h, poi_zone):
        """
        Step 4 to 8:
        - Check if 5m price tapped 30m POI zone
        - Ignore initial shift against 4H
        - Detect first 5m Market Structure Shift (MSS / CHoCH) WITH 4H bias
        - Calculate Stop Loss beyond 5m swing & Take Profit
        """
        if df_5m is None or len(df_5m) < 20 or not poi_zone:
            return None
        
        closes = df_5m['close'].values
        highs = df_5m['high'].values
        lows = df_5m['low'].values
        last_price = closes[-1]
        
        # Step 4: Check if price tapped the 30m POI area within the last 10 bars
        recent_lows = lows[-10:]
        recent_highs = highs[-10:]
        
        tapped_poi = False
        if poi_zone['type'] in ['DEMAND', 'DEMAND_BREAKOUT']:
            tapped_poi = any(l <= poi_zone['top'] and l >= poi_zone['bottom'] * 0.99 for l in recent_lows) or (last_price <= poi_zone['top'])
        else:
            tapped_poi = any(h >= poi_zone['bottom'] and h <= poi_zone['top'] * 1.01 for h in recent_highs) or (last_price >= poi_zone['bottom'])
            
        if not tapped_poi:
            return None # Waiting for 30m POI tap
            
        sh_5m, sl_5m = self.identify_swings(df_5m, window=2)
        if not sh_5m or not sl_5m:
            return None
            
        # Step 7: First 5m MSS / CHoCH back WITH 4H Bias
        signal = None
        
        if bias_4h == 'BULLISH':
            # MSS Long: 5m Candle closes above the last 5m Swing High (Breaking counter-trend pullback)
            last_5m_sh = sh_5m[-1][1]
            last_5m_sl = sl_5m[-1][1]
            
            # Close broke above 5m Swing High
            if closes[-1] > last_5m_sh and closes[-2] <= last_5m_sh * 1.001:
                sl_price = min(last_5m_sl, lows[-5:].min()) * 0.9985 # Stop beyond 5m swing low
                risk_dist = last_price - sl_price
                if risk_dist > 0:
                    tp_target = max(poi_zone.get('target_level', last_price + risk_dist * self.rr_ratio), last_price + risk_dist * self.rr_ratio)
                    signal = {
                        'symbol': self.symbol,
                        'action': 'BUY',
                        'type': '5m_MSS_CHoCH_LONG',
                        'entry_price': last_price,
                        'stop_loss': sl_price,
                        'take_profit': tp_target,
                        'risk_reward': round((tp_target - last_price) / risk_dist, 2),
                        'bias_4h': bias_4h,
                        'mss_break_level': last_5m_sh,
                        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                    }
        else:
            # MSS Short: 5m Candle closes below the last 5m Swing Low (Breaking counter-trend pullback)
            last_5m_sh = sh_5m[-1][1]
            last_5m_sl = sl_5m[-1][1]
            
            # Close broke below 5m Swing Low
            if closes[-1] < last_5m_sl and closes[-2] >= last_5m_sl * 0.999:
                sl_price = max(last_5m_sh, highs[-5:].max()) * 1.0015 # Stop beyond 5m swing high
                risk_dist = sl_price - last_price
                if risk_dist > 0:
                    tp_target = min(poi_zone.get('target_level', last_price - risk_dist * self.rr_ratio), last_price - risk_dist * self.rr_ratio)
                    signal = {
                        'symbol': self.symbol,
                        'action': 'SELL',
                        'type': '5m_MSS_CHoCH_SHORT',
                        'entry_price': last_price,
                        'stop_loss': sl_price,
                        'take_profit': tp_target,
                        'risk_reward': round((last_price - tp_target) / risk_dist, 2),
                        'bias_4h': bias_4h,
                        'mss_break_level': last_5m_sl,
                        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                    }
                    
        return signal

    def analyze_full_market_structure(self):
        """Runs the complete 8-step pipeline"""
        df_4h = self.fetch_klines(interval="4h", limit=50)
        df_30m = self.fetch_klines(interval="30m", limit=60)
        df_5m = self.fetch_klines(interval="5m", limit=60)
        
        bias_4h = self.get_4h_bias(df_4h)
        poi_zone, mode_30m = self.get_30m_poi_and_mode(df_30m, bias_4h)
        signal = self.evaluate_5m_mss(df_5m, bias_4h, poi_zone)
        
        current_price = df_5m['close'].iloc[-1] if df_5m is not None else 0.0
        
        return {
            'symbol': self.symbol,
            'current_price': current_price,
            'step1_4h_bias': bias_4h,
            'step2_30m_mode': mode_30m,
            'step3_30m_poi': poi_zone,
            'step7_signal': signal
        }

if __name__ == '__main__':
    print("=" * 80)
    print(" 🏛️ SMART MONEY CONCEPTS (SMC) 4H -> 30M -> 5M MSS LIVE SCANNER")
    print("=" * 80)
    
    symbols = ["XAUUSDT", "XRPUSDT", "SUIUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "NEARUSDT", "SOLUSDT", "BTCUSDT"]
    for sym in symbols:
        engine = SmartMoneyStructureEngine(symbol=sym)
        res = engine.analyze_full_market_structure()
        
        bias_emoji = "🟢 BUYS ONLY" if res['step1_4h_bias'] == 'BULLISH' else "🔴 SELLS ONLY"
        print(f"\n📌 ASSET: #{sym} | Current Price: ${res['current_price']:,.4f}")
        print(f"   • Step 1 (4H Macro Bias):   {bias_emoji}")
        print(f"   • Step 2 (30m Mode):        {res['step2_30m_mode']}")
        if res['step3_30m_poi']:
            print(f"   • Step 3 (30m POI Area):    {res['step3_30m_poi']['type']} (${res['step3_30m_poi']['bottom']:,.4f} - ${res['step3_30m_poi']['top']:,.4f})")
        
        if res['step7_signal']:
            sig = res['step7_signal']
            print(f"   🚨 STEP 7 TRIGGER (5m MSS / CHoCH DETECTED!):")
            print(f"      Action: {sig['action']} @ ${sig['entry_price']:,.4f}")
            print(f"      Stop Loss: ${sig['stop_loss']:,.4f} | Take Profit: ${sig['take_profit']:,.4f} (1:{sig['risk_reward']} RR)")
        else:
            print(f"   • Step 7 Status:            Waiting for 5m MSS / CHoCH alignment...")
            
    print("\n" + "=" * 80)
