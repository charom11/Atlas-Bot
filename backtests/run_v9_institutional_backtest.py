#!/usr/bin/env python3
"""
==========================================================================================
⚡ STRATEGY CANDIDATE V9: 15-MINUTE MULTI-SETUP INSTITUTIONAL BACKTEST ENGINE
==========================================================================================
Evaluates the 10 setup families and 6 market regimes across 15m perpetual futures data:
- 10 Setup Families: TREND_CONTINUATION, PULLBACK_CONTINUATION, FIB_OTE, MSS_SHIFT,
  LIQUIDITY_SWEEP, BREAKOUT_RETEST, VWAP_TREND, VWAP_REVERSION, BB_ATR_EXPANSION,
  EXHAUSTION_REVERSAL.
- 6 Regimes: STRONG_TREND, MILD_TREND, RANGE, HIGH_VOL, BREAKDOWN, CHOP.
- Next-bar execution simulation with realistic friction (0.026 R base).
- Per-asset breakdown across the liquid Binance Futures universe.
- Dual out-of-sample walk-forward partitions (2022-2023, 2024, 2025, 2026).
- Cost-stress testing (0.015 R to 0.060 R).
==========================================================================================
"""

from __future__ import annotations
from dataclasses import asdict
import os
import sys
import json
import time
from pathlib import Path
from typing import Mapping, Sequence

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import concurrent.futures
from strategy_candidate_v9 import (
    SETUPS,
    REGIMES,
    LONG,
    SHORT,
    FLAT,
    Trade,
    BacktestStats,
    load_ohlcv_csv,
    backtest_frame,
    summarize,
    report,
    walk_forward,
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_data_cache")

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
]


def _backtest_worker(sym: str, df: pd.DataFrame, min_score: int, min_confirmations: int, friction_r: float):
    t0 = time.time()
    trades = backtest_frame(df, min_score=min_score, min_confirmations=min_confirmations, friction_r=friction_r)
    st = summarize(trades)
    return sym, trades, st, len(df), time.time() - t0


