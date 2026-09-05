#!/usr/bin/env python3
"""
Backtest Runner with Current Live Balance ($9.79 USDT)
Tests 1x, 2x, 3x risk tiers and timeframe comparisons with best tuned ATLAS settings.
"""

import os
import sys
import numpy as np
import pandas as pd
from collections import deque

# Import core backtest components from backtest_3year_atlas_perfect_synergy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtests'))
from backtest_3year_atlas_perfect_synergy import (
    CACHE_DIR, SYMBOLS, FEE_SCHEDULE, AtlasDarwinianWeights, precompute_signals
)

LIVE_BALANCE = 9.79  # Current live Binance Futures balance

def load_all_data():
    print(f"Loading 3-year historical dataset for 10 assets from {CACHE_DIR}...")
    data_map = {}
    highs_map = {}
    lows_map = {}
    closes_map = {}
    signals_map = {}
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
    print(f"Synchronized {n_bars:,} 15m bars across 36 months.\n")

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

    return {
        'time_index': time_index,
        'n_bars': n_bars,
        'highs_map': highs_map,
        'lows_map': lows_map,
        'closes_map': closes_map,
        'signals_map': signals_map,
        'idx_maps': idx_maps,
        'btc_dump_arr': btc_dump_arr
    }

def simulate_pass(data, initial_balance=9.79, leverage=75, margin_pct=0.03,
                  max_positions=5, max_directional=5, fib_weight=1.5,
                  mss_weight=1.0, ma_weight=1.0, tp1_atr=2.2, trail_atr=1.0,
                  start_bar_offset=0, label=""):
    time_index = data['time_index']
    n_bars = data['n_bars']
    highs_map = data['highs_map']
    lows_map = data['lows_map']
    closes_map = data['closes_map']
    signals_map = data['signals_map']
    idx_maps = data['idx_maps']
    btc_dump_arr = data['btc_dump_arr']

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

    start_i = max(50, start_bar_offset)

    for bar_i in range(start_i, n_bars):
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
            monthly_pnl[m_k] = monthly_pnl.get(m_k, 0.0) + pos['realized_pnl']

        if balance > peak_balance:
            peak_balance = balance
        dd_pct = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct

        if len(active_positions) >= max_positions or balance <= 0:
            continue

        long_count = sum(1 for p in active_positions.values() if p['side'] == 'LONG')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SHORT')

        for sym in SYMBOLS:
            if sym in active_positions:
                continue
            if bar_i - symbol_last_trade_bar[sym] < cooldown_bars:
                continue
            s_idx = idx_maps[sym][bar_i]
            if s_idx == -1:
                continue

            sig = signals_map[sym][s_idx]
            close_p = closes_map[sym][s_idx]

            entry_side = None
            channel = None
            tp1_p = 0.0
            sl_p = 0.0

            # Signal evaluation with directional cap check
            if sig['mss_long'] and not btc_dump and long_count < max_directional:
                entry_side = 'LONG'
                channel = 'MSS_SHIFT'
                tp1_p = close_p + (tp1_atr * sig['atr'])
                sl_p = sig['last_sl']
            elif sig['mss_short'] and short_count < max_directional:
                entry_side = 'SHORT'
                channel = 'MSS_SHIFT'
                tp1_p = close_p - (tp1_atr * sig['atr'])
                sl_p = sig['last_sh']
            elif sig['cons_long'] and not btc_dump and long_count < max_directional:
                entry_side = 'LONG'
                channel = '5MA_CONSENSUS'
                tp1_p = close_p + (tp1_atr * sig['atr'])
                sl_p = close_p - (1.5 * sig['atr'])
            elif sig['cons_short'] and short_count < max_directional:
                entry_side = 'SHORT'
                channel = '5MA_CONSENSUS'
                tp1_p = close_p - (tp1_atr * sig['atr'])
                sl_p = close_p + (1.5 * sig['atr'])
            elif sig['fib_long'] and not btc_dump and long_count < max_directional:
                entry_side = 'LONG'
                channel = 'FIBONACCI'
                tp1_p = close_p + (tp1_atr * sig['atr'])
                sl_p = close_p - (1.5 * sig['atr'])
            elif sig['fib_short'] and short_count < max_directional:
                entry_side = 'SHORT'
                channel = 'FIBONACCI'
                tp1_p = close_p - (tp1_atr * sig['atr'])
                sl_p = close_p + (1.5 * sig['atr'])

            if entry_side:
                # Adversarial CRO risk check
                if entry_side == 'LONG' and (close_p - sig['ema50']) > (2.8 * sig['atr']):
                    continue
                if entry_side == 'SHORT' and (sig['ema50'] - close_p) > (2.8 * sig['atr']):
                    continue

                weight_mult = darwin.get_multiplier(channel)
                base_trade_margin = balance * margin_pct
                pos_margin = base_trade_margin * weight_mult

                if pos_margin < 0.10 or balance < pos_margin:
                    continue

                notional = pos_margin * leverage
                qty = notional / close_p
                fee_entry = notional * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                balance -= (pos_margin + fee_entry)

                active_positions[sym] = {
                    'symbol': sym,
                    'side': entry_side,
                    'channel': channel,
                    'entry_price': close_p,
                    'qty': qty,
                    'remaining_qty': qty,
                    'margin': pos_margin,
                    'tp1_p': tp1_p,
                    'sl_p': sl_p,
                    'tp1_hit': False,
                    'atr': sig['atr'],
                    'highest_since_entry': close_p,
                    'lowest_since_entry': close_p,
                    'realized_pnl': -fee_entry,
                    'entry_time': cur_time
                }

                if entry_side == 'LONG':
                    long_count += 1
                else:
                    short_count += 1

                if len(active_positions) >= max_positions:
                    break

    for sym, pos in list(active_positions.items()):
        s_idx = idx_maps[sym][-1]
        c = closes_map[sym][s_idx] if s_idx != -1 else pos['entry_price']
        pnl = (c - pos['entry_price']) * pos['remaining_qty'] if pos['side'] == 'LONG' else (pos['entry_price'] - c) * pos['remaining_qty']
        balance += (pos['margin'] * (0.50 if pos['tp1_hit'] else 1.00)) + pnl
        pos['realized_pnl'] += pnl
        pos['exit_time'] = pd.Timestamp(time_index[-1])
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
    years = (n_bars - start_i) / (4 * 24 * 365)
    ann_roi = ((balance / initial_balance) ** (1.0 / max(0.1, years)) - 1.0) * 100.0
    sorted_months = sorted(monthly_pnl.keys())
    green_m = sum(1 for m in sorted_months if monthly_pnl[m] > 0)

    res = {
        'label': label,
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
        'years': years
    }
    return res

