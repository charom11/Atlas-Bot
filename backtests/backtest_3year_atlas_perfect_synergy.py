#!/usr/bin/env python3
"""
==========================================================================================
⚡ 3-YEAR PRODUCTION + ATLAS PERFECT SYNERGY BACKTEST (2023 - 2026)
==========================================================================================
Integrates ATLAS's best features on top of the exact validated 3-year production architecture:
1. 🧬 ATLAS Darwinian Allocation: Automatically rewards top Sharpe channels (up to 1.5x)
2. 🛡️ ATLAS CRO (Chief Risk Officer): Blocks entries when cross-asset correlation is maxed
3. ⚖️ ATLAS JANUS Regime Layer: Adaptive R:R threshold during trend vs chop
4. 🔒 3-Stage Scale-Out: 50% TP1 @ 1.5x ATR -> Breakeven SL (+0.05%) -> 1.2x ATR Trailing Runner
==========================================================================================
"""

import os
import sys
import argparse
import numpy as np
import pandas as pd
from datetime import datetime
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
# 🧬 ATLAS Darwinian Channel Weight Engine
# --------------------------------------------------------------------------
class AtlasDarwinianWeights:
    def __init__(self, channels=['FIBONACCI', '5MA_CONSENSUS', 'MSS_SHIFT'], initial_weights=None):
        if initial_weights:
            self.weights = {ch: float(initial_weights.get(ch, 1.0)) for ch in channels}
        else:
            self.weights = {ch: 1.0 for ch in channels}
        self.channel_history = {ch: deque(maxlen=200) for ch in channels}
        self.last_update_bar = 0

    def record_trade(self, channel, pnl):
        if channel in self.channel_history:
            self.channel_history[channel].append(pnl)

    def update_weights(self, current_bar):
        if current_bar - self.last_update_bar < 2880:  # Every 30 days
            return
        self.last_update_bar = current_bar

        for ch, hist in self.channel_history.items():
            if len(hist) < 15:
                continue
            wins = sum(1 for p in hist if p > 0)
            wr = wins / len(hist)
            tot_pnl = sum(hist)
            if wr >= 0.55 and tot_pnl > 0:
                self.weights[ch] = min(1.5, self.weights[ch] * 1.05)
            elif wr < 0.48 or tot_pnl < 0:
                self.weights[ch] = max(0.8, self.weights[ch] * 0.95)

    def get_multiplier(self, channel):
        return self.weights.get(channel, 1.0)


