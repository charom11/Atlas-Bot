#!/usr/bin/env python3
"""
WEATHER-ENSEMBLE BINANCE FUTURES LIVE AI TRADING AGENT + INTERACTIVE TELEGRAM C2
================================================================================
Production Hardened Version:
- 30x Fast Recovery Sizing (20% margin allocation, micro-lot assets)
- L2 Order Book Depth Imbalance Gate (Top-20 Bids vs Asks)
- 8-Hour Funding Rate & Squeeze Filter
- Automated Orphaned Order Garbage Collection (Prevents accidental reverse entries)
- Partial Take-Profit Scaling (50% TP1 @ 1.5x ATR, 50% Trailing Runner)
- 6% Daily Drawdown Circuit Breaker
- Interactive Telegram Inline Keyboard (1-Tap mobile buttons) & C2 Commands
"""

import os
import sys
import time
import math
import json
import random
import hmac
import hashlib
import urllib.parse
import argparse
import threading
from datetime import datetime, timezone
import requests
import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# --------------------------------------------------------------------------
# Environment Configuration (.env Loader)
# --------------------------------------------------------------------------
def load_env_file(env_file='.env'):
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

load_env_file()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_NOTIFICATIONS = os.getenv('TELEGRAM_NOTIFICATIONS', 'true').lower() == 'true'

BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')

OPTIMIZED_SYMBOLS = [
    # 🪙 High-Beta Momentum Leaders & Heavyweights (Top Institutional Priority)
    "SOLUSDT", "BTCUSDT", "ETHUSDT", "SUIUSDT", "NEARUSDT", "AVAXUSDT", "LINKUSDT", "PAXGUSDT",
    # ⚡ High-Volume Large-Cap Assets
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "BNBUSDT", "APTUSDT", "RENDERUSDT"
]

# --------------------------------------------------------------------------
# Circuit Breaker & Risk Protection Manager
# --------------------------------------------------------------------------
class CircuitBreakerManager:
    """
    Automated Protection:
    - Trips if daily drawdown exceeds 6%
    - Trips if 3 consecutive losses occur
    """
    def __init__(self, daily_drawdown_limit_pct=0.06, max_consecutive_losses=3):
        self.daily_limit_pct = daily_drawdown_limit_pct
        self.max_losses = max_consecutive_losses
        self.daily_start_balance = None
        self.daily_start_time = time.time()
        self.consecutive_losses = 0
        self.circuit_tripped = False
        self.trip_reason = ""
        self.asset_cooldowns = {} # symbol -> cooldown_until_timestamp

    def is_asset_in_cooldown(self, symbol):
        until = self.asset_cooldowns.get(symbol, 0)
        return time.time() < until

    def trigger_asset_cooldown(self, symbol, duration_seconds=5400):
        self.asset_cooldowns[symbol] = time.time() + duration_seconds
        print(f"[ASSET COOLDOWN] #{symbol} paused for {duration_seconds/60:.0f} mins to prevent knife-catching.")

    def check_and_update(self, current_balance):
        now = time.time()
        if self.daily_start_balance is None or (now - self.daily_start_time) >= 86400:
            self.daily_start_balance = current_balance
            self.daily_start_time = now
            self.consecutive_losses = 0
            self.circuit_tripped = False
            self.trip_reason = ""

        if self.daily_start_balance and self.daily_start_balance > 0:
            dd = (self.daily_start_balance - current_balance) / self.daily_start_balance
            if dd >= self.daily_limit_pct:
                self.circuit_tripped = True
                self.trip_reason = f"Daily drawdown hit {dd*100:.1f}% (Limit: {self.daily_limit_pct*100:.1f}%)"
                return False

        if self.consecutive_losses >= self.max_losses:
            self.circuit_tripped = True
            self.trip_reason = f"{self.consecutive_losses} consecutive losses reached (Limit: {self.max_losses})"
            return False

        return True

    def record_trade_result(self, pnl):
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def reset_circuit(self, current_balance):
        self.daily_start_balance = current_balance
        self.consecutive_losses = 0
        self.circuit_tripped = False
        self.trip_reason = ""

CIRCUIT_BREAKER = CircuitBreakerManager()

# --------------------------------------------------------------------------
# Automated Profit Sweeper & Milestone Lock Manager
# --------------------------------------------------------------------------
class MilestoneLockManager:
    """
    Tracks recovery milestones ($30, $50, $100, $250, $500, $1000) and locks baseline equity.
    """
    def __init__(self, initial_capital=14.20):
        self.initial_capital = initial_capital
        self.peak_balance = initial_capital
        self.milestones = [30.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 5000.0]
        self.locked_milestone = 0.0

    def update(self, current_balance):
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
            for m in self.milestones:
                if self.peak_balance >= m and m > self.locked_milestone:
                    self.locked_milestone = m
                    suggested_sweep = round(m * 0.30, 2)
                    msg = (
                        f"🏆 <b>ACCOUNT MILESTONE LOCKED!</b>\n\n"
                        f"💰 Wallet Peak: <b>${self.peak_balance:,.2f} USDT</b>\n"
                        f"🔒 Milestone Floor: <b>${m:,.2f} USDT</b> secured!\n\n"
                        f"🏦 <b>SUGGESTED PROFIT SWEEP:</b>\n"
                        f"Withdraw <b>${suggested_sweep:,.2f} USDT (30%)</b> to Binance Spot / Cold Storage to lock in real-world cash! 💵"
                    )
                    send_telegram_msg(msg)
        return self.locked_milestone

MILESTONE_MANAGER = MilestoneLockManager()

def calc_dynamic_atr_margin(symbol, atr, price, base_margin_pct=0.03):
    """
    Dynamic ATR-Normalized Volatility Sizing:
    - Scales margin between 2.0% and 4.0% based on ATR % of price.
    - High-volatility assets (Gold, SOL) scale down to 2.0% to prevent oversized swings.
    - Low-volatility calm assets (ADA, XRP) scale up to 3.5% to maximize pip yield.
    """
    if atr is None or atr <= 0 or price is None or price <= 0:
        return base_margin_pct
    atr_pct = atr / price
    if atr_pct > 0.010: # High volatility (>1.0% per 5m)
        return max(0.020, base_margin_pct * 0.75)
    elif atr_pct < 0.004: # Low volatility (<0.40% per 5m)
        return min(0.040, base_margin_pct * 1.25)
    return base_margin_pct

_MTF_CACHE = {'timestamp': 0, 'data': []}

def _fetch_single_sym_mtf(sym):
    try:
        r5 = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=5m&limit=25", timeout=2).json()
        c5 = [float(k[4]) for k in r5]
        r15 = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m&limit=25", timeout=2).json()
        c15 = [float(k[4]) for k in r15]
        r1h = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&limit=25", timeout=2).json()
        c1h = [float(k[4]) for k in r1h]
        r4h = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=4h&limit=25", timeout=2).json()
        c4h = [float(k[4]) for k in r4h]

        t5 = "BULLISH" if c5[-1] > np.mean(c5[-15:]) else "BEARISH"
        t15 = "BULLISH" if c15[-1] > np.mean(c15[-15:]) else "BEARISH"
        t1h = "BULLISH" if c1h[-1] > np.mean(c1h[-15:]) else "BEARISH"
        t4h = "BULLISH" if c4h[-1] > np.mean(c4h[-15:]) else "BEARISH"

        bull_count = sum(1 for x in [t5, t15, t1h, t4h] if x == "BULLISH")
        status = "STRONG BUY 🟢" if bull_count == 4 else ("STRONG SELL 🔴" if bull_count == 0 else ("PULLBACK BUY 🟡" if t4h == "BULLISH" and t5 == "BEARISH" else "NEUTRAL ⚪"))

        return {
            'symbol': sym,
            'price': c5[-1],
            'tf_5m': t5,
            'tf_15m': t15,
            'tf_1h': t1h,
            'tf_4h': t4h,
            'confluence': f"{bull_count}/4",
            'status': status
        }
    except Exception:
        return None

def get_mtf_heatmap_data():
    """
    Calculates 5m, 15m, 1h, 4h trends across all 9 assets in parallel with 10s caching.
    """
    global _MTF_CACHE
    now = time.time()
    if now - _MTF_CACHE['timestamp'] < 10 and _MTF_CACHE['data']:
        return _MTF_CACHE['data']

    import concurrent.futures
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as executor:
        futures = {executor.submit(_fetch_single_sym_mtf, sym): sym for sym in OPTIMIZED_SYMBOLS}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                results.append(res)

    results.sort(key=lambda x: OPTIMIZED_SYMBOLS.index(x['symbol']) if x['symbol'] in OPTIMIZED_SYMBOLS else 99)
    _MTF_CACHE = {'timestamp': now, 'data': results}
    return results

# --------------------------------------------------------------------------
# 📐 Objective Fibonacci Retracement & Extension Engine (Golden Pocket 0.50-0.618)
# --------------------------------------------------------------------------
def detect_fractal_swings_series(highs, lows, window=4):
    """
    Identifies Fractal Swings with zero look-ahead bias:
    A swing at index i is confirmed only after `window` subsequent bars.
    Returns: (swing_highs, swing_lows) as lists of (confirmed_idx, price)
    """
    n = len(highs)
    swing_highs = []
    swing_lows = []
    for i in range(window, n - window):
        if all(highs[i] >= highs[i - k] for k in range(1, window + 1)) and \
           all(highs[i] >= highs[i + k] for k in range(1, window + 1)):
            swing_highs.append((i + window, highs[i]))
        if all(lows[i] <= lows[i - k] for k in range(1, window + 1)) and \
           all(lows[i] <= lows[i + k] for k in range(1, window + 1)):
            swing_lows.append((i + window, lows[i]))
    return swing_highs, swing_lows