def main():
    data = load_all_data()
    n_bars = data['n_bars']
    bars_1yr = int(n_bars * (1.0 / 3.0))
    bars_2yr = int(n_bars * (2.0 / 3.0))

    print(f"=== BENCHMARK SUITE: LIVE BALANCE ${LIVE_BALANCE:.2f} USDT ===")
    print("Settings: 75x Leverage | TP1 2.2x ATR | Trail 1.0x ATR | Fib Weight 1.5x | Dircap 5 | Maxpos 5\n")

    # Set 1: Risk Tiers (1x = 1% margin, 2x = 2% margin, 3x = 3% margin)
    print(">>> Testing Margin Tier 1: 1% (1x), 2% (2x), 3% (3x)")
    r_1pct = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.01, label="1x Risk (1.0% Margin)")
    r_2pct = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.02, label="2x Risk (2.0% Margin)")
    r_3pct = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.03, label="3x Risk (3.0% Margin - Standard)")

    # Set 2: Base Risk Multipliers (1x = 3% margin, 2x = 6% margin, 3x = 9% margin)
    print(">>> Testing Margin Tier 2: 3% (1x base), 6% (2x base), 9% (3x base)")
    r_6pct = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.06, label="2x Base Risk (6.0% Margin)")
    r_9pct = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.09, label="3x Base Risk (9.0% Margin)")

    # Set 3: Timeframe Tiers (1 Year, 2 Years, 3 Years at standard 3% margin)
    print(">>> Testing Time Horizon Tier: 1 Year (1x), 2 Years (2x), 3 Years (3x)")
    r_1yr = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.03, start_bar_offset=n_bars - bars_1yr, label="1-Year Horizon (Last 12M)")
    r_2yr = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.03, start_bar_offset=n_bars - bars_2yr, label="2-Year Horizon (Last 24M)")
    r_3yr = simulate_pass(data, initial_balance=LIVE_BALANCE, margin_pct=0.03, start_bar_offset=0, label="3-Year Horizon (Full 36M)")

    results = [r_1pct, r_2pct, r_3pct, r_6pct, r_9pct, r_1yr, r_2yr, r_3yr]

    print("\n" + "=" * 115)
    print(f"{'Simulation Configuration':<32} | {'Final USDT':>12} | {'Net Profit':>12} | {'ROI %':>10} | {'PF':>6} | {'WR %':>6} | {'Max DD':>7} | {'Green M':>12}")
    print("=" * 115)
    for r in results:
        print(f"{r['label']:<32} | ${r['final_balance']:>11,.2f} | ${r['net_profit']:>+11,.2f} | {r['total_roi']:>+9.1f}% | {r['profit_factor']:>6.2f} | {r['win_rate']:>5.1f}% | {r['max_drawdown']:>6.2f}% | {r['green_months']:>12}")
    print("=" * 115)

if __name__ == '__main__':
    main()
