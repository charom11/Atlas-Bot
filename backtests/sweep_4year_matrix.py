#!/usr/bin/env python3
"""
==========================================================================================
⚡ 4-YEAR COMPREHENSIVE PARAMETER SWEEP (2022 - 2026)
==========================================================================================
Iterates through all key strategy parameters on the 48-Month / 140,387 bar dataset
with the live balance ($9.79 USDT) to isolate and highlight the optimal settings.
==========================================================================================
"""

import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from backtest_3year_atlas_perfect_synergy import (
    CACHE_DIR, SYMBOLS, run_3year_synergy_backtest, precompute_signals
)
import backtest_3year_atlas_perfect_synergy

LIVE_BALANCE = 9.79

def load_4year_dataset():
    print("Loading 4-year historical dataset for 11 assets (2022-09 to 2026-09)...", flush=True)
    data_map = {}
    highs_map = {}
    lows_map = {}
    closes_map = {}
    signals_map = {}
    for sym in SYMBOLS:
        cache_file = os.path.join(CACHE_DIR, f"{sym}_15m_4year_2022-09-01.csv")
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

    print(f"[TIMELINE] Synchronized {n_bars:,} 15m bars across 48 months (2022-09 to 2026-09)\n", flush=True)
    return {
        'data_map': data_map, 'signals_map': signals_map,
        'highs_map': highs_map, 'lows_map': lows_map, 'closes_map': closes_map,
        'time_index': time_index, 'n_bars': n_bars, 'idx_maps': idx_maps,
        'btc_dump_arr': btc_dump_arr
    }

def main():
    backtest_3year_atlas_perfect_synergy._DATA_CACHE = load_4year_dataset()

    test_grid = [
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

        # --- 6. DIRECTIONAL CAP SWEEP ---
        {"cat": "Dircap",      "name": "Dircap 3 / Maxpos 5",      "lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 3, "pos": 5},
        {"cat": "Dircap",      "name": "Dircap 5 / Maxpos 5 (Prod)","lev": 75, "margin": 0.03, "tp1": 2.2, "trail": 1.0, "fib": 1.5, "dir": 5, "pos": 5},
    ]

    results = []
    for cfg in test_grid:
        print(f"Sweeping: {cfg['name']}...", flush=True)
        r = run_3year_synergy_backtest(
            initial_balance=LIVE_BALANCE,
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
    print(" 🏆 4-YEAR COMPREHENSIVE STRATEGY PARAMETER SWEEP SCORECARD (2022 - 2026)")
    print("=" * 125)
    print(f"{'Category':<14} | {'Configuration Name':<30} | {'Final Capital':>13} | {'Total ROI':>11} | {'PF':>6} | {'WR %':>6} | {'Max DD':>8} | {'Green M':>12}")
    print("-" * 125)
    for r in results:
        is_highlight = "⭐ BEST" if ("(Prod)" in r['name'] or "(Production)" in r['name'] or "(Ultra-Safe)" in r['name']) else "      "
        print(f"{r['cat']:<14} | {r['name']:<30} | ${r['final_balance']:>12,.2f} | {r['total_roi']:>+10.1f}% | {r['profit_factor']:>6.2f} | {r['win_rate']:>5.1f}% | {r['max_drawdown']:>7.2f}% | {r['green_months']:>12} {is_highlight}")
    print("=" * 125)

if __name__ == '__main__':
    main()