def run_v9_institutional_audit(
    cache_dir: str = CACHE_DIR,
    dataset_type: str = "1year",
    friction_r: float = 0.026,
    min_score: int = 5,
    min_confirmations: int = 1,
    output_path: str = "backtests/v9_institutional_backtest_report.json",
) -> dict:
    t_start = time.time()
    print("=" * 105)
    print(" [AUDIT] STRATEGY CANDIDATE V9: 15-MINUTE MULTI-SETUP INSTITUTIONAL BACKTEST")
    print("=" * 105)
    print(f" • Dataset Configuration:  15m Resolution ({dataset_type.upper()})")
    print(f" • Target Universe:        {len(SYMBOLS)} Perpetual Futures Assets")
    print(f" • Execution Model:        Next-Bar Open Entry | 1.25x ATR SL | 2.0x ATR TP | Friction: {friction_r} R")
    print(f" • Setups Evaluated:       10 Independent Families (Trend, Pullback, OTE, MSS, Sweep, VWAP, BB, Rev)")
    print(f" • Quality Gates:          Min Score >= {min_score} | Min Confirmations >= {min_confirmations}")
    print("=" * 105 + "\n")

    # Load datasets
    asset_dfs: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        if dataset_type == "4year":
            fpath = os.path.join(cache_dir, f"{sym}_15m_4year_2022-09-01.csv")
        else:
            fpath = os.path.join(cache_dir, f"{sym}_15m_from_2025-07-01.csv")
            if not os.path.exists(fpath):
                fpath = os.path.join(cache_dir, f"{sym}_15m_from_2024-08-25.csv")

        if os.path.exists(fpath):
            try:
                df = load_ohlcv_csv(fpath)
                df["symbol"] = sym
                asset_dfs[sym] = df
            except Exception as e:
                print(f"Warning: Failed to load {fpath}: {e}")

    if not asset_dfs:
        print("Error: No historical data files found.")
        return {}

    print(f" Loaded {len(asset_dfs)} assets ({sum(len(df) for df in asset_dfs.values()):,} total 15m bars across universe).\n")

    all_trades: list[Trade] = []
    asset_stats: dict[str, BacktestStats] = {}

    workers = min(len(asset_dfs), os.cpu_count() or 4)
    print(f" Simulating 15m execution across universe with {workers} parallel workers...")
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_backtest_worker, sym, df, min_score, min_confirmations, friction_r): sym
            for sym, df in asset_dfs.items()
        }
        for f in concurrent.futures.as_completed(futures):
            sym, trades, st, n_bars, dur = f.result()
            all_trades.extend(trades)
            asset_stats[sym] = st
            print(f"  -> {sym:<10} | Bars: {n_bars:>7,} | Trades: {st.trades:>6,} | WR: {st.win_rate*100:>5.1f}% | PF: {st.profit_factor:>5.2f} | Net R: {st.net_r:>+8.2f} | ({dur:.1f}s)")

    portfolio_stats = summarize(all_trades)

    # -------------------------------------------------------------------------
    # Audit 1: Overall Portfolio Summary
    # -------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print(" [AUDIT 1] CANDIDATE V9 15M PORTFOLIO BENCHMARK SUMMARY")
    print("=" * 105)
    print(f" Total Trades:          {portfolio_stats.trades:,}")
    print(f" Win Rate:              {portfolio_stats.win_rate*100:.1f}% ({portfolio_stats.wins:,} wins / {portfolio_stats.trades - portfolio_stats.wins:,} losses)")
    print(f" Profit Factor:         {portfolio_stats.profit_factor:.2f}")
    print(f" Net Realized R:        {portfolio_stats.net_r:+.2f} R")
    print(f" Expectancy per Trade:  {portfolio_stats.expectancy_r:+.4f} R")
    print(f" Max Drawdown (R):      {portfolio_stats.max_drawdown_r:.2f} R")
    print(f" Avg Bars Held:         {portfolio_stats.avg_bars_held:.1f} bars (~{portfolio_stats.avg_bars_held*15/60:.1f} hours)")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 2: Setup Family Alpha Decomposition
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 2] 10-SETUP FAMILY ALPHA DECOMPOSITION")
    print("=" * 105)
    print(f" {'Setup Family':<25} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9} | {'Avg Held':>9}")
    print("-" * 85)

    setup_stats: dict[str, BacktestStats] = {}
    for setup in SETUPS:
        s_trades = [t for t in all_trades if t.setup == setup]
        st = summarize(s_trades)
        setup_stats[setup] = st
        status = "🟢" if st.expectancy_r > 0 else ("🟡" if st.profit_factor >= 0.95 else "🔴")
        print(f" {setup:<25} | {st.trades:>8,} | {st.win_rate*100:>8.1f}% | {st.profit_factor:>6.2f} | {st.net_r:>+10.2f} | {st.expectancy_r:>+9.4f} | {st.avg_bars_held:>8.1f}b {status}")
    print("-" * 85 + "\n")

    # -------------------------------------------------------------------------
    # Audit 3: Market Regime Attribution
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 3] 15M MARKET REGIME PERFORMANCE MATRIX")
    print("=" * 105)
    print(f" {'Market Regime':<20} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9}")
    print("-" * 75)

    regime_stats: dict[str, BacktestStats] = {}
    for regime in REGIMES:
        r_trades = [t for t in all_trades if t.regime == regime]
        st = summarize(r_trades)
        regime_stats[regime] = st
        status = "🟢" if st.expectancy_r > 0 else ("🟡" if st.profit_factor >= 0.95 else "🔴")
        print(f" {regime:<20} | {st.trades:>8,} | {st.win_rate*100:>8.1f}% | {st.profit_factor:>6.2f} | {st.net_r:>+10.2f} | {st.expectancy_r:>+9.4f} {status}")
    print("-" * 75 + "\n")

    # -------------------------------------------------------------------------
    # Audit 4: Out-Of-Sample Walk-Forward Scorecard
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 4] OUT-OF-SAMPLE WALK-FORWARD SCORECARD")
    print("=" * 105)
    print(f" {'Partition Period':<23} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9}")
    print("-" * 75)

    periods = [
        ("TRAIN (2022-2023)", "2022-09-01", "2024-01-01"),
        ("VALIDATE (2024)", "2024-01-01", "2025-01-01"),
        ("OOS #1 (2025)", "2025-01-01", "2026-01-01"),
        ("OOS #2 (2026)", "2026-01-01", "2027-01-01"),
    ]

    wf_stats = {}
    for label, start, end in periods:
        p_trades = [t for t in all_trades if start <= t.timestamp < end]
        st = summarize(p_trades)
        wf_stats[label] = st
        status = "🟢" if st.expectancy_r > 0 else ("🟡" if st.profit_factor >= 0.95 else "🔴")
        print(f" {label:<23} | {st.trades:>8,} | {st.win_rate*100:>8.1f}% | {st.profit_factor:>6.2f} | {st.net_r:>+10.2f} | {st.expectancy_r:>+9.4f} {status}")
    print("-" * 75 + "\n")

    # -------------------------------------------------------------------------
    # Audit 5: Cost Stress Robustness Matrix
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 5] COST STRESS MATRIX (Slippage & Taker Friction Sensitivity)")
    print("=" * 105)
    print(f" {'Friction Scenario':<25} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9}")
    print("-" * 75)

    cost_scenarios = [
        ("Low Friction (0.015 R)", 0.015),
        ("Base VIP0 (0.026 R)", 0.026),
        ("Stressed (+50%: 0.040 R)", 0.040),
        ("Severe (+130%: 0.060 R)", 0.060),
    ]

    stress_stats = {}
    for label, c_frict in cost_scenarios:
        diff_frict = c_frict - friction_r
        stressed_vals = [t.r_multiple - diff_frict for t in all_trades]
        wins = sum(v > 0 for v in stressed_vals)
        st_pf = _pf_calc(stressed_vals)
        net_r_val = sum(stressed_vals)
        exp_val = net_r_val / len(stressed_vals) if stressed_vals else 0.0
        print(f" {label:<25} | {len(stressed_vals):>8,} | {wins/len(stressed_vals)*100:>8.1f}% | {st_pf:>6.2f} | {net_r_val:>+10.2f} | {exp_val:>+9.4f}")
        stress_stats[label] = {
            "friction_r": c_frict,
            "trades": len(stressed_vals),
            "profit_factor": st_pf,
            "net_r": net_r_val,
            "expectancy_r": exp_val,
        }
    print("-" * 75 + "\n")

    report_data = {
        "dataset": dataset_type,
        "portfolio": asdict(portfolio_stats),
        "by_asset": {k: asdict(v) for k, v in asset_stats.items()},
        "by_setup": {k: asdict(v) for k, v in setup_stats.items()},
        "by_regime": {k: asdict(v) for k, v in regime_stats.items()},
        "walk_forward": {k: asdict(v) for k, v in wf_stats.items()},
        "cost_stress": stress_stats,
        "elapsed_seconds": time.time() - t_start,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    def _json_serial(obj):
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, (np.floating, float)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return str(obj)

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report_data, fh, indent=2, default=_json_serial)

    print(f" Full institutional audit report saved to: {output_path} (Completed in {time.time()-t_start:.1f}s)")
    print("=" * 105 + "\n")
    return report_data


def _pf_calc(vals: Sequence[float]) -> float:
    w = sum(x for x in vals if x > 0)
    l = -sum(x for x in vals if x < 0)
    return round(w / l, 2) if l > 0 else 999.0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Candidate V9 15m Institutional Backtest")
    parser.add_argument("--dataset", default="1year", choices=["1year", "4year"], help="Dataset range (default: 1year)")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="Path to cache")
    parser.add_argument("--friction-r", type=float, default=0.026, help="Friction in R (default: 0.026)")
    parser.add_argument("--min-score", type=int, default=5, help="Min opportunity score (default: 5)")
    parser.add_argument("--min-confirmations", type=int, default=1, help="Min confirmations (default: 1)")
    parser.add_argument("--output", default="backtests/v9_institutional_backtest_report.json", help="Output JSON path")
    args = parser.parse_args()

    run_v9_institutional_audit(
        cache_dir=args.cache_dir,
        dataset_type=args.dataset,
        friction_r=args.friction_r,
        min_score=args.min_score,
        min_confirmations=args.min_confirmations,
        output_path=args.output,
    )
