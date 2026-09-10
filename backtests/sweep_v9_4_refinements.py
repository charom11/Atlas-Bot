#!/usr/bin/env python3
"""
Comparative Sweep for V9.4 Strategic Improvements.
Tests the 4 specific leak fixes on the 4-year historical dataset:
1. Baseline V9.4 (6 assets, MILD_TREND allowed, BE=1.0R)
2. Experiment A: Gate MILD_TREND (allow_mild_trend=False)
3. Experiment B: Prune DOGE & XRP (Trade only SOL, BTC, ETH, SUI)
4. Experiment C: Gate MILD_TREND + Prune DOGE & XRP (Combined Asset & Regime Filter)
5. Experiment D: Combined Filter + Breakeven Trigger tuned to 1.35R
6. Experiment E: Combined Filter + Breakeven Trigger tuned to 1.50R
"""
from __future__ import annotations
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from strategy_candidate_v9 import load_ohlcv_csv, summarize, Trade
from strategy_candidate_v9_4 import V94Config, backtest_frame_v94

CACHE_DIR = Path(__file__).resolve().parent / "historical_data_cache"
SYMBOLS = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "SUIUSDT", "DOGEUSDT", "XRPUSDT"]
CORE_4 = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "SUIUSDT"]


def load_all_data():
    print("Loading 4-year datasets into memory...", flush=True)
    dfs = {}
    for sym in SYMBOLS:
        p = CACHE_DIR / f"{sym}_15m_4year_2022-09-01.csv"
        if p.exists():
            df = load_ohlcv_csv(str(p))
            df["symbol"] = sym
            dfs[sym] = df
            print(f"  Loaded {sym}: {len(df):,} bars")
    return dfs


def run_experiment(name: str, dfs: dict[str, pd.DataFrame], symbols: list[str], config: V94Config):
    t0 = time.time()
    all_trades: list[Trade] = []
    asset_results = {}
    for sym in symbols:
        if sym not in dfs:
            continue
        trades = backtest_frame_v94(dfs[sym], config=config)
        all_trades.extend(trades)
        st = summarize(trades)
        asset_results[sym] = st

    port = summarize(all_trades)
    elapsed = time.time() - t0
    return {
        "name": name,
        "config": config,
        "symbols": symbols,
        "trades": port.trades,
        "win_rate": port.win_rate,
        "net_r": port.net_r,
        "profit_factor": port.profit_factor,
        "expectancy": port.expectancy_r,
        "max_dd": port.max_drawdown_r,
        "avg_bars": port.avg_bars_held,
        "asset_results": asset_results,
        "elapsed": elapsed,
    }


def main():
    dfs = load_all_data()

    experiments = [
        ("1. Baseline V9.4 (6 Assets, MILD_TREND, BE=1.0R)",
         SYMBOLS,
         V94Config(allow_mild_trend=True, breakeven_trigger_r=1.00)),

        ("2. Gate MILD_TREND (6 Assets, MILD=Gated, BE=1.0R)",
         SYMBOLS,
         V94Config(allow_mild_trend=False, breakeven_trigger_r=1.00)),

        ("3. Prune DOGE & XRP (Core 4 Assets, MILD=Allowed, BE=1.0R)",
         CORE_4,
         V94Config(allow_mild_trend=True, breakeven_trigger_r=1.00)),

        ("4. Combined: Core 4 Assets + Gate MILD_TREND (BE=1.0R)",
         CORE_4,
         V94Config(allow_mild_trend=False, breakeven_trigger_r=1.00)),

        ("5. Combined + Breakeven 1.35R (Core 4, MILD=Gated, BE=1.35R)",
         CORE_4,
         V94Config(allow_mild_trend=False, breakeven_trigger_r=1.35)),

        ("6. Combined + Breakeven 1.50R (Core 4, MILD=Gated, BE=1.50R)",
         CORE_4,
         V94Config(allow_mild_trend=False, breakeven_trigger_r=1.50)),

        ("7. Combined + Breakeven Disabled (Core 4, MILD=Gated, No BE)",
         CORE_4,
         V94Config(allow_mild_trend=False, enable_breakeven_trail=False)),
    ]

    results = []
    print("\n" + "=" * 110)
    print(" 🚀 RUNNING COMPARATIVE REFINEMENT SWEEP (4-YEAR 15M REAL OHLCV)")
    print("=" * 110 + "\n")

    for name, syms, cfg in experiments:
        print(f"Running: {name}...", flush=True)
        res = run_experiment(name, dfs, syms, cfg)
        results.append(res)
        print(f"   ➔ Net R: {res['net_r']:>+8.2f} R | PF: {res['profit_factor']:>5.2f} | WR: {res['win_rate']*100:>5.1f}% | Trades: {res['trades']:>6,} | MaxDD: {res['max_dd']:>6.2f} R ({res['elapsed']:.1f}s)")

    print("\n" + "=" * 110)
    print(f" {'EXPERIMENT / CONFIGURATION':<58} | {'TRADES':>6} | {'NET R':>9} | {'PF':>5} | {'WR %':>5} | {'MAX DD':>8} | {'EXP/TR':>8}")
    print("=" * 110)
    for r in results:
        print(f" {r['name']:<58} | {r['trades']:>6,} | {r['net_r']:>+9.2f} | {r['profit_factor']:>5.2f} | {r['win_rate']*100:>5.1f}% | {r['max_dd']:>8.2f} | {r['expectancy']:>+7.4f}R")
    print("=" * 110 + "\n")


if __name__ == "__main__":
    main()
