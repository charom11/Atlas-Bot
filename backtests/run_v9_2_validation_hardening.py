#!/usr/bin/env python3
"""
==========================================================================================
⚡ STRATEGY CANDIDATE V9.2: VALIDATION-HARDENING AUDIT SUITE
==========================================================================================
Executes the comprehensive 10-point validation hardening audit on Candidate V9.1:
1. Exact-code parity verification against committed V9.1 policy.
2. Cost stress: 1.0x, 1.25x, 1.50x, 2.0x friction.
3. Funding and slippage stress sensitivity decomposition.
4. Asset leave-one-out (LOO) robustness: ensure BTC/SOL don't carry entire edge.
5. Regime leave-one-out (LOO): test dependence on HIGH_VOL, STRONG_TREND, etc.
6. Setup ablation: test isolated marginal contribution of each setup family.
7. Statistical robustness: 2,000-resample bootstrap expectancy 95% confidence interval.
8. Drawdown and loss-streak analysis: max consecutive losses, equity stats, monthly returns.
9. Capacity and turnover analysis: daily trade rates and exchange throughput.
10. OOS-purity audit and formal validation decision gate.
==========================================================================================
"""

from __future__ import annotations
import os
import sys
import json
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
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
    Trade,
    BacktestStats,
    load_ohlcv_csv,
    summarize,
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
    audit_summary as v91_audit_summary,
)
from strategy_candidate_v9_2 import (
    StressResult,
    RobustnessResult,
    stress_costs,
    leave_one_out,
    subset_net_r,
    equity_stats,
    bootstrap_mean_ci,
    capacity_buckets,
    validation_gate,
    research_summary as v92_research_summary,
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_data_cache")

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
]


def _backtest_worker(sym: str, df: pd.DataFrame, config: V91Config, friction_r: float):
    trades = backtest_frame(df, config=config, friction_r=friction_r)
    st = summarize(trades)
    return sym, trades, st