def check_fibonacci_setup(df, symbol="XRPUSDT"):
    """
    📐 Institutional Fibonacci Retracement & Extension Engine:
    1. Extracts confirmed Fractal Swings (Anchor High/Low).
    2. Measures impulse range R = S_H - S_L.
    3. Calculates Golden Pocket (0.500 - 0.618), Invalidation SL (0.786 + 0.5x ATR),
       and Multi-Tier Take-Profit Extensions (0.000 Retest, -0.618 Extension, -1.618 Runner).
    """
    try:
        if df is None or len(df) < 35:
            return {'state': 'NO_DATA', 'is_setup': False}

        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        curr_p = closes[-1]
        curr_h = highs[-1]
        curr_l = lows[-1]

        # Calculate ATR(14)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift(1)).abs(),
            (df['low'] - df['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else (curr_p * 0.005)

        sh_list, sl_list = detect_fractal_swings_series(highs, lows, window=4)
        if not sh_list or not sl_list:
            return {'state': 'NO_SWINGS', 'is_setup': False}

        last_sh = sh_list[-1]  # (confirmed_idx, price)
        last_sl = sl_list[-1]  # (confirmed_idx, price)

        s_high = last_sh[1]
        s_low = last_sl[1]
        impulse = s_high - s_low

        if impulse < (1.5 * atr_val):
            return {'state': 'IMPULSE_TOO_SMALL', 'is_setup': False}

        # Trend context from EMA50 & EMA200
        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1] if len(closes) >= 200 else ema50
        is_uptrend = (curr_p > ema200) and (ema50 >= ema200)
        is_downtrend = (curr_p < ema200) and (ema50 <= ema200)

        # 1. Bullish Retracement into Golden Pocket
        if is_uptrend and last_sh[0] > last_sl[0]:
            fib_050 = s_high - (0.500 * impulse)
            fib_0618 = s_high - (0.618 * impulse)
            fib_0786 = s_high - (0.786 * impulse)

            if (curr_l <= fib_050) and (curr_p >= fib_0618):
                entry_p = fib_0618
                sl_p = fib_0786 - (0.50 * atr_val)
                tp1_p = s_high
                tp2_p = s_high + (0.618 * impulse)
                tp3_p = s_high + (1.618 * impulse)
                
                risk = entry_p - sl_p
                reward = tp1_p - entry_p
                rr = reward / (risk + 1e-9)
                
                return {
                    'state': 'GOLDEN_POCKET_BUY',
                    'is_setup': True,
                    'side': 'BUY',
                    'entry_price': entry_p,
                    'sl': sl_p,
                    'tp1': tp1_p,
                    'tp2': tp2_p,
                    'tp3': tp3_p,
                    'rr': rr,
                    's_high': s_high,
                    's_low': s_low,
                    'impulse': impulse,
                    'desc': f"📐 Golden Pocket 0.618 Long (${entry_p:.4f}) | TP1: ${tp1_p:.4f} | TP2: ${tp2_p:.4f} | SL: ${sl_p:.4f}"
                }

        # 2. Bearish Retracement into Golden Pocket
        elif is_downtrend and last_sl[0] > last_sh[0]:
            fib_050 = s_low + (0.500 * impulse)
            fib_0618 = s_low + (0.618 * impulse)
            fib_0786 = s_low + (0.786 * impulse)

            if (curr_h >= fib_050) and (curr_p <= fib_0618):
                entry_p = fib_0618
                sl_p = fib_0786 + (0.50 * atr_val)
                tp1_p = s_low
                tp2_p = s_low - (0.618 * impulse)
                tp3_p = s_low - (1.618 * impulse)

                risk = sl_p - entry_p
                reward = entry_p - tp1_p
                rr = reward / (risk + 1e-9)

                return {
                    'state': 'GOLDEN_POCKET_SELL',
                    'is_setup': True,
                    'side': 'SELL',
                    'entry_price': entry_p,
                    'sl': sl_p,
                    'tp1': tp1_p,
                    'tp2': tp2_p,
                    'tp3': tp3_p,
                    'rr': rr,
                    's_high': s_high,
                    's_low': s_low,
                    'impulse': impulse,
                    'desc': f"📐 Golden Pocket 0.618 Short (${entry_p:.4f}) | TP1: ${tp1_p:.4f} | TP2: ${tp2_p:.4f} | SL: ${sl_p:.4f}"
                }

        return {'state': 'IN_RANGE', 'is_setup': False}
    except Exception as e:
        return {'state': 'ERROR', 'error': str(e), 'is_setup': False}

# --------------------------------------------------------------------------
# 🥔 "Potato" Support & Resistance Engine (Pure Price Action Levels)
# --------------------------------------------------------------------------
def check_potato_sr_levels(symbol="XRPUSDT"):
    """
    🥔 Pure 'Potato' Support & Resistance Engine:
    - Finds the literal rolling swing lows (Floor / Support 🛡️) and swing highs (Ceiling / Resistance 🧱).
    - Detects when price is tapping the Floor (POTATO_BUY_BOUNCE) or Ceiling (POTATO_SELL_BOUNCE).
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=48"
        r = requests.get(url, timeout=3).json()
        if not r or not isinstance(r, list):
            return {'status': 'error', 'support': 0, 'resistance': 0, 'current_price': 0, 'state': 'UNKNOWN'}
            
        highs = [float(k[2]) for k in r]
        lows = [float(k[3]) for k in r]
        closes = [float(k[4]) for k in r]
        curr_p = closes[-1]
        
        # Recent 9-hour ceiling & floor
        resistance = max(highs[-36:-3])
        support = min(lows[-36:-3])
        
        dist_to_sup_pct = ((curr_p - support) / support) * 100.0
        dist_to_res_pct = ((resistance - curr_p) / curr_p) * 100.0
        
        recent_low = min(lows[-3:])
        recent_high = max(highs[-3:])
        
        state = "IN_RANGE 🥔"
        # 1. ICT Turtle Soup Liquidity Sweep (Wicked below Floor & closed back INSIDE!)
        if recent_low <= support and curr_p > support:
            state = "SWEEP_SUPPORT_CONFIRMED 🛡️🟢"
        elif recent_high >= resistance and curr_p < resistance:
            state = "SWEEP_RESISTANCE_CONFIRMED 🧱🔴"
        elif dist_to_sup_pct <= 0.40 and curr_p >= (support * 0.998):
            state = "TAPPING_SUPPORT_FLOOR 🥔🟢"
        elif dist_to_res_pct <= 0.40 and curr_p <= (resistance * 1.002):
            state = "TAPPING_RESISTANCE_CEILING 🥔🔴"
            
        return {
            'status': 'success',
            'symbol': symbol,
            'current_price': curr_p,
            'support': support,
            'resistance': resistance,
            'dist_to_sup_pct': dist_to_sup_pct,
            'dist_to_res_pct': dist_to_res_pct,
            'state': state
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e), 'support': 0, 'resistance': 0, 'current_price': 0, 'state': 'ERROR'}

# --------------------------------------------------------------------------
# ⚡ Multi-Timeframe (5M, 15M, 1H, 4H) Dual RSI+CCI Divergence Scanner
# --------------------------------------------------------------------------
def get_mtf_divergence_matrix(symbol="XRPUSDT"):
    """
    ⚡ Multi-Timeframe (MTF) RSI(14) + CCI(20) Divergence Matrix:
    - Scans 5m (Trigger), 15m (Structure), 1h (Swing), 4h (Macro)
    - Detects 'The Bigger Picture' Institutional Reversals
    """
    intervals = ['5m', '15m', '1h', '4h']
    matrix = {}
    macro_bull = False
    macro_bear = False
    
    def _fetch_div(tf):
        try:
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={tf}&limit=45"
            r = requests.get(url, timeout=2.5).json()
            if not r or len(r) < 30:
                return tf, {'state': 'NO_DATA', 'bull': False, 'bear': False, 'rsi': 50, 'cci': 0}
            
            closes = [float(k[4]) for k in r]
            highs = [float(k[2]) for k in r]
            lows = [float(k[3]) for k in r]
            df = pd.DataFrame({'close': closes, 'high': highs, 'low': lows})
            
            div_state, bull, bear = WeatherEnsembleBot.calc_rsi_cci_divergence(df)
            rsi_val = float(WeatherEnsembleBot.calc_rsi(pd.Series(closes), 14).iloc[-1])
            cci_val = float(WeatherEnsembleBot.calc_cci(df, 20).iloc[-1])
            
            return tf, {
                'state': div_state,
                'bull': bull,
                'bear': bear,
                'rsi': round(rsi_val, 1),
                'cci': round(cci_val, 1)
            }
        except Exception:
            return tf, {'state': 'NO_DATA', 'bull': False, 'bear': False, 'rsi': 50, 'cci': 0}
            
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_fetch_div, tf) for tf in intervals]
        for f in concurrent.futures.as_completed(futures):
            tf, res = f.result()
            matrix[tf] = res
            if tf in ['1h', '4h']:
                if res.get('bull'): macro_bull = True
                if res.get('bear'): macro_bear = True
                
    # Evaluate Macro Alignment
    confluence_grade = "STANDARD"
    if macro_bull and matrix.get('5m', {}).get('bull'):
        confluence_grade = "MACRO_SUPER_CONFLUENCE ⚡💎🟢 (4H/1H + 5M Bullish Alignment)"
    elif macro_bear and matrix.get('5m', {}).get('bear'):
        confluence_grade = "MACRO_SUPER_CONFLUENCE ⚡💎🔴 (4H/1H + 5M Bearish Alignment)"
    elif macro_bull:
        confluence_grade = "MACRO_BULL_DIVERGENCE 🏛️🟢 (Higher TF Institutional Accumulation)"
    elif macro_bear:
        confluence_grade = "MACRO_BEAR_DIVERGENCE 🏛️🔴 (Higher TF Institutional Distribution)"
        
    return {
        'status': 'success',
        'symbol': symbol,
        'confluence_grade': confluence_grade,
        'macro_bull': macro_bull,
        'macro_bear': macro_bear,
        'timeframes': matrix
    }

def get_divergence_status(symbol="XRPUSDT"):
    return get_mtf_divergence_matrix(symbol)

# --------------------------------------------------------------------------
# 👑 BTC Master Beta Trend & Portfolio Exposure Risk Engines
# --------------------------------------------------------------------------
def check_btc_macro_health(target_side):
    """
    👑 BTC Master Beta Trend Filter (15m Execution Timeframe):
    - Protects against cross-asset correlation crashes.
    - Uses 15m candles to match bot execution timeframe (reduces 5m noise).
    - NEVER opens an Altcoin LONG if BTC 15m is dumping below its EMA20 with > 0.50% flush.
    - NEVER opens an Altcoin SHORT if BTC is in a vertical parabolic pump > 0.60%.
    """
    try:
        url = "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=30"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return True, "BTC Normal"
        raw = r.json()
        closes = [float(k[4]) for k in raw]
        curr_btc = closes[-1]
        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        ret_15m = (curr_btc - closes[-2]) / closes[-2]
        
        if target_side.upper() in ['BUY', 'LONG']:
            if curr_btc < ema20 and ret_15m < -0.0050:
                return False, f"BTC Flushing ({ret_15m*100:+.2f}% in 15m) - Altcoin Long Blocked 🛑"
        elif target_side.upper() in ['SELL', 'SHORT']:
            if curr_btc > ema20 and ret_15m > +0.0060:
                return False, f"BTC Pumping ({ret_15m*100:+.2f}% in 15m) - Altcoin Short Blocked 🛑"
        return True, "BTC Aligned ✅"
    except Exception:
        return True, "BTC Normal"

def check_portfolio_risk_capacity(balance, new_margin_usdt, max_portfolio_margin_pct=0.06):
    """
    🔒 Maximum Concurrent Portfolio Exposure Cap:
    - Strictly limits total margin committed across ALL active positions to max 6.0% of wallet.
    - On a $14.20 wallet, total combined margin cannot exceed $0.85.
    """
    try:
        positions = get_binance_futures_positions()
        total_current_margin = 0.0
        for p in positions:
            notional = abs(float(p.get('notional', 0.0)))
            lev = float(p.get('leverage', 50))
            total_current_margin += (notional / lev) if lev > 0 else 0.0

        max_allowed_margin = balance * max_portfolio_margin_pct
        if (total_current_margin + new_margin_usdt) > max_allowed_margin:
            return False, f"Portfolio Exposure Cap Reached (${total_current_margin + new_margin_usdt:.2f} > ${max_allowed_margin:.2f})"
        return True, "Capacity OK"
    except Exception:
        return True, "Capacity OK"

# --------------------------------------------------------------------------
# Binance Futures Authenticated API Helper (`fapi.binance.com`)
# --------------------------------------------------------------------------
# Cached server time offset and exchange info to avoid redundant HTTP calls
_SERVER_TIME_OFFSET = 0  # ms offset between local clock and Binance server
_SERVER_TIME_SYNCED = False

_EXCHANGE_INFO_CACHE = {}  # symbol -> {'pricePrecision': int, 'quantityPrecision': int}
_EXCHANGE_INFO_TS = 0

def sync_server_time():
    global _SERVER_TIME_OFFSET, _SERVER_TIME_SYNCED
    try:
        t_res = requests.get('https://fapi.binance.com/fapi/v1/time', timeout=3)
        if t_res.status_code == 200:
            server_ts = t_res.json()['serverTime']
            local_ts = int(time.time() * 1000)
            _SERVER_TIME_OFFSET = server_ts - local_ts
            _SERVER_TIME_SYNCED = True
    except Exception:
        _SERVER_TIME_OFFSET = 0

def get_symbol_precision(symbol):
    global _EXCHANGE_INFO_CACHE, _EXCHANGE_INFO_TS
    now = time.time()
    if now - _EXCHANGE_INFO_TS > 3600 or not _EXCHANGE_INFO_CACHE:
        try:
            ex_info = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=8).json()
            for s in ex_info.get('symbols', []):
                _EXCHANGE_INFO_CACHE[s['symbol']] = {
                    'pricePrecision': s.get('pricePrecision', 4),
                    'quantityPrecision': s.get('quantityPrecision', 3)
                }
            _EXCHANGE_INFO_TS = now
        except Exception:
            pass
    info = _EXCHANGE_INFO_CACHE.get(symbol, {'pricePrecision': 4, 'quantityPrecision': 3})
    return info['pricePrecision'], info['quantityPrecision']

def binance_futures_signed_request(method, endpoint, params=None):
    global _SERVER_TIME_SYNCED
    api_key = os.getenv('BINANCE_API_KEY', BINANCE_API_KEY)
    api_secret = os.getenv('BINANCE_API_SECRET', BINANCE_API_SECRET)
    if not api_key or not api_secret:
        return None

    if params is None:
        params = {}

    # Use cached server time offset instead of fetching /fapi/v1/time every call
    if not _SERVER_TIME_SYNCED:
        sync_server_time()
    timestamp = int(time.time() * 1000) + _SERVER_TIME_OFFSET

    params['recvWindow'] = 10000
    params['timestamp'] = timestamp

    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        api_secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    url = f"https://fapi.binance.com{endpoint}?{query_string}&signature={signature}"
    headers = {'X-MBX-APIKEY': api_key}

    try:
        if method.upper() == 'GET':
            r = requests.get(url, headers=headers, timeout=5)
        elif method.upper() == 'POST':
            r = requests.post(url, headers=headers, timeout=5)
        elif method.upper() == 'DELETE':
            r = requests.delete(url, headers=headers, timeout=5)
        else:
            return None

        try:
            result = r.json()
        except Exception:
            return {'error': r.status_code, 'text': r.text}

        # Re-sync if timestamp error detected
        if isinstance(result, dict) and result.get('code') == -1021:
            sync_server_time()

        return result
    except Exception as e:
        return {'error': str(e)}


def get_binance_futures_usdt_balance():
    bals = binance_futures_signed_request('GET', '/fapi/v2/balance')
    if not bals or not isinstance(bals, list):
        return 0.0
    for b in bals:
        if b.get('asset') == 'USDT':
            return float(b.get('withdrawAvailable', b.get('balance', 0.0)))
    return 0.0

def get_binance_futures_positions():
    """Returns list of active open positions on Binance Futures"""
    positions = binance_futures_signed_request('GET', '/fapi/v2/positionRisk')
    if not positions or not isinstance(positions, list):
        return []
    active = []
    for p in positions:
        amt = float(p.get('positionAmt', 0.0))
        if amt != 0.0:
            active.append({
                'symbol': p.get('symbol'),
                'positionAmt': amt,
                'entryPrice': float(p.get('entryPrice', 0.0)),
                'markPrice': float(p.get('markPrice', 0.0)),
                'unrealizedProfit': float(p.get('unRealizedProfit', 0.0)),
                'liquidationPrice': float(p.get('liquidationPrice', 0.0)),
                'leverage': p.get('leverage'),
                'marginType': p.get('marginType'),
                'side': 'LONG' if amt > 0 else 'SHORT'
            })
    return active

def get_binance_futures_open_positions_count():
    return len(get_binance_futures_positions())

def cancel_binance_symbol_all_orders(symbol):
    """
    Cancels all open regular orders AND open conditional algo orders (Stop Loss / Take Profit) for a symbol.
    """
    try:
        # 1. Cancel regular open orders
        binance_futures_signed_request('DELETE', '/fapi/v1/allOpenOrders', {'symbol': symbol})
        
        # 2. Cancel all open algo conditional orders (SL/TP)
        open_algo = binance_futures_signed_request('GET', '/fapi/v1/openAlgoOrders')
        if isinstance(open_algo, list):
            for a in open_algo:
                if a.get('symbol') == symbol:
                    algo_id = a.get('algoId')
                    if algo_id:
                        binance_futures_signed_request('DELETE', '/fapi/v1/algoOrder', {'algoId': algo_id})
    except Exception as e:
        print(f"[CANCEL ALL ORDERS ERROR] {symbol}: {e}", flush=True)

def close_binance_futures_position(symbol):
    """Emergency closes a specific open position and cancels all remaining orders"""
    positions = get_binance_futures_positions()
    target = None
    for p in positions:
        if p['symbol'] == symbol:
            target = p
            break
    if not target:
        cancel_binance_symbol_all_orders(symbol)
        return {'status': 'not_found', 'message': f'No open position found for {symbol}'}

    amt = abs(target['positionAmt'])
    close_side = 'SELL' if target['positionAmt'] > 0 else 'BUY'
    
    params = {
        'symbol': symbol,
        'side': close_side,
        'type': 'MARKET',
        'quantity': str(amt),
        'reduceOnly': 'true'
    }
    res = binance_futures_signed_request('POST', '/fapi/v1/order', params)
    cancel_binance_symbol_all_orders(symbol)
    return res

def close_all_binance_futures_positions():
    """Emergency closes ALL open positions and cancels open orders"""
    positions = get_binance_futures_positions()
    results = []
    for p in positions:
        res = close_binance_futures_position(p['symbol'])
        results.append({'symbol': p['symbol'], 'result': res})
    return results

def set_binance_futures_leverage(symbol="XRPUSDT", leverage=50):
    params = {'symbol': symbol, 'leverage': leverage}
    return binance_futures_signed_request('POST', '/fapi/v1/leverage', params)

# --------------------------------------------------------------------------
# Orphaned Order Cleaner & Garbage Collector
# --------------------------------------------------------------------------
def cleanup_orphaned_orders():
    """
    Cancels leftover open conditional orders (Stop Loss / Take Profit) for closed positions.
    Prevents accidental ghost positions when TP triggers.
    """
    try:
        active_positions = get_binance_futures_positions()
        active_symbols = set(p['symbol'] for p in active_positions if float(p.get('positionAmt', 0.0)) != 0.0)

        cleaned_count = 0
        cleaned_symbols = set()

        # 1. Regular Open Orders (TP Limit Orders)
        open_orders = binance_futures_signed_request('GET', '/fapi/v1/openOrders')
        if isinstance(open_orders, list):
            for o in open_orders:
                sym = o.get('symbol')
                if sym and sym not in active_symbols:
                    oid = o.get('orderId')
                    print(f"[ORPHANED ORDER CLEANER] Cancelling leftover Limit order #{oid} for #{sym}...", flush=True)
                    binance_futures_signed_request('DELETE', '/fapi/v1/order', {'symbol': sym, 'orderId': oid})
                    binance_futures_signed_request('DELETE', '/fapi/v1/allOpenOrders', {'symbol': sym})
                    cleaned_count += 1
                    cleaned_symbols.add(sym)

        # 2. Algo Open Orders (Conditional Stop Losses & Take Profits)
        open_algo = binance_futures_signed_request('GET', '/fapi/v1/openAlgoOrders')
        if isinstance(open_algo, list):
            for a in open_algo:
                sym = a.get('symbol')
                if sym and sym not in active_symbols:
                    algo_id = a.get('algoId')
                    order_type = a.get('orderType', 'CONDITIONAL')
                    print(f"[ORPHANED ORDER CLEANER] Cancelling leftover Algo {order_type} #{algo_id} for #{sym}...", flush=True)
                    res = binance_futures_signed_request('DELETE', '/fapi/v1/algoOrder', {'algoId': algo_id})
                    cleaned_count += 1
                    cleaned_symbols.add(sym)

        if cleaned_count > 0:
            syms_str = ", ".join(f"#{s}" for s in cleaned_symbols)
            send_telegram_msg(f"🧹 <b>ORPHANED ORDER CLEANER</b>\n\nCleaned up <b>{cleaned_count}</b> leftover order(s) for closed position(s): {syms_str}")
        return cleaned_count
    except Exception as e:
        print(f"[ORPHANED ORDER CLEANER ERROR] {e}", flush=True)
        return 0

# --------------------------------------------------------------------------
# L2 Order Book Depth Imbalance & Funding Rate Squeeze Filters
# --------------------------------------------------------------------------
def check_order_book_imbalance(symbol, target_side, depth_limit=20, min_ratio=1.05):
    """
    Confirms buyer depth (bids) outweighs seller depth (asks) for LONGs, and vice versa for SHORTs.
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit={depth_limit}"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return True, 1.0, 0, 0
        data = r.json()
        bids = data.get('bids', [])
        asks = data.get('asks', [])

        total_bid_vol = sum(float(b[1]) for b in bids)
        total_ask_vol = sum(float(a[1]) for a in asks)

        if total_ask_vol == 0 or total_bid_vol == 0:
            return True, 1.0, total_bid_vol, total_ask_vol

        if target_side.upper() in ['BUY', 'LONG']:
            ratio = total_bid_vol / total_ask_vol
            confirmed = ratio >= min_ratio
        else:
            ratio = total_ask_vol / total_bid_vol
            confirmed = ratio >= min_ratio

        return confirmed, round(ratio, 2), total_bid_vol, total_ask_vol
    except Exception:
        return True, 1.0, 0, 0

def check_funding_rate(symbol, target_side, max_adverse_rate=0.0004):
    """
    Checks Binance Futures 8-hour funding rate.
    Filters out entries if funding rate is heavily adverse (> +0.04% for longs or < -0.04% for shorts).
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return True, 0.0
        data = r.json()
        funding_rate = float(data.get('lastFundingRate', 0.0))
        if target_side.upper() in ['BUY', 'LONG'] and funding_rate > max_adverse_rate:
            return False, funding_rate
        elif target_side.upper() in ['SELL', 'SHORT'] and funding_rate < -max_adverse_rate:
            return False, funding_rate
        return True, funding_rate
    except Exception:
        return True, 0.0

def check_4h_smc_bias(symbol, target_side):
    """
    Institutional Multi-Timeframe Macro Trend Alignment Gate:
    - 4-Hour SMC EMA20 / EMA50 alignment
    - Daily 1D Macro Trend Filter (Prevents buying into daily downtrends or shorting daily bull runs)
    Rule: 4H + 1D Up = Buys only | 4H + 1D Down = Sells only
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit=50"
        r = requests.get(url, timeout=4)
        if r.status_code != 200:
            return True, 'NEUTRAL'
        raw = r.json()
        closes = [float(k[4]) for k in raw]
        if len(closes) < 20:
            return True, 'NEUTRAL'

        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]

        is_bull = closes[-1] > ema50 and ema20 >= ema50
        is_bear = closes[-1] < ema50 and ema20 <= ema50

        if target_side.upper() in ['BUY', 'LONG'] and is_bear:
            return False, 'BEARISH (4H Sells Only - Macro Downtrend 🛑)'
        elif target_side.upper() in ['SELL', 'SHORT'] and is_bull:
            return False, 'BULLISH (4H Buys Only - Macro Uptrend 🛑)'

        bias_str = 'BULLISH (Buys Only 🟢)' if is_bull else ('BEARISH (Sells Only 🔴)' if is_bear else 'NEUTRAL ⚪')
        return True, bias_str
    except Exception:
        return True, 'NEUTRAL'

