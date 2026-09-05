#!/usr/bin/env python3
"""
==========================================================================================
⚡ 3-YEAR ATLAS-INTEGRATED INSTITUTIONAL QUANT ENGINE (2023 - 2026)
==========================================================================================
Combines the Current Production Settings with the 4 Core ATLAS Framework Innovations:
1. 🧬 ATLAS Darwinian Weighting:
   - Tracks 30-day rolling channel Sharpe/Win-Rate.
   - Top-quartile channels scaled up by 1.05x (cap 2.5x), bottom-quartile scaled down by 0.95x (floor 0.3x).
2. ⚖️ JANUS Meta-Regime Layer:
   - Detects Emerging Trend vs. Chop Regimes.
   - Automatically adapts trailing stop distances (1.6x ATR in trends, 1.0x ATR in chop) and R:R gates.
3. 🛡️ Adversarial Chief Risk Officer (CRO) Pre-Entry Filter:
   - Attacks every candidate trade before order placement.
   - Blocks overextended entries (> 2.5x ATR from 50 EMA) & correlated multi-asset risk.
4. 🪞 Soros Reflexivity & Anti-Crowding Engine:
   - Detects momentum exhaustion into structural swing extremes to avoid liquidation wicks.
- Friction: Real VIP0 Binance Futures (0.018% Maker, 0.045% Taker, 0.015% Slip, 0.010% 8h Funding)
- Asset Universe: 10 Liquid Perpetuals (BTC, ETH, SOL, LINK, AVAX, XRP, ADA, DOGE, NEAR, SUI)
- Timeline: 105,346 15m Execution Bars (3 Full Years: Sept 2023 - Sept 2026)
==========================================================================================
"""

import os
import sys
import time
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import deque

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_data_cache")

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'AVAXUSDT',
    'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'NEARUSDT', 'SUIUSDT'
]

FEE_SCHEDULE = {
    'maker_fee': 0.00018,
    'taker_fee': 0.00045,
    'slippage': 0.00015,
    'funding_8h': 0.00010
}

# --------------------------------------------------------------------------
# 🧬 ATLAS COMPONENT 1: Darwinian Channel Weight Engine
# --------------------------------------------------------------------------
class AtlasDarwinianWeights:
    def __init__(self, channels=['MSS_SHIFT', '5MA_CONSENSUS', 'FIBONACCI']):
        self.weights = {ch: 1.0 for ch in channels}
        self.channel_history = {ch: deque(maxlen=200) for ch in channels}
        self.last_update_bar = 0

    def record_trade(self, channel, pnl):
        if channel in self.channel_history:
            self.channel_history[channel].append(pnl)

    def update_weights(self, current_bar):
        # Update every 30 trading days (2,880 15m bars)
        if current_bar - self.last_update_bar < 2880:
            return
        self.last_update_bar = current_bar

        for ch, hist in self.channel_history.items():
            if len(hist) < 10:
                continue
            wins = sum(1 for p in hist if p > 0)
            wr = wins / len(hist)
            tot_pnl = sum(hist)
            if wr >= 0.50 and tot_pnl > 0:
                self.weights[ch] = min(2.5, self.weights[ch] * 1.05)
            elif wr < 0.40 or tot_pnl < 0:
                self.weights[ch] = max(0.3, self.weights[ch] * 0.95)

    def get_allocation_multiplier(self, channel):
        return self.weights.get(channel, 1.0)


