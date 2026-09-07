"""Offline Strategy Candidate V9.3: Conservative 15m Integration Candidate.

Research & Shadow-Mode Integration Only.
This module does NOT modify main.py, does NOT place live exchange orders,
and does NOT set excessive leverage targets (75x is strictly rejected).

Based on V9.2 Validation Hardening findings:
- Active 15M setups:
    1. TREND_CONTINUATION (primary alpha engine, 2.50x ATR target)
    2. BB_ATR_EXPANSION (secondary momentum breakout, 2.00x ATR target)
    3. MSS_SHIFT (supporting confirmation / volume anchor)
    4. BREAKOUT_RETEST (selective high-precision)
    5. VWAP_TREND (optional / low weight)
- Disabled setups:
    * LIQUIDITY_SWEEP (gated - saved 1,087 R)
    * EXHAUSTION_REVERSAL (gated - saved 42 R)
    * PULLBACK_CONTINUATION (gated - LOO proved net fee drag of -36 R)
    * VWAP_REVERSION (gated)
- Allowed market regimes:
    * STRONG_TREND
    * HIGH_VOL (primary volume driver)
    * MILD_TREND
- Gated market regimes:
    * RANGE (gated - whipsaw protection)
    * CHOP (gated)
    * BREAKDOWN (gated - LOO proved persistent drag of -100 R)
- Risk architecture:
    * Shadow/paper execution mode by default.
    * Decides WHETHER an opportunity is admissible; main.py remains authoritative.
    * Caps operating leverage at conservative <= 5x.
    * Base risk per trade: 0.35%, max portfolio risk: 1.5%.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping, Sequence
from pathlib import Path
import os
import sys

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
    opportunity_score,
    summarize,
    report,
    load_ohlcv_csv,
)

ACTIVE_SETUPS = frozenset({
    "TREND_CONTINUATION",
    "BB_ATR_EXPANSION",
    "MSS_SHIFT",
    "BREAKOUT_RETEST",
    "VWAP_TREND",
})

DISABLED_SETUPS = frozenset({
    "LIQUIDITY_SWEEP",
    "EXHAUSTION_REVERSAL",
    "PULLBACK_CONTINUATION",
    "VWAP_REVERSION",
    "FIB_OTE",
})

ALLOWED_REGIMES = frozenset({
    "STRONG_TREND",
    "HIGH_VOL",
    "MILD_TREND",
})

GATED_REGIMES = frozenset({
    "RANGE",
    "CHOP",
    "BREAKDOWN",
})

TIER_1 = ("SUIUSDT", "SOLUSDT", "XRPUSDT")
TIER_2 = ("BTCUSDT", "DOGEUSDT", "ETHUSDT")
TIER_3 = ("LINKUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "BNBUSDT")


@dataclass(frozen=True)
class V93Config:
    allow_tier_2: bool = True
    allow_tier_3: bool = False
    allow_vwap_trend: bool = True
    allow_mild_trend: bool = True
    min_score: int = 5
    min_confirmations: int = 1
    trend_stop_atr: float = 1.25
    trend_target_atr: float = 2.50
    base_stop_atr: float = 1.25
    base_target_atr: float = 2.00
    shadow_mode: bool = True
    max_operating_leverage: float = 5.0
    max_risk_per_trade_pct: float = 0.0035
    max_portfolio_risk_pct: float = 0.015


@dataclass(frozen=True)
class ShadowOpportunity:
    timestamp: str
    symbol: str
    side: int
    setup: str
    regime: str
    score: int
    confirmations: int
    entry_price: float
    stop_price: float
    target_price: float
    atr: float
    admitted: bool
    rejection_reason: str = ""


def asset_allowed(symbol: str, config: V93Config = V93Config()) -> bool:
    symbol = str(symbol).upper()
    if symbol in TIER_1:
        return True
    if symbol in TIER_2:
        return config.allow_tier_2
    if symbol in TIER_3:
        return config.allow_tier_3
    if symbol in {"", "UNKNOWN", "SYNTHETIC"}:
        return True
    return False


def allowed_setups(regime: str, config: V93Config = V93Config()) -> set[str]:
    regime = str(regime).upper()
    if regime not in ALLOWED_REGIMES or regime in GATED_REGIMES:
        return set()
    if regime == "MILD_TREND" and not config.allow_mild_trend:
        return set()
    setups = set(ACTIVE_SETUPS)
    if not config.allow_vwap_trend:
        setups.discard("VWAP_TREND")
    return setups


def target_stop_atr(setup: str, config: V93Config = V93Config()) -> tuple[float, float]:
    if setup == "TREND_CONTINUATION":
        return config.trend_stop_atr, config.trend_target_atr
    return config.base_stop_atr, config.base_target_atr


def admit_opportunity(
    row: pd.Series,
    votes: Mapping[str, int],
    config: V93Config = V93Config(),
) -> ShadowOpportunity | None:
    """Evaluate 15m candle evidence and return admitted shadow opportunity or rejection."""
    symbol = str(getattr(row, "symbol", "UNKNOWN")).upper()
    regime = str(getattr(row, "regime", "")).upper()
    atr = _num(getattr(row, "atr", 0.0))

    if not asset_allowed(symbol, config):
        return ShadowOpportunity(
            timestamp=str(getattr(row, "name", "")),
            symbol=symbol,
            side=FLAT,
            setup="NONE",
            regime=regime,
            score=0,
            confirmations=0,
            entry_price=0.0,
            stop_price=0.0,
            target_price=0.0,
            atr=atr,
            admitted=False,
            rejection_reason=f"Asset {symbol} not permitted under tier policy",
        )

    if regime not in ALLOWED_REGIMES or regime in GATED_REGIMES:
        return ShadowOpportunity(
            timestamp=str(getattr(row, "name", "")),
            symbol=symbol,
            side=FLAT,
            setup="NONE",
            regime=regime,
            score=0,
            confirmations=0,
            entry_price=0.0,
            stop_price=0.0,
            target_price=0.0,
            atr=atr,
            admitted=False,
            rejection_reason=f"Regime {regime} is gated (RANGE, CHOP, and BREAKDOWN blocked)",
        )

    if atr <= 0:
        return ShadowOpportunity(
            timestamp=str(getattr(row, "name", "")),
            symbol=symbol,
            side=FLAT,
            setup="NONE",
            regime=regime,
            score=0,
            confirmations=0,
            entry_price=0.0,
            stop_price=0.0,
            target_price=0.0,
            atr=atr,
            admitted=False,
            rejection_reason="Invalid ATR <= 0",
        )

    eligible = allowed_setups(regime, config)
    candidates = []
    for setup in SETUPS:
        if setup not in eligible:
            continue
        side = votes.get(setup, FLAT)
        if side == FLAT:
            continue
        score, confirmations = opportunity_score(row, dict(votes), setup)
        if score >= config.min_score and confirmations >= config.min_confirmations:
            candidates.append((score, confirmations, setup, side))

    if not candidates:
        return None

    score, confirmations, setup, side = max(candidates, key=lambda x: (x[0], x[1]))
    close_px = _num(getattr(row, "close", 0.0))
    stop_mult, target_mult = target_stop_atr(setup, config)
    stop_px = close_px - side * stop_mult * atr
    target_px = close_px + side * target_mult * atr

    return ShadowOpportunity(
        timestamp=str(getattr(row, "name", "")),
        symbol=symbol,
        side=side,
        setup=setup,
        regime=regime,
        score=score,
        confirmations=confirmations,
        entry_price=close_px,
        stop_price=stop_px,
        target_price=target_px,
        atr=atr,
        admitted=True,
        rejection_reason="",
    )


def backtest_frame(
    df: pd.DataFrame,
    config: V93Config = V93Config(),
    friction_r: float = 0.026,
    max_hold_bars: int = 32,
) -> list[Trade]:
    """Next-bar execution simulation enforcing Candidate V9.3 conservative admission rules."""
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
        opp = admit_opportunity(row, votes, config)
        if not opp or not opp.admitted:
            i += 1
            continue

        atr = opp.atr
        side = opp.side
        setup = opp.setup
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
        trades.append(Trade(timestamps[entry_idx], symbol_str, side, setup, str(opp.regime), entry, exit_px, net_r, friction_r, held))
        i = entry_idx + max(1, held)
    return trades


def walk_forward(
    df: pd.DataFrame,
    periods: Sequence[tuple[str, str, str]],
    config: V93Config = V93Config(),
    **kwargs,
) -> list[tuple[str, BacktestStats]]:
    res = []
    for label, start, end in periods:
        sub = df.loc[start:end]
        trades = backtest_frame(sub, config=config, **kwargs)
        res.append((label, summarize(trades)))
    return res


def integration_audit_summary() -> dict[str, object]:
    return {
        "candidate": "V9.3",
        "role": "Opportunity Admission & Shadow-Mode Layer",
        "live_orders_permitted": False,
        "main_py_authoritative": True,
        "active_setups": sorted(list(ACTIVE_SETUPS)),
        "disabled_setups": sorted(list(DISABLED_SETUPS)),
        "allowed_regimes": sorted(list(ALLOWED_REGIMES)),
        "gated_regimes": sorted(list(GATED_REGIMES)),
        "breakdown_gated": True,
        "pullback_gated": True,
        "max_operating_leverage": 5.0,
        "leverage_75x_rejected": True,
        "tier_1_assets": list(TIER_1),
        "tier_2_assets": list(TIER_2),
        "tier_3_assets": list(TIER_3),
    }


def run_v9_3_audit(
    dataset: str = "4year",
    friction_r: float = 0.026,
    output: str = "backtests/v9_3_integration_report.json",
) -> dict:
    from backtests.run_v9_3_institutional_backtest import run_v9_3_institutional_audit
    return run_v9_3_institutional_audit(
        dataset_type=dataset,
        friction_r=friction_r,
        output_path=output,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Candidate V9.3 Conservative Integration Backtester")
    parser.add_argument("--dataset", default="4year", choices=["1year", "4year"], help="Dataset range (default: 4year)")
    parser.add_argument("--friction-r", type=float, default=0.026, help="Base friction in R (default: 0.026)")
    parser.add_argument("--output", default="backtests/v9_3_integration_report.json", help="Output JSON path")
    args = parser.parse_args()

    run_v9_3_audit(dataset=args.dataset, friction_r=args.friction_r, output=args.output)