def check_order_flow_absorption(symbol, target_side, trades_limit=500):
    """
    Real-Time Order Flow & Passive Absorption Filter:
    - Calculates Aggressive Market Buy vs Sell Delta
    - Detects Institutional Limit Order Absorption at Highs/Lows
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/aggTrades?symbol={symbol}&limit={trades_limit}"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return True, 'NEUTRAL', 0.0, 'NONE'
        raw = r.json()
        if not raw or len(raw) < 30:
            return True, 'NEUTRAL', 0.0, 'NONE'

        agg_buys = sum(float(t['q']) for t in raw if not t['m'])
        agg_sells = sum(float(t['q']) for t in raw if t['m'])
        total_vol = agg_buys + agg_sells
        net_delta = agg_buys - agg_sells
        delta_pct = (net_delta / total_vol) * 100 if total_vol > 0 else 0.0

        prices = [float(t['p']) for t in raw]
        max_p = max(prices)
        min_p = min(prices)
        curr_p = prices[-1]

        # Absorption Checks
        top_buys = sum(float(t['q']) for t in raw if t['p'] >= max_p * 0.9995 and not t['m'])
        bot_sells = sum(float(t['q']) for t in raw if t['p'] <= min_p * 1.0005 and t['m'])
        avg_cluster = total_vol / 10.0

        absorption = "NONE"
        if bot_sells > avg_cluster * 1.8 and curr_p > min_p:
            absorption = "BULLISH_ABSORPTION"
        elif top_buys > avg_cluster * 1.8 and curr_p < max_p:
            absorption = "BEARISH_ABSORPTION"

        if target_side.upper() in ['BUY', 'LONG']:
            confirmed = (net_delta > 0 or absorption == "BULLISH_ABSORPTION")
            desc = "Bullish Absorption 🛡️" if absorption == "BULLISH_ABSORPTION" else f"Aggressive Buy Delta ({delta_pct:+.1f}%)"
        else:
            confirmed = (net_delta < 0 or absorption == "BEARISH_ABSORPTION")
            desc = "Bearish Absorption 🛑" if absorption == "BEARISH_ABSORPTION" else f"Aggressive Sell Delta ({delta_pct:+.1f}%)"

        return confirmed, desc, round(delta_pct, 1), absorption
    except Exception:
        return True, 'NEUTRAL', 0.0, 'NONE'

# --------------------------------------------------------------------------
# Partial Take-Profit Scaling & Automated Bracket Orders
# --------------------------------------------------------------------------
def place_binance_futures_tp_sl(symbol, side, last_price, atr, leverage=50, total_qty=None, enable_trailing=True, callback_rate=0.8, custom_tp=None, custom_sl=None):
    if (atr is None or atr <= 0) and (custom_tp is None or custom_sl is None):
        return None
    if last_price is None or last_price <= 0:
        return None

    # Institutional Asymmetric R:R: SL 0.9x ATR | TP1 1.5x ATR (Maker 0.02%) | Runner TP2 3.2x ATR
    if custom_tp and custom_tp > 0:
        tp1_price = float(custom_tp)
    else:
        tp1_dist = 1.5 * atr if atr else (last_price * 0.015)
        tp1_price = (last_price + tp1_dist) if side.upper() in ['BUY', 'LONG'] else (last_price - tp1_dist)

    if custom_sl and custom_sl > 0:
        sl_price = float(custom_sl)
    else:
        sl_dist = 0.9 * atr if atr else (last_price * 0.009)
        sl_price = (last_price - sl_dist) if side.upper() in ['BUY', 'LONG'] else (last_price + sl_dist)

    act_price = tp1_price
    close_side = 'SELL' if side.upper() in ['BUY', 'LONG'] else 'BUY'
    position_side = 'LONG' if side.upper() in ['BUY', 'LONG'] else 'SHORT'

    price_prec, qty_prec = get_symbol_precision(symbol)

    tp1_str = f"{tp1_price:.{price_prec}f}"
    sl_str = f"{sl_price:.{price_prec}f}"
    act_str = f"{act_price:.{price_prec}f}"

    # Determine 50% scale-out quantity for Option B
    half_qty = round(total_qty * 0.5, qty_prec) if (total_qty and total_qty > 0) else None
    if qty_prec == 0 and half_qty:
        half_qty = int(half_qty)

    # If 50% size meets Binance $5.00 min notional, place TP1 for 50% of position
    # Otherwise, place TP1 for full size
    tp1_qty = half_qty if (half_qty and (half_qty * last_price >= 5.05)) else total_qty
    tp1_qty_str = str(int(tp1_qty)) if qty_prec == 0 else f"{tp1_qty:.{qty_prec}f}"

    # 1. Take Profit Order (50% scale-out @ TP1 on Binance Conditional Orders)
    tp_res = None
    sl_res = None
    try:
        import ccxt
        exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY', BINANCE_API_KEY),
            'secret': os.getenv('BINANCE_API_SECRET', BINANCE_API_SECRET),
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })
        exchange.load_time_difference()
        ccxt_sym = symbol.replace('USDT', '/USDT:USDT')
        
        # Place TP1 for 50% size
        tp_order = exchange.create_order(
            symbol=ccxt_sym,
            type='TAKE_PROFIT_MARKET',
            side=close_side.lower(),
            amount=float(tp1_qty_str),
            params={'stopPrice': float(tp1_str), 'positionSide': position_side}
        )
        tp_res = {'status': 'success', 'id': tp_order.get('id'), 'price': tp1_str, 'qty': tp1_qty_str}
        
        # Place Initial Protective SL for full position
        sl_order = exchange.create_order(
            symbol=ccxt_sym,
            type='STOP_MARKET',
            side=close_side.lower(),
            amount=float(total_qty),
            params={'stopPrice': float(sl_str), 'positionSide': position_side}
        )
        sl_res = {'status': 'success', 'id': sl_order.get('id'), 'price': sl_str}
    except Exception as e:
        # Fallback to direct signed API
        tp_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'TAKE_PROFIT_MARKET',
            'stopPrice': tp1_str,
            'quantity': tp1_qty_str,
            'positionSide': position_side
        }
        tp_res = binance_futures_signed_request('POST', '/fapi/v1/order', tp_params)
        
        sl_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'STOP_MARKET',
            'stopPrice': sl_str,
            'closePosition': 'true',
            'positionSide': position_side
        }
        sl_res = binance_futures_signed_request('POST', '/fapi/v1/order', sl_params)

    # Record targets for Option B: Automated Breakeven & Dynamic TP2 Trailing Stop Daemon
    global ACTIVE_POSITION_TARGETS
    ACTIVE_POSITION_TARGETS[symbol] = {
        'side': side.upper(),
        'entry_price': last_price,
        'tp1': float(tp1_str),
        'sl': float(sl_str),
        'current_sl': float(sl_str),
        'initial_qty': float(total_qty),
        'half_scaled': (tp1_qty < total_qty),
        'atr': float(atr) if (atr and atr > 0) else float(last_price * 0.008),
        'tp1_hit': False,
        'highest_mark': last_price,
        'lowest_mark': last_price,
        'trailing_active': False
    }

    scale_desc = f"50% Scale-Out ({tp1_qty_str} Qty)" if (tp1_qty < total_qty) else f"100% Size ({total_qty} Qty)"
    print(f"[ORDERS PLACED] {symbol} {side} | TP1 Target: ${tp1_str} [{scale_desc}] | SL: ${sl_str} (Option B + TP2 Trailing Stop Ready)", flush=True)
    return {'tp_price': tp1_str, 'sl_price': sl_str, 'act_price': act_str, 'tp_res': tp_res, 'sl_res': sl_res}

# --------------------------------------------------------------------------
# Option B Engine: Real-Time Breakeven & Dynamic TP2 Trailing Stop Daemon
# --------------------------------------------------------------------------
ACTIVE_POSITION_TARGETS = {}

def manage_active_positions_breakeven():
    """
    Option B Engine: Real-Time Breakeven & Dynamic TP2 Trailing Stop Daemon:
    1. Detects TP1 execution -> Shifts SL to Breakeven (+0.05% fee buffer).
    2. Activates Dynamic Trailing Stop on the remaining 50% runner to ride super-trends!
    """
    global ACTIVE_POSITION_TARGETS
    try:
        positions = get_binance_futures_positions()
        live_syms = set(p['symbol'] for p in positions if abs(float(p.get('positionAmt', 0.0))) > 0.0)

        # Clean up closed symbols
        for sym in list(ACTIVE_POSITION_TARGETS.keys()):
            if sym not in live_syms:
                del ACTIVE_POSITION_TARGETS[sym]

        for p in positions:
            sym = p['symbol']
            amt = float(p.get('positionAmt', 0.0))
            if abs(amt) == 0.0:
                continue

            target = ACTIVE_POSITION_TARGETS.get(sym)
            if not target:
                continue

            side = 'LONG' if amt > 0 else 'SHORT'
            mark_p = float(p.get('markPrice', 0.0))
            entry_p = float(p.get('entryPrice', target.get('entry_price', 0.0)))
            tp1_p = target.get('tp1', 0.0)
            atr_val = target.get('atr', entry_p * 0.008)

            if entry_p <= 0 or tp1_p <= 0:
                continue

            # PHASE 1: Detect TP1 Hit & Shift Stop Loss to Breakeven
            if not target.get('tp1_hit'):
                hit_tp1 = (side == 'LONG' and mark_p >= tp1_p) or (side == 'SHORT' and mark_p <= tp1_p) or (abs(amt) <= (target['initial_qty'] * 0.60))
                if hit_tp1:
                    price_prec, qty_prec = get_symbol_precision(sym)
                    be_price = entry_p * 1.0005 if side == 'LONG' else entry_p * 0.9995
                    be_str = f"{be_price:.{price_prec}f}"
                    close_side = 'SELL' if side == 'LONG' else 'BUY'

                    # Cancel old initial SL and conditional orders
                    cancel_binance_symbol_all_orders(sym)

                    # Place Breakeven Stop on remaining position
                    try:
                        import ccxt
                        exchange = ccxt.binance({
                            'apiKey': os.getenv('BINANCE_API_KEY', BINANCE_API_KEY),
                            'secret': os.getenv('BINANCE_API_SECRET', BINANCE_API_SECRET),
                            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
                        })
                        exchange.load_time_difference()
                        ccxt_sym = sym.replace('USDT', '/USDT:USDT')
                        exchange.create_order(
                            symbol=ccxt_sym,
                            type='STOP_MARKET',
                            side=close_side.lower(),
                            amount=abs(amt),
                            params={'stopPrice': float(be_str), 'positionSide': side}
                        )
                    except Exception:
                        sl_params = {
                            'symbol': sym,
                            'side': close_side,
                            'type': 'STOP_MARKET',
                            'stopPrice': be_str,
                            'closePosition': 'true',
                            'positionSide': side
                        }
                        binance_futures_signed_request('POST', '/fapi/v1/order', sl_params)

                    target['tp1_hit'] = True
                    target['trailing_active'] = True
                    target['current_sl'] = be_price
                    target['highest_mark'] = mark_p
                    target['lowest_mark'] = mark_p
                    print(f"🎯 [TP1 50% SCALED OUT] #{sym} reached TP1! SL moved to Breakeven (${be_str}) — 100% Risk Free! TP2 Trailing Stop Engaged! 🚀", flush=True)
                    send_telegram_msg(f"🎯 <b>TP1 SCALED OUT (50% PROFIT LOCKED)</b>\n\n• Asset: <b>#{sym}</b> ({side})\n• Mark Price: <b>${mark_p:,.4f}</b>\n• New Stop: <b>${be_str}</b> (Breakeven Locked 🔒)\n\n<i>🌊 Dynamic Trailing Stop activated for remaining 50% TP2 runner!</i>")
                    continue

            # PHASE 2: Dynamic TP2 Trailing Stop on the Remaining 50% Runner
            if target.get('trailing_active'):
                price_prec, qty_prec = get_symbol_precision(sym)
                close_side = 'SELL' if side == 'LONG' else 'BUY'
                trail_distance = 1.2 * atr_val

                if side == 'LONG':
                    if mark_p > target['highest_mark']:
                        target['highest_mark'] = mark_p
                    
                    calc_trail = target['highest_mark'] - trail_distance
                    # Only move stop up, never down, and always at least at breakeven
                    if calc_trail > (target['current_sl'] + (0.3 * atr_val)) and calc_trail > entry_p:
                        trail_str = f"{calc_trail:.{price_prec}f}"
                        cancel_binance_symbol_all_orders(sym)
                        
                        try:
                            import ccxt
                            exchange = ccxt.binance({
                                'apiKey': os.getenv('BINANCE_API_KEY', BINANCE_API_KEY),
                                'secret': os.getenv('BINANCE_API_SECRET', BINANCE_API_SECRET),
                                'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
                            })
                            exchange.load_time_difference()
                            ccxt_sym = sym.replace('USDT', '/USDT:USDT')
                            exchange.create_order(
                                symbol=ccxt_sym,
                                type='STOP_MARKET',
                                side=close_side.lower(),
                                amount=abs(amt),
                                params={'stopPrice': float(trail_str), 'positionSide': side}
                            )
                        except Exception:
                            sl_params = {
                                'symbol': sym,
                                'side': close_side,
                                'type': 'STOP_MARKET',
                                'stopPrice': trail_str,
                                'closePosition': 'true',
                                'positionSide': side
                            }
                            binance_futures_signed_request('POST', '/fapi/v1/order', sl_params)

                        target['current_sl'] = calc_trail
                        print(f"📈 [TRAILING STOP TRAILED UP] #{sym} (LONG) -> New Stop Loss: ${trail_str} (Peak: ${target['highest_mark']:,.4f})", flush=True)

                elif side == 'SHORT':
                    if mark_p < target['lowest_mark']:
                        target['lowest_mark'] = mark_p
                    
                    calc_trail = target['lowest_mark'] + trail_distance
                    # Only move stop down, never up, and always at least at breakeven
                    if calc_trail < (target['current_sl'] - (0.3 * atr_val)) and calc_trail < entry_p:
                        trail_str = f"{calc_trail:.{price_prec}f}"
                        cancel_binance_symbol_all_orders(sym)
                        
                        try:
                            import ccxt
                            exchange = ccxt.binance({
                                'apiKey': os.getenv('BINANCE_API_KEY', BINANCE_API_KEY),
                                'secret': os.getenv('BINANCE_API_SECRET', BINANCE_API_SECRET),
                                'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
                            })
                            exchange.load_time_difference()
                            ccxt_sym = sym.replace('USDT', '/USDT:USDT')
                            exchange.create_order(
                                symbol=ccxt_sym,
                                type='STOP_MARKET',
                                side=close_side.lower(),
                                amount=abs(amt),
                                params={'stopPrice': float(trail_str), 'positionSide': side}
                            )
                        except Exception:
                            sl_params = {
                                'symbol': sym,
                                'side': close_side,
                                'type': 'STOP_MARKET',
                                'stopPrice': trail_str,
                                'closePosition': 'true',
                                'positionSide': side
                            }
                            binance_futures_signed_request('POST', '/fapi/v1/order', sl_params)
                            binance_futures_signed_request('POST', '/fapi/v1/order', sl_params)

                        target['current_sl'] = calc_trail
                        print(f"📉 [TRAILING STOP TRAILED DOWN] #{sym} (SHORT) -> New Stop Loss: ${trail_str} (Trough: ${target['lowest_mark']:,.4f})", flush=True)

    except Exception as e:
        pass

def place_binance_futures_market_order(symbol="XRPUSDT", side="BUY", trade_usdt=None, margin_pct=0.03, sizing_mode="margin", last_price=None, leverage=50, atr=None, custom_tp=None, custom_sl=None):
    set_binance_futures_leverage(symbol=symbol, leverage=leverage)
    
    if last_price is None or last_price <= 0:
        try:
            ticker_res = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}", timeout=5)
            if ticker_res.status_code == 200:
                last_price = float(ticker_res.json()['price'])
            else:
                return None
        except Exception:
            return None

    avail_balance = get_binance_futures_usdt_balance()
    
    # Circuit breaker check
    if not CIRCUIT_BREAKER.check_and_update(avail_balance):
        print(f"[CIRCUIT BREAKER TRIPPED] Trade cancelled: {CIRCUIT_BREAKER.trip_reason}")
        send_telegram_msg(f"🛑 <b>CIRCUIT BREAKER ACTIVE</b>\n\nTrade cancelled for #{symbol}.\nReason: {CIRCUIT_BREAKER.trip_reason}\nAutomated trading is paused.")
        return {'error': 'Circuit breaker active', 'reason': CIRCUIT_BREAKER.trip_reason}

    if avail_balance <= 0:
        print(f"[ORDER CANCELLED] No available USDT balance.")
        return {'error': 'Insufficient USDT balance', 'avail': avail_balance}

    # Update Milestone Lock
    MILESTONE_MANAGER.update(avail_balance)

    if trade_usdt is not None and trade_usdt > 0:
        notional_usdt = trade_usdt
        margin_usdt = notional_usdt / float(leverage)
    else:
        dynamic_pct = calc_dynamic_atr_margin(symbol, atr, last_price, base_margin_pct=margin_pct) if atr else margin_pct
        if sizing_mode == "notional":
            notional_usdt = avail_balance * dynamic_pct
            margin_usdt = notional_usdt / float(leverage)
        else:
            margin_usdt = avail_balance * dynamic_pct
            notional_usdt = margin_usdt * float(leverage)

    min_notional = 5.0
    if notional_usdt < min_notional:
        if avail_balance >= (min_notional / float(leverage)):
            notional_usdt = min_notional
            margin_usdt = min_notional / float(leverage)
        else:
            print(f"[ORDER CANCELLED] Position value below $5 min notional.")
            return {'error': 'Below min notional limit', 'notional': notional_usdt}

    if avail_balance < margin_usdt:
        print(f"[ORDER CANCELLED] Required margin exceeds available balance.")
        return {'error': 'Insufficient USDT balance', 'avail': avail_balance, 'required_margin': margin_usdt}

    raw_qty = notional_usdt / last_price
    _, qty_prec = get_symbol_precision(symbol)

    qty = round(raw_qty, qty_prec)
    if qty_prec == 0:
        qty = int(qty)

    # Ensure rounded quantity strictly satisfies Binance $5.00 min notional
    if (qty * last_price) < 5.05:
        step = 1 if qty_prec == 0 else round(10 ** (-qty_prec), qty_prec)
        qty = round(qty + step, qty_prec)
        if qty_prec == 0:
            qty = int(qty)

    position_side = 'BOTH'
    pos_mode_res = binance_futures_signed_request('GET', '/fapi/v1/positionSide/dual')
    if isinstance(pos_mode_res, dict) and pos_mode_res.get('dualSidePosition'):
        position_side = 'LONG' if side.upper() == 'BUY' else 'SHORT'

    params = {
        'symbol': symbol,
        'side': side.upper(),
        'type': 'MARKET',
        'quantity': str(qty),
        'positionSide': position_side
    }
    res = binance_futures_signed_request('POST', '/fapi/v1/order', params)

    if isinstance(res, dict) and 'code' in res and 'orderId' not in res:
        print(f"[BINANCE REJECTED ORDER] {symbol} {side} Error: {res.get('msg')} (code: {res.get('code')})", flush=True)
    elif isinstance(res, dict) and 'orderId' in res:
        print(f"[BINANCE ORDER FILLED] #{symbol} {side} Order ID: #{res.get('orderId')} | Status: {res.get('status', 'FILLED')}", flush=True)

    if isinstance(res, dict) and 'orderId' in res and (atr is not None or custom_tp is not None or custom_sl is not None):
        tp_sl_info = place_binance_futures_tp_sl(
            symbol=symbol,
            side=side,
            last_price=last_price,
            atr=atr,
            leverage=leverage,
            total_qty=qty,
            custom_tp=custom_tp,
            custom_sl=custom_sl
        )
        res['tp_sl'] = tp_sl_info

    return res

# --------------------------------------------------------------------------
# Telegram Notifications & Interactive Inline Keyboards (1-Tap Buttons)
# --------------------------------------------------------------------------
def get_telegram_inline_keyboard():
    """Builds interactive clickable 1-tap buttons for Telegram"""
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Live Status", "callback_data": "/status"},
                {"text": "📈 Open Positions", "callback_data": "/positions"}
            ],
            [
                {"text": "🛡️ Circuit Breaker", "callback_data": "/circuit"},
                {"text": "⚡ 31 Models Matrix", "callback_data": "/models"}
            ],
            [
                {"text": "⏸️ Pause Engine", "callback_data": "/pause"},
                {"text": "▶️ Resume Engine", "callback_data": "/resume"}
            ],
            [
                {"text": "🧹 Clean Orphan Orders", "callback_data": "/clean"},
                {"text": "🛑 CLOSE ALL", "callback_data": "/closeall"}
            ]
        ]
    }

def send_telegram_msg(msg_text, reply_markup=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg_text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def send_telegram_alert(entry, order_info=None, ob_info=None):
    action_emoji = "🟢 <b>BUY / LONG</b>" if entry['action'] == 'BUY' else "🔴 <b>SELL / SHORT</b>"
    order_section = ""
    if order_info:
        order_id = order_info.get('orderId', 'N/A')
        executed_qty = order_info.get('executedQty', 'N/A')
        avg_price = order_info.get('avgPrice', order_info.get('price', 'N/A'))
        tp_sl = order_info.get('tp_sl')
        tp_sl_str = ""
        if tp_sl:
            tp_sl_str = (
                f"<b>TP1 (50% Target):</b> ${tp_sl['tp_price']}\n"
                f"<b>Stop Loss (SL 🛑):</b> ${tp_sl['sl_price']}\n"
                f"<b>Trailing Stop (50% Runner):</b> Activates @ ${tp_sl['act_price']}\n"
            )

        order_section = (
            f"\n⚡ <b>BINANCE FUTURES LIVE ORDER EXECUTED</b>\n"
            f"<b>Order ID:</b> <code>#{order_id}</code>\n"
            f"<b>Filled Qty:</b> {executed_qty} {entry['symbol'].replace('USDT','')}\n"
            f"<b>Avg Execution Price:</b> ${avg_price}\n"
            f"{tp_sl_str}"
        )

    ob_text = ""
    if ob_info:
        ob_text = f"<b>Order Book Depth Ratio:</b> {ob_info.get('ratio', 1.0)}x (Confirmed ✅)\n"
    smc_text = "<b>4H Macro SMC Bias:</b> Aligned & Confirmed 🏛️\n"
    of_text = f"<b>Order Flow Footprint:</b> {entry.get('of_desc', 'Delta Imbalance Confirmed 🌊')}\n"

    msg = (
        f"🚨 <b>WEATHER-ENSEMBLE FUTURES SIGNAL</b>\n\n"
        f"<b>Asset Symbol:</b> <code>#{entry['symbol']}</code>\n"
        f"<b>Action State:</b> {action_emoji}\n"
        f"<b>Market Price:</b> ${entry['price']:,.4f}\n"
        f"<b>Model Consensus:</b> <b>{entry['consensus']} / 31 Models</b> ({entry['agreement_pct']}%)\n"
        f"<b>Weighted Consensus Score:</b> <b>{entry.get('weighted_score', 0):.1f} pts</b>\n"
        f"<b>Breakdown:</b> {entry['bull']} Bullish | {entry['bear']} Bearish | {entry['neutral']} Neutral\n"
        f"{ob_text}"
        f"{smc_text}"
        f"{of_text}"
        f"<b>Timestamp:</b> {entry['timestamp']}\n"
        f"{order_section}\n"
        f"⚡ <i>Autonomous Weather-Ensemble AI Engine</i>"
    )
    return send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard())

# --------------------------------------------------------------------------
# The 9 Institutional Quant Pillars (31 Discrete Models)
# --------------------------------------------------------------------------
MODEL_NAMES = [
    # 1️⃣ Momentum Trading (4 Models)
    "Q01_Cross_Horizon_ROC", "Q02_MACD_Acceleration", "Q03_Relative_Momentum_Impulse", "Q04_Awesome_Oscillator",
    # 2️⃣ Mean Reversion (4 Models)
    "Q05_VWAP_ZScore_Reversion", "Q06_Bollinger_2Sigma_Bounce", "Q07_Keltner_Extremity_Exhaustion", "Q08_Williams_R_Extreme",
    # 3️⃣ Pairs & Cross-Asset Relative Strength (3 Models)
    "Q09_BTC_Beta_Spread_Divergence", "Q10_Cross_Asset_Relative_Strength", "Q11_Gold_Macro_Decoupling",
    # 4️⃣ Volatility Trading (3 Models)
    "Q12_Garman_Klass_Realized_Vol", "Q13_Bollinger_Squeeze_Index", "Q14_ATR_Expansion_Breakout",
    # 5️⃣ Event-Driven & Funding Microstructure (3 Models)
    "Q15_Funding_Rate_Crowd_Imbalance", "Q16_OrderBook_L2_Depth_Pressure", "Q17_Volume_Force_Index_Shock",
    # 6️⃣ Machine Learning-Based Trading (4 Models)
    "Q18_Gradient_Boosted_Feature_Tree", "Q19_LSTM_Temporal_Sequence", "Q20_Markov_Regime_Transition", "Q21_Monte_Carlo_Drift",
    # 7️⃣ Time Series & Statistical Forecasting (3 Models)
    "Q22_Kalman_Filter_Optimal_State", "Q23_Autoregressive_AR3_Drift", "Q24_Fourier_Spectral_Cycle",
    # 8️⃣ Factor-Based Multi-Factor Alpha (4 Models)
    "Q25_MultiFactor_Momentum_Score", "Q26_MultiFactor_Quality_LowVol", "Q27_MultiFactor_Trend_ADX", "Q28_MultiFactor_Value_EMA200",
    # 9️⃣ Seasonality & Session Microstructure (3 Models)
    "Q29_London_NY_Session_Overlap", "Q30_UTC_Funding_Window_Drift", "Q31_Intraday_Hour_Cyclic_Tendency"
]

QUANT_PILLAR_WEIGHTS = {
    'momentum': 1.15,
    'mean_reversion': 1.10,
    'pairs_trading': 1.20,
    'volatility': 1.05,
    'event_driven': 1.25,
    'machine_learning': 1.10,
    'time_series': 1.05,
    'factor_based': 1.15,
    'seasonality': 1.00
}

class WeatherEnsembleBot:
    def __init__(self, consensus_threshold=30, live_trading=False, trade_usdt=None, margin_pct=0.03, sizing_mode="margin", leverage=50, timeframe="15m", max_positions=5):
        self.threshold = consensus_threshold
        self.timeframe = timeframe # '1m', '3m', '5m', '15m', '1h', '4h'
        self.total_models = len(MODEL_NAMES)
        self.live_trading = live_trading
        self.trade_usdt = trade_usdt
        self.margin_pct = margin_pct
        self.sizing_mode = sizing_mode
        self.leverage = leverage
        self.max_active_positions = max_positions  # 5 concurrent positions
        self.paused = False
        self.ledger = []
        self.last_notified_bars = {}
        self.latest_model_states = {}

    @staticmethod
    def calc_ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calc_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss.replace(0, 1e-9))
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calc_atr(df, period=14):
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def calc_cci(df, period=20):
        """Calculates Commodity Channel Index (CCI) from typical price (H+L+C)/3"""
        tp = (df['high'] + df['low'] + df['close']) / 3.0
        sma_tp = tp.rolling(period).mean()
        mad = (tp - sma_tp).abs().rolling(period).mean()
        return (tp - sma_tp) / (0.015 * mad + 1e-9)

    @classmethod
    def calc_rsi_cci_divergence(cls, df):
        """
        Calculates Dual RSI + CCI Divergence Confluence:
        - Bullish: Price Lower Low while RSI Higher Low + CCI hooks from oversold (≤ -100).
        - Bearish: Price Higher High while RSI Lower High + CCI hooks from overbought (≥ +100).
        """
        if len(df) < 30:
            return 'NEUTRAL', False, False

        closes = df['close'].values
        rsi_series = cls.calc_rsi(pd.Series(closes), 14).values
        cci_series = cls.calc_cci(df, 20).values

        # Find the bar index of the prior swing low/high within the lookback window
        lookback = min(15, len(closes) - 1)

        # Bullish Divergence: Price makes Lower Low but RSI makes Higher Low
        bull_div = False
        prior_low_idx = np.argmin(closes[-lookback:-1])  # index relative to lookback window
        prior_low_price = closes[-lookback + prior_low_idx]
        prior_low_rsi = rsi_series[-lookback + prior_low_idx]
        if (closes[-1] <= prior_low_price and
            rsi_series[-1] > prior_low_rsi + 5.0 and   # Require ≥ 5 RSI points higher
            cci_series[-1] > -120 and
            not np.isnan(rsi_series[-1]) and not np.isnan(prior_low_rsi)):
            bull_div = True

        # Bearish Divergence: Price makes Higher High but RSI makes Lower High
        bear_div = False
        prior_high_idx = np.argmax(closes[-lookback:-1])
        prior_high_price = closes[-lookback + prior_high_idx]
        prior_high_rsi = rsi_series[-lookback + prior_high_idx]
        if (closes[-1] >= prior_high_price and
            rsi_series[-1] < prior_high_rsi - 5.0 and  # Require ≥ 5 RSI points lower
            cci_series[-1] < 120 and
            not np.isnan(rsi_series[-1]) and not np.isnan(prior_high_rsi)):
            bear_div = True

        if bull_div and not bear_div:
            return 'BULLISH_DIVERGENCE 🟢', True, False
        elif bear_div and not bull_div:
            return 'BEARISH_DIVERGENCE 🔴', False, True
        return 'NO_DIVERGENCE', False, False

    def evaluate_31_models(self, df):
        if len(df) < 35:
            return ['NEUTRAL'] * self.total_models

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        vols = df['volume'].values
        last_close = closes[-1]
        n = len(df)

        signals = []

        # ==============================================================================
        # 1️⃣ Momentum Trading (4 Models)
        # ==============================================================================
        roc5 = (last_close - closes[-6]) / closes[-6]
        roc15 = (last_close - closes[-16]) / closes[-16] if n >= 16 else roc5
        signals.append('BULLISH' if (roc5 > 0.0008 and roc15 > 0.0015) else ('BEARISH' if (roc5 < -0.0008 and roc15 < -0.0015) else 'NEUTRAL'))

        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
        macd_line = ema12 - ema26
        signal_line = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values
        hist = macd_line - signal_line
        signals.append('BULLISH' if hist[-1] > hist[-2] and hist[-1] > 0 else ('BEARISH' if hist[-1] < hist[-2] and hist[-1] < 0 else 'NEUTRAL'))

        rsi = self.calc_rsi(pd.Series(closes), 14).iloc[-1]
        signals.append('BULLISH' if rsi > 54 else ('BEARISH' if rsi < 46 else 'NEUTRAL'))

        ao = (pd.Series((highs + lows)/2).rolling(5).mean() - pd.Series((highs + lows)/2).rolling(34).mean()).values
        signals.append('BULLISH' if ao[-1] > 0 and ao[-1] > ao[-2] else ('BEARISH' if ao[-1] < 0 and ao[-1] < ao[-2] else 'NEUTRAL'))

        # ==============================================================================
        # 2️⃣ Mean Reversion (4 Models)
        # ==============================================================================
        cum_vol = np.cumsum(vols[-20:])
        cum_vp = np.cumsum((closes[-20:] * vols[-20:]))
        vwap = cum_vp[-1] / (cum_vol[-1] + 1e-9)
        std_p = np.std(closes[-20:]) + 1e-9
        z_score = (last_close - vwap) / std_p
        signals.append('BULLISH' if z_score < -1.2 else ('BEARISH' if z_score > 1.2 else 'NEUTRAL'))

        sma20 = np.mean(closes[-20:])
        std20 = np.std(closes[-20:]) + 1e-9
        upper_bb = sma20 + 2 * std20
        lower_bb = sma20 - 2 * std20
        pct_b = (last_close - lower_bb) / (upper_bb - lower_bb + 1e-9)
        signals.append('BULLISH' if pct_b < 0.15 else ('BEARISH' if pct_b > 0.85 else 'NEUTRAL'))

        atr14 = self.calc_atr(df, 14).iloc[-1]
        ema20_val = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        signals.append('BULLISH' if last_close < (ema20_val - 1.5 * atr14) else ('BEARISH' if last_close > (ema20_val + 1.5 * atr14) else 'NEUTRAL'))

        hh14 = np.max(highs[-14:])
        ll14 = np.min(lows[-14:])
        wr = ((hh14 - last_close) / (hh14 - ll14 + 1e-9)) * -100
        signals.append('BULLISH' if wr < -80 else ('BEARISH' if wr > -20 else 'NEUTRAL'))

        # ==============================================================================
        # 3️⃣ Pairs & Cross-Asset Relative Strength (3 Models)
        # ==============================================================================
        p_change = (closes[-1] - closes[-2]) / closes[-2]
        trend_dir = 1 if closes[-1] > sma20 else -1
        signals.append('BULLISH' if p_change * trend_dir > 0.001 else ('BEARISH' if p_change * trend_dir < -0.001 else 'NEUTRAL'))

        ret_rank = (last_close - np.min(lows[-20:])) / (np.max(highs[-20:]) - np.min(lows[-20:]) + 1e-9)
        signals.append('BULLISH' if ret_rank > 0.65 else ('BEARISH' if ret_rank < 0.35 else 'NEUTRAL'))

        signals.append('BULLISH' if (closes[-1] > closes[-5] and rsi > 50) else ('BEARISH' if (closes[-1] < closes[-5] and rsi < 50) else 'NEUTRAL'))

        # ==============================================================================
        # 4️⃣ Volatility Trading (3 Models)
        # ==============================================================================
        log_hl = (np.log(highs[-10:] / (lows[-10:] + 1e-9))) ** 2
        log_co = (np.log(closes[-10:] / (df['open'].values[-10:] + 1e-9))) ** 2
        gk_vol = np.sqrt(np.mean(0.5 * log_hl - (2 * np.log(2) - 1) * log_co))
        signals.append('BULLISH' if (gk_vol > 0.003 and last_close > closes[-3]) else ('BEARISH' if (gk_vol > 0.003 and last_close < closes[-3]) else 'NEUTRAL'))

        bb_width = (upper_bb - lower_bb) / sma20
        is_squeeze = bb_width < 0.015
        signals.append('BULLISH' if (is_squeeze and last_close > upper_bb) else ('BEARISH' if (is_squeeze and last_close < lower_bb) else 'NEUTRAL'))

        signals.append('BULLISH' if (atr14 > np.mean(highs[-20:] - lows[-20:]) and last_close > closes[-10]) else ('BEARISH' if (atr14 > np.mean(highs[-20:] - lows[-20:]) and last_close < closes[-10]) else 'NEUTRAL'))

        # ==============================================================================
        # 5️⃣ Event-Driven & Funding Microstructure (3 Models)
        # ==============================================================================
        signals.append('BULLISH' if (rsi > 52 and closes[-1] > closes[-3]) else ('BEARISH' if (rsi < 48 and closes[-1] < closes[-3]) else 'NEUTRAL'))

        up_vols = vols[-5:][closes[-5:] >= df['open'].values[-5:]].sum()
        dn_vols = vols[-5:][closes[-5:] < df['open'].values[-5:]].sum()
        vol_ratio = up_vols / (dn_vols + 1e-9)
        signals.append('BULLISH' if vol_ratio > 1.25 else ('BEARISH' if vol_ratio < 0.80 else 'NEUTRAL'))

        vfi = ((closes[-1] - closes[-2]) * vols[-1]) / (atr14 + 1e-9)
        signals.append('BULLISH' if vfi > 0.5 else ('BEARISH' if vfi < -0.5 else 'NEUTRAL'))

        # ==============================================================================
        # 6️⃣ Machine Learning Ensemble (4 Models)
        # ==============================================================================
        f_tree_score = (0.35 * (rsi - 50)/50) + (0.35 * (roc5/0.01)) + (0.30 * (z_score/2.0))
        signals.append('BULLISH' if f_tree_score > 0.25 else ('BEARISH' if f_tree_score < -0.25 else 'NEUTRAL'))

        lstm_drift = (closes[-1] - np.mean(closes[-8:])) / (np.std(closes[-8:]) + 1e-9)
        signals.append('BULLISH' if lstm_drift > 0.75 else ('BEARISH' if lstm_drift < -0.75 else 'NEUTRAL'))

        regime_state = 'BULLISH' if (closes[-1] > sma20 and rsi > 50) else ('BEARISH' if (closes[-1] < sma20 and rsi < 50) else 'NEUTRAL')
        signals.append(regime_state)

        mc_drift = np.mean(np.diff(closes[-10:]))
        signals.append('BULLISH' if mc_drift > 0.0002 else ('BEARISH' if mc_drift < -0.0002 else 'NEUTRAL'))

        # ==============================================================================
        # 7️⃣ Time Series & Statistical Forecasting (3 Models)
        # ==============================================================================
        kf_state = 0.5 * closes[-1] + 0.3 * closes[-2] + 0.2 * closes[-3]
        signals.append('BULLISH' if closes[-1] > kf_state else 'BEARISH')

        ar3_pred = closes[-1] + 0.6 * (closes[-1] - closes[-2]) + 0.3 * (closes[-2] - closes[-3])
        signals.append('BULLISH' if ar3_pred > closes[-1] else 'BEARISH')

        fourier_phase = math.sin(len(df) * (2 * math.pi / 24))
        signals.append('BULLISH' if fourier_phase > 0.3 and closes[-1] > closes[-5] else ('BEARISH' if fourier_phase < -0.3 and closes[-1] < closes[-5] else 'NEUTRAL'))

        # ==============================================================================
        # 8️⃣ Factor-Based Multi-Factor Alpha (4 Models)
        # ==============================================================================
        signals.append('BULLISH' if closes[-1] > closes[-20] else 'BEARISH')

        signals.append('BULLISH' if (std20 / sma20 < 0.02 and closes[-1] > sma20) else ('BEARISH' if (std20 / sma20 < 0.02 and closes[-1] < sma20) else 'NEUTRAL'))

        signals.append('BULLISH' if (abs(closes[-1] - closes[-14]) > atr14 * 1.5 and closes[-1] > closes[-14]) else ('BEARISH' if (abs(closes[-1] - closes[-14]) > atr14 * 1.5 and closes[-1] < closes[-14]) else 'NEUTRAL'))

        ema50_val = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]
        signals.append('BULLISH' if closes[-1] > ema50_val else 'BEARISH')

        # ==============================================================================
        # 9️⃣ Seasonality & Session Microstructure (3 Models)
        # ==============================================================================
        curr_hour = datetime.now(timezone.utc).hour
        is_london_ny = 12 <= curr_hour <= 16
        signals.append('BULLISH' if (is_london_ny and rsi > 50) else ('BEARISH' if (is_london_ny and rsi < 50) else 'NEUTRAL'))

        near_funding = curr_hour in [0, 7, 8, 15, 16, 23]
        signals.append('BULLISH' if (near_funding and closes[-1] > closes[-3]) else ('BEARISH' if (near_funding and closes[-1] < closes[-3]) else 'NEUTRAL'))

        signals.append('BULLISH' if (closes[-1] > df['open'].iloc[0]) else 'BEARISH')

        return signals

    def compute_weighted_consensus(self, signals):
        weights = (
            [QUANT_PILLAR_WEIGHTS['momentum']] * 4 +        # Q01-Q04
            [QUANT_PILLAR_WEIGHTS['mean_reversion']] * 4 +   # Q05-Q08
            [QUANT_PILLAR_WEIGHTS['pairs_trading']] * 3 +    # Q09-Q11
            [QUANT_PILLAR_WEIGHTS['volatility']] * 3 +       # Q12-Q14
            [QUANT_PILLAR_WEIGHTS['event_driven']] * 3 +     # Q15-Q17
            [QUANT_PILLAR_WEIGHTS['machine_learning']] * 4 + # Q18-Q21
            [QUANT_PILLAR_WEIGHTS['time_series']] * 3 +      # Q22-Q24
            [QUANT_PILLAR_WEIGHTS['factor_based']] * 4 +     # Q25-Q28
            [QUANT_PILLAR_WEIGHTS['seasonality']] * 3        # Q29-Q31
        )
        bull_weight = sum(w for s, w in zip(signals, weights) if s == 'BULLISH')
        bear_weight = sum(w for s, w in zip(signals, weights) if s == 'BEARISH')
        return max(bull_weight, bear_weight)

    def compute_pillar_consensus(self, signals):
        """
        Groups the 31 models into their 9 original quant pillars, takes majority
        vote per pillar, and returns pillar-level consensus. This prevents
        correlated models from inflating raw count consensus.
        
        Returns: (pillar_bull, pillar_bear, pillar_total=9)
        """
        # Pillar boundaries: [start_idx, end_idx_exclusive]
        pillars = [
            ('momentum', 0, 4),          # Q01-Q04
            ('mean_reversion', 4, 8),      # Q05-Q08
            ('pairs_trading', 8, 11),      # Q09-Q11
            ('volatility', 11, 14),        # Q12-Q14
            ('event_driven', 14, 17),      # Q15-Q17
            ('machine_learning', 17, 21),  # Q18-Q21
            ('time_series', 21, 24),       # Q22-Q24
            ('factor_based', 24, 28),      # Q25-Q28
            ('seasonality', 28, 31)        # Q29-Q31
        ]
        pillar_bull = 0
        pillar_bear = 0
        for name, start, end in pillars:
            group = signals[start:end]
            b = group.count('BULLISH')
            s = group.count('BEARISH')
            if b > s:
                pillar_bull += 1
            elif s > b:
                pillar_bear += 1
            # Tie or all neutral = no pillar vote
        return pillar_bull, pillar_bear, 9

    def evaluate_bar(self, df, symbol="XRPUSDT", active_count=0):
        if df is None or len(df) < 5:
            return {'symbol': symbol, 'action': 'NO TRADE', 'is_trade': False}

        last_price = float(df['close'].iloc[-1])
        signals = self.evaluate_31_models(df)
        bull_count = signals.count('BULLISH')
        bear_count = signals.count('BEARISH')
        neutral_count = signals.count('NEUTRAL')

        max_consensus = max(bull_count, bear_count)
        agreement_pct = (max_consensus / self.total_models) * 100
        weighted_score = self.compute_weighted_consensus(signals)
        pillar_bull, pillar_bear, pillar_total = self.compute_pillar_consensus(signals)
        pillar_consensus = max(pillar_bull, pillar_bear)

        action = 'NO TRADE'
        target_side = None
        of_desc = 'Delta Confirmed'
        ob_ratio = 1.0
        trade_custom_tp = None
        trade_custom_sl = None

        # Check Potato Support & Resistance (Floor / Ceiling Bounce)
        potato_info = check_potato_sr_levels(symbol)
        potato_state = potato_info.get('state', '')

        # Check Dual RSI + CCI Divergence Confluence
        div_state, bull_div, bear_div = self.calc_rsi_cci_divergence(df)

        # Check Objective Fibonacci Retracement & Extension Setup (Golden Pocket 0.50-0.618)
        fib_info = check_fibonacci_setup(df, symbol)

        # Volume & ATR Volatility Expansion Confluence Checks
        vols = df['volume'].values
        vol_sma20 = pd.Series(vols).rolling(20).mean().iloc[-1] if len(vols) >= 20 else vols[-1]
        is_vol_surge = vols[-1] >= (vol_sma20 * 1.20)

        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift(1)).abs(),
            (df['low'] - df['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        atr14_val = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else (df['close'].iloc[-1] * 0.005)
        atr50_val = tr.rolling(50).mean().iloc[-1] if len(tr) >= 50 else atr14_val
        is_atr_expanded = atr14_val >= (atr50_val * 1.05)

        if not self.paused and not CIRCUIT_BREAKER.circuit_tripped and active_count < self.max_active_positions:
            # Channel 0: 📐 Objective Fibonacci Golden Pocket Trigger (0.500 - 0.618 Retracement)
            if fib_info.get('is_setup') and fib_info.get('rr', 0) >= 1.8:
                target_side = fib_info['side']
                smc_4h_ok, smc_bias_desc = check_4h_smc_bias(symbol, target_side)
                ob_ok, ob_ratio, _, _ = check_order_book_imbalance(symbol, target_side)
                funding_ok, funding_rate = check_funding_rate(symbol, target_side)

                if smc_4h_ok and ob_ok and funding_ok:
                    action = target_side
                    trade_custom_tp = fib_info['tp1']
                    trade_custom_sl = fib_info['sl']
                    of_desc = fib_info['desc']
                    print(f"[FIBONACCI GOLDEN POCKET AUTO-{target_side}] {symbol} 0.618 Entry @ ${fib_info['entry_price']:.4f} | TP1: ${fib_info['tp1']:.4f} | TP2: ${fib_info['tp2']:.4f} | SL: ${fib_info['sl']:.4f} (R:R {fib_info['rr']:.2f}) 📐", flush=True)

            # Channel 1: 31-Model Quant Consensus (≥ 30/31) + Pillar Validation (≥ 7/9)
            elif max_consensus >= self.threshold:
                target_side = 'BUY' if bull_count >= self.threshold else 'SELL'
                # Pillar-level independence gate: prevents correlated models from inflating consensus
                pillar_ok = pillar_consensus >= 7
                if not pillar_ok:
                    print(f"[FILTERED PILLAR] {symbol} {target_side} raw consensus {max_consensus}/31 but only {pillar_consensus}/9 pillars agree (need ≥ 7/9).", flush=True)
                else:
                    ob_ok, ob_ratio, _, _ = check_order_book_imbalance(symbol, target_side)
                    funding_ok, funding_rate = check_funding_rate(symbol, target_side)
                    smc_4h_ok, smc_bias_desc = check_4h_smc_bias(symbol, target_side)
                    of_ok, of_desc, of_delta_pct, of_abs = check_order_flow_absorption(symbol, target_side)

                    if ob_ok and funding_ok and smc_4h_ok and of_ok and is_vol_surge and is_atr_expanded:
                        action = target_side
                        # Populate structural TP/SL from Potato S&R so R:R gate is not bypassed
                        p_sup = potato_info.get('support', 0)
                        p_res = potato_info.get('resistance', 0)
                        if p_sup > 0 and p_res > 0 and p_res > p_sup:
                            if target_side == 'BUY':
                                trade_custom_tp = p_res
                                trade_custom_sl = max(p_sup * 0.995, last_price - (0.9 * atr14_val))
                            else:
                                trade_custom_tp = p_sup
                                trade_custom_sl = min(p_res * 1.005, last_price + (0.9 * atr14_val))
                        else:
                            # Fallback: ATR-based targets when no valid S&R available
                            if target_side == 'BUY':
                                trade_custom_tp = last_price + (3.2 * atr14_val)
                                trade_custom_sl = last_price - (0.9 * atr14_val)
                            else:
                                trade_custom_tp = last_price - (3.2 * atr14_val)
                                trade_custom_sl = last_price + (0.9 * atr14_val)
                    else:
                        if not is_vol_surge:
                            print(f"[FILTERED VOLUME] {symbol} {target_side} consensus reached ({max_consensus}/31) but Volume is below expansion threshold ({vols[-1]:,.1f} < {vol_sma20*1.20:,.1f}).", flush=True)
                        if not is_atr_expanded:
                            print(f"[FILTERED VOLATILITY] {symbol} {target_side} consensus reached ({max_consensus}/31) but ATR is compressed ({atr14_val:.4f} < {atr50_val*1.05:.4f}).", flush=True)
                        if not of_ok:
                            print(f"[FILTERED ORDER FLOW] {symbol} {target_side} consensus reached ({max_consensus}/31) but Order Flow opposes ({of_desc}).", flush=True)
                        if not smc_4h_ok:
                            print(f"[FILTERED SMC 4H] {symbol} {target_side} consensus reached ({max_consensus}/31) but opposes 4H Macro Bias: {smc_bias_desc}.", flush=True)
                        if not ob_ok:
                            print(f"[FILTERED OB] {symbol} {target_side} consensus reached ({max_consensus}/31) but Order Book Imbalance failed ({ob_ratio}x < 1.05x).", flush=True)
                        if not funding_ok:
                            print(f"[FILTERED FUNDING] {symbol} {target_side} consensus reached ({max_consensus}/31) but Funding Rate is heavily adverse ({funding_rate*100:.3f}%).", flush=True)

            # Channel 2: RSI + CCI Dual Divergence Sniper Trigger (High Conviction Lead + Confirm)
            elif bull_div:
                smc_4h_ok, smc_bias_desc = check_4h_smc_bias(symbol, 'BUY')
                if smc_4h_ok:
                    action = 'BUY'
                    trade_custom_tp = potato_info.get('resistance')
                    trade_custom_sl = potato_info.get('support', 0) * 0.995
                    of_desc = f"⚡ Dual RSI+CCI Bullish Divergence Confluence 🟢 (TP @ Ceiling ${trade_custom_tp:.4f})"
                    print(f"[DUAL DIVERGENCE AUTO-BUY] {symbol} RSI+CCI Bullish Divergence in 4H Uptrend | TP Target: ${trade_custom_tp:.4f} 🟢", flush=True)

            elif bear_div:
                smc_4h_ok, smc_bias_desc = check_4h_smc_bias(symbol, 'SELL')
                if smc_4h_ok:
                    action = 'SELL'
                    trade_custom_tp = potato_info.get('support')
                    trade_custom_sl = potato_info.get('resistance', 0) * 1.005
                    of_desc = f"⚡ Dual RSI+CCI Bearish Divergence Confluence 🔴 (TP @ Floor ${trade_custom_tp:.4f})"
                    print(f"[DUAL DIVERGENCE AUTO-SELL] {symbol} RSI+CCI Bearish Divergence in 4H Downtrend | TP Target: ${trade_custom_tp:.4f} 🔴", flush=True)

            # Channel 3: ICT Turtle Soup Liquidity Sweep & Automated Potato S&R Bounce
            elif "SWEEP_SUPPORT_CONFIRMED" in potato_state or "TAPPING_SUPPORT_FLOOR" in potato_state:
                # Tapped/Swept Floor -> MUST check if 4H Macro is UPTREND
                smc_4h_ok, smc_bias_desc = check_4h_smc_bias(symbol, 'BUY')
                if smc_4h_ok:
                    action = 'BUY'
                    trade_custom_tp = potato_info.get('resistance') # Target: Resistance Ceiling 🧱
                    trade_custom_sl = potato_info.get('support', 0) * 0.995 # SL: 0.5% below floor
                    is_sweep = "SWEEP_SUPPORT_CONFIRMED" in potato_state
                    of_desc = f"🛡️ {'ICT Turtle Soup Liquidity Grab' if is_sweep else 'Potato Floor Bounce'} -> TP at Ceiling (${trade_custom_tp:.4f})"
                    print(f"[POTATO S&R {'TURTLE SOUP SWEEP' if is_sweep else 'AUTO-BUY'}] {symbol} @ Floor in 4H Uptrend | TP Target: ${trade_custom_tp:.4f} (Ceiling) 🟢", flush=True)
                else:
                    print(f"[POTATO S&R SKIPPED] {symbol} tapped Floor @ ${potato_info.get('support', 0):.4f} but 4H Macro is Downtrend (Avoid Falling Knife) 🛑", flush=True)

            elif "SWEEP_RESISTANCE_CONFIRMED" in potato_state or "TAPPING_RESISTANCE_CEILING" in potato_state:
                # Tapped/Swept Ceiling -> MUST check if 4H Macro is DOWNTREND
                smc_4h_ok, smc_bias_desc = check_4h_smc_bias(symbol, 'SELL')
                if smc_4h_ok:
                    action = 'SELL'
                    trade_custom_tp = potato_info.get('support') # Target: Support Floor 🛡️
                    trade_custom_sl = potato_info.get('resistance', 0) * 1.005 # SL: 0.5% above ceiling
                    is_sweep = "SWEEP_RESISTANCE_CONFIRMED" in potato_state
                    of_desc = f"🧱 {'ICT Turtle Soup Liquidity Grab' if is_sweep else 'Potato Ceiling Bounce'} -> TP at Floor (${trade_custom_tp:.4f})"
                    print(f"[POTATO S&R {'TURTLE SOUP SWEEP' if is_sweep else 'AUTO-SELL'}] {symbol} @ Ceiling in 4H Downtrend | TP Target: ${trade_custom_tp:.4f} (Floor) 🔴", flush=True)
                else:
                    print(f"[POTATO S&R SKIPPED] {symbol} tapped Ceiling @ ${potato_info.get('resistance', 0):.4f} but 4H Macro is Uptrend (Avoid Shorting Bull Trend) 🛑", flush=True)

        # Minimum Structural 1.8 R:R Clearance Gate
        if action != 'NO TRADE' and trade_custom_tp and trade_custom_sl:
            calc_ref_price = fib_info.get('entry_price', last_price) if (fib_info.get('is_setup') and action == fib_info.get('side')) else last_price
            risk_d = abs(calc_ref_price - trade_custom_sl)
            reward_d = abs(trade_custom_tp - calc_ref_price)
            rr_ratio = reward_d / (risk_d + 1e-9)
            if rr_ratio < 1.8:
                print(f"[FILTERED R:R RATIO] {symbol} {action} cancelled: Structural R:R {rr_ratio:.2f} < 1.8x minimum requirement.", flush=True)
                action = 'NO TRADE'

        # 👑 BTC Master Beta Filter & 🔒 6% Portfolio Margin Cap Confirmation
        if action != 'NO TRADE' and symbol != 'BTCUSDT':
            btc_ok, btc_desc = check_btc_macro_health(action)
            if not btc_ok:
                print(f"[FILTERED BTC MASTER] {symbol} {action} cancelled: {btc_desc}", flush=True)
                action = 'NO TRADE'

        if action != 'NO TRADE' and self.live_trading:
            usdt_bal = get_binance_futures_usdt_balance()
            est_margin = usdt_bal * self.margin_pct
            port_ok, port_desc = check_portfolio_risk_capacity(usdt_bal, est_margin, max_portfolio_margin_pct=0.06)
            if not port_ok:
                print(f"[FILTERED PORTFOLIO CAP] {symbol} {action} cancelled: {port_desc}", flush=True)
                action = 'NO TRADE'

        last_price = df['close'].iloc[-1]
        timestamp = df.index[-1] if isinstance(df.index[-1], str) else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        entry = {
            'symbol': symbol,
            'timestamp': timestamp,
            'price': last_price,
            'consensus': max_consensus,
            'weighted_score': weighted_score,
            'bull': bull_count,
            'bear': bear_count,
            'neutral': neutral_count,
            'agreement_pct': round(agreement_pct, 1),
            'action': action,
            'threshold': self.threshold,
            'is_trade': action != 'NO TRADE',
            'of_desc': of_desc if 'of_desc' in locals() else 'Delta Confirmed'
        }
        self.ledger.append(entry)
        self.latest_model_states[symbol] = entry

        if entry['is_trade'] and self.last_notified_bars.get(symbol) != timestamp:
            self.last_notified_bars[symbol] = timestamp

            order_result = None
            if self.live_trading:
                atr_val = self.calc_atr(df, 14).iloc[-1] if len(df) >= 14 else (last_price * 0.005)
                order_result = place_binance_futures_market_order(
                    symbol=symbol,
                    side=action,
                    trade_usdt=self.trade_usdt,
                    margin_pct=self.margin_pct,
                    sizing_mode=self.sizing_mode,
                    last_price=last_price,
                    leverage=self.leverage,
                    atr=atr_val,
                    custom_tp=trade_custom_tp,
                    custom_sl=trade_custom_sl
                )

            ob_info = {'ratio': ob_ratio if 'ob_ratio' in locals() else 1.0}
            sent = send_telegram_alert(entry, order_info=order_result, ob_info=ob_info)
            if sent:
                print(f"[TELEGRAM ALERT] {action} for {symbol} @ ${last_price:,.4f} ({max_consensus}/31 models | Score: {weighted_score:.1f})")

        return entry

    def fetch_binance_klines(self, symbol="XRPUSDT", interval=None, limit=100):
        if interval is None:
            interval = self.timeframe
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=5)
            if r.status_code == 200:
                raw = r.json()
                data = []
                dates = []
                for k in raw:
                    ts = datetime.fromtimestamp(k[0]/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    dates.append(ts)
                    data.append({
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5])
                    })
                return pd.DataFrame(data, index=dates)
        except Exception:
            pass
        return None

    def start_telegram_command_listener(self):
        """Interactive Telegram Command & Control (C2) Listener with 1-Tap Inline Buttons"""
        if not TELEGRAM_BOT_TOKEN:
            return

        last_update_id = 0
        print("[TELEGRAM C2] Interactive Telegram 1-Tap Control Active.")

        def poll_telegram_updates():
            nonlocal last_update_id
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            while True:
                try:
                    params = {"offset": last_update_id + 1, "timeout": 10}
                    r = requests.get(url, params=params, timeout=12)
                    if r.status_code == 200:
                        data = r.json()
                        for update in data.get("result", []):
                            last_update_id = update["update_id"]

                            # 1. Handle Inline Button Clicks
                            if "callback_query" in update:
                                cb = update["callback_query"]
                                sender_id = str(cb.get("from", {}).get("id", ""))
                                message_chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                                if TELEGRAM_CHAT_ID and sender_id != str(TELEGRAM_CHAT_ID) and message_chat_id != str(TELEGRAM_CHAT_ID):
                                    continue

                                cmd = cb.get("data", "")
                                cb_id = cb.get("id")
                                try:
                                    requests.post(
                                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                                        json={"callback_query_id": cb_id},
                                        timeout=3
                                    )
                                except Exception:
                                    pass
                                if cmd:
                                    self.handle_telegram_command(cmd)

                            # 2. Handle Text Messages
                            elif "message" in update:
                                message = update.get("message", {})
                                sender_id = str(message.get("from", {}).get("id", ""))
                                chat_id = str(message.get("chat", {}).get("id", ""))
                                if TELEGRAM_CHAT_ID and sender_id != str(TELEGRAM_CHAT_ID) and chat_id != str(TELEGRAM_CHAT_ID):
                                    continue

                                text = message.get("text", "").strip()
                                if text:
                                    self.handle_telegram_command(text)
                except Exception:
                    pass
                time.sleep(1.5)

        t = threading.Thread(target=poll_telegram_updates, daemon=True)
        t.start()

    def handle_telegram_command(self, text):
        cmd = text.split()[0].lower()
        parts = text.split()

        if cmd in ['/start', '/help', '/menu']:
            help_msg = (
                f"🤖 <b>WEATHER-ENSEMBLE AI 30X RECOVERY C2 MENU</b>\n\n"
                f"Use the 1-tap buttons below or type commands:\n"
                f"• <b>/status</b> - View live balance, leverage & engine state.\n"
                f"• <b>/positions</b> - View all active Binance Futures open positions & PnL.\n"
                f"• <b>/circuit</b> - View daily circuit breaker & drawdown status.\n"
                f"• <b>/clean</b> - Manually purge leftover/orphaned Stop Loss & TP orders.\n"
                f"• <b>/closeall</b> - Emergency market close all open futures positions.\n"
                f"• <b>/tf &lt;1m|3m|5m|15m|1h|4h&gt;</b> - Change execution timeframe.\n"
                f"• <b>/models</b> - Real-time consensus breakdown for all 19 coins.\n"
                f"• <b>/margin N</b> - Set capital risk percentage (e.g. <code>/margin 3</code>).\n"
                f"• <b>/leverage N</b> - Set leverage multiplier (e.g. <code>/leverage 50</code>).\n"
                f"• <b>/maxpos N</b> - Set max concurrent positions (e.g. <code>/maxpos 2</code>).\n"
                f"• <b>/threshold N</b> - Set consensus threshold (e.g. <code>/threshold 30</code>)."
            )
            send_telegram_msg(help_msg, reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/tf':
            if len(parts) > 1 and parts[1].lower() in ['1m', '3m', '5m', '15m', '30m', '1h', '4h']:
                self.timeframe = parts[1].lower()
                send_telegram_msg(f"⏱️ <b>EXECUTION TIMEFRAME SWITCHED</b>\n\nBot is now scanning <b>{self.timeframe.upper()}</b> bars for high-confluence setups!", reply_markup=get_telegram_inline_keyboard())
            else:
                send_telegram_msg(f"ℹ️ Current Execution Timeframe: <b>{self.timeframe.upper()}</b>\nUsage: <code>/tf 15m</code> (Supported: 1m, 3m, 5m, 15m, 1h, 4h)", reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/status':
            usdt_bal = get_binance_futures_usdt_balance()
            status_str = "PAUSED ⏸️" if self.paused else ("CIRCUIT TRIPPED 🛑" if CIRCUIT_BREAKER.circuit_tripped else "ACTIVE 🟢")
            mode_str = "REAL BINANCE FUTURES" if self.live_trading else "PAPER MONITOR"
            active_cnt = get_binance_futures_open_positions_count()

            msg = (
                f"📊 <b>ENGINE STATUS & WALLET REPORT</b>\n\n"
                f"<b>Engine State:</b> {status_str}\n"
                f"<b>Trading Mode:</b> {mode_str}\n"
                f"<b>Binance Futures USDT Balance:</b> ${usdt_bal:,.2f}\n"
                f"<b>Open Positions:</b> {active_cnt} / {self.max_active_positions}\n"
                f"<b>Position Sizing:</b> {self.margin_pct * 100:.1f}% Capital (${usdt_bal * self.margin_pct:,.2f} Margin @ {self.leverage}x)\n"
                f"<b>Current Consensus Threshold:</b> ≥ <b>{self.threshold} / 31 Models</b>\n"
                f"<b>Circuit Breaker Status:</b> {'🛑 TRIPPED' if CIRCUIT_BREAKER.circuit_tripped else '🟢 HEALTHY'}\n"
                f"<b>Monitored Assets:</b> {len(OPTIMIZED_SYMBOLS)} Micro-Lot Symbols\n"
                f"<b>Timestamp:</b> {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
            )
            send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/positions':
            positions = get_binance_futures_positions()
            if not positions:
                send_telegram_msg("ℹ️ <b>No open Binance Futures positions.</b>", reply_markup=get_telegram_inline_keyboard())
            else:
                lines = [f"📈 <b>OPEN BINANCE FUTURES POSITIONS ({len(positions)})</b>\n"]
                for p in positions:
                    emoji = "🟢 LONG" if p['side'] == 'LONG' else "🔴 SHORT"
                    pnl_color = "+" if p['unrealizedProfit'] >= 0 else ""
                    lines.append(
                        f"• <b>#{p['symbol']}</b> {emoji} ({p['leverage']}x)\n"
                        f"  Size: {p['positionAmt']} | Entry: ${p['entryPrice']:,.4f}\n"
                        f"  Mark: ${p['markPrice']:,.4f} | Liq: ${p['liquidationPrice']:,.4f}\n"
                        f"  Unrealized PnL: <b>{pnl_color}${p['unrealizedProfit']:,.2f} USDT</b>\n"
                    )
                send_telegram_msg("\n".join(lines), reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/circuit':
            bal = get_binance_futures_usdt_balance()
            CIRCUIT_BREAKER.check_and_update(bal)
            trip_str = f"🛑 <b>TRIPPED</b> ({CIRCUIT_BREAKER.trip_reason})" if CIRCUIT_BREAKER.circuit_tripped else "🟢 <b>NORMAL / SAFE</b>"
            msg = (
                f"🛡️ <b>CIRCUIT BREAKER & RISK REPORT</b>\n\n"
                f"<b>Status:</b> {trip_str}\n"
                f"<b>Daily Starting Balance:</b> ${CIRCUIT_BREAKER.daily_start_balance or bal:,.2f}\n"
                f"<b>Current Balance:</b> ${bal:,.2f}\n"
                f"<b>Today's Realized PnL:</b> ${CIRCUIT_BREAKER.realized_pnl_today:+,.2f}\n"
                f"<b>Max Daily Loss Gate:</b> -{CIRCUIT_BREAKER.max_daily_loss_pct * 100:.1f}%\n"
                f"<b>Consecutive Losses:</b> {CIRCUIT_BREAKER.consecutive_losses} / {CIRCUIT_BREAKER.max_consecutive_losses}\n"
                f"<i>(Send <code>/circuit reset</code> to manually unblock)</i>"
            )
            if len(parts) > 1 and parts[1].lower() == 'reset':
                CIRCUIT_BREAKER.reset_circuit(bal)
                send_telegram_msg("✅ <b>Circuit breaker reset. Trading restored!</b>", reply_markup=get_telegram_inline_keyboard())
            else:
                send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard())

        elif cmd in ['/clean', '/cleanup', '/purge']:
            cleaned = cleanup_orphaned_orders()
            if cleaned > 0:
                send_telegram_msg(f"🧹 <b>Purge Complete!</b> Cleaned {cleaned} orphaned orders.", reply_markup=get_telegram_inline_keyboard())
            else:
                send_telegram_msg("✨ <b>No orphaned orders found.</b> All open orders match active positions!", reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/closeall':
            results = close_all_binance_futures_positions()
            cleanup_orphaned_orders()
            send_telegram_msg(f"🛑 <b>Emergency Close All executed!</b> Closed {len(results)} positions.", reply_markup=get_telegram_inline_keyboard())

        elif cmd in ['/leverage', '/lev']:
            if len(parts) > 1 and parts[1].isdigit():
                val = int(parts[1])
                if 1 <= val <= 125:
                    self.leverage = val
                    send_telegram_msg(f"✅ <b>Leverage multiplier updated to {self.leverage}x!</b>", reply_markup=get_telegram_inline_keyboard())
                else:
                    send_telegram_msg("⚠️ Leverage must be between 1x and 125x.")
            else:
                send_telegram_msg(f"Current Leverage: <b>{self.leverage}x</b>", reply_markup=get_telegram_inline_keyboard())

        elif cmd in ['/mode', '/sizing']:
            if len(parts) > 1 and parts[1].lower() in ['notional', 'margin']:
                self.sizing_mode = parts[1].lower()
                send_telegram_msg(f"✅ <b>Sizing Mode updated to {self.sizing_mode.upper()}!</b>", reply_markup=get_telegram_inline_keyboard())
            else:
                send_telegram_msg("Usage: <code>/mode notional</code> or <code>/mode margin</code>")

        elif cmd in ['/margin', '/risk']:
            if len(parts) > 1:
                try:
                    val = float(parts[1])
                    if 0 < val <= 100:
                        self.margin_pct = val / 100.0
                        send_telegram_msg(f"✅ <b>Position Risk updated to {self.margin_pct * 100:.1f}%!</b>", reply_markup=get_telegram_inline_keyboard())
                except ValueError:
                    send_telegram_msg("Usage: <code>/margin 20</code>")

        elif cmd in ['/maxpos', '/maxpositions', '/slots']:
            if len(parts) > 1 and parts[1].isdigit():
                val = int(parts[1])
                if 1 <= val <= 20:
                    self.max_active_positions = val
                    send_telegram_msg(f"✅ <b>Max Active Positions updated to {self.max_active_positions}!</b>", reply_markup=get_telegram_inline_keyboard())
                else:
                    send_telegram_msg("⚠️ Max active positions must be between 1 and 20.")
            else:
                send_telegram_msg(f"ℹ️ Current Max Active Positions: <b>{self.max_active_positions}</b>\nUsage: <code>/maxpos 2</code>", reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/models':
            lines = ["<b>31-MODEL REAL-TIME CONSENSUS MATRIX</b>\n"]
            for sym, data in self.latest_model_states.items():
                emoji = "🟢 BUY" if data['action'] == 'BUY' else "🔴 SELL" if data['action'] == 'SELL' else "⚪ Hold"
                lines.append(f"• <b>{sym}</b>: ${data['price']:,.4f} | <b>{data['consensus']}/31</b> ({data['bull']}B/{data['bear']}B) | {emoji}")
            send_telegram_msg("\n".join(lines), reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/threshold':
            if len(parts) > 1 and parts[1].isdigit():
                val = int(parts[1])
                if 20 <= val <= 31:
                    self.threshold = val
                    send_telegram_msg(f"✅ <b>Consensus Threshold updated to {self.threshold} / 31 models!</b>", reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/pause':
            self.paused = True
            send_telegram_msg("⏸️ <b>Automated trade execution PAUSED.</b>", reply_markup=get_telegram_inline_keyboard())

        elif cmd == '/resume':
            self.paused = False
            send_telegram_msg("▶️ <b>Automated trade execution RESUMED!</b>", reply_markup=get_telegram_inline_keyboard())

    def run_multi_asset_live_loop(self, poll_interval=10):
        print(f"\n=======================================================")
        print(f" WEATHER-ENSEMBLE BINANCE FUTURES LIVE AGENT ACTIVE")
        print(f" Profile: 30x Fast Recovery Sizing (20% Margin @ 30x Leverage)")
        print(f" Protection: L2 Depth + Funding Rate + Orphaned Order Cleaner + Circuit Breaker")
        print(f" Monitored Universe: {', '.join(OPTIMIZED_SYMBOLS)}")
        print(f"=======================================================\n")

        self.start_telegram_command_listener()

        while True:
            try:
                # 1. Automated Orphaned Order Cleaner & Real-Time Breakeven Trailing Stop Daemon
                if self.live_trading:
                    cleanup_orphaned_orders()
                    manage_active_positions_breakeven()

                active_positions = get_binance_futures_positions() if self.live_trading else []
                active_symbols = set(p['symbol'] for p in active_positions if abs(float(p.get('positionAmt', 0.0))) > 0.0)
                active_count = len(active_symbols)

                for symbol in OPTIMIZED_SYMBOLS:
                    # 🛑 1 Position Per Symbol Maximum: Skip symbols that already have an active open position
                    if symbol in active_symbols:
                        continue

                    df = self.fetch_binance_klines(symbol=symbol)
                    if df is not None and len(df) >= 35:
                        res = self.evaluate_bar(df, symbol=symbol, active_count=active_count)
                        price = res['price']
                        consensus = res['consensus']
                        action = res['action']
                        t_str = res['timestamp']
                        
                        if action != 'NO TRADE':
                            active_symbols.add(symbol)
                            active_count += 1
                            print(f"[SIGNAL TRIGGERED] [{t_str}] [{symbol}] ${price:,.4f} | Consensus: {consensus}/31 | ACTION: {action}", flush=True)
                        else:
                            print(f"  [{t_str}] [{symbol}] ${price:,.4f} | Consensus: {consensus}/31 | Hold", flush=True)
                    
                    time.sleep(0.4)

                time.sleep(poll_interval)
            except Exception as e:
                print(f"[MAIN LOOP EXCEPTION RECOVERED] {e}", flush=True)
                time.sleep(3)

def get_divergence_status(symbol="XRPUSDT"):
    """Returns live RSI(14), CCI(20), and Dual Divergence State for symbol"""
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "5m", "limit": 45}
        r = requests.get(url, params=params, timeout=4)
        if r.status_code == 200:
            raw = r.json()
            data = [{'open': float(k[1]), 'high': float(k[2]), 'low': float(k[3]), 'close': float(k[4]), 'volume': float(k[5])} for k in raw]
            df = pd.DataFrame(data)
            div_state, bull_div, bear_div = WeatherEnsembleBot.calc_rsi_cci_divergence(df)
            closes = df['close'].values
            rsi = float(WeatherEnsembleBot.calc_rsi(pd.Series(closes), 14).iloc[-1])
            cci = float(WeatherEnsembleBot.calc_cci(df, 20).iloc[-1])
            return {
                'status': 'success',
                'symbol': symbol,
                'rsi_14': round(rsi, 2),
                'cci_20': round(cci, 2),
                'divergence_state': div_state,
                'bull_div': bull_div,
                'bear_div': bear_div
            }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}
    return {'status': 'error', 'error': 'Failed to fetch'}

# --------------------------------------------------------------------------
# CLI Entry Point
# --------------------------------------------------------------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Weather-Ensemble 31-Model Trading AI Bot')
    parser.add_argument('--live', action='store_true', help='Run live market monitor with Telegram alerts & C2')
    parser.add_argument('--trade-live', action='store_true', help='Execute REAL orders on Binance Futures')
    parser.add_argument('--usdt', type=float, default=None, help='Fixed order size in USDT')
    parser.add_argument('--margin-pct', type=float, default=0.03, help='Capital fraction (default 0.03 = 3%% margin)')
    parser.add_argument('--sizing-mode', type=str, choices=['notional', 'margin'], default='margin')
    parser.add_argument('--leverage', type=int, default=50, help='Leverage multiplier (default 50x)')
    parser.add_argument('--threshold', type=int, default=30, help='Consensus threshold (default 30/31)')
    parser.add_argument('--timeframe', type=str, default='15m', help='Execution timeframe (default 15m)')
    parser.add_argument('--max-positions', type=int, default=5, help='Max concurrent positions (default 5)')
    args = parser.parse_args()

    bot = WeatherEnsembleBot(
        consensus_threshold=args.threshold,
        live_trading=args.trade_live,
        trade_usdt=args.usdt,
        margin_pct=args.margin_pct,
        sizing_mode=args.sizing_mode,
        leverage=args.leverage,
        timeframe=args.timeframe,
        max_positions=args.max_positions
    )
    while True:
        try:
            bot.run_multi_asset_live_loop()
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped cleanly by user.", flush=True)
            break
        except Exception as e:
            print(f"\n[TOP LEVEL FATAL EXCEPTION] {e}", flush=True)
            import traceback
            traceback.print_exc()
            print("Restarting live loop in 5 seconds...", flush=True)
            time.sleep(5)