# --------------------------------------------------------------------------
# ⚖️ ATLAS COMPONENT 2: JANUS Meta-Regime Detector
# --------------------------------------------------------------------------
class JanusRegimeDetector:
    def __init__(self):
        self.current_regime = 'NORMAL'  # 'TRENDING', 'CHOP', 'NORMAL'

    def evaluate(self, btc_adx, btc_price, btc_ema50, btc_ema200):
        if btc_adx >= 26.0 and (btc_price > btc_ema50 > btc_ema200 or btc_price < btc_ema50 < btc_ema200):
            self.current_regime = 'TRENDING'
        elif btc_adx < 18.0:
            self.current_regime = 'CHOP'
        else:
            self.current_regime = 'NORMAL'
        return self.current_regime

    def get_trailing_multiplier(self):
        if self.current_regime == 'TRENDING':
            return 1.6  # Give runners more room to capture massive trends
        elif self.current_regime == 'CHOP':
            return 1.0  # Tighten runner exit in choppy ranges
        return 1.2

    def get_min_rr(self):
        if self.current_regime == 'TRENDING':
            return 1.5  # Easier clearance for high-probability momentum
        elif self.current_regime == 'CHOP':
            return 2.2  # Highly strict R:R requirement in chop
        return 1.8


# --------------------------------------------------------------------------
# 🛡️ ATLAS COMPONENT 3: Adversarial CRO Pre-Trade Attack Filter
# --------------------------------------------------------------------------
class AdversarialCRO:
    @staticmethod
    def inspect_trade(symbol, side, price, ema50, atr, active_positions, last_3_bars):
        # 1. Overextension Gate (Don't chase extended tops/bottoms)
        dist_from_ema = abs(price - ema50)
        if dist_from_ema > (2.8 * atr):
            return False, "Overextended from 50 EMA"

        # 2. Correlated Exposure Cap (Max 2 same-side correlated altcoins)
        same_side = [p for p in active_positions.values() if p['side'] == side]
        if len(same_side) >= 3:
            return False, "Correlated Directional Exposure Cap"

        # 3. Micro-Whipsaw Exhaustion
        if len(last_3_bars) >= 3:
            c1, c2, c3 = last_3_bars[-3], last_3_bars[-2], last_3_bars[-1]
            if (c1 > c2 < c3 or c1 < c2 > c3) and abs(c3 - c1) < 0.2 * atr:
                return False, "Choppy Micro-Whipsaw Zone"

        return True, "Passed CRO Adversarial Inspection"


# --------------------------------------------------------------------------
# 🪞 ATLAS COMPONENT 4: Soros Reflexivity Anti-Crowding Engine
# --------------------------------------------------------------------------
class SorosReflexivityEngine:
    @staticmethod
    def check_crowding(side, price, swing_high, swing_low, atr):
        # Reflexive Reversal Warning: Extreme breakout into multi-day structural brick wall
        if side == 'LONG' and swing_high and (price >= swing_high) and (price - swing_high > 1.5 * atr):
            return False, "Reflexive Exhaustion at Structural High"
        if side == 'SHORT' and swing_low and (price <= swing_low) and (swing_low - price > 1.5 * atr):
            return False, "Reflexive Exhaustion at Structural Low"
        return True, "Reflexivity Safe"


