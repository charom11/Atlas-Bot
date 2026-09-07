#!/usr/bin/env python3
"""
==========================================================================================
⚡ STRATEGY CANDIDATE V9.1: 15-MINUTE SELECTIVE ALPHA INSTITUTIONAL BACKTEST
==========================================================================================
Evaluates the pruned, regime-gated, and tiered Candidate V9.1 engine:
- Prunes toxic setups: LIQUIDITY_SWEEP, EXHAUSTION_REVERSAL.
- Gates weak regimes: RANGE and CHOP.
- Confirms FIB_OTE strictly with structural trend alignment.
- Tiered asset universe: Tier 1 (SUI, SOL, XRP), Tier 2 (BTC, DOGE, ETH).
- Asymmetric 2.50 ATR target calibration on TREND_CONTINUATION.
- Direct side-by-side comparative scorecard vs Candidate V9 baseline.
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
    summarize,
    report,
)
from strategy_candidate_v9_1 import (
    V91Config,
    PRUNED_SETUPS,
    TIER_1,
    TIER_2,
    TIER_3,
    asset_allowed,
    allowed_setups,
    backtest_frame,
    audit_summary,
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_data_cache")

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
]


def _backtest_worker(sym: str, df: pd.DataFrame, config: V91Config, friction_r: float):
    t0 = time.time()
    trades = backtest_frame(df, config=config, friction_r=friction_r)
    st = summarize(trades)
    return sym, trades, st, len(df), time.time() - t0


def run_v9_1_institutional_audit(
    cache_dir: str = CACHE_DIR,
    dataset_type: str = "1year",
    friction_r: float = 0.026,
    allow_tier_2: bool = True,
    allow_tier_3: bool = False,
    allow_fibonacci: bool = True,
    allow_mild_trend: bool = True,
    allow_high_vol: bool = True,
    output_path: str = "backtests/v9_1_institutional_backtest_report.json",
) -> dict:
    t_start = time.time()
    config = V91Config(
        allow_tier_2=allow_tier_2,
        allow_tier_3=allow_tier_3,
        allow_fibonacci=allow_fibonacci,
        allow_mild_trend=allow_mild_trend,
        allow_high_vol=allow_high_vol,
    )

    print("=" * 105)
    print(" [AUDIT] STRATEGY CANDIDATE V9.1: 15-MINUTE SELECTIVE ALPHA INSTITUTIONAL BACKTEST")
    print("=" * 105)
    print(f" • Dataset Configuration:  15m Resolution ({dataset_type.upper()})")
    print(f" • Active Tiers:           Tier 1: {list(TIER_1)} | Tier 2: {list(TIER_2) if allow_tier_2 else 'DISABLED'} | Tier 3: {'ENABLED' if allow_tier_3 else 'GATED'}")
    print(f" • Pruned Setups:          {sorted(list(PRUNED_SETUPS))} (Gated completely)")
    print(f" • Hard-Gated Regimes:     RANGE, CHOP (0 trades allowed)")
    print(f" • Asymmetric Target:      TREND_CONTINUATION: 2.50x ATR Target | Base: 2.00x ATR | SL: 1.25x ATR")
    print(f" • Friction Model:         {friction_r} R per trade (VIP0 conservative)")
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
    print(f" Simulating V9.1 execution across universe with {workers} parallel workers...")
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_backtest_worker, sym, df, config, friction_r): sym
            for sym, df in asset_dfs.items()
        }
        for f in concurrent.futures.as_completed(futures):
            sym, trades, st, n_bars, dur = f.result()
            all_trades.extend(trades)
            asset_stats[sym] = st
            status = "🟢" if st.net_r > 0 else ("🟡" if st.trades == 0 else "🔴")
            print(f"  -> {sym:<10} | Bars: {n_bars:>7,} | Trades: {st.trades:>6,} | WR: {st.win_rate*100:>5.1f}% | PF: {st.profit_factor:>5.2f} | Net R: {st.net_r:>+8.2f} {status} | ({dur:.1f}s)")

    portfolio_stats = summarize(all_trades)

    # -------------------------------------------------------------------------
    # Audit 1: Overall Portfolio Summary
    # -------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print(" [AUDIT 1] CANDIDATE V9.1 15M PORTFOLIO BENCHMARK SUMMARY")
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

    setup_stats = {}
    for setup in SETUPS:
        s_trades = [t for t in all_trades if t.setup == setup]
        st = summarize(s_trades)
        setup_stats[setup] = st
        status = "🟢" if st.net_r > 0 else ("🛡️ GATED" if st.trades == 0 else "🔴")
        print(f" {setup:<25} | {st.trades:>8,} | {st.win_rate*100:>8.1f}% | {st.profit_factor:>6.2f} | {st.net_r:>+10.2f} | {st.expectancy_r:>+9.4f} | {st.avg_bars_held:>8.1f}b {status}")
    print("-" * 85 + "\n")

    # -------------------------------------------------------------------------
    # Audit 3: 15m Market Regime Performance Matrix
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 3] 15M MARKET REGIME PERFORMANCE MATRIX")
    print("=" * 105)
    print(f" {'Market Regime':<20} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9}")
    print("-" * 75)

    regime_stats = {}
    for regime in REGIMES:
        r_trades = [t for t in all_trades if t.regime == regime]
        st = summarize(r_trades)
        regime_stats[regime] = st
        status = "🟢" if st.net_r > 0 else ("🛡️ GATED" if st.trades == 0 else "🔴")
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
        print(f" {label:<25} | {len(stressed_vals):>8,} | {wins/len(stressed_vals)*100 if stressed_vals else 0:>8.1f}% | {st_pf:>6.2f} | {net_r_val:>+10.2f} | {exp_val:>+9.4f}")
        stress_stats[label] = {
            "friction_r": c_frict,
            "trades": len(stressed_vals),
            "profit_factor": st_pf,
            "net_r": net_r_val,
            "expectancy_r": exp_val,
        }
    print("-" * 75 + "\n")

    # -------------------------------------------------------------------------
    # Audit 6: Candidate V9 Baseline vs Candidate V9.1 Comparative Delta
    # -------------------------------------------------------------------------
    v9_report_path = f"backtests/v9_institutional_backtest_report{'_4year' if dataset_type == '4year' else ''}.json"
    if os.path.exists(v9_report_path):
        try:
            with open(v9_report_path, "r", encoding="utf-8") as f:
                v9_rep = json.load(f)
            v9_port = v9_rep.get("portfolio", {})
            print("=" * 105)
            print(" [AUDIT 6] V9 BASELINE VS V9.1 SELECTIVE OPTIMIZER COMPARATIVE DELTA")
            print("=" * 105)
            print(f" {'Metric':<25} | {'V9 Baseline':>15} | {'V9.1 Pruned':>15} | {'Delta':>15}")
            print("-" * 75)
            t_diff = portfolio_stats.trades - v9_port.get("trades", 0)
            pf_diff = portfolio_stats.profit_factor - v9_port.get("profit_factor", 0.0)
            net_diff = portfolio_stats.net_r - v9_port.get("net_r", 0.0)
            dd_diff = portfolio_stats.max_drawdown_r - v9_port.get("max_drawdown_r", 0.0)
            print(f" {'Total Trades':<25} | {v9_port.get('trades', 0):>15,} | {portfolio_stats.trades:>15,} | {t_diff:>+15,} ({t_diff/max(v9_port.get('trades', 1), 1)*100:+.1f}%)")
            print(f" {'Win Rate':<25} | {v9_port.get('win_rate', 0.0)*100:>14.1f}% | {portfolio_stats.win_rate*100:>14.1f}% | {portfolio_stats.win_rate*100 - v9_port.get('win_rate', 0.0)*100:>+14.1f}%")
            print(f" {'Profit Factor':<25} | {v9_port.get('profit_factor', 0.0):>15.2f} | {portfolio_stats.profit_factor:>15.2f} | {pf_diff:>+15.2f}")
            print(f" {'Net Realized R':<25} | {v9_port.get('net_r', 0.0):>+14.2f} R | {portfolio_stats.net_r:>+14.2f} R | {net_diff:>+14.2f} R")
            print(f" {'Max Drawdown (R)':<25} | {v9_port.get('max_drawdown_r', 0.0):>14.2f} R | {portfolio_stats.max_drawdown_r:>14.2f} R | {dd_diff:>+14.2f} R ({dd_diff/max(v9_port.get('max_drawdown_r', 1), 1)*100:+.1f}%)")
            print("-" * 75 + "\n")
        except Exception as e:
            print(f"Note: Could not compare against V9 baseline report: {e}")

    report_data = {
        "candidate": "V9.1",
        "dataset": dataset_type,
        "config": asdict(config),
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

    print(f" Full V9.1 institutional audit report saved to: {output_path} (Completed in {time.time()-t_start:.1f}s)")
    print("=" * 105 + "\n")
    return report_data


def _pf_calc(vals: Sequence[float]) -> float:
    w = sum(x for x in vals if x > 0)
    l = -sum(x for x in vals if x < 0)
    return round(w / l, 2) if l > 0 else 999.0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Candidate V9.1 15m Institutional Backtest")
    parser.add_argument("--dataset", default="1year", choices=["1year", "4year"], help="Dataset range (default: 1year)")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="Path to cache")
    parser.add_argument("--friction-r", type=float, default=0.026, help="Friction in R (default: 0.026)")
    parser.add_argument("--no-tier2", action="store_true", help="Disable Tier 2 assets (trade Tier 1 only)")
    parser.add_argument("--tier3", action="store_true", help="Enable Tier 3 assets")
    parser.add_argument("--no-fib", action="store_true", help="Disable FIB_OTE completely")
    parser.add_argument("--no-mild-trend", action="store_true", help="Disable MILD_TREND regime")
    parser.add_argument("--no-high-vol", action="store_true", help="Disable HIGH_VOL regime")
    parser.add_argument("--output", default="backtests/v9_1_institutional_backtest_report.json", help="Output JSON path")
    args = parser.parse_args()

    run_v9_1_institutional_audit(
        cache_dir=args.cache_dir,
        dataset_type=args.dataset,
        friction_r=args.friction_r,
        allow_tier_2=not args.no_tier2,
        allow_tier_3=args.tier3,
        allow_fibonacci=not args.no_fib,
        allow_mild_trend=not args.no_mild_trend,
        allow_high_vol=not args.no_high_vol,
        output_path=args.output,
    )