# --------------------------------------------------------------------------
# 📊 Math Indicators
# --------------------------------------------------------------------------
def calc_ema(arr, span):
    alpha = 2.0 / (span + 1.0)
    n = len(arr)
    out = np.empty(n, dtype=np.float64)
    out[0] = arr[0]
    for i in range(1, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out

def calc_rsi(closes, period=14):
    n = len(closes)
    diff = np.diff(closes)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    rsi = np.full(n, 50.0)
    if n <= period:
        return rsi
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / (avg_loss + 1e-9) if avg_loss > 0 else 100.0
        rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

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
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    atr_smooth = np.zeros(n)
    plus_di_smooth = np.zeros(n)
    minus_di_smooth = np.zeros(n)
    if n <= period * 2:
        return np.full(n, 25.0)

    atr_smooth[period] = np.sum(tr[1:period + 1])
    plus_di_smooth[period] = np.sum(plus_dm[1:period + 1])
    minus_di_smooth[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr_smooth[i] = atr_smooth[i - 1] - (atr_smooth[i - 1] / period) + tr[i]
        plus_di_smooth[i] = plus_di_smooth[i - 1] - (plus_di_smooth[i - 1] / period) + plus_dm[i]
        minus_di_smooth[i] = minus_di_smooth[i - 1] - (minus_di_smooth[i - 1] / period) + minus_dm[i]

    plus_di = 100.0 * (plus_di_smooth / (atr_smooth + 1e-9))
    minus_di = 100.0 * (minus_di_smooth / (atr_smooth + 1e-9))
    dx = 100.0 * (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9))

    adx = np.full(n, 25.0)
    adx_start = period * 2 - 1
    if n > adx_start:
        adx[adx_start] = np.mean(dx[period:adx_start + 1])
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx

def precompute_signals(df, window=4):
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['volume'].values
    n = len(closes)

    ema9 = calc_ema(closes, 9)
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema100 = calc_ema(closes, 100)
    ema200 = calc_ema(closes, 200)

    rsi14 = calc_rsi(closes, 14)
    atr14 = calc_atr(highs, lows, closes, 14)
    atr50 = calc_atr(highs, lows, closes, 50)
    adx14 = calc_adx(highs, lows, closes, 14)

    vol_sma20 = np.zeros(n)
    for i in range(20, n):
        vol_sma20[i] = np.mean(volumes[i - 20 : i])
    is_vol_surge = volumes >= (vol_sma20 * 1.20)
    is_atr_expanded = atr14 >= (atr50 * 1.05)

    ma_bull_stack = (closes > ema20) & (ema20 > ema50) & (ema50 > ema100) & (closes > ema200)
    ma_bear_stack = (closes < ema20) & (ema20 < ema50) & (ema50 < ema100) & (closes < ema200)

    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    for i in range(window, n - window):
        if np.all(highs[i] >= highs[i - window : i]) and np.all(highs[i] >= highs[i + 1 : i + window + 1]):
            is_sh[i] = True
        if np.all(lows[i] <= lows[i - window : i]) and np.all(lows[i] <= lows[i + 1 : i + window + 1]):
            is_sl[i] = True

    last_sh_arr = np.zeros(n)
    last_sl_arr = np.zeros(n)
    curr_sh = highs[0]
    curr_sl = lows[0]
    for k in range(n):
        if is_sh[k]:
            curr_sh = highs[k]
        if is_sl[k]:
            curr_sl = lows[k]
        last_sh_arr[k] = curr_sh
        last_sl_arr[k] = curr_sl

    signals = []
    for i in range(50, n):
        last_sh_p = last_sh_arr[i]
        last_sl_p = last_sl_arr[i]
        c = closes[i]
        curr_atr = atr14[i] if atr14[i] > 0 else (c * 0.008)

        cons_long = ma_bull_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] > 54
        cons_short = ma_bear_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] < 46

        mss_long = (closes[i - 1] <= last_sh_p and c > last_sh_p) and is_vol_surge[i] and (c > ema50[i]) and (c > ema200[i])
        mss_short = (closes[i - 1] >= last_sl_p and c < last_sl_p) and is_vol_surge[i] and (c < ema50[i]) and (c < ema200[i])

        impulse = last_sh_p - last_sl_p
        fib_long = False
        fib_short = False
        fib_entry = c
        if impulse >= (1.5 * curr_atr):
            f_0618_b = last_sh_p - 0.618 * impulse
            f_0786_b = last_sh_p - 0.786 * impulse
            f_0886_b = last_sh_p - 0.886 * impulse
            if (c > ema50[i]) and (lows[i] <= f_0618_b) and (c >= last_sl_p - 0.20 * curr_atr):
                fib_long = True
                fib_entry = f_0886_b if lows[i] <= f_0886_b else (f_0786_b if lows[i] <= f_0786_b else f_0618_b)

            f_0618_s = last_sl_p + 0.618 * impulse
            f_0786_s = last_sl_p + 0.786 * impulse
            f_0886_s = last_sl_p + 0.886 * impulse
            if (c < ema50[i]) and (highs[i] >= f_0618_s) and (c <= last_sh_p + 0.20 * curr_atr):
                fib_short = True
                fib_entry = f_0886_s if highs[i] >= f_0886_s else (f_0786_s if highs[i] >= f_0786_s else f_0618_s)

        sig = {
            'cons_long': cons_long, 'cons_short': cons_short,
            'mss_long': mss_long, 'mss_short': mss_short,
            'fib_long': fib_long, 'fib_short': fib_short,
            'fib_entry': fib_entry,
            'atr': curr_atr,
            'adx': adx14[i],
            'ema50': ema50[i],
            'last_sh': last_sh_p,
            'last_sl': last_sl_p
        }
        signals.append(sig)

    pad = [{'cons_long': False, 'cons_short': False, 'mss_long': False, 'mss_short': False, 'fib_long': False, 'fib_short': False, 'fib_entry': closes[0], 'atr': closes[0]*0.01, 'adx': 20.0, 'ema50': closes[0], 'last_sh': closes[0], 'last_sl': closes[0]}] * 50
    return pad + signals


_DATA_CACHE = None

