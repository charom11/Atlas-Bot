#!/usr/bin/env python3
"""
==========================================================================================
⚡ STRATEGY CANDIDATE V9.4: ADAPTIVE VOLATILITY & BREAKEVEN-TRAILING INSTITUTIONAL BACKTEST
==========================================================================================
Evaluates Candidate V9.4 with:
- Active setups (4): TREND_CONTINUATION, BB_ATR_EXPANSION, MSS_SHIFT, BREAKOUT_RETEST
- Gated Setups: VWAP_TREND, PULLBACK_CONTINUATION, LIQUIDITY_SWEEP,
                EXHAUSTION_REVERSAL, VWAP_REVERSION, FIB_OTE
- Gated regimes: RANGE, CHOP, and BREAKDOWN
- Volatility band filter: normalized ATR in [0.0015, 0.0600]
- Regime-aware score requirement: MILD_TREND min_score >= 6
- Breakeven-trailing ratchet: arms at +1.0R favorable excursion
- Tiered assets: Tier 1 (SUI, SOL, XRP) & Tier 2 (BTC, DOGE, ETH)
==========================================================================================
"""

from __future__ import annotations
from dataclasses import asdict
import os
import sys
import json
import time
from pathlib import Path

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
    report,
)
from strategy_candidate_v9_4 import (
    V94Config,
    ACTIVE_SETUPS_V94,
    DISABLED_SETUPS_V94,
    ALLOWED_REGIMES_V94,
    GATED_REGIMES_V94,
    TIER_1,
    TIER_2,
    TIER_3,
    asset_allowed,
    backtest_frame_v94,
    integration_audit_summary,
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_data_cache")

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
]


def _backtest_worker(sym: str, df: pd.DataFrame, config: V94Config, friction_r: float):
    t0 = time.time()
    trades = backtest_frame_v94(df, config=config, friction_r=friction_r)
    st = summarize(trades)
    return sym, trades, st, len(df), time.time() - t0