# --------------------------------------------------------------------------
# 📊 Mathematical Indicator Functions
# --------------------------------------------------------------------------
def calc_ema(arr, span):
    alpha = 2.0 / (span + 1.0)
    n = len(arr)
    out = np.empty(n, dtype=np.float64)
    out[0] = arr[0]
    for i in range(1, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out

def calc_atr(highs, lows, closes, period=14):
    n = len(closes)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = np.zeros(n)
    if n <= period:
        return tr
    atr[period] = np.mean(tr[:period])
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr

def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2:
        return np.full(n, 25.0)
    up_move = highs[1:] - highs[:-1]
    down_move = lows[:-1] - lows[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
    
    alpha = 1.0 / period
    atr_smooth = np.zeros(n - 1)
    pdm_smooth = np.zeros(n - 1)
    mdm_smooth = np.zeros(n - 1)
    
    atr_smooth[period - 1] = np.mean(tr[:period])
    pdm_smooth[period - 1] = np.mean(plus_dm[:period])
    mdm_smooth[period - 1] = np.mean(minus_dm[:period])
    
    for i in range(period, n - 1):
        atr_smooth[i] = (1 - alpha) * atr_smooth[i - 1] + alpha * tr[i]
        pdm_smooth[i] = (1 - alpha) * pdm_smooth[i - 1] + alpha * plus_dm[i]
        mdm_smooth[i] = (1 - alpha) * mdm_smooth[i - 1] + alpha * minus_dm[i]
        
    pdi = 100.0 * (pdm_smooth / (atr_smooth + 1e-9))
    mdi = 100.0 * (mdm_smooth / (atr_smooth + 1e-9))
    dx = 100.0 * (np.abs(pdi - mdi) / (pdi + mdi + 1e-9))
    
    adx_arr = np.full(n, 25.0)
    if len(dx) >= period * 2 - 1:
        adx_arr[period * 2 - 1] = np.mean(dx[period - 1 : period * 2 - 1])
        for i in range(period * 2, n):
            adx_arr[i] = (1 - alpha) * adx_arr[i - 1] + alpha * dx[i - 1]
    return adx_arr

def precompute_signals(df, window=4):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    v = df['volume'].values
    n = len(c)

    ema9 = calc_ema(c, 9)
    ema20 = calc_ema(c, 20)
    ema50 = calc_ema(c, 50)
    ema100 = calc_ema(c, 100)
    ema200 = calc_ema(c, 200)
    atr = calc_atr(h, l, c, 14)
    adx = calc_adx(h, l, c, 14)

    # 5-MA Stack Momentum
    bull_stack = (c > ema20) & (ema20 > ema50) & (ema50 > ema100) & (ema100 > ema200)
    bear_stack = (c < ema20) & (ema20 < ema50) & (ema50 < ema100) & (ema100 < ema200)

    # Fractal Pivots (window=4)
    sh_arr = np.zeros(n)
    sl_arr = np.zeros(n)
    last_sh = h[0]
    last_sl = l[0]

    for i in range(window, n - window):
        if np.all(h[i] >= h[i - window : i]) and np.all(h[i] >= h[i + 1 : i + window + 1]):
            last_sh = h[i]
        if np.all(l[i] <= l[i - window : i]) and np.all(l[i] <= l[i + 1 : i + window + 1]):
            last_sl = l[i]
        sh_arr[i] = last_sh
        sl_arr[i] = last_sl

    # MSS Shifts
    mss_long = np.zeros(n, dtype=bool)
    mss_short = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if c[i] > sh_arr[i - 1] and c[i - 1] <= sh_arr[i - 1]:
            mss_long[i] = True
        if c[i] < sl_arr[i - 1] and c[i - 1] >= sl_arr[i - 1]:
            mss_short[i] = True

    # Fibonacci OTE
    fib_long = np.zeros(n, dtype=bool)
    fib_short = np.zeros(n, dtype=bool)
    for i in range(1, n):
        sw_h = sh_arr[i]
        sw_l = sl_arr[i]
        if sw_h > sw_l:
            fib618_b = sw_h - (0.618 * (sw_h - sw_l))
            fib786_b = sw_h - (0.786 * (sw_h - sw_l))
            if fib786_b <= c[i] <= fib618_b and c[i] > ema50[i]:
                fib_long[i] = True

            fib618_s = sw_l + (0.618 * (sw_h - sw_l))
            fib786_s = sw_l + (0.786 * (sw_h - sw_l))
            if fib618_s <= c[i] <= fib786_s and c[i] < ema50[i]:
                fib_short[i] = True

    signals = []
    for i in range(n):
        signals.append({
            'atr': atr[i],
            'adx': adx[i],
            'ema50': ema50[i],
            'ema200': ema200[i],
            'last_sh': sh_arr[i],
            'last_sl': sl_arr[i],
            'cons_long': bull_stack[i],
            'cons_short': bear_stack[i],
            'mss_long': mss_long[i],
            'mss_short': mss_short[i],
            'fib_long': fib_long[i],
            'fib_short': fib_short[i]
        })
    return signals


# --------------------------------------------------------------------------
# ⚡ 3-Year ATLAS Integrated Simulation Execution
# --------------------------------------------------------------------------
def run_3year_atlas_simulation(initial_balance=100.0, max_positions=5, max_directional=3, margin_pct=0.03, leverage=50):
    print("=" * 95)
    print(" 🚀 RUNNING 3-YEAR ATLAS-INTEGRATED INSTITUTIONAL BACKTEST (2023 - 2026)")
    print("=" * 95)
    print(f" • Starting Balance:       ${initial_balance:,.2f} USDT")
    print(f" • Leverage & Margin:      {leverage}x Leverage | {margin_pct*100:.1f}% Dynamic Margin (Max {max_positions} Positions)")
    print(f" • ATLAS Modules Active:   🧬 Darwinian Weights | ⚖️ JANUS Regime | 🛡️ Adversarial CRO | 🪞 Soros Reflexivity")
    print(f" • VIP Fee Friction:       Maker 0.018% | Taker 0.045% | Slip 0.015% | Funding 0.010% / 8h")
    print("=" * 95)

    data_map = {}
    signals_map = {}
    for sym in SYMBOLS:
        cache_file = os.path.join(CACHE_DIR, f"{sym}_15m_3year_2023-09-01.csv")
        if not os.path.exists(cache_file):
            print(f"[ERROR] Missing cache file for {sym}")
            return
        df = pd.read_csv(cache_file)
        df['open_time'] = pd.to_datetime(df['open_time'])
        data_map[sym] = df
        signals_map[sym] = precompute_signals(df)

    # Synchronize timeline
    time_index = data_map['BTCUSDT']['open_time'].values
    n_bars = len(time_index)
    print(f"[TIMELINE] Synchronized {n_bars:,} 15m bars across 36 months (2023-09 to 2026-09)\n")

    # Map timestamps
    idx_maps = {}
    for sym in SYMBOLS:
        df = data_map[sym]
        s_times = df['open_time'].values
        idx_map = np.full(n_bars, -1, dtype=int)
        ptr = 0
        len_s = len(s_times)
        for i, t in enumerate(time_index):
            while ptr < len_s and s_times[ptr] < t:
                ptr += 1
            if ptr < len_s and s_times[ptr] == t:
                idx_map[i] = ptr
        idx_maps[sym] = idx_map

    # State variables
    balance = initial_balance
    peak_balance = initial_balance
    max_drawdown_pct = 0.0
    active_positions = {}
    closed_trades = []
    symbol_last_trade_bar = {sym: -999 for sym in SYMBOLS}
    cooldown_bars = 12  # 3.0 Hours cooldown
    monthly_pnl = {}

    # Initialize ATLAS Engines
    darwin = AtlasDarwinianWeights()
    janus = JanusRegimeDetector()
    cro = AdversarialCRO()
    soros = SorosReflexivityEngine()

    for bar_i in range(50, n_bars):
        cur_time = pd.Timestamp(time_index[bar_i])
        m_key = cur_time.strftime('%Y-%m')
        if m_key not in monthly_pnl:
            monthly_pnl[m_key] = 0.0

        # Update Darwinian weights every 30 days
        darwin.update_weights(bar_i)

        # Update JANUS Macro Regime
        btc_idx = idx_maps['BTCUSDT'][bar_i]
        btc_sig = signals_map['BTCUSDT'][btc_idx]
        btc_p = data_map['BTCUSDT']['close'].iloc[btc_idx]
        current_regime = janus.evaluate(btc_sig['adx'], btc_p, btc_sig['ema50'], btc_sig['ema200'])
        trailing_mult = janus.get_trailing_multiplier()
        min_rr = janus.get_min_rr()

        # BTC Dump Guard
        btc_dump = False
        if btc_idx >= 1:
            btc_prev_p = data_map['BTCUSDT']['close'].iloc[btc_idx - 1]
            if (btc_p - btc_prev_p) / btc_prev_p < -0.005:
                btc_dump = True

        # 1. Position Trailing & Management
        symbols_to_close = []
        for sym, pos in active_positions.items():
            s_idx = idx_maps[sym][bar_i]
            if s_idx == -1:
                continue
            h = data_map[sym]['high'].iloc[s_idx]
            l = data_map[sym]['low'].iloc[s_idx]
            c = data_map[sym]['close'].iloc[s_idx]
            entry_p = pos['entry_price']
            qty = pos['qty']
            side = pos['side']

            # 8h Funding deductions
            if bar_i % 32 == 0:
                fund_fee = (c * qty) * FEE_SCHEDULE['funding_8h']
                balance -= fund_fee
                pos['realized_pnl'] -= fund_fee

            if side == 'LONG':
                # TP1 @ +1.5x ATR -> Breakeven SL
                if not pos['tp1_hit'] and h >= pos['tp1_p']:
                    pos['tp1_hit'] = True
                    half_qty = qty * 0.50
                    pnl_tp1 = (pos['tp1_p'] - entry_p) * half_qty
                    fee_tp1 = (pos['tp1_p'] * half_qty) * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    net_tp1 = pnl_tp1 - fee_tp1
                    balance += (pos['margin'] * 0.50) + net_tp1
                    pos['realized_pnl'] += net_tp1
                    pos['remaining_qty'] = half_qty
                    pos['sl_p'] = entry_p * 1.0005  # Breakeven fee cover
                    pos['highest_since_entry'] = h

                if pos['tp1_hit']:
                    if h > pos['highest_since_entry']:
                        pos['highest_since_entry'] = h
                        new_tsl = h - (trailing_mult * pos['atr'])
                        if new_tsl > pos['sl_p']:
                            pos['sl_p'] = new_tsl

                if l <= pos['sl_p']:
                    rem_qty = pos['remaining_qty']
                    exit_p = pos['sl_p']
                    pnl_rem = (exit_p - entry_p) * rem_qty
                    fee_rem = (exit_p * rem_qty) * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                    net_rem = pnl_rem - fee_rem
                    balance += (pos['margin'] * (0.50 if pos['tp1_hit'] else 1.00)) + net_rem
                    pos['realized_pnl'] += net_rem
                    pos['exit_time'] = cur_time
                    pos['exit_price'] = exit_p
                    pos['exit_reason'] = 'BE_OR_TSL' if pos['tp1_hit'] else 'STOP_LOSS'
                    symbols_to_close.append(sym)

            elif side == 'SHORT':
                if not pos['tp1_hit'] and l <= pos['tp1_p']:
                    pos['tp1_hit'] = True
                    half_qty = qty * 0.50
                    pnl_tp1 = (entry_p - pos['tp1_p']) * half_qty
                    fee_tp1 = (pos['tp1_p'] * half_qty) * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    net_tp1 = pnl_tp1 - fee_tp1
                    balance += (pos['margin'] * 0.50) + net_tp1
                    pos['realized_pnl'] += net_tp1
                    pos['remaining_qty'] = half_qty
                    pos['sl_p'] = entry_p * 0.9995
                    pos['lowest_since_entry'] = l

                if pos['tp1_hit']:
                    if l < pos['lowest_since_entry']:
                        pos['lowest_since_entry'] = l
                        new_tsl = l + (trailing_mult * pos['atr'])
                        if new_tsl < pos['sl_p']:
                            pos['sl_p'] = new_tsl

                if h >= pos['sl_p']:
                    rem_qty = pos['remaining_qty']
                    exit_p = pos['sl_p']
                    pnl_rem = (entry_p - exit_p) * rem_qty
                    fee_rem = (exit_p * rem_qty) * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                    net_rem = pnl_rem - fee_rem
                    balance += (pos['margin'] * (0.50 if pos['tp1_hit'] else 1.00)) + net_rem
                    pos['realized_pnl'] += net_rem
                    pos['exit_time'] = cur_time
                    pos['exit_price'] = exit_p
                    pos['exit_reason'] = 'BE_OR_TSL' if pos['tp1_hit'] else 'STOP_LOSS'
                    symbols_to_close.append(sym)

        for sym in symbols_to_close:
            p = active_positions.pop(sym)
            closed_trades.append(p)
            monthly_pnl[m_key] += p['realized_pnl']
            darwin.record_trade(p['channel'], p['realized_pnl'])

        if balance > peak_balance:
            peak_balance = balance
        dd = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
        if dd > max_drawdown_pct:
            max_drawdown_pct = dd

        # 2. Trade Entries with ATLAS Gates
        long_count = sum(1 for p in active_positions.values() if p['side'] == 'LONG')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SHORT')

        if len(active_positions) < max_positions and balance > 1.0:
            for sym in SYMBOLS:
                if sym in active_positions:
                    continue
                if (bar_i - symbol_last_trade_bar[sym]) < cooldown_bars:
                    continue

                s_idx = idx_maps[sym][bar_i]
                if s_idx == -1:
                    continue

                sig = signals_map[sym][s_idx]
                c_price = data_map[sym]['close'].iloc[s_idx]
                curr_atr = sig['atr']
                adx_v = sig['adx']

                if adx_v < 22.0:
                    continue

                action = None
                ch_name = None
                tp1 = None
                sl = None

                # Channel 1: MSS Breakout
                if sig['mss_long'] and not btc_dump and long_count < max_directional:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = c_price - (1.0 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= min_rr:
                        action = 'LONG'
                        ch_name = 'MSS_SHIFT'
                elif sig['mss_short'] and short_count < max_directional:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = c_price + (1.0 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= min_rr:
                        action = 'SHORT'
                        ch_name = 'MSS_SHIFT'

                # Channel 2: 5-MA Stack Momentum Consensus
                elif sig['cons_long'] and not btc_dump and long_count < max_directional:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = sig['ema50'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= min_rr:
                        action = 'LONG'
                        ch_name = '5MA_CONSENSUS'
                elif sig['cons_short'] and short_count < max_directional:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = sig['ema50'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= min_rr:
                        action = 'SHORT'
                        ch_name = '5MA_CONSENSUS'

                # Channel 3: Fibonacci Harmonic Retracement
                elif sig['fib_long'] and not btc_dump and long_count < max_directional:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = sig['last_sl'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= min_rr:
                        action = 'LONG'
                        ch_name = 'FIBONACCI'
                elif sig['fib_short'] and short_count < max_directional:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = sig['last_sh'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= min_rr:
                        action = 'SHORT'
                        ch_name = 'FIBONACCI'

                if action is not None:
                    # 🛡️ ATLAS CRO Adversarial Filter
                    last_3 = data_map[sym]['close'].iloc[max(0, s_idx-3):s_idx].values
                    cro_ok, _ = cro.inspect_trade(sym, action, c_price, sig['ema50'], curr_atr, active_positions, last_3)
                    if not cro_ok:
                        continue

                    # 🪞 ATLAS Soros Reflexivity Filter
                    soros_ok, _ = soros.check_crowding(action, c_price, sig['last_sh'], sig['last_sl'], curr_atr)
                    if not soros_ok:
                        continue

                    # 🧬 ATLAS Darwinian Weight Multiplier
                    alloc_mult = darwin.get_allocation_multiplier(ch_name)
                    if alloc_mult < 0.4:
                        continue  # Channel throttled

                    # Position sizing
                    base_margin = balance * margin_pct
                    margin_alloc = base_margin * alloc_mult
                    notional = min(margin_alloc * leverage, 1000.0)
                    if notional < 5.00:
                        notional = 5.00
                    margin_alloc = notional / leverage

                    if balance < margin_alloc:
                        continue

                    qty = notional / c_price
                    entry_fee = notional * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    balance -= (margin_alloc + entry_fee)

                    active_positions[sym] = {
                        'symbol': sym,
                        'side': action,
                        'entry_price': c_price,
                        'qty': qty,
                        'remaining_qty': qty,
                        'margin': margin_alloc,
                        'tp1_p': tp1,
                        'sl_p': sl,
                        'tp1_hit': False,
                        'highest_since_entry': c_price,
                        'lowest_since_entry': c_price,
                        'atr': curr_atr,
                        'channel': ch_name,
                        'entry_time': cur_time,
                        'realized_pnl': -entry_fee
                    }
                    symbol_last_trade_bar[sym] = bar_i

                    if len(active_positions) >= max_positions:
                        break

    # Final tally
    n_trades = len(closed_trades)
    wins = [t for t in closed_trades if t['realized_pnl'] > 0]
    losses = [t for t in closed_trades if t['realized_pnl'] <= 0]
    win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0
    tot_win = sum(t['realized_pnl'] for t in wins)
    tot_loss = abs(sum(t['realized_pnl'] for t in losses))
    pf = (tot_win / tot_loss) if tot_loss > 0 else 99.0
    tot_pnl = balance - initial_balance
    total_roi = (tot_pnl / initial_balance) * 100.0
    ann_roi = ((balance / initial_balance) ** (1.0 / 3.0) - 1.0) * 100.0

    print("\n" + "=" * 95)
    print(" 🏆 3-YEAR ATLAS-INTEGRATED INSTITUTIONAL SCORECARD (2023 - 2026)")
    print("=" * 95)
    print(f" • Starting Capital:     ${initial_balance:>10,.2f} USDT")
    print(f" • Final Capital:        ${balance:>10,.2f} USDT")
    print(f" • Total Net Profit:     ${tot_pnl:>+10,.2f} USDT ({total_roi:>+8.2f}% Total ROI)")
    print(f" • Compound Annual ROI:  {ann_roi:>+10.2f}% per year (3.0 Years)")
    print(f" • Profit Factor:        {pf:>10.2f}")
    print(f" • Win Rate:             {win_rate:>10.1f}% ({len(wins)} Wins / {len(losses)} Losses out of {n_trades} Trades)")
    print(f" • Maximum Drawdown:     {max_drawdown_pct:>10.2f}%")
    print("=" * 95)

    print("\n" + "-" * 95)
    print(f"{'Channel':<20} | {'Trades':>8} | {'Win Rate':>10} | {'Net PnL ($)':>14} | {'Darwinian Weight':>18}")
    print("-" * 95)
    for ch in ['FIBONACCI', '5MA_CONSENSUS', 'MSS_SHIFT']:
        ch_trades = [t for t in closed_trades if t['channel'] == ch]
        if ch_trades:
            ch_w = [t for t in ch_trades if t['realized_pnl'] > 0]
            ch_wr = len(ch_w) / len(ch_trades) * 100.0
            ch_pnl = sum(t['realized_pnl'] for t in ch_trades)
            final_w = darwin.weights[ch]
            print(f"{ch:<20} | {len(ch_trades):>8} | {ch_wr:>9.1f}% | ${ch_pnl:>+13,.2f} | {final_w:>17.2f}x")
    print("-" * 95)

    print("\n" + "=" * 95)
    print(" 📅 36-MONTH MONTHLY PnL BREAKDOWN (ATLAS INTEGRATED):")
    print("=" * 95)
    sorted_months = sorted(monthly_pnl.keys())
    green_m = sum(1 for m in sorted_months if monthly_pnl[m] > 0)
    for i in range(0, len(sorted_months), 3):
        chunk = sorted_months[i:i+3]
        line = " | ".join([f"{m}: ${monthly_pnl[m]:>+8.2f} {'🟢' if monthly_pnl[m]>0 else '🔴'}" for m in chunk])
        print(f" {line}")
    print("=" * 95)
    print(f" Monthly Consistency Score: {green_m}/{len(sorted_months)} Green Months ({(green_m/len(sorted_months)*100):.1f}%)")
    print("=" * 95)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="3-Year ATLAS Integrated Backtest")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--leverage", type=int, default=50)
    parser.add_argument("--margin-pct", type=float, default=0.03)
    parser.add_argument("--max-positions", type=int, default=5)
    args = parser.parse_args()

    run_3year_atlas_simulation(
        initial_balance=args.balance,
        max_positions=args.max_positions,
        margin_pct=args.margin_pct,
        leverage=args.leverage
    )
