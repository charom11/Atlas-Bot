"""Offline Strategy Candidate V9.1: selective 15m alpha optimizer.

Research-only. Builds on Candidate V9 without modifying or importing main.py.
The audit showed that V9's opportunity expansion was overwhelmed by three
counter-trend/reversal families and weak regimes. V9.1 therefore applies
explicit, auditable admission rules rather than adding more indicators.

Key changes from V9:
- permanently disables LIQUIDITY_SWEEP and EXHAUSTION_REVERSAL;
- keeps FIB_OTE available only with trend/MSS confirmation;
- gates RANGE entirely and treats HIGH_VOL as selective rather than universal;
- prioritizes empirically stronger assets via tiers, while retaining a
  configurable broad-universe fallback for research;
- gives TREND_CONTINUATION a 2.5 ATR target and 1.25 ATR stop, while keeping
  other setups at V9's 2.0/1.25 baseline;
- exposes pure functions so the institutional runner can test each gate.

No exchange, network, credentials, or order placement are used here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from strategy_candidate_v9 import (
    LONG,
    SHORT,
    FLAT,
    SETUPS,
    allowed_setups as v9_allowed_setups,
    opportunity_score,
    setup_votes,
    _num,
)

PRUNED_SETUPS = frozenset({"LIQUIDITY_SWEEP", "EXHAUSTION_REVERSAL"})
FIB_CONFIRMATION_SETUPS = frozenset({"MSS_SHIFT", "TREND_CONTINUATION", "PULLBACK_CONTINUATION"})

# Evidence tiers from the supplied V9 audit. Tiering is deliberately explicit
# and configurable so it cannot silently become a live asset blacklist.
TIER_1 = ("SUIUSDT", "SOLUSDT", "XRPUSDT")
TIER_2 = ("BTCUSDT", "DOGEUSDT", "ETHUSDT")
TIER_3 = ("LINKUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT")

@dataclass(frozen=True)
class V91Config:
    allow_tier_2: bool = True
    allow_tier_3: bool = False
    allow_fibonacci: bool = True
    allow_mild_trend: bool = True
    allow_high_vol: bool = True
    min_score: int = 5
    min_confirmations: int = 1
    trend_stop_atr: float = 1.25
    trend_target_atr: float = 2.50
    base_stop_atr: float = 1.25
    base_target_atr: float = 2.00


def asset_allowed(symbol: str, config: V91Config = V91Config()) -> bool:
    """Apply research asset tiers without modifying the configured universe."""
    symbol = str(symbol).upper()
    if symbol in TIER_1:
        return True
    if symbol in TIER_2:
        return config.allow_tier_2
    if symbol in TIER_3:
        return config.allow_tier_3
    return False


def allowed_setups(regime: str, config: V91Config = V91Config()) -> set[str]:
    """Return V9 setup eligibility after evidence-based pruning/regime gates."""
    regime = str(regime).upper()
    if regime == "RANGE":
        return set()
    if regime == "CHOP":
        return set()
    if regime == "HIGH_VOL" and not config.allow_high_vol:
        return set()
    if regime == "MILD_TREND" and not config.allow_mild_trend:
        return set()

    allowed = set(v9_allowed_setups(regime)) - PRUNED_SETUPS
    if not config.allow_fibonacci:
        allowed.discard("FIB_OTE")
    return allowed


def confirmation_ok(row, setup: str, votes: Mapping[str, int]) -> bool:
    """Prevent standalone Fib/OTE; require an aligned structural confirmation."""
    side = votes.get(setup, FLAT)
    if side == FLAT:
        return False
    if setup != "FIB_OTE":
        return True
    return any(votes.get(other, FLAT) == side for other in FIB_CONFIRMATION_SETUPS)


def select_opportunity(row, votes: Mapping[str, int], config: V91Config = V91Config()):
    """Select one V9.1 opportunity from a precomputed indicator row."""
    if not asset_allowed(str(getattr(row, "symbol", "")), config):
        return None
    regime = str(getattr(row, "regime", ""))
    eligible = allowed_setups(regime, config)
    candidates = []
    for setup in SETUPS:
        if setup not in eligible:
            continue
        if not confirmation_ok(row, setup, votes):
            continue
        score, confirmations = opportunity_score(row, dict(votes), setup)
        if score >= config.min_score and confirmations >= config.min_confirmations:
            candidates.append((score, confirmations, setup, votes[setup]))
    if not candidates:
        return None
    return max(candidates, key=lambda x: (x[0], x[1]))


def target_stop_atr(setup: str, config: V91Config = V91Config()) -> tuple[float, float]:
    """Return (stop ATR, target ATR) for a selected setup."""
    if setup == "TREND_CONTINUATION":
        return config.trend_stop_atr, config.trend_target_atr
    return config.base_stop_atr, config.base_target_atr


def direction_from_side(side: int) -> str:
    return {LONG: "LONG", SHORT: "SHORT", FLAT: "FLAT"}.get(side, "FLAT")


def audit_summary() -> dict[str, object]:
    """Machine-readable statement of V9.1 research policy."""
    return {
        "pruned_setups": sorted(PRUNED_SETUPS),
        "range_allowed": False,
        "chop_allowed": False,
        "tier_1": list(TIER_1),
        "tier_2": list(TIER_2),
        "tier_3": list(TIER_3),
        "fib_requires_confirmation": True,
        "trend_target_atr": 2.50,
        "base_target_atr": 2.00,
        "production_wired": False,
    }