def run_v9_4_institutional_audit(
    cache_dir: str = CACHE_DIR,
    dataset_type: str = "4year",
    friction_r: float = 0.026,
    output_path: str = "backtests/v9_4_integration_report.json",
) -> dict:
    t_start = time.time()
    config = V94Config()

    print("=" * 105)
    print(" [AUDIT] STRATEGY CANDIDATE V9.4: ADAPTIVE VOLATILITY & BREAKEVEN-TRAILING INSTITUTIONAL BACKTEST")
    print("=" * 105)
    print(f" • Dataset Configuration:  15m Resolution ({dataset_type.upper()})")
    print(f" • Active Setups (4):      {sorted(list(ACTIVE_SETUPS_V94))}")
    print(f" • Hard-Gated Regimes:     RANGE, CHOP, and BREAKDOWN")
    print(f" • Volatility Band:        [{config.atr_pct_floor:.4%}, {config.atr_pct_ceiling:.4%}]")
    print(f" • Mild Trend Score Gate:  min_score >= {config.mild_trend_min_score}")
    print(f" • Breakeven Trailing:     armed at +{config.breakeven_trigger_r:.2f}R")
    print(f" • Target Universe:        Tier 1 {list(TIER_1)} & Tier 2 {list(TIER_2)}")
    print(f" • Friction Model:         {friction_r} R per trade")
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

    workers = min(len(asset_dfs), os.cpu_count() or 4)
    print(f" Simulating V9.4 execution across universe with {workers} parallel workers...")
    all_trades: list[Trade] = []
    asset_stats: dict[str, BacktestStats] = {}

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_backtest_worker, sym, df, config, friction_r): sym
            for sym, df in asset_dfs.items()
        }
        for future in concurrent.futures.as_completed(futures):
            sym, trades, st, bars_cnt, elapsed = future.result()
            all_trades.extend(trades)
            asset_stats[sym] = st
            tier = "Tier 1" if sym in TIER_1 else ("Tier 2" if sym in TIER_2 else "Tier 3 (Gated)")
            print(f"   ✓ {sym:<8} ({tier:<14}) | {bars_cnt:>8,} bars | Trades: {st.trades:>5} | Net R: {st.net_r:>+8.2f} R | WR: {st.win_rate*100:>5.1f}% | PF: {st.profit_factor:>5.2f} | MaxDD: {st.max_drawdown_r:>6.2f} R ({elapsed:.1f}s)")

    # Global Portfolio Aggregation
    portfolio_stats = summarize(all_trades)
    print("\n" + "=" * 105)
    print(f" 📊 CANDIDATE V9.4 PORTFOLIO SUMMARY ({dataset_type.upper()})")
    print("=" * 105)
    print(f" Total Trades Resolved:   {portfolio_stats.trades:,}")
    print(f" Win Rate:                {portfolio_stats.win_rate*100:.2f}%")
    print(f" Net PnL (R):             {portfolio_stats.net_r:+.2f} R")
    print(f" Profit Factor:           {portfolio_stats.profit_factor:.2f}")
    print(f" Expectancy / Trade:      {portfolio_stats.expectancy_r:+.4f} R")
    print(f" Max Portfolio Drawdown:  {portfolio_stats.max_drawdown_r:.2f} R")
    print(f" Avg Bars Held:           {portfolio_stats.avg_bars_held:.1f} bars (~{portfolio_stats.avg_bars_held*15:.0f} mins)")
    print("=" * 105 + "\n")

    # Granular Setup Breakdown
    print(" 🎯 Setup Performance Breakdown:")
    print("-" * 75)
    setup_stats: dict[str, BacktestStats] = {}
    for s in sorted(list(ACTIVE_SETUPS_V94)):
        s_trades = [t for t in all_trades if t.setup == s]
        st = summarize(s_trades)
        setup_stats[s] = st
        print(f"   • {s:<24} | Trades: {st.trades:>5} | Net R: {st.net_r:>+8.2f} R | WR: {st.win_rate*100:>5.1f}% | PF: {st.profit_factor:>5.2f}")
    print("-" * 75 + "\n")

    # Granular Regime Breakdown
    print(" 🌊 Regime Performance Breakdown:")
    print("-" * 75)
    regime_stats: dict[str, BacktestStats] = {}
    for r in sorted(list(ALLOWED_REGIMES_V94)):
        r_trades = [t for t in all_trades if t.regime == r]
        st = summarize(r_trades)
        regime_stats[r] = st
        print(f"   • {r:<24} | Trades: {st.trades:>5} | Net R: {st.net_r:>+8.2f} R | WR: {st.win_rate*100:>5.1f}% | PF: {st.profit_factor:>5.2f}")
    print("-" * 75 + "\n")

    # Walk-forward period slicing
    print(" 📅 Annual Walk-Forward Analysis:")
    print("-" * 75)
    wf_stats: dict[str, BacktestStats] = {}
    periods = [
        ("Y2022_H2", "2022-09-01", "2023-01-01"),
        ("Y2023",    "2023-01-01", "2024-01-01"),
        ("Y2024",    "2024-01-01", "2025-01-01"),
        ("Y2025",    "2025-01-01", "2026-01-01"),
        ("Y2026_YTD","2026-01-01", "2026-12-31"),
    ]
    for p_name, p_start, p_end in periods:
        p_trades = [
            t for t in all_trades
            if p_start <= str(t.timestamp)[:10] < p_end
        ]
        st = summarize(p_trades)
        wf_stats[p_name] = st
        print(f"   • {p_name:<12} | Trades: {st.trades:>5} | Net R: {st.net_r:>+8.2f} R | WR: {st.win_rate*100:>5.1f}% | PF: {st.profit_factor:>5.2f} | MaxDD: {st.max_drawdown_r:>6.2f} R")
    print("-" * 75 + "\n")

    report_data = {
        "candidate": "V9.4",
        "dataset": dataset_type,
        "config": asdict(config),
        "audit_summary": integration_audit_summary(),
        "portfolio": asdict(portfolio_stats),
        "by_asset": {k: asdict(v) for k, v in asset_stats.items()},
        "by_setup": {k: asdict(v) for k, v in setup_stats.items()},
        "by_regime": {k: asdict(v) for k, v in regime_stats.items()},
        "walk_forward": {k: asdict(v) for k, v in wf_stats.items()},
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

    print(f" Full V9.4 integration audit report saved to: {output_path} (Completed in {time.time()-t_start:.1f}s)")
    print("=" * 105 + "\n")
    return report_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Candidate V9.4 Institutional Backtest")
    parser.add_argument("--dataset", default="4year", choices=["1year", "4year"], help="Dataset range (default: 4year)")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="Path to cache")
    parser.add_argument("--friction-r", type=float, default=0.026, help="Friction in R (default: 0.026)")
    parser.add_argument("--output", default="backtests/v9_4_integration_report.json", help="Output JSON path")
    args = parser.parse_args()

    run_v9_4_institutional_audit(
        cache_dir=args.cache_dir,
        dataset_type=args.dataset,
        friction_r=args.friction_r,
        output_path=args.output,
    )
