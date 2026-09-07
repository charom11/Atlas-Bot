"""Offline Strategy Candidate V9.1: selective 15m alpha optimizer.

Research-only. Builds on Candidate V9 without modifying main.py. The V9 audit
showed that opportunity expansion was overwhelmed by counter-trend/reversal
families and weak regimes. V9.1 applies explicit admission rules instead of
adding more indicators.

Key changes:
- disables LIQUIDITY_SWEEP and EXHAUSTION_REVERSAL;
- keeps FIB_OTE only with trend/MSS confirmation;
- gates RANGE and CHOP;
- prioritizes empirically stronger assets through configurable tiers;
- gives TREND_CONTINUATION a 2.5 ATR target with a 1.25 ATR stop;
- exposes pure functions for institutional backtesting.

No exchange, network, credentials, or order placement are used here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from strategy_candidate_v9 import (
    LONG,
    SHORT,
    FLAT,
    SETUPS,
    REGIMES,
    Trade,
    BacktestStats,
    _num,
    add_indicators,
    classify_regime,
    setup_votes,
    allowed_setups as v9_allowed_setups,
    opportunity_score,
    summarize,
    report,
    walk_forward as v9_walk_forward,
    load_ohlcv_csv,
)

PRUNED_SETUPS = frozenset({"LIQUIDITY_SWEEP", "EXHAUSTION_REVERSAL"})
FIB_CONFIRMATION_SETUPS = frozenset({"MSS_SHIFT", "TREND_CONTINUATION", "PULLBACK_CONTINUATION"})
TIER_1 = ("SUIUSDT", "SOLUSDT", "XRPUSDT")
TIER_2 = ("BTCUSDT", "DOGEUSDT", "ETHUSDT")
TIER_3 = ("LINKUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "BNBUSDT")

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
    symbol = str(symbol).upper()
    if symbol in TIER_1:
        return True
    if symbol in TIER_2:
        return config.allow_tier_2
    if symbol in TIER_3:
        return config.allow_tier_3
    return False


def allowed_setups(regime: str, config: V91Config = V91Config()) -> set[str]:
    regime = str(regime).upper()
    if regime in {"RANGE", "CHOP"}:
        return set()
    if regime == "HIGH_VOL" and not config.allow_high_vol:
        return set()
    if regime == "MILD_TREND" and not config.allow_mild_trend:
        return set()
    allowed = set(v9_allowed_setups(regime)) - PRUNED_SETUPS
    if not config.allow_fibonacci:
        allowed.discard("FIB_OTE")
    return allowed


def confirmation_ok(setup: str, votes: Mapping[str, int]) -> bool:
    side = votes.get(setup, FLAT)
    if side == FLAT:
        return False
    if setup != "FIB_OTE":
        return True
    return any(votes.get(other, FLAT) == side for other in FIB_CONFIRMATION_SETUPS)


def select_opportunity(row, votes: Mapping[str, int], config: V91Config = V91Config()):
    symbol = str(getattr(row, "symbol", "")).upper()
    if symbol and symbol != "UNKNOWN" and not asset_allowed(symbol, config):
        return None
    eligible = allowed_setups(getattr(row, "regime", ""), config)
    candidates = []
    for setup in SETUPS:
        if setup not in eligible or not confirmation_ok(setup, votes):
            continue
        score, confirmations = opportunity_score(row, dict(votes), setup)
        if score >= config.min_score and confirmations >= config.min_confirmations:
            candidates.append((score, confirmations, setup, votes[setup]))
    return max(candidates, key=lambda x: (x[0], x[1])) if candidates else None


def target_stop_atr(setup: str, config: V91Config = V91Config()) -> tuple[float, float]:
    if setup == "TREND_CONTINUATION":
        return config.trend_stop_atr, config.trend_target_atr
    return config.base_stop_atr, config.base_target_atr


def backtest_frame(
    df: pd.DataFrame,
    config: V91Config = V91Config(),
    friction_r: float = 0.026,
    max_hold_bars: int = 32,
) -> list[Trade]:
    """Next-bar execution simulation using V9.1 selective admission and asymmetric targets."""
    if df.empty or len(df) <= 201:
        return []

    data = add_indicators(df)
    symbol_str = str(data["symbol"].iloc[0]) if "symbol" in data.columns else "UNKNOWN"
    if symbol_str != "UNKNOWN" and not asset_allowed(symbol_str, config):
        return []
    if "symbol" not in data.columns:
        data["symbol"] = symbol_str
    data["regime"] = data.apply(classify_regime, axis=1)

    trades: list[Trade] = []
    n = len(data)
    opens = data["open"].values
    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values
    timestamps = [str(t) for t in data.index]

    i = 201
    while i < n - 1:
        row, prev = data.iloc[i], data.iloc[i-1]
        votes = setup_votes(row, prev)
        opp = select_opportunity(row, votes, config)
        if not opp:
            i += 1
            continue

        score, confirmations, setup, side = opp
        atr = _num(getattr(row, "atr", 0.0))
        if atr <= 0:
            i += 1
            continue

        entry_idx = i + 1
        entry = opens[entry_idx]
        stop_mult, target_mult = target_stop_atr(setup, config)
        stop = entry - side * stop_mult * atr
        target = entry + side * target_mult * atr

        exit_px, held = entry, 0
        end_bar = min(n, entry_idx + max_hold_bars)
        for j in range(entry_idx, end_bar):
            held += 1
            l_val, h_val = lows[j], highs[j]
            stop_hit = (l_val <= stop) if side == LONG else (h_val >= stop)
            target_hit = (h_val >= target) if side == LONG else (l_val <= target)
            if stop_hit:
                exit_px = stop
                break
            if target_hit:
                exit_px = target
                break
            exit_px = closes[j]

        gross_r = side * (exit_px - entry) / max(abs(entry - stop), 1e-12)
        net_r = gross_r - friction_r
        trades.append(Trade(timestamps[entry_idx], symbol_str, side, setup, str(row.regime), entry, exit_px, net_r, friction_r, held))
        i = entry_idx + max(1, held)
    return trades


def walk_forward(
    df: pd.DataFrame,
    periods: Sequence[tuple[str, str, str]],
    config: V91Config = V91Config(),
    **kwargs,
) -> list[tuple[str, BacktestStats]]:
    res = []
    for label, start, end in periods:
        sub = df.loc[start:end]
        trades = backtest_frame(sub, config=config, **kwargs)
        res.append((label, summarize(trades)))
    return res


def direction_from_side(side: int) -> str:
    return {LONG: "LONG", SHORT: "SHORT", FLAT: "FLAT"}.get(side, "FLAT")


def audit_summary() -> dict[str, object]:
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
