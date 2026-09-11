"""Account-level risk guardrails for Atlas-Bot.

Pure, side-effect-free checks intended to run immediately before order submission.
The guard fails closed: invalid or unavailable account inputs raise rather than
being interpreted as zero exposure.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Optional


class RiskLimitBreached(RuntimeError):
    """Raised when an order would exceed an account-level risk limit."""


class RiskStateUnavailable(RuntimeError):
    """Raised when required account/position state is missing or invalid."""


@dataclass(frozen=True)
class RiskLimits:
    max_leverage: float = 10.0
    max_positions: int = 3
    max_margin_utilization: float = 0.10
    max_total_notional_pct: float = 1.00
    max_daily_loss_pct: float = 0.05

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_leverage) or self.max_leverage <= 0:
            raise ValueError("max_leverage must be finite and positive")
        if self.max_positions < 1:
            raise ValueError("max_positions must be at least 1")
        for name in ("max_margin_utilization", "max_total_notional_pct", "max_daily_loss_pct"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0 or value > 1:
                raise ValueError(f"{name} must be in (0, 1]")


def _finite_positive(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise RiskStateUnavailable(f"{name} is not numeric")
    if not math.isfinite(result) or result <= 0:
        raise RiskStateUnavailable(f"{name} must be finite and positive")
    return result


def validate_order_risk(
    *,
    equity: float,
    existing_notional: float,
    existing_margin: float,
    open_positions: int,
    order_notional: float,
    order_margin: float,
    requested_leverage: float,
    daily_pnl: float,
    limits: RiskLimits = RiskLimits(),
) -> None:
    """Fail closed if a proposed order breaches account-level risk limits.

    ``order_margin`` is the actual margin to reserve for the proposed order.
    ``daily_pnl`` is account PnL since the configured daily reset; a negative
    value represents a loss.
    """
    eq = _finite_positive(equity, "equity")
    on = float(existing_notional)
    om = float(existing_margin)
    nn = _finite_positive(order_notional, "order_notional")
    nm = _finite_positive(order_margin, "order_margin")
    lev = _finite_positive(requested_leverage, "requested_leverage")
    if not math.isfinite(on) or on < 0 or not math.isfinite(om) or om < 0:
        raise RiskStateUnavailable("existing exposure state is invalid")
    if not isinstance(open_positions, int) or open_positions < 0:
        raise RiskStateUnavailable("open_positions is invalid")

    if lev > limits.max_leverage:
        raise RiskLimitBreached(f"leverage {lev:g} exceeds limit {limits.max_leverage:g}")
    if open_positions + 1 > limits.max_positions:
        raise RiskLimitBreached("maximum open-position count would be exceeded")

    margin_utilization = (om + nm) / eq
    if margin_utilization > limits.max_margin_utilization + 1e-12:
        raise RiskLimitBreached("maximum margin utilization would be exceeded")

    total_notional_pct = (on + nn) / eq
    if total_notional_pct > limits.max_total_notional_pct + 1e-12:
        raise RiskLimitBreached("maximum total notional exposure would be exceeded")

    if daily_pnl < 0 and abs(float(daily_pnl)) / eq >= limits.max_daily_loss_pct:
        raise RiskLimitBreached("daily loss limit has been reached; no new positions")


def load_limits_from_env(env: Optional[Mapping[str, str]] = None) -> RiskLimits:
    """Build limits from environment variables, with conservative defaults."""
    import os
    source = env if env is not None else os.environ

    def num(name: str, default: str) -> float:
        raw = source.get(name, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be numeric")

    def integer(name: str, default: str) -> int:
        raw = source.get(name, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer")

    return RiskLimits(
        max_leverage=num("ATLAS_MAX_LEVERAGE", "10"),
        max_positions=integer("ATLAS_MAX_POSITIONS", "3"),
        max_margin_utilization=num("ATLAS_MAX_MARGIN_UTILIZATION", "0.10"),
        max_total_notional_pct=num("ATLAS_MAX_TOTAL_NOTIONAL_PCT", "1.00"),
        max_daily_loss_pct=num("ATLAS_MAX_DAILY_LOSS_PCT", "0.05"),
    )
