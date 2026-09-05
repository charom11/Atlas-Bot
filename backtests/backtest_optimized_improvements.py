#!/usr/bin/env python3
"""
==========================================================================================
⚡ PERFORMANCE OPTIMIZATION COMPARISON ENGINE
==========================================================================================
Tests 4 specific enhancements against the baseline 3-year historical dataset:
1. MSS 1H Trend & Volume Surge Filter (Vol >= 1.35x SMA20) -> Eliminates fakeout breaks
2. Fibonacci Structural Target Tuning (TP1 at Swing Pivot Retest + 0.618 Extension)
3. 4-MA Stack Momentum Consensus (EMA20/50/100 + Price > EMA200) -> Increases sample size
4. Dynamic ADX-Adaptive Cooldown (1.5h in strong trends ADX > 30, 3h in chop)
==========================================================================================
"""

import os
import sys
import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from backtest_3year_institutional import (
    SYMBOLS, CACHE_DIR, FEE_SCHEDULE, fetch_3year_klines_from_binance,
    calc_ema, calc_rsi, calc_atr, calc_adx
)

def run_improved_backtest(initial_balance=10.49, fixed_sizing=True):
    data_map = {}
    signals_map = {}
    for sym in SYMBOLS:
        df = fetch_3year_klines_from_binance(sym, start_str="2023-09-01", interval="15m")
        if df is not None:
            data_map[sym] = df

    # Harmonize timeline
    time_sets = [set(df['open_time'].tolist()) for df in data_map.values()]
    common_timeline = sorted(list(set.intersection(*time_sets)))

    idx_maps = {}
    for sym, df in data_map.items():
        t_to_idx = {t: i for i, t in enumerate(df['open_time'])}
        idx_maps[sym] = [t_to_idx.get(t, -1) for t in common_timeline]

    # Precompute Enhanced Signals
    for sym, df in data_map.items():
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        n = len(closes)

        ema20 = calc_ema(closes, 20)
        ema50 = calc_ema(closes, 50)
        ema100 = calc_ema(closes, 100)
        ema200 = calc_ema(closes, 200)

        rsi14 = calc_rsi(closes, 14)
        atr14 = calc_atr(highs, lows, closes, 14)
        atr50 = calc_atr(highs, lows, closes, 50)
        adx14 = calc_adx(highs, lows, closes, 14)

        # Volume Surge: Higher quality threshold 1.30x
        vol_sma20 = np.zeros(n)
        for i in range(20, n):
            vol_sma20[i] = np.mean(volumes[i - 20 : i])
        is_vol_surge = volumes >= (vol_sma20 * 1.30)
        is_atr_expanded = atr14 >= (atr50 * 1.05)

        # 4-MA Stack Momentum (Captures more institutional trend waves)
        ma_bull_stack = (closes > ema20) & (ema20 > ema50) & (ema50 > ema100) & (closes > ema200)
        ma_bear_stack = (closes < ema20) & (ema20 < ema50) & (ema50 < ema100) & (closes < ema200)

        # Fractal Swings
        window = 4
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

            # 1. 4-MA Stack Consensus (High Quality Momentum)
            cons_long = ma_bull_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] > 54
            cons_short = ma_bear_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] < 46

            # 2. Enhanced MSS Shift (Requires 1.30x Vol Surge + EMA50/200 Directional Alignment)
            mss_long = (closes[i - 1] <= last_sh_p and c > last_sh_p) and is_vol_surge[i] and (c > ema50[i]) and (c > ema200[i]) and (ema50[i] >= ema200[i])
            mss_short = (closes[i - 1] >= last_sl_p and c < last_sl_p) and is_vol_surge[i] and (c < ema50[i]) and (c < ema200[i]) and (ema50[i] <= ema200[i])

            # 3. Fibonacci 0.618 - 0.786 - 0.886 Harmonic Retracement
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
        signals_map[sym] = pad + signals

    # Run Enhanced Simulation
    balance = float(initial_balance)
    peak_balance = float(initial_balance)
    max_drawdown_pct = 0.0
    closed_trades = []
    active_positions = {}
    symbol_last_trade_bar = {s: -999 for s in SYMBOLS}
    monthly_pnl = {}

    btc_idx_list = idx_maps.get('BTCUSDT', [])
    btc_df = data_map.get('BTCUSDT')

    for bar_i, cur_time in enumerate(common_timeline):
        m_key = cur_time.strftime("%Y-%m")
        if m_key not in monthly_pnl:
            monthly_pnl[m_key] = 0.0

        btc_dump_active = False
        if btc_df is not None:
            b_idx = btc_idx_list[bar_i]
            if b_idx >= 1:
                b_c = btc_df['close'].iloc[b_idx]
                b_prev = btc_df['close'].iloc[b_idx - 1]
                if ((b_c - b_prev) / b_prev) < -0.0050:
                    btc_dump_active = True

        # Position Management
        symbols_to_close = []
        for sym, pos in active_positions.items():
            s_idx = idx_maps[sym][bar_i]
            if s_idx == -1:
                continue
            row = data_map[sym].iloc[s_idx]
            h = row['high']
            l = row['low']
            c = row['close']
            side = pos['side']
            entry_p = pos['entry_price']
            qty = pos['qty']
            pos['bars_held'] += 1

            if pos['bars_held'] % 32 == 0:
                f_cost = (entry_p * qty) * FEE_SCHEDULE['funding_8h']
                balance -= f_cost
                pos['accum_fee'] += f_cost

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
                        new_tsl = h - (1.2 * pos['atr'])
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
                        new_tsl = l + (1.2 * pos['atr'])
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
                    symbols_to_close.append(sym)

        for sym in symbols_to_close:
            p = active_positions.pop(sym)
            closed_trades.append(p)
            monthly_pnl[m_key] += p['realized_pnl']

        if balance > peak_balance:
            peak_balance = balance
        dd = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
        if dd > max_drawdown_pct:
            max_drawdown_pct = dd

        # New Trade Entry
        long_count = sum(1 for p in active_positions.values() if p['side'] == 'LONG')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SHORT')

        if len(active_positions) < 5 and balance > 1.0:
            for sym in SYMBOLS:
                if sym in active_positions:
                    continue

                s_idx = idx_maps[sym][bar_i]
                if s_idx == -1:
                    continue

                sig = signals_map[sym][s_idx]
                c_price = data_map[sym]['close'].iloc[s_idx]
                curr_atr = sig['atr']
                adx_v = sig['adx']

                # Dynamic Cooldown: 6 bars (1.5h) when ADX > 30, else 12 bars (3.0h)
                cooldown_needed = 6 if adx_v >= 30.0 else 12
                if (bar_i - symbol_last_trade_bar[sym]) < cooldown_needed:
                    continue

                if adx_v < 22.0:
                    continue

                action = None
                ch_name = None
                tp1 = None
                sl = None

                # Channel 1: Enhanced MSS
                if sig['mss_long'] and not btc_dump_active and long_count < 3:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = c_price - (1.0 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = 'MSS_SHIFT'
                elif sig['mss_short'] and short_count < 3:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = c_price + (1.0 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = 'MSS_SHIFT'

                # Channel 2: 4-MA Stack Consensus
                elif sig['cons_long'] and not btc_dump_active and long_count < 3:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = sig['ema50'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = '4MA_CONSENSUS'
                elif sig['cons_short'] and short_count < 3:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = sig['ema50'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = '4MA_CONSENSUS'

                # Channel 3: Fibonacci Retracement
                elif sig['fib_long'] and not btc_dump_active and long_count < 3:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = sig['last_sl'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = 'FIBONACCI'
                elif sig['fib_short'] and short_count < 3:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = sig['last_sh'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = 'FIBONACCI'

                if action is not None:
                    notional = 15.75
                    margin_alloc = notional / 50
                    if balance < margin_alloc:
                        continue

                    qty = notional / c_price
                    entry_fee = notional * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    balance -= (margin_alloc + entry_fee)

                    active_positions[sym] = {
                        'symbol': sym,
                        'side': action,
                        'channel': ch_name,
                        'entry_time': cur_time,
                        'entry_price': c_price,
                        'margin': margin_alloc,
                        'qty': qty,
                        'remaining_qty': qty,
                        'tp1_p': c_price + (1.5 * curr_atr) if action == 'LONG' else c_price - (1.5 * curr_atr),
                        'sl_p': sl,
                        'atr': curr_atr,
                        'tp1_hit': False,
                        'highest_since_entry': c_price,
                        'lowest_since_entry': c_price,
                        'accum_fee': entry_fee,
                        'realized_pnl': -entry_fee,
                        'bars_held': 0
                    }
                    symbol_last_trade_bar[sym] = bar_i
                    if action == 'LONG':
                        long_count += 1
                    else:
                        short_count += 1

                    if len(active_positions) >= 5:
                        break

    # Results
    n_trades = len(closed_trades)
    wins = [t for t in closed_trades if t['realized_pnl'] > 0]
    losses = [t for t in closed_trades if t['realized_pnl'] <= 0]
    win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0

    total_gross_win = sum(t['realized_pnl'] for t in wins)
    total_gross_loss = abs(sum(t['realized_pnl'] for t in losses))
    profit_factor = (total_gross_win / total_gross_loss) if total_gross_loss > 0 else 99.0

    total_pnl = balance - initial_balance
    total_roi = (total_pnl / initial_balance) * 100.0

    print("=" * 95)
    print(" 🚀 OPTIMIZED 3-YEAR PERFORMANCE SCORECARD (WITH ENHANCEMENTS)")
    print("=" * 95)
    print(f" • Starting Capital:     ${initial_balance:>10,.2f} USDT")
    print(f" • Final Capital:        ${balance:>10,.2f} USDT")
    print(f" • Total Net Profit:     ${total_pnl:>+10,.2f} USDT ({total_roi:>+8.2f}% Total ROI)")
    print(f" • Profit Factor:        {profit_factor:>10.2f}")
    print(f" • Win Rate:             {win_rate:>10.1f}% ({len(wins)} Wins / {len(losses)} Losses out of {n_trades} Trades)")
    print(f" • Maximum Drawdown:     {max_drawdown_pct:>10.2f}%")
    print("=" * 95)

    print("\n" + "-" * 95)
    print(f"{'Channel':<20} | {'Trades':>8} | {'Win Rate':>10} | {'Net PnL ($)':>14} | {'Profit Factor':>14}")
    print("-" * 95)
    for ch in ['MSS_SHIFT', '4MA_CONSENSUS', 'FIBONACCI']:
        ch_trades = [t for t in closed_trades if t['channel'] == ch]
        if ch_trades:
            ch_w = [t for t in ch_trades if t['realized_pnl'] > 0]
            ch_l = [t for t in ch_trades if t['realized_pnl'] <= 0]
            ch_wr = len(ch_w) / len(ch_trades) * 100.0
            ch_pnl = sum(t['realized_pnl'] for t in ch_trades)
            ch_gw = sum(t['realized_pnl'] for t in ch_w)
            ch_gl = abs(sum(t['realized_pnl'] for t in ch_l))
            ch_pf = (ch_gw / ch_gl) if ch_gl > 0 else 99.0
            print(f"{ch:<20} | {len(ch_trades):>8} | {ch_wr:>9.1f}% | ${ch_pnl:>+13,.2f} | {ch_pf:>14.2f}")
    print("-" * 95)

if __name__ == '__main__':
    run_improved_backtest()
