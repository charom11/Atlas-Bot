#!/usr/bin/env python3
"""V9.3.1 four-year 15m historical data backtest entrypoint.

This is a thin, research-only entrypoint for running the exact V9.3.1 shadow
observer replay against the repository's four-year OHLCV cache and producing a
comparison against the stored institutional V9.3.1 report when available.

No exchange client, network request, live order, or main.py integration is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtests.run_v9_3_1_shadow_observer_backtest import run


def _get(d: dict, *keys, default=0.0):
    cur = d
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def compare(result: dict, reference_path: Path) -> dict:
    current = result.get("portfolio", {})
    reference = {}
    if reference_path.exists():
        reference = json.loads(reference_path.read_text(encoding="utf-8")).get("portfolio", {})

    fields = {
        "trades": (current.get("trades", 0), reference.get("trades", 0)),
        "win_rate": (current.get("win_rate", 0.0), reference.get("win_rate", 0.0)),
        "profit_factor": (current.get("profit_factor", 0.0), reference.get("profit_factor", 0.0)),
        "net_r": (current.get("net_r", 0.0), reference.get("net_r", 0.0)),
        "expectancy_r": (current.get("expectancy_r", 0.0), reference.get("expectancy_r", 0.0)),
        "max_drawdown_r": (current.get("max_drawdown_r", 0.0), reference.get("max_drawdown_r", 0.0)),
    }

    comparison = {}
    for name, (observer, institutional) in fields.items():
        comparison[name] = {
            "observer_replay": observer,
            "institutional_reference": institutional,
            "difference_observer_minus_reference": observer - institutional,
        }

    return {
        "reference_exists": reference_path.exists(),
        "reference_path": str(reference_path),
        "comparison": comparison,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the V9.3.1 4-year 15m shadow-observer historical data backtest"
    )
    parser.add_argument(
        "--cache-dir",
        default="backtests/historical_data_cache",
        help="Four-year OHLCV cache directory",
    )
    parser.add_argument(
        "--output",
        default="backtests/v9_3_1_4year_data_backtest_report.json",
        help="Observer replay output JSON",
    )
    parser.add_argument(
        "--reference",
        default="backtests/v9_3_1_integration_report.json",
        help="Stored institutional V9.3.1 report for side-by-side comparison",
    )
    parser.add_argument(
        "--friction-r",
        type=float,
        default=0.026,
        help="Friction charged per trade in R",
    )
    args = parser.parse_args()

    output = Path(args.output)
    result = run("4year", Path(args.cache_dir), output, args.friction_r)
    comparison = compare(result, Path(args.reference))

    result["institutional_comparison"] = comparison
    output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    p = result["portfolio"]
    print("\n" + "=" * 88)
    print("V9.3.1 — FOUR-YEAR 15M DATA BACKTEST / OBSERVER REPLAY")
    print("=" * 88)
    print(f"Observer replay : {p.get('trades', 0):,} trades | PF {p.get('profit_factor', 0):.2f} | Net {p.get('net_r', 0):+.2f}R")
    print(f"Expectancy      : {p.get('expectancy_r', 0):+.4f}R | Max DD {p.get('max_drawdown_r', 0):.2f}R")

    if comparison["reference_exists"]:
        print("\nInstitutional reference vs observer replay:")
        for name, values in comparison["comparison"].items():
            print(
                f"  {name:<18} observer={values['observer_replay']} | "
                f"reference={values['institutional_reference']} | "
                f"delta={values['difference_observer_minus_reference']:+.6f}"
            )
    else:
        print(f"\nNo institutional reference found at: {args.reference}")

    print(f"\nSaved: {output}")
    print("This run is research-only; it does not modify main.py or place orders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
