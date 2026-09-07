"""Offline Strategy Candidate V9.2: validation-hardening toolkit.

Research-only. V9.2 does not add indicators or modify main.py. It provides
small, deterministic helpers for robustness validation of the V9.1 policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable, Mapping, Sequence

from strategy_candidate_v9 import (
    LONG,
    SHORT,
    FLAT,
    SETUPS,
    REGIMES,
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
    walk_forward,
)

@dataclass(frozen=True)
class StressResult:
    multiplier: float
    net_r: float
    profit_factor: float
    max_drawdown_r: float

@dataclass(frozen=True)
class RobustnessResult:
    baseline_net_r: float
    remaining_net_r: float
    delta_r: float
    retained_fraction: float

def stress_costs(gross_r: float, friction_r: float, profit_r: float, loss_r: float,
                 max_drawdown_r: float, multipliers: Sequence[float] = (1.0, 1.25, 1.5, 2.0)) -> list[StressResult]:
    if friction_r < 0 or profit_r < 0 or loss_r < 0:
        raise ValueError("R pools must be non-negative")
    out = []
    for multiplier in multipliers:
        if multiplier < 0:
            raise ValueError("cost multiplier must be non-negative")
        out.append(StressResult(float(multiplier), gross_r - friction_r * multiplier,
                                profit_r / loss_r if loss_r else float("inf"),
                                max_drawdown_r + max(0.0, friction_r * (multiplier - 1.0))))
    return out

def leave_one_out(total_net_r: float, excluded_net_r: float) -> RobustnessResult:
    remaining = total_net_r - excluded_net_r
    return RobustnessResult(total_net_r, remaining, remaining - total_net_r,
                            remaining / total_net_r if total_net_r else 0.0)

def subset_net_r(total_net_r: float, excluded_components: Iterable[float]) -> float:
    return total_net_r - sum(float(x) for x in excluded_components)

def equity_stats(trades_r: Iterable[float]) -> dict[str, float | int]:
    values = [float(x) for x in trades_r]
    equity = peak = max_dd = 0.0
    streak = max_streak = 0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if value < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {"trades": len(values), "net_r": sum(values), "max_drawdown_r": max_dd,
            "max_consecutive_losses": max_streak}

def bootstrap_mean_ci(trades_r: Sequence[float], samples: int = 2000,
                      seed: int = 7, alpha: float = 0.05) -> tuple[float, float, float]:
    values = [float(x) for x in trades_r]
    if not values:
        raise ValueError("trades_r cannot be empty")
    if samples < 100:
        raise ValueError("samples must be >= 100")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    import random
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean(rng.choice(values) for _ in range(n)) for _ in range(samples))
    return mean(values), means[int(alpha / 2 * samples)], means[min(samples - 1, int((1 - alpha / 2) * samples))]

def capacity_buckets(trades_per_day: Sequence[float], limits: Sequence[float] = (5, 10, 20, 30)) -> dict[float, float]:
    values = [float(x) for x in trades_per_day]
    return {float(limit): (sum(x > limit for x in values) / len(values) if values else 0.0) for limit in limits}

def validation_gate(metrics: Mapping[str, float], *, min_oos_pf: float = 1.0,
                    max_dd_r: float | None = None, min_oos_net_r: float = 0.0) -> dict[str, object]:
    oos_pf = float(metrics.get("oos_pf", 0.0))
    oos_net = float(metrics.get("oos_net_r", 0.0))
    dd = float(metrics.get("max_drawdown_r", float("inf")))
    checks = {"oos_pf": oos_pf >= min_oos_pf, "oos_net_r": oos_net > min_oos_net_r,
              "drawdown": max_dd_r is None or dd <= max_dd_r}
    return {"pass": all(checks.values()), "checks": checks}

def research_summary() -> dict[str, object]:
    return {"research_only": True, "main_py_modified": False, "live_execution": False,
            "validation_focus": ["cost_stress", "asset_leave_one_out", "regime_leave_one_out",
                                  "setup_ablation", "bootstrap_expectancy", "loss_streaks", "capacity"],
            "recommended_oos_pf_floor": 1.00}


def run_v9_2_audit(
    dataset: str = "4year",
    friction_r: float = 0.026,
    bootstrap_samples: int = 2000,
    output: str = "backtests/v9_2_validation_report.json",
) -> dict:
    from backtests.run_v9_2_validation_hardening import run_v9_2_validation_hardening
    return run_v9_2_validation_hardening(
        dataset_type=dataset,
        friction_r=friction_r,
        bootstrap_samples=bootstrap_samples,
        output_path=output,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Strategy Candidate V9.2 Validation-Hardening Backtester")
    parser.add_argument("--dataset", default="4year", choices=["1year", "4year"], help="Dataset range (default: 4year)")
    parser.add_argument("--friction-r", type=float, default=0.026, help="Base friction in R (default: 0.026)")
    parser.add_argument("--bootstrap-samples", type=int, default=2000, help="Bootstrap resamples (default: 2000)")
    parser.add_argument("--output", default="backtests/v9_2_validation_report.json", help="Output JSON path")
    args = parser.parse_args()

    run_v9_2_audit(
        dataset=args.dataset,
        friction_r=args.friction_r,
        bootstrap_samples=args.bootstrap_samples,
        output=args.output,
    )

