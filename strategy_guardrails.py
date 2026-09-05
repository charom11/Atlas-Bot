"""Pure strategy guardrails for Atlas-Bot.

This module contains side-effect-free helpers that can be imported by the live
strategy without placing, cancelling, or modifying exchange orders.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple


def atr_neutral_signal(relative_move: float, atr: float, neutral_atr: float = 0.15) -> str:
    """Return BULLISH/BEARISH only when the move clears an ATR-scaled band."""
    if atr <= 0 or neutral_atr < 0:
        return "NEUTRAL"
    threshold = atr * neutral_atr
    if relative_move > threshold:
        return "BULLISH"
    if relative_move < -threshold:
        return "BEARISH"
    return "NEUTRAL"


def require_fresh_data(ok: bool, *, reason: str = "data unavailable") -> Tuple[bool, str]:
    """Fail closed when a required market-data dependency is unavailable."""
    if not ok:
        return False, reason
    return True, "ok"


def directional_cap_allowed(
    authoritative: bool,
    current_directional_exposure: float,
    proposed_directional_exposure: float,
    cap: float,
) -> bool:
    """Allow a directional increase only with authoritative exposure data."""
    if not authoritative:
        return False
    if cap < 0:
        return False
    return current_directional_exposure + proposed_directional_exposure <= cap


def validate_external_filter(
    result: Optional[Mapping[str, Any]],
    *,
    required_keys: tuple[str, ...] = (),
) -> bool:
    """Validate a dependency result instead of treating exceptions/missing data as OK."""
    if not isinstance(result, Mapping):
        return False
    return all(key in result and result[key] is not None for key in required_keys)


def seasonality_signal(validated: bool, signal: str) -> str:
    """Do not emit a directional seasonality vote without validated statistics."""
    if not validated:
        return "NEUTRAL"
    return signal if signal in {"BULLISH", "BEARISH", "NEUTRAL"} else "NEUTRAL"


def check_consensus_eligibility(
    bull_count: int,
    bear_count: int,
    *,
    min_active: int = 12,
    min_votes: int = 13,
    min_ratio: float = 0.75,
) -> Tuple[bool, int, int, float]:
    """
    Check if a normalized consensus supermajority is reached among active models.
    Returns: (is_eligible, active_models, max_consensus, consensus_ratio)
    """
    active_models = bull_count + bear_count
    max_consensus = max(bull_count, bear_count)
    consensus_ratio = (max_consensus / active_models) if active_models > 0 else 0.0
    is_eligible = (
        active_models >= min_active
        and max_consensus >= min_votes
        and consensus_ratio >= min_ratio
    )
    return is_eligible, active_models, max_consensus, consensus_ratio