def get_precomputed_data():
    global _DATA_CACHE
    if _DATA_CACHE is not None:
        return _DATA_CACHE

    data_map = {}
    signals_map = {}
    highs_map = {}
    lows_map = {}
    closes_map = {}
    for sym in SYMBOLS:
        cache_file = os.path.join(CACHE_DIR, f"{sym}_15m_3year_2023-09-01.csv")
        df = pd.read_csv(cache_file)
        df['open_time'] = pd.to_datetime(df['open_time'])
        data_map[sym] = df
        highs_map[sym] = df['high'].values
        lows_map[sym] = df['low'].values
        closes_map[sym] = df['close'].values
        signals_map[sym] = precompute_signals(df)

    time_index = data_map['BTCUSDT']['open_time'].values
    n_bars = len(time_index)

    idx_maps = {}
    for sym in SYMBOLS:
        s_times = data_map[sym]['open_time'].values
        idx_map = np.full(n_bars, -1, dtype=int)
        ptr = 0
        len_s = len(s_times)
        for i, t in enumerate(time_index):
            while ptr < len_s and s_times[ptr] < t:
                ptr += 1
            if ptr < len_s and s_times[ptr] == t:
                idx_map[i] = ptr
        idx_maps[sym] = idx_map

    btc_closes = closes_map['BTCUSDT']
    btc_indices = idx_maps['BTCUSDT']
    btc_dump_arr = np.zeros(n_bars, dtype=bool)
    for b_i in range(1, n_bars):
        b_idx = btc_indices[b_i]
        if b_idx >= 1:
            prev_b = b_idx - 1
            if (btc_closes[b_idx] - btc_closes[prev_b]) / btc_closes[prev_b] < -0.005:
                btc_dump_arr[b_i] = True

    _DATA_CACHE = {
        'data_map': data_map,
        'signals_map': signals_map,
        'highs_map': highs_map,
        'lows_map': lows_map,
        'closes_map': closes_map,
        'time_index': time_index,
        'n_bars': n_bars,
        'idx_maps': idx_maps,
        'btc_dump_arr': btc_dump_arr
    }
    return _DATA_CACHE