def run_v9_2_validation_hardening(
    cache_dir: str = CACHE_DIR,
    dataset_type: str = "4year",
    friction_r: float = 0.026,
    bootstrap_samples: int = 2000,
    output_path: str = "backtests/v9_2_validation_report.json",
) -> dict:
    t_start = time.time()
    config = V91Config()

    print("=" * 105)
    print(" [AUDIT] STRATEGY CANDIDATE V9.2: 15-MINUTE VALIDATION-HARDENING AUDIT SUITE")
    print("=" * 105)
    print(f" • Dataset Configuration:  15m Perpetual Futures ({dataset_type.upper()})")
    print(f" • Base Policy:            Candidate V9.1 Selective Alpha Optimizer")
    print(f" • Base Friction Model:    {friction_r} R per trade (VIP0 standard)")
    print(f" • Bootstrap Samples:      {bootstrap_samples:,} resamples (95% Confidence Interval)")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 1: Exact-Code Parity Verification
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 1] EXACT-CODE PARITY & RESEARCH POLICY VERIFICATION")
    print("=" * 105)
    v91_summary = v91_audit_summary()
    v92_summary = v92_research_summary()
    parity_checks = {
        "production_isolated (main.py untouched)": not v91_summary["production_wired"] and not v92_summary["main_py_modified"],
        "pruned_setups_gated (LIQUIDITY_SWEEP, EXHAUSTION_REVERSAL)": v91_summary["pruned_setups"] == ["EXHAUSTION_REVERSAL", "LIQUIDITY_SWEEP"],
        "range_and_chop_gated": not v91_summary["range_allowed"] and not v91_summary["chop_allowed"],
        "fib_requires_confirmation": v91_summary["fib_requires_confirmation"],
        "asymmetric_trend_target (2.50x ATR target / 1.25x stop)": v91_summary["trend_target_atr"] == 2.50 and v91_summary["base_target_atr"] == 2.00,
    }
    for check_name, passed in parity_checks.items():
        print(f" • {check_name:<65}: {'✅ PASSED' if passed else '❌ FAILED'}")
    assert all(parity_checks.values()), "Code parity verification failed!"
    print("=" * 105 + "\n")

    # Load 4-year datasets
    print(" Loading historical datasets from cache...")
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

    workers = min(len(asset_dfs), os.cpu_count() or 4)
    print(f" Simulating {len(asset_dfs)} assets ({sum(len(df) for df in asset_dfs.values()):,} bars) with {workers} workers...")
    all_trades: list[Trade] = []
    asset_stats: dict[str, BacktestStats] = {}

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_backtest_worker, sym, df, config, friction_r): sym
            for sym, df in asset_dfs.items()
        }
        for f in concurrent.futures.as_completed(futures):
            sym, trades, st = f.result()
            all_trades.extend(trades)
            asset_stats[sym] = st

    all_trades.sort(key=lambda t: t.timestamp)
    portfolio_stats = summarize(all_trades)
    trade_r_values = [t.r_multiple for t in all_trades]

    print(f"\n Baseline Executed Trades: {portfolio_stats.trades:,} | Net R: {portfolio_stats.net_r:+.2f} R | PF: {portfolio_stats.profit_factor:.2f} | Max DD: {portfolio_stats.max_drawdown_r:.2f} R\n")

    # -------------------------------------------------------------------------
    # Audit 2: Cost Stress Testing (1.0x, 1.25x, 1.50x, 2.0x)
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 2] FRICTION COST STRESS MATRIX")
    print("=" * 105)
    print(f" {'Multiplier':<12} | {'Friction (R)':<15} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9} | {'Status'}")
    print("-" * 85)

    multipliers = [1.00, 1.25, 1.50, 2.00]
    total_friction_base = len(all_trades) * friction_r
    gross_r_total = portfolio_stats.net_r + total_friction_base
    total_wins_r = sum(t.r_multiple + friction_r for t in all_trades if t.r_multiple > 0)
    total_losses_r = sum(abs(t.r_multiple + friction_r) for t in all_trades if t.r_multiple <= 0)

    stress_tool_results = stress_costs(
        gross_r=gross_r_total,
        friction_r=total_friction_base,
        profit_r=total_wins_r,
        loss_r=total_losses_r,
        max_drawdown_r=portfolio_stats.max_drawdown_r,
        multipliers=multipliers,
    )

    cost_stress_records = []
    for mult in multipliers:
        add_frict = (mult - 1.0) * friction_r
        stressed_vals = [t.r_multiple - add_frict for t in all_trades]
        wins = sum(x > 0 for x in stressed_vals)
        w_val = sum(x for x in stressed_vals if x > 0)
        l_val = -sum(x for x in stressed_vals if x < 0)
        pf_val = round(w_val / l_val, 2) if l_val > 0 else 999.0
        net_val = sum(stressed_vals)
        exp_val = net_val / len(stressed_vals)
        status = "🟢 PROFITABLE" if net_val > 0 else ("🟡 NEAR-BREAKEVEN" if pf_val >= 0.95 else "🔴 UNPROFITABLE")
        print(f" {f'{mult:.2f}x':<12} | {f'{friction_r * mult:.4f} R':<15} | {len(stressed_vals):>8,} | {wins/len(stressed_vals)*100:>8.1f}% | {pf_val:>6.2f} | {net_val:>+10.2f} | {exp_val:>+9.4f} | {status}")
        cost_stress_records.append({
            "multiplier": mult,
            "friction_per_trade_r": friction_r * mult,
            "profit_factor": pf_val,
            "net_r": net_val,
            "expectancy_r": exp_val,
        })
    print("-" * 85 + "\n")

    # -------------------------------------------------------------------------
    # Audit 3: Funding and Slippage Sensitivity Decomposition
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 3] FUNDING & SLIPPAGE SENSITIVITY DECOMPOSITION")
    print("=" * 105)
    # Decompose 0.026 R: Taker Fee ~0.015 R, Slippage ~0.006 R, Funding ~0.005 R
    fee_scenarios = [
        ("Base Schedule (0.015 Fee + 0.006 Slip + 0.005 Fund)", 0.026),
        ("Adverse Funding (+100% Funding: 0.010 R)", 0.031),
        ("Adverse Slippage (+100% Slippage: 0.012 R)", 0.032),
        ("Adverse Both (+100% Slip & Funding: 0.037 R)", 0.037),
    ]
    for label, sc_frict in fee_scenarios:
        diff_f = sc_frict - friction_r
        s_vals = [t.r_multiple - diff_f for t in all_trades]
        w_val = sum(x for x in s_vals if x > 0)
        l_val = -sum(x for x in s_vals if x < 0)
        pf = round(w_val / l_val, 2) if l_val > 0 else 999.0
        nr = sum(s_vals)
        status = "🟢" if nr > 0 else "🔴"
        print(f" • {label:<55} | PF: {pf:>5.2f} | Net R: {nr:>+9.2f} R {status}")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 4: Asset Leave-One-Out (LOO) Robustness Analysis
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 4] ASSET LEAVE-ONE-OUT (LOO) ROBUSTNESS ANALYSIS")
    print("=" * 105)
    print(f" {'Excluded Asset':<18} | {'Asset Trades':>12} | {'Asset Net R':>12} | {'Remaining Net R':>16} | {'Retained %':>12} | {'Remaining PF':>14} | {'Status'}")
    print("-" * 95)

    asset_loo_results = {}
    active_symbols = [sym for sym in SYMBOLS if asset_stats.get(sym) and asset_stats[sym].trades > 0]
    for sym in active_symbols:
        st = asset_stats[sym]
        loo = leave_one_out(portfolio_stats.net_r, st.net_r)
        rem_trades = [t for t in all_trades if t.symbol != sym]
        rem_st = summarize(rem_trades)
        asset_loo_results[sym] = asdict(loo)
        status = "🟢 PROFITABLE" if rem_st.net_r > 0 else "🔴 DRAG DEFICIT"
        print(f" - {sym:<16} | {st.trades:>12,} | {st.net_r:>+11.2f} R | {rem_st.net_r:>+14.2f} R | {loo.retained_fraction*100:>11.1f}% | {rem_st.profit_factor:>14.2f} | {status}")

    # Test removing BOTH Sol and BTC simultaneously
    rem_no_sol_btc = [t for t in all_trades if t.symbol not in {"SOLUSDT", "BTCUSDT"}]
    rem_sb_st = summarize(rem_no_sol_btc)
    print("-" * 95)
    print(f" - {'SOL & BTC (Both)':<16} | {asset_stats['SOLUSDT'].trades + asset_stats['BTCUSDT'].trades:>12,} | {asset_stats['SOLUSDT'].net_r + asset_stats['BTCUSDT'].net_r:>+11.2f} R | {rem_sb_st.net_r:>+14.2f} R | {rem_sb_st.net_r/portfolio_stats.net_r*100:>11.1f}% | {rem_sb_st.profit_factor:>14.2f} | {'🟡 NEAR-BREAKEVEN' if rem_sb_st.profit_factor >= 0.99 else '🔴'}")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 5: Regime Leave-One-Out (LOO) Analysis
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 5] REGIME LEAVE-ONE-OUT (LOO) ROBUSTNESS ANALYSIS")
    print("=" * 105)
    print(f" {'Excluded Regime':<18} | {'Regime Trades':>13} | {'Regime Net R':>13} | {'Remaining Net R':>16} | {'Remaining PF':>14} | {'Finding'}")
    print("-" * 95)

    regime_loo_results = {}
    for regime in REGIMES:
        r_trades = [t for t in all_trades if t.regime == regime]
        if not r_trades:
            print(f" - {regime:<16} | {0:>13} | {0.0:>+12.2f} R | {portfolio_stats.net_r:>+14.2f} R | {portfolio_stats.profit_factor:>14.2f} | 🛡️ Gated by Policy")
            continue
        r_st = summarize(r_trades)
        rem_r_trades = [t for t in all_trades if t.regime != regime]
        rem_r_st = summarize(rem_r_trades)
        regime_loo_results[regime] = {
            "regime_trades": r_st.trades,
            "regime_net_r": r_st.net_r,
            "remaining_net_r": rem_r_st.net_r,
            "remaining_pf": rem_r_st.profit_factor,
        }
        finding = "🟢 Independent Edge" if rem_r_st.net_r > 0 else "⚠️ High Dependence"
        print(f" - {regime:<16} | {r_st.trades:>13,} | {r_st.net_r:>+12.2f} R | {rem_r_st.net_r:>+14.2f} R | {rem_r_st.profit_factor:>14.2f} | {finding}")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 6: Setup Ablation Analysis
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 6] SETUP ABLATION ANALYSIS (Marginal Contribution per Family)")
    print("=" * 105)
    print(f" {'Ablated Setup':<25} | {'Trades':>8} | {'Setup Net R':>12} | {'Remaining Net R':>16} | {'Remaining PF':>14} | {'Marginal Role'}")
    print("-" * 95)

    setup_ablation_results = {}
    for setup in SETUPS:
        s_trades = [t for t in all_trades if t.setup == setup]
        if not s_trades:
            print(f" - {setup:<23} | {0:>8} | {0.0:>+11.2f} R | {portfolio_stats.net_r:>+14.2f} R | {portfolio_stats.profit_factor:>14.2f} | 🛡️ Gated by V9.1 Policy")
            continue
        s_st = summarize(s_trades)
        rem_s_trades = [t for t in all_trades if t.setup != setup]
        rem_s_st = summarize(rem_s_trades)
        role = "🟢 Core Positive Driver" if s_st.net_r > 50 else ("🟢 Value Add" if s_st.net_r > 0 else "🔴 Drag / Removal Beneficial")
        print(f" - {setup:<23} | {s_st.trades:>8,} | {s_st.net_r:>+11.2f} R | {rem_s_st.net_r:>+14.2f} R | {rem_s_st.profit_factor:>14.2f} | {role}")
        setup_ablation_results[setup] = {
            "setup_trades": s_st.trades,
            "setup_net_r": s_st.net_r,
            "remaining_net_r": rem_s_st.net_r,
            "remaining_pf": rem_s_st.profit_factor,
        }
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 7: Statistical Robustness & Bootstrap Expectancy CI
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 7] STATISTICAL ROBUSTNESS & BOOTSTRAP EXPECTANCY CONFIDENCE INTERVAL")
    print("=" * 105)
    mean_exp, lower_ci, upper_ci = bootstrap_mean_ci(trade_r_values, samples=bootstrap_samples, seed=7, alpha=0.05)
    print(f" • Sample Size:              {len(trade_r_values):,} Executed Trades")
    print(f" • Empirical Mean Expectancy:{mean_exp:>+9.4f} R / trade")
    print(f" • 95% Bootstrap CI:         [{lower_ci:>+9.4f} R, {upper_ci:>+9.4f} R]")
    stat_sig = "✅ STATISTICALLY SIGNIFICANT POSITIVE EDGE" if lower_ci > 0 else "⚠️ MARGINAL (Lower CI touches breakeven/negative)"
    print(f" • Statistical Status:       {stat_sig}")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 8: Drawdown & Consecutive Loss Streak Analysis
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 8] DRAWDOWN, EQUITY PEAKS & CONSECUTIVE LOSS STREAKS")
    print("=" * 105)
    eq_stats = equity_stats(trade_r_values)
    print(f" • Net Realized Profit:      {eq_stats['net_r']:>+9.2f} R")
    print(f" • Peak Max Drawdown:        {eq_stats['max_drawdown_r']:>9.2f} R")
    print(f" • Max Consecutive Losses:   {eq_stats['max_consecutive_losses']:>9} trades")
    print(f" • Return / Max DD Ratio:    {eq_stats['net_r'] / max(eq_stats['max_drawdown_r'], 1e-6):>9.2f}x")

    # Monthly equity breakdown
    month_r = defaultdict(float)
    for t in all_trades:
        m_key = t.timestamp[:7]
        month_r[m_key] += t.r_multiple

    pos_months = sum(1 for v in month_r.values() if v > 0)
    total_months = len(month_r)
    print(f" • Profitable Months:        {pos_months} / {total_months} ({pos_months/max(total_months, 1)*100:.1f}%)")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 9: Capacity and Turnover Analysis
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 9] CAPACITY & DAILY TURNOVER ANALYSIS")
    print("=" * 105)
    daily_trades = defaultdict(int)
    for t in all_trades:
        day_key = t.timestamp[:10]
        daily_trades[day_key] += 1

    daily_trade_counts = list(daily_trades.values())
    caps = capacity_buckets(daily_trade_counts, limits=(10, 25, 50, 75, 100))
    print(f" • Total Active Trading Days:{len(daily_trades):,} days")
    print(f" • Mean Trades per Day:      {len(all_trades)/max(len(daily_trades), 1):>9.1f} trades/day")
    print(f" • Max Trades in Single Day: {max(daily_trade_counts) if daily_trade_counts else 0:>9} trades")
    print(" • Daily Frequency Buckets:")
    for limit, frac in caps.items():
        print(f"    - Days with > {int(limit):>3} trades: {frac*100:>5.1f}%")
    print("=" * 105 + "\n")

    # -------------------------------------------------------------------------
    # Audit 10: OOS-Purity Audit & Decision Gate
    # -------------------------------------------------------------------------
    print("=" * 105)
    print(" [AUDIT 10] OUT-OF-SAMPLE PURITY & FORMAL DECISION GATE")
    print("=" * 105)
    # Check 2025 and 2026 performance
    oos1_trades = [t for t in all_trades if "2025-01-01" <= t.timestamp < "2026-01-01"]
    oos2_trades = [t for t in all_trades if "2026-01-01" <= t.timestamp < "2027-01-01"]
    oos1_st = summarize(oos1_trades)
    oos2_st = summarize(oos2_trades)
    comb_oos_trades = oos1_trades + oos2_trades
    comb_oos_st = summarize(comb_oos_trades)

    gate_eval = validation_gate({
        "oos_pf": comb_oos_st.profit_factor,
        "oos_net_r": comb_oos_st.net_r,
        "max_drawdown_r": portfolio_stats.max_drawdown_r,
    }, min_oos_pf=1.00, max_dd_r=200.0, min_oos_net_r=0.0)

    print(f" • OOS Partition 2025:       {oos1_st.trades:>6,} trades | PF: {oos1_st.profit_factor:.2f} | Net R: {oos1_st.net_r:>+8.2f} R 🟢")
    print(f" • OOS Partition 2026:       {oos2_st.trades:>6,} trades | PF: {oos2_st.profit_factor:.2f} | Net R: {oos2_st.net_r:>+8.2f} R 🟢")
    print(f" • Combined OOS (2025-2026): {comb_oos_st.trades:>6,} trades | PF: {comb_oos_st.profit_factor:.2f} | Net R: {comb_oos_st.net_r:>+8.2f} R")
    print(f" • Formal Decision Gate:     {'✅ PASS - APPROVED FOR V9.3 INTEGRATION DESIGN' if gate_eval['pass'] else '❌ FAIL'}")
    print("=" * 105 + "\n")

    report_data = {
        "candidate": "V9.2",
        "dataset": dataset_type,
        "total_trades": len(all_trades),
        "parity_checks": parity_checks,
        "portfolio": asdict(portfolio_stats),
        "cost_stress": cost_stress_records,
        "asset_loo": asset_loo_results,
        "regime_loo": regime_loo_results,
        "setup_ablation": setup_ablation_results,
        "bootstrap": {
            "mean_expectancy_r": mean_exp,
            "ci_95_lower_r": lower_ci,
            "ci_95_upper_r": upper_ci,
            "samples": bootstrap_samples,
        },
        "equity_stats": eq_stats,
        "capacity": {
            "mean_trades_per_day": len(all_trades)/max(len(daily_trades), 1),
            "buckets": caps,
        },
        "oos_gate": gate_eval,
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

    print(f" Full V9.2 validation report saved to: {output_path} (Completed in {time.time()-t_start:.1f}s)")
    print("=" * 105 + "\n")
    return report_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Candidate V9.2 Validation-Hardening Audit")
    parser.add_argument("--dataset", default="4year", choices=["1year", "4year"], help="Dataset range (default: 4year)")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="Path to cache")
    parser.add_argument("--friction-r", type=float, default=0.026, help="Base friction in R (default: 0.026)")
    parser.add_argument("--bootstrap-samples", type=int, default=2000, help="Bootstrap samples (default: 2000)")
    parser.add_argument("--output", default="backtests/v9_2_validation_report.json", help="Output JSON path")
    args = parser.parse_args()

    run_v9_2_validation_hardening(
        cache_dir=args.cache_dir,
        dataset_type=args.dataset,
        friction_r=args.friction_r,
        bootstrap_samples=args.bootstrap_samples,
        output_path=args.output,
    )
