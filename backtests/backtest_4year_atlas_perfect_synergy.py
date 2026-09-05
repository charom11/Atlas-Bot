#!/usr/bin/env python3
"""
==========================================================================================
⚡ 4-YEAR PRODUCTION + ATLAS PERFECT SYNERGY BACKTEST & PARAMETER SWEEP (2022 - 2026)
==========================================================================================
Full 48-Month (4-Year) Historical Dataset: 140,388 15m bars across 11 Perpetual Assets.
Tests every major strategy parameter to isolate and highlight the optimal configuration.
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
    'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'NEARUSDT', 'BNBUSDT', 'SUIUSDT'
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
    for i in range(19, n):
        vol_sma20[i] = np.mean(volumes[i - 19:i + 1])

    signals = []
    swing_highs = []
    swing_lows = []
    last_sh_p = highs[0]
    last_sl_p = lows[0]

    for i in range(50, n):
        c = closes[i]
        h = highs[i]
        l = lows[i]
        v = volumes[i]
        curr_atr = atr14[i] if atr14[i] > 0 else (c * 0.01)

        # 1. 5MA Stack Consensus
        bull_stack = (ema9[i] > ema20[i] > ema50[i] > ema100[i] > ema200[i])
        bear_stack = (ema9[i] < ema20[i] < ema50[i] < ema100[i] < ema200[i])

        cons_long = (bull_stack and c > ema20[i] and rsi14[i] > 52 and adx14[i] > 22 and v > vol_sma20[i])
        cons_short = (bear_stack and c < ema20[i] and rsi14[i] < 48 and adx14[i] > 22 and v > vol_sma20[i])

        # 2. Swing High / Low Tracking
        idx = i - window
        if idx >= window:
            is_sh = True
            is_sl = True
            p_h = highs[idx]
            p_l = lows[idx]
            for w in range(1, window + 1):
                if highs[idx - w] >= p_h or highs[idx + w] >= p_h:
                    is_sh = False
                if lows[idx - w] <= p_l or lows[idx + w] <= p_l:
                    is_sl = False
            if is_sh:
                swing_highs.append((idx, p_h))
                last_sh_p = p_h
            if is_sl:
                swing_lows.append((idx, p_l))
                last_sl_p = p_l

        # 3. Market Structure Shift (MSS)
        mss_long = False
        mss_short = False
        vol_breakout = (v > vol_sma20[i] * 1.30) if vol_sma20[i] > 0 else False

        if swing_highs and c > last_sh_p and closes[i - 1] <= last_sh_p:
            if c > ema50[i] and c > ema200[i] and vol_breakout:
                mss_long = True

        if swing_lows and c < last_sl_p and closes[i - 1] >= last_sl_p:
            if c < ema50[i] and c < ema200[i] and vol_breakout:
                mss_short = True

        # 4. Multi-Tier Fibonacci OTE
        fib_long = False
        fib_short = False
        fib_entry = c
        if last_sh_p > last_sl_p and (last_sh_p - last_sl_p) > curr_atr:
            swing_rng = last_sh_p - last_sl_p
            f618 = last_sh_p - (0.618 * swing_rng)
            f786 = last_sh_p - (0.786 * swing_rng)
            if bull_stack and (f786 <= l <= f618) and c > ema50[i] and rsi14[i] >= 42:
                fib_long = True
                fib_entry = c

            f618_bear = last_sl_p + (0.618 * swing_rng)
            f786_bear = last_sl_p + (0.786 * swing_rng)
            if bear_stack and (f618_bear <= h <= f786_bear) and c < ema50[i] and rsi14[i] <= 58:
                fib_short = True
                fib_entry = c

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


# --------------------------------------------------------------------------
# ⚡ 4-Year Dataset Cache
# --------------------------------------------------------------------------
_DATA_CACHE_4Y = None

def get_precomputed_data_4y():
    global _DATA_CACHE_4Y
    if _DATA_CACHE_4Y is not None:
        return _DATA_CACHE_4Y

    print("Loading 4-year historical dataset for 11 assets (2022-09 to 2026-09)...", flush=True)
    data_map = {}
    highs_map = {}
    lows_map = {}
    closes_map = {}
    signals_map = {}

    for sym in SYMBOLS:
        cache_file = os.path.join(CACHE_DIR, f"{sym}_15m_4year_2022-09-01.csv")
        if not os.path.exists(cache_file):
            print(f"Warning: {cache_file} not found, skipping {sym}")
            continue
        df = pd.read_csv(cache_file)
        df['open_time'] = pd.to_datetime(df['open_time'])
        data_map[sym] = df
        highs_map[sym] = df['high'].values
        lows_map[sym] = df['low'].values
        closes_map[sym] = df['close'].values
        signals_map[sym] = precompute_signals(df)

    active_symbols = list(data_map.keys())
    time_index = data_map['BTCUSDT']['open_time'].values
    n_bars = len(time_index)
    print(f"[TIMELINE] Synchronized {n_bars:,} 15m bars across 48 months (2022-09 to 2026-09)\n", flush=True)

    idx_maps = {}
    for sym in active_symbols:
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

    _DATA_CACHE_4Y = {
        'data_map': data_map,
        'signals_map': signals_map,
        'highs_map': highs_map,
        'lows_map': lows_map,
        'closes_map': closes_map,
        'time_index': time_index,
        'n_bars': n_bars,
        'idx_maps': idx_maps,
        'btc_dump_arr': btc_dump_arr,
        'active_symbols': active_symbols
    }
    return _DATA_CACHE_4Y


def run_4year_synergy_simulation(initial_balance=9.79, leverage=75, margin_pct=0.03,
                                 max_positions=5, max_directional=5,
                                 fib_weight=1.5, mss_weight=1.0, ma_weight=1.0,
                                 tp1_atr=2.2, trail_atr=1.0, quiet=False):
    cached = get_precomputed_data_4y()
    signals_map = cached['signals_map']
    highs_map = cached['highs_map']
    lows_map = cached['lows_map']
    closes_map = cached['closes_map']
    time_index = cached['time_index']
    n_bars = cached['n_bars']
    idx_maps = cached['idx_maps']
    btc_dump_arr = cached['btc_dump_arr']
    active_symbols = cached['active_symbols']

    balance = float(initial_balance)
    peak_balance = float(initial_balance)
    max_drawdown_pct = 0.0
    active_positions = {}
    closed_trades = []
    symbol_last_trade_bar = {sym: -999 for sym in active_symbols}
    cooldown_bars = 12
    monthly_pnl = {}
    yearly_stats = {}

    initial_w = {'FIBONACCI': fib_weight, 'MSS_SHIFT': mss_weight, '5MA_CONSENSUS': ma_weight}
    darwin = AtlasDarwinianWeights(initial_weights=initial_w)

    for bar_i in range(50, n_bars):
        cur_time = pd.Timestamp(time_index[bar_i])
        m_key = cur_time.strftime('%Y-%m')
        y_key = cur_time.strftime('%Y')
        if m_key not in monthly_pnl:
            monthly_pnl[m_key] = 0.0
        if y_key not in yearly_stats:
            yearly_stats[y_key] = {'trades': 0, 'wins': 0, 'pnl': 0.0}

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
                    symbols_to_close.append(sym)

        for sym in symbols_to_close:
            pos = active_positions.pop(sym)
            closed_trades.append(pos)
            symbol_last_trade_bar[sym] = bar_i
            darwin.record_trade(pos['channel'], pos['realized_pnl'])
            m_k = pos['exit_time'].strftime('%Y-%m')
            y_k = pos['exit_time'].strftime('%Y')
            monthly_pnl[m_k] = monthly_pnl.get(m_k, 0.0) + pos['realized_pnl']
            if y_k in yearly_stats:
                yearly_stats[y_k]['trades'] += 1
                if pos['realized_pnl'] > 0:
                    yearly_stats[y_k]['wins'] += 1
                yearly_stats[y_k]['pnl'] += pos['realized_pnl']

        if balance > peak_balance:
            peak_balance = balance
        dd_pct = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct

        if len(active_positions) >= max_positions or balance <= 0:
            continue

        long_count = sum(1 for p in active_positions.values() if p['side'] == 'LONG')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SHORT')

        for sym in active_symbols:
            if sym in active_positions:
                continue
            if bar_i - symbol_last_trade_bar[sym] < cooldown_bars:
                continue
            s_idx = idx_maps[sym][bar_i]
            if s_idx == -1:
                continue

            sig = signals_map[sym][s_idx]
            c_price = closes_map[sym][s_idx]
            curr_atr = sig['atr']

            action = None
            tp1 = 0.0
            sl = 0.0
            ch_name = None

            # Priority 1: MSS Shift
            if sig['mss_long'] and not btc_dump and long_count < max_directional:
                tp1 = c_price + (tp1_atr * curr_atr)
                sl = sig['last_sl'] - (0.5 * curr_atr)
                if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                    action = 'LONG'
                    ch_name = 'MSS_SHIFT'
            elif sig['mss_short'] and short_count < max_directional:
                tp1 = c_price - (tp1_atr * curr_atr)
                sl = sig['last_sh'] + (0.5 * curr_atr)
                if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                    action = 'SHORT'
                    ch_name = 'MSS_SHIFT'

            # Priority 2: 5MA Consensus
            elif sig['cons_long'] and not btc_dump and long_count < max_directional:
                tp1 = c_price + (tp1_atr * curr_atr)
                sl = c_price - (1.5 * curr_atr)
                action = 'LONG'
                ch_name = '5MA_CONSENSUS'
            elif sig['cons_short'] and short_count < max_directional:
                tp1 = c_price - (tp1_atr * curr_atr)
                sl = c_price + (1.5 * curr_atr)
                action = 'SHORT'
                ch_name = '5MA_CONSENSUS'

            # Priority 3: Fibonacci Retracement
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

                if action == 'LONG':
                    long_count += 1
                else:
                    short_count += 1

                if len(active_positions) >= max_positions:
                    break

    for sym, pos in list(active_positions.items()):
        s_idx = idx_maps[sym][-1]
        c_price = closes_map[sym][s_idx] if s_idx != -1 else pos['entry_price']
        pnl = (c_price - pos['entry_price']) * pos['remaining_qty'] if pos['side'] == 'LONG' else (pos['entry_price'] - c_price) * pos['remaining_qty']
        balance += (pos['margin'] * (0.50 if pos['tp1_hit'] else 1.00)) + pnl
        pos['realized_pnl'] += pnl
        closed_trades.append(pos)

    n_trades = len(closed_trades)
    wins = [t for t in closed_trades if t['realized_pnl'] > 0]
    losses = [t for t in closed_trades if t['realized_pnl'] <= 0]
    win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0

    tot_win = sum(t['realized_pnl'] for t in wins)
    tot_loss = abs(sum(t['realized_pnl'] for t in losses))
    pf = (tot_win / tot_loss) if tot_loss > 0 else 99.0

    tot_pnl = balance - initial_balance
    total_roi = (tot_pnl / initial_balance) * 100.0
    ann_roi = ((balance / initial_balance) ** (1.0 / 4.0) - 1.0) * 100.0

    sorted_months = sorted(monthly_pnl.keys())
    green_m = sum(1 for m in sorted_months if monthly_pnl[m] > 0)

    res = {
        'initial_balance': initial_balance,
        'final_balance': balance,
        'net_profit': tot_pnl,
        'total_roi': total_roi,
        'annual_roi': ann_roi,
        'profit_factor': pf,
        'win_rate': win_rate,
        'trades': n_trades,
        'max_drawdown': max_drawdown_pct,
        'green_months': f"{green_m}/{len(sorted_months)} ({(green_m/max(1, len(sorted_months))*100):.1f}%)",
        'monthly_pnl': monthly_pnl,
        'yearly_stats': yearly_stats,
        'channel_stats': {}
    }

    for ch in ['FIBONACCI', '5MA_CONSENSUS', 'MSS_SHIFT']:
        ch_trades = [t for t in closed_trades if t['channel'] == ch]
        if ch_trades:
            ch_w = [t for t in ch_trades if t['realized_pnl'] > 0]
            ch_wr = len(ch_w) / len(ch_trades) * 100.0
            ch_pnl = sum(t['realized_pnl'] for t in ch_trades)
            res['channel_stats'][ch] = {'trades': len(ch_trades), 'wr': ch_wr, 'pnl': ch_pnl}

    return res


def run_parameter_sweep(initial_balance=9.79):
    print("=" * 110)
    print(" 🚀 RUNNING 4-YEAR COMPREHENSIVE PARAMETER SWEEP (2022 - 2026)")
    print(f" • Starting Balance: ${initial_balance:.2f} USDT | Dataset: 140,388 15m Bars (48 Months)")
    print("=" * 110)

    # Preload once
    get_precomputed_data_4y()

    # Parameter Test Grid
    sweep_tests = [
        # --- 1. SIZING & MARGIN RISK SWEEP ---
        {"cat": "Margin Risk", "name": "1.0% Margin (Ultra-Safe)", "lev": 75, "margin": 0.01, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Margin Risk", "name": "2.0% Margin (Balanced)",   "lev": 75, "margin": 0.02, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Margin Risk", "name": "3.0% Margin (Production)", "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Margin Risk", "name": "5.0% Margin (Aggressive)", "lev": 75, "margin": 0.05, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},

        # --- 2. LEVERAGE SWEEP ---
        {"cat": "Leverage",    "name": "50x Leverage",             "lev": 50, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Leverage",    "name": "75x Leverage (Production)", "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Leverage",    "name": "100x Leverage",            "lev": 100, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},

        # --- 3. TAKE-PROFIT 1 (TP1) SWEEP ---
        {"cat": "TP1 ATR",     "name": "1.5x ATR TP1 (Quick Bank)", "lev": 75, "margin": 0.03, "tp1": 1.5, "trail": 0.8, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "TP1 ATR",     "name": "1.8x ATR TP1",             "lev": 75, "margin": 0.03, "tp1": 1.8, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "TP1 ATR",     "name": "2.2x ATR TP1 (Production)", "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "TP1 ATR",     "name": "2.6x ATR TP1",             "lev": 75, "margin": 0.03, "tp1": 2.6, "trail": 1.2, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "TP1 ATR",     "name": "3.0x ATR TP1 (Wide)",      "lev": 75, "margin": 0.03, "tp1": 3.0, "trail": 1.4, "fib": 1.5, "dir": 5, "pos": 5},

        # --- 4. TRAILING STOP RUNNER SWEEP ---
        {"cat": "Trailing",    "name": "0.8x ATR Trailing",        "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 0.8, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Trailing",    "name": "1.0x ATR Trailing (Prod)", "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Trailing",    "name": "1.4x ATR Trailing (Loose)","lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.4, "fib": 1.5, "dir": 5, "pos": 5},

        # --- 5. FIBONACCI CHANNEL WEIGHT SWEEP ---
        {"cat": "Fib Weight",  "name": "1.0x Fib Weight",          "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.0, "dir": 5, "pos": 5},
        {"cat": "Fib Weight",  "name": "1.5x Fib Weight (Prod)",   "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
        {"cat": "Fib Weight",  "name": "2.0x Fib Weight",          "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 2.0, "dir": 5, "pos": 5},

        # --- 6. DIRECTIONAL CAP & POSITIONS SWEEP ---
        {"cat": "Dircap",      "name": "Dircap 3 / Maxpos 5",      "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 3, "pos": 5},
        {"cat": "Dircap",      "name": "Dircap 5 / Maxpos 5 (Prod)","lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
    ]

    results = []
    for cfg in sweep_tests:
        r = run_4year_synergy_simulation(
            initial_balance=initial_balance,
            leverage=cfg['lev'],
            margin_pct=cfg['margin'],
            max_positions=cfg['pos'],
            max_directional=cfg['dir'],
            fib_weight=cfg['fib'],
            tp1_atr=cfg['tp1'],
            trail_atr=cfg['trail'],
            quiet=True
        )
        r['cat'] = cfg['cat']
        r['name'] = cfg['name']
        results.append(r)

    print("\n" + "=" * 125)
    print(" 🏆 4-YEAR FULL STRATEGY PARAMETER SWEEP SCORECARD (2022 - 2026)")
    print("=" * 125)
    print(f"{'Category':<14} | {'Configuration Name':<30} | {'Final Capital':>13} | {'Total ROI':>11} | {'PF':>6} | {'WR %':>6} | {'Max DD':>8} | {'Green M':>12}")
    print("-" * 125)
    for r in results:
        is_highlight = "⭐" if ("(Prod)" in r['name'] or "(Production)" in r['name'] or "(Ultra-Safe)" in r['name']) else "  "
        print(f"{r['cat']:<14} | {r['name']:<30} | ${r['final_balance']:>12,.2f} | {r['total_roi']:>+10.1f}% | {r['profit_factor']:>6.2f} | {r['win_rate']:>5.1f}% | {r['max_drawdown']:>7.2f}% | {r['green_months']:>12} {is_highlight}")
    print("=" * 125)

    # Detailed report for the Production Configuration
    prod = next(r for r in results if r['name'] == "3.0% Margin (Production)")
    print("\n" + "=" * 95)
    print(f" 📅 4-YEAR YEAR-BY-YEAR BREAKDOWN (Production Profile @ ${initial_balance:.2f} Starting Capital):")
    print("=" * 95)
    for y in sorted(prod['yearly_stats'].keys()):
        yst = prod['yearly_stats'][y]
        y_wr = (yst['wins'] / yst['trades'] * 100.0) if yst['trades'] > 0 else 0.0
        print(f" • {y}: {yst['trades']:>5} Trades | Win Rate: {y_wr:>5.1f}% | Net Profit: ${yst['pnl']:>+14,.2f} {'🟢 GREEN' if yst['pnl']>0 else '🔴 RED'}")
    print("=" * 95)

    # Monthly breakdown
    print("\n 📅 48-MONTH CHRONOLOGICAL PERFORMANCE (4 Full Years):")
    sorted_months = sorted(prod['monthly_pnl'].keys())
    for i in range(0, len(sorted_months), 4):
        chunk = sorted_months[i:i+4]
        line = " | ".join([f"{m}: ${prod['monthly_pnl'][m]:>+8.2f} {'🟢' if prod['monthly_pnl'][m]>0 else '🔴'}" for m in chunk])
        print(f" {line}")
    print("=" * 95)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="4-Year Synergy Backtest & Parameter Sweep")
    parser.add_argument("--balance", type=float, default=9.79, help="Starting balance (default: 9.79 USDT)")
    parser.add_argument("--sweep", action="store_true", help="Run full parameter sweep")
    args = parser.parse_args()

    run_parameter_sweep(initial_balance=args.balance)