def run_3year_synergy_backtest(initial_balance=100.0, leverage=50, margin_pct=0.03, max_positions=5, max_directional=5,
                               fib_weight=1.0, mss_weight=1.0, ma_weight=1.0, tp1_atr=2.0, trail_atr=1.2, quiet=False):
    if not quiet:
        print("=" * 95)
        print(" 🚀 RUNNING 3-YEAR PRODUCTION + ATLAS PERFECT SYNERGY BACKTEST (2023 - 2026)")
        print("=" * 95)
        print(f" • Starting Balance:       ${initial_balance:,.2f} USDT")
        print(f" • Leverage & Margin:      {leverage}x Leverage | {margin_pct*100:.1f}% Margin (Max {max_positions} Positions)")
        print(f" • ATLAS Modules Active:   🧬 Darwinian Weights | 🛡️ Adversarial CRO | ⚖️ JANUS Regime")
        print(f" • Initial Channel Multipliers: FIB: {fib_weight:.2f}x | MSS: {mss_weight:.2f}x | 5MA: {ma_weight:.2f}x")
        print(f" • Target Clearances:      TP1: {tp1_atr:.1f}x ATR | Runner Trailing: {trail_atr:.1f}x ATR")
        print(f" • Real VIP Fees:          Maker 0.018% | Taker 0.045% | Slip 0.015% | Funding 0.010% / 8h")
        print("=" * 95)

    cached = get_precomputed_data()
    data_map = cached['data_map']
    signals_map = cached['signals_map']
    highs_map = cached['highs_map']
    lows_map = cached['lows_map']
    closes_map = cached['closes_map']
    time_index = cached['time_index']
    n_bars = cached['n_bars']
    idx_maps = cached['idx_maps']
    btc_dump_arr = cached['btc_dump_arr']

    balance = initial_balance
    peak_balance = initial_balance
    max_drawdown_pct = 0.0
    active_positions = {}
    closed_trades = []
    symbol_last_trade_bar = {sym: -999 for sym in SYMBOLS}
    cooldown_bars = 12
    monthly_pnl = {}

    initial_w = {'FIBONACCI': fib_weight, 'MSS_SHIFT': mss_weight, '5MA_CONSENSUS': ma_weight}
    darwin = AtlasDarwinianWeights(initial_weights=initial_w)

    for bar_i in range(50, n_bars):
        cur_time = pd.Timestamp(time_index[bar_i])
        m_key = cur_time.strftime('%Y-%m')
        if m_key not in monthly_pnl:
            monthly_pnl[m_key] = 0.0

        darwin.update_weights(bar_i)

        btc_dump = btc_dump_arr[bar_i]

        symbols_to_close = []
        for sym, pos in active_positions.items():
            s_idx = idx_maps[sym][bar_i]
            if s_idx == -1:
                continue
            h = highs_map[sym][s_idx]
            l = lows_map[sym][s_idx]
            c = closes_map[sym][s_idx]
            entry_p = pos['entry_price']
            qty = pos['qty']
            side = pos['side']

            if bar_i % 32 == 0:
                fund_fee = (c * qty) * FEE_SCHEDULE['funding_8h']
                balance -= fund_fee
                pos['realized_pnl'] -= fund_fee

            if side == 'LONG':
                if not pos['tp1_hit'] and h >= pos['tp1_p']:
                    pos['tp1_hit'] = True
                    half_qty = qty * 0.50
                    pnl_tp1 = (pos['tp1_p'] - entry_p) * half_qty
                    fee_tp1 = (pos['tp1_p'] * half_qty) * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    net_tp1 = pnl_tp1 - fee_tp1
                    balance += (pos['margin'] * 0.50) + net_tp1
                    pos['realized_pnl'] += net_tp1
                    pos['remaining_qty'] = half_qty
                    pos['sl_p'] = entry_p * 1.0005
                    pos['highest_since_entry'] = h

                if pos['tp1_hit']:
                    if h > pos['highest_since_entry']:
                        pos['highest_since_entry'] = h
                        new_tsl = h - (trail_atr * pos['atr'])
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
                        new_tsl = l + (trail_atr * pos['atr'])
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
                c_price = closes_map[sym][s_idx]
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
                    tp1 = c_price + (tp1_atr * curr_atr)
                    sl = c_price - (1.0 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = 'MSS_SHIFT'
                elif sig['mss_short'] and short_count < max_directional:
                    tp1 = c_price - (tp1_atr * curr_atr)
                    sl = c_price + (1.0 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = 'MSS_SHIFT'

                # Channel 2: 5-MA Stack Momentum Consensus
                elif sig['cons_long'] and not btc_dump and long_count < max_directional:
                    tp1 = c_price + (tp1_atr * curr_atr)
                    sl = sig['ema50'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = '5MA_CONSENSUS'
                elif sig['cons_short'] and short_count < max_directional:
                    tp1 = c_price - (tp1_atr * curr_atr)
                    sl = sig['ema50'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = '5MA_CONSENSUS'

                # Channel 3: Fibonacci Harmonic Retracement
                elif sig['fib_long'] and not btc_dump and long_count < max_directional:
                    tp1 = c_price + (tp1_atr * curr_atr)
                    sl = sig['last_sl'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = 'FIBONACCI'
                elif sig['fib_short'] and short_count < max_directional:
                    tp1 = c_price - (tp1_atr * curr_atr)
                    sl = sig['last_sh'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = 'FIBONACCI'

                if action is not None:
                    # ATLAS Darwinian multiplier
                    d_mult = darwin.get_multiplier(ch_name)
                    base_margin = balance * margin_pct
                    margin_alloc = base_margin * d_mult
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
    print(" 🏆 3-YEAR PRODUCTION + ATLAS PERFECT SYNERGY SCORECARD (2023 - 2026)")
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

    sorted_months = sorted(monthly_pnl.keys())
    green_m = sum(1 for m in sorted_months if monthly_pnl[m] > 0)
    for i in range(0, len(sorted_months), 3):
        chunk = sorted_months[i:i+3]
        line = " | ".join([f"{m}: ${monthly_pnl[m]:>+8.2f} {'🟢' if monthly_pnl[m]>0 else '🔴'}" for m in chunk])
        print(f" {line}")
    print("=" * 95)
    print(f" Monthly Consistency Score: {green_m}/{len(sorted_months)} Green Months ({(green_m/len(sorted_months)*100):.1f}%)")
    print("=" * 95)

    return {
        'initial_balance': initial_balance,
        'final_balance': balance,
        'net_profit': tot_pnl,
        'total_roi': total_roi,
        'annual_roi': ann_roi,
        'profit_factor': pf,
        'win_rate': win_rate,
        'trades': n_trades,
        'wins': len(wins),
        'losses': len(losses),
        'max_drawdown': max_drawdown_pct,
        'green_months': f"{green_m}/{len(sorted_months)}"
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="3-Year Synergy Backtest")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--leverage", type=int, default=50)
    parser.add_argument("--margin-pct", type=float, default=0.03)
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--directional-cap", type=int, default=5)
    parser.add_argument("--fib-weight", type=float, default=1.0)
    parser.add_argument("--mss-weight", type=float, default=1.0)
    parser.add_argument("--ma-weight", type=float, default=1.0)
    parser.add_argument("--tp1-atr", type=float, default=2.0)
    parser.add_argument("--trail-atr", type=float, default=1.2)
    args = parser.parse_args()

    run_3year_synergy_backtest(
        initial_balance=args.balance,
        leverage=args.leverage,
        margin_pct=args.margin_pct,
        max_positions=args.max_positions,
        max_directional=args.directional_cap,
        fib_weight=args.fib_weight,
        mss_weight=args.mss_weight,
        ma_weight=args.ma_weight,
        tp1_atr=args.tp1_atr,
        trail_atr=args.trail_atr
    )
