#!/usr/bin/env python3
"""
==========================================================================================
⚡ CHANNEL-BY-CHANNEL QUANT DECOMPOSITION: COUNTER-MACRO QUICK SCALPS
==========================================================================================
Determines exactly WHICH strategy channels produce positive alpha as Quick Scalps (Counter-Macro)
versus which ones should be restricted to Trend Runners (With-Macro).
==========================================================================================
"""

import os
import sys
import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from backtest_counter_macro_quick_scalp import (
    SYMBOLS, CACHE_DIR, FEE_SCHEDULE, calc_ema, calc_rsi, calc_cci, calc_atr, calc_adx,
    precompute_market_signals
)

def run_channel_audit():
    data = {}
    for sym in SYMBOLS:
        fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_2025-07-01.csv")
        if not os.path.exists(fpath):
            fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_2024-08-25.csv")
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            t_col = 'open_time' if 'open_time' in df.columns else 'timestamp'
            df['open_time'] = pd.to_datetime(df[t_col], utc=True)
            df = df.sort_values('open_time').reset_index(drop=True)
            data[sym] = df

    sym_signals = {}
    for sym, df in data.items():
        sym_signals[sym] = precompute_market_signals(df)

    min_len = min(len(df) for df in data.values())

    channels = ['POTATO_SR', 'DIVERGENCE', 'FIBONACCI', 'CONSENSUS']
    results = {}

    for ch in channels:
        for mode in ['SCALP_COUNTER', 'RUNNER_MACRO']:
            key = f"{ch}_{mode}"
            results[key] = {
                'channel': ch,
                'mode': mode,
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'pnl': 0.0,
                'gross_win': 0.0,
                'gross_loss': 0.0
            }

    for sym, df in data.items():
        sig_list = sym_signals[sym]
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        n = len(closes)

        for i in range(60, n - 40):
            idx = i - 50
            if idx < 0 or idx >= len(sig_list):
                continue
            _, sig = sig_list[idx]
            cur_p = closes[i]
            atr_v = sig['atr']
            if sig.get('adx', 25.0) < 22.0:
                continue

            trade_candidates = []
            if sig['potato_long']:
                trade_candidates.append(('BUY', 'POTATO_SR'))
            if sig['potato_short']:
                trade_candidates.append(('SELL', 'POTATO_SR'))
            if sig['div_long']:
                trade_candidates.append(('BUY', 'DIVERGENCE'))
            if sig['div_short']:
                trade_candidates.append(('SELL', 'DIVERGENCE'))
            if sig['fib_long']:
                trade_candidates.append(('BUY', 'FIBONACCI'))
            if sig['fib_short']:
                trade_candidates.append(('SELL', 'FIBONACCI'))
            if sig['cons_long']:
                trade_candidates.append(('BUY', 'CONSENSUS'))
            if sig['cons_short']:
                trade_candidates.append(('SELL', 'CONSENSUS'))

            for action, ch in trade_candidates:
                # Classify Quick Scalp vs Trend Runner
                is_quick_scalp = (action == 'SELL' and sig['macro_bull']) or (action == 'BUY' and sig['macro_bear'])
                mode_k = 'SCALP_COUNTER' if is_quick_scalp else 'RUNNER_MACRO'
                res_bucket = results[f"{ch}_{mode_k}"]

                # Simulate standard fixed 100 USDT notional trade
                notional = 100.0
                qty = notional / cur_p
                maker_fee = notional * FEE_SCHEDULE['maker_fee']
                taker_fee = notional * FEE_SCHEDULE['taker_fee']

                if is_quick_scalp:
                    tp1 = (cur_p + 1.3 * atr_v) if action == 'BUY' else (cur_p - 1.3 * atr_v)
                    tp2 = (cur_p + 2.0 * atr_v) if action == 'BUY' else (cur_p - 2.0 * atr_v)
                    sl  = (cur_p - 0.9 * atr_v) if action == 'BUY' else (cur_p + 0.9 * atr_v)
                    trail_dist = 0.7 * atr_v
                else:
                    tp1 = (cur_p + 1.8 * atr_v) if action == 'BUY' else (cur_p - 1.8 * atr_v)
                    tp2 = (cur_p + 2.8 * atr_v) if action == 'BUY' else (cur_p - 2.8 * atr_v)
                    sl  = (cur_p - 1.5 * atr_v) if action == 'BUY' else (cur_p + 1.5 * atr_v)
                    trail_dist = 1.4 * atr_v

                # Simulate trade forward
                rem_qty = qty
                trade_pnl = -maker_fee
                tp1_hit = False
                tp2_hit = False
                cur_sl = sl
                highest = cur_p
                lowest = cur_p

                for step in range(1, 35):
                    bar_k = i + step
                    if bar_k >= n:
                        break
                    bh = highs[bar_k]
                    bl = lows[bar_k]
                    bc = closes[bar_k]

                    # Check SL
                    hit_sl = (action == 'BUY' and bl <= cur_sl) or (action == 'SELL' and bh >= cur_sl)
                    if hit_sl:
                        exit_p = cur_sl
                        pnl_slice = rem_qty * (exit_p - cur_p) if action == 'BUY' else rem_qty * (cur_p - exit_p)
                        trade_pnl += pnl_slice - (rem_qty * exit_p * FEE_SCHEDULE['taker_fee'])
                        rem_qty = 0
                        break

                    # Check TP1
                    if not tp1_hit:
                        hit_tp1 = (action == 'BUY' and bh >= tp1) or (action == 'SELL' and bl <= tp1)
                        if hit_tp1:
                            tp1_hit = True
                            q_close = qty * 0.33
                            rem_qty -= q_close
                            pnl_slice = q_close * (tp1 - cur_p) if action == 'BUY' else q_close * (cur_p - tp1)
                            trade_pnl += pnl_slice - (q_close * tp1 * FEE_SCHEDULE['maker_fee'])
                            # Move SL to Breakeven
                            cur_sl = cur_p * 1.0005 if action == 'BUY' else cur_p * 0.9995
                            highest = bh
                            lowest = bl

                    # Check TP2
                    if tp1_hit and not tp2_hit:
                        hit_tp2 = (action == 'BUY' and bh >= tp2) or (action == 'SELL' and bl <= tp2)
                        if hit_tp2:
                            tp2_hit = True
                            q_close = qty * 0.33
                            rem_qty -= q_close
                            pnl_slice = q_close * (tp2 - cur_p) if action == 'BUY' else q_close * (cur_p - tp2)
                            trade_pnl += pnl_slice - (q_close * tp2 * FEE_SCHEDULE['maker_fee'])

                    # Trailing Runner
                    if tp1_hit:
                        if action == 'BUY':
                            if bh > highest:
                                highest = bh
                            calc_trail = highest - (0.5 * atr_v if tp2_hit else trail_dist)
                            if calc_trail > cur_sl and calc_trail > cur_p:
                                cur_sl = calc_trail
                        else:
                            if bl < lowest:
                                lowest = bl
                            calc_trail = lowest + (0.5 * atr_v if tp2_hit else trail_dist)
                            if calc_trail < cur_sl and calc_trail < cur_p:
                                cur_sl = calc_trail

                # End of window exit
                if rem_qty > 0:
                    exit_p = closes[min(i + 34, n - 1)]
                    pnl_slice = rem_qty * (exit_p - cur_p) if action == 'BUY' else rem_qty * (cur_p - exit_p)
                    trade_pnl += pnl_slice - (rem_qty * exit_p * FEE_SCHEDULE['taker_fee'])

                res_bucket['trades'] += 1
                res_bucket['pnl'] += trade_pnl
                if trade_pnl > 0:
                    res_bucket['wins'] += 1
                    res_bucket['gross_win'] += trade_pnl
                else:
                    res_bucket['losses'] += 1
                    res_bucket['gross_loss'] += abs(trade_pnl)

    print("=" * 110)
    print(" 🔬 STRATEGY CHANNEL QUANT DECOMPOSITION: COUNTER-MACRO QUICK SCALP VS WITH-MACRO RUNNER")
    print("=" * 110)
    print(f"{'Strategy Channel':<22} | {'Mode':<16} | {'Trades':>7} | {'Win Rate':>9} | {'Profit Factor':>14} | {'Net PnL ($)':>14} | {'Verdict':<15}")
    print("-" * 110)

    for k, v in results.items():
        wr = (v['wins'] / v['trades'] * 100.0) if v['trades'] > 0 else 0.0
        pf = (v['gross_win'] / (v['gross_loss'] + 1e-9)) if v['gross_loss'] > 0 else 99.0
        verdict = "🔥 STRONG ALPHA" if v['pnl'] > 0 and pf > 1.2 else ("⚠️ NEGATIVE" if v['pnl'] < 0 else "⚖️ NEUTRAL")
        mode_label = "⚡ Quick Scalp" if "SCALP" in v['mode'] else "🌊 Trend Runner"
        print(f"{v['channel']:<22} | {mode_label:<16} | {v['trades']:>7} | {wr:>8.1f}% | {pf:>14.2f} | ${v['pnl']:>+13.2f} | {verdict:<15}")

    print("=" * 110)

if __name__ == '__main__':
    run_channel_audit()
