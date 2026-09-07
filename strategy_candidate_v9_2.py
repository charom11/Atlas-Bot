"""Offline Strategy Candidate V9.2: validation-hardening toolkit.

Research-only. V9.2 does not add indicators or modify main.py. It provides
small, deterministic helpers for robustness validation of the V9.1 policy.

The toolkit is intentionally data-agnostic: callers supply completed trade
records or metric mappings from an isolated backtest runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Iterable, Mapping, Sequence


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
    """Recompute net R and PF under friction multipliers.

    profit_r/loss_r are the absolute positive/negative gross outcome pools.
    """
    if friction_r < 0 or profit_r < 0 or loss_r < 0:
        raise ValueError("R pools must be non-negative")
    results = []
    for multiplier in multipliers:
        if multiplier < 0:
            raise ValueError("cost multiplier must be non-negative")
        net = gross_r - friction_r * multiplier
        pf = profit_r / loss_r if loss_r else float("inf")
        results.append(StressResult(float(multiplier), net, pf, max_drawdown_r + max(0.0, friction_r * (multiplier - 1.0))))
    return results


def leave_one_out(total_net_r: float, excluded_net_r: float) -> RobustnessResult:
    """Measure portfolio robustness after removing one component."""
    remaining = total_net_r - excluded_net_r
    retained = remaining / total_net_r if total_net_r else 0.0
    return RobustnessResult(total_net_r, remaining, remaining - total_net_r, retained)


def subset_net_r(total_net_r: float, excluded_components: Iterable[float]) -> float:
    """Return net R after removing known component contributions."""
    return total_net_r - sum(float(x) for x in excluded_components)


def equity_stats(trades_r: Iterable[float]) -> dict[str, float | int]:
    """Calculate drawdown and loss-streak statistics from completed trade R."""
    values = [float(x) for x in trades_r]
    equity = peak = 0.0
    max_dd = 0.0
    max_loss_streak = loss_streak = 0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if value < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0
    return {"trades": len(values), "net_r": sum(values), "max_drawdown_r": max_dd,
            "max_consecutive_losses": max_loss_streak}


def bootstrap_mean_ci(trades_r: Sequence[float], samples: int = 2000,
                      seed: int = 7, alpha: float = 0.05) -> tuple[float, float, float]:
    """Deterministic bootstrap CI for mean trade expectancy."""
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
    means = [mean(rng.choice(values) for _ in range(n)) for _ in range(samples)]
    means.sort()
    lo = means[int((alpha / 2) * samples)]
    hi = means[min(samples - 1, int((1 - alpha / 2) * samples))]
    return mean(values), lo, hi


def capacity_buckets(trades_per_day: Sequence[float], limits: Sequence[float] = (5, 10, 20, 30)) -> dict[float, float]:
    """Return the fraction of observed days exceeding each trade-rate limit."""
    values = [float(x) for x in trades_per_day]
    if not values:
        return {float(limit): 0.0 for limit in limits}
    return {float(limit): sum(x > limit for x in values) / len(values) for limit in limits}


def validation_gate(metrics: Mapping[str, float], *, min_oos_pf: float = 1.0,
                    max_dd_r: float | None = None, min_oos_net_r: float = 0.0) -> dict[str, object]:
    """Apply conservative, explicit V9.2 acceptance checks."""
    oos_pf = float(metrics.get("oos_pf", 0.0))
    oos_net = float(metrics.get("oos_net_r", 0.0))
    dd = float(metrics.get("max_drawdown_r", float("inf")))
    checks = {
        "oos_pf": oos_pf >= min_oos_pf,
        "oos_net_r": oos_net > min_oos_net_r,
        "drawdown": max_dd_r is None or dd <= max_dd_r,
    }
    return {"pass": all(checks.values()), "checks": checks}


def research_summary() -> dict[str, object]:
    return {
        "research_only": True,
        "main_py_modified": False,
        "live_execution": False,
        "validation_focus": [
            "cost_stress", "asset_leave_one_out", "regime_leave_one_out",
            "setup_ablation", "bootstrap_expectancy", "loss_streaks", "capacity",
        ],
        "recommended_oos_pf_floor": 1.00,
    }
