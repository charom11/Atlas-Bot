#!/usr/bin/env python3
"""
Comprehensive Live Balance ($9.79 USDT) Multi-Tier Backtest Runner
Tests 1x, 2x, 3x settings across:
1. Margin Risk (1%, 2%, 3% and 3%, 6%, 9%)
2. Fibonacci Channel Weight (1.0x, 2.0x, 3.0x)
3. Take Profit Targets (1.5x, 2.2x, 3.0x ATR)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtests'))
from backtest_3year_atlas_perfect_synergy import run_3year_synergy_backtest, get_precomputed_data

LIVE_BALANCE = 9.79

def main():
    print(f"Precomputing/loading 3-year data once...")
    get_precomputed_data()
    print("Data loaded successfully! Running test matrix...\n")

    test_configs = [
        # Margin % Tiers (1x, 2x, 3x)
        {"name": "1x Risk (1.0% Margin)", "margin": 0.01, "fib": 1.5, "tp1": 2.2, "trail": 1.0, "lev": 75},
        {"name": "2x Risk (2.0% Margin)", "margin": 0.02, "fib": 1.5, "tp1": 2.2, "trail": 1.0, "lev": 75},
        {"name": "3x Risk (3.0% Margin - Standard)", "margin": 0.03, "fib": 1.5, "tp1": 2.2, "trail": 1.0, "lev": 75},

        # Base Risk Multipliers (1x, 2x, 3x Base)
        {"name": "1x Base (3.0% Margin)", "margin": 0.03, "fib": 1.5, "tp1": 2.2, "trail": 1.0, "lev": 75},
        {"name": "2x Base (6.0% Margin)", "margin": 0.06, "fib": 1.5, "tp1": 2.2, "trail": 1.0, "lev": 75},
        {"name": "3x Base (9.0% Margin)", "margin": 0.09, "fib": 1.5, "tp1": 2.2, "trail": 1.0, "lev": 75},

        # Fibonacci Channel Weight Tiers (1x, 2x, 3x)
        {"name": "1x Fib Weight (1.0x)", "margin": 0.03, "fib": 1.0, "tp1": 2.2, "trail": 1.0, "lev": 75},
        {"name": "2x Fib Weight (2.0x)", "margin": 0.03, "fib": 2.0, "tp1": 2.2, "trail": 1.0, "lev": 75},
        {"name": "3x Fib Weight (3.0x)", "margin": 0.03, "fib": 3.0, "tp1": 2.2, "trail": 1.0, "lev": 75},

        # Target Clearances (1x, 2x, 3x ATR)
        {"name": "1x ATR TP1 (1.5x ATR)", "margin": 0.03, "fib": 1.5, "tp1": 1.5, "trail": 0.8, "lev": 75},
        {"name": "2x ATR TP1 (2.2x ATR - Standard)", "margin": 0.03, "fib": 1.5, "tp1": 2.2, "trail": 1.0, "lev": 75},
        {"name": "3x ATR TP1 (3.0x ATR)", "margin": 0.03, "fib": 1.5, "tp1": 3.0, "trail": 1.4, "lev": 75},
    ]

    results = []
    for cfg in test_configs:
        print(f"Running: {cfg['name']} ...", flush=True)
        r = run_3year_synergy_backtest(
            initial_balance=LIVE_BALANCE,
            leverage=cfg['lev'],
            margin_pct=cfg['margin'],
            max_positions=5,
            max_directional=5,
            fib_weight=cfg['fib'],
            tp1_atr=cfg['tp1'],
            trail_atr=cfg['trail'],
            quiet=True
        )
        r['name'] = cfg['name']
        results.append(r)

    print("\n" + "=" * 120)
    print(f" 🏆 LIVE BALANCE (${LIVE_BALANCE:.2f} USDT) 3-YEAR MULTI-TIER SCORECARD MATRIX")
    print("=" * 120)
    print(f"{'Configuration Tier':<34} | {'Final Capital':>14} | {'Net Profit':>14} | {'Total ROI':>11} | {'PF':>6} | {'WR %':>6} | {'Max DD':>8} | {'Green Months':>10}")
    print("-" * 120)
    for r in results:
        print(f"{r['name']:<34} | ${r['final_balance']:>13,.2f} | ${r['net_profit']:>+13,.2f} | {r['total_roi']:>+10.1f}% | {r['profit_factor']:>6.2f} | {r['win_rate']:>5.1f}% | {r['max_drawdown']:>7.2f}% | {r['green_months']:>10}")
    print("=" * 120)

if __name__ == '__main__':
    main()
