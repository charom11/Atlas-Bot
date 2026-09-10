"""Offline Strategy Candidate V9.4: Adaptive Volatility & Breakeven-Trailing Candidate.

Research & Shadow-Mode Integration Layer.
Builds directly on Candidate V9.3.1 (refined conservative 15m admission) and adds
three risk-coherent refinements while preserving the full safety architecture:

- Inherited Core Active 15M Alpha Engines (unchanged from V9.3.1):
    1. TREND_CONTINUATION (primary alpha engine, 2.50x ATR asymmetric target)
    2. BB_ATR_EXPANSION (secondary momentum breakout, 2.00x ATR target)
    3. MSS_SHIFT (supporting confirmation / volume anchor)
    4. BREAKOUT_RETEST (selective high-precision)

- New in V9.4:
    * VOLATILITY-BAND ADMISSION FILTER
        Rejects entries whose normalized ATR (atr / close) falls outside
        [atr_pct_floor, atr_pct_ceiling]. Screens dead/illiquid tape (too low)
        and news-shock spikes (too high) that historically fed whipsaw drag.
    * REGIME-SCALED RISK SIZING (telemetry-only)
        Per-regime risk multiplier applied to the base risk budget. Does NOT
        alter normalized-R trade accounting; surfaced via telemetry + audit so
        downstream sizing (main.py) stays authoritative.
    * BREAKEVEN-TRAILING STOP (simulator)
        Once favorable excursion reaches breakeven_trigger_r * initial_risk,
        the stop ratchets to entry (breakeven). Conservative intrabar handling:
        original stop/target are evaluated adverse-first before the breakeven
        arms for subsequent bars (no intrabar lookahead).

- Gated Regimes (unchanged): RANGE, CHOP, BREAKDOWN
- Allowed Regimes (unchanged): STRONG_TREND, HIGH_VOL, MILD_TREND

- Safety Architecture (unchanged and enforced):
    * Strictly decoupled from live order execution (shadow/paper mode only).
    * Operating leverage capped at <= 5.0x (75x rejected).
    * main.py remains authoritative execution, reconciliation, and fail-closed
      safety citadel. This module admits and simulates; it never sends orders.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from strategy_candidate_v9 import (
    LONG,
    FLAT,
    Trade,
    BacktestStats,
    _num,
    add_indicators,
    classify_regime,
    setup_votes,
    summarize,
)
from strategy_candidate_v9_3 import (
    ShadowOpportunity,
    TIER_1,
    TIER_2,
    TIER_3,
)
from strategy_candidate_v9_3_1 import (
    ACTIVE_SETUPS_V931,
    DISABLED_SETUPS_V931,
    ALLOWED_REGIMES_V931,
    GATED_REGIMES_V931,
    asset_allowed,
    target_stop_atr,
    admit_opportunity,
)

# V9.4 inherits the V9.3.1 setup/regime policy verbatim (pruning discipline held).
ACTIVE_SETUPS_V94 = frozenset(ACTIVE_SETUPS_V931)
DISABLED_SETUPS_V94 = frozenset(DISABLED_SETUPS_V931)
ALLOWED_REGIMES_V94 = frozenset(ALLOWED_REGIMES_V931)
GATED_REGIMES_V94 = frozenset(GATED_REGIMES_V931)

# Regime-scaled risk multipliers (telemetry-only; never mutate normalized R).
REGIME_RISK_MULTIPLIERS_V94 = {
    "STRONG_TREND": 1.00,
    "HIGH_VOL": 0.60,
    "MILD_TREND": 0.75,
}


@dataclass(frozen=True)
class V94Config:
    # --- Inherited V9.3.1 fields (duck-compatible with V931Config consumers) ---
    allow_tier_2: bool = True
    allow_tier_3: bool = False
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

    # --- New V9.4 tunables ---
    # Volatility-band admission filter (normalized ATR = atr / close).
    enable_volatility_band: bool = True
    atr_pct_floor: float = 0.0015      # reject dead/illiquid tape below 0.15%
    atr_pct_ceiling: float = 0.0600    # reject news-shock spikes above 6.00%
    # Stricter score requirement in the weaker MILD_TREND regime.
    mild_trend_min_score: int = 6
    # Regime-scaled risk sizing (telemetry-only).
    enable_regime_risk_scaling: bool = True
    # Breakeven-trailing stop.
    enable_breakeven_trail: bool = True
    breakeven_trigger_r: float = 1.00  # arm breakeven once +1.00R favorable


def normalized_atr(close_px: float, atr: float) -> float:
    """ATR expressed as a fraction of price. Returns 0.0 on invalid price."""
    close_px = _num(close_px)
    atr = _num(atr)
    if close_px <= 0:
        return 0.0
    return atr / close_px


def volatility_band_ok(close_px: float, atr: float, config: V94Config) -> bool:
    """True if normalized ATR is inside the admissible volatility band."""
    if not config.enable_volatility_band:
        return True
    natr = normalized_atr(close_px, atr)
    if natr <= 0:
        return False
    return config.atr_pct_floor <= natr <= config.atr_pct_ceiling


def effective_min_score(regime: str, config: V94Config) -> int:
    """Regime-aware score gate: MILD_TREND demands a higher bar."""
    if str(regime).upper() == "MILD_TREND":
        return max(config.min_score, config.mild_trend_min_score)
    return config.min_score


def effective_risk_pct(regime: str, config: V94Config) -> float:
    """Telemetry-only per-trade risk budget after regime scaling."""
    base = config.max_risk_per_trade_pct
    if not config.enable_regime_risk_scaling:
        return base
    mult = REGIME_RISK_MULTIPLIERS_V94.get(str(regime).upper(), 1.0)
    return round(base * mult, 6)


def admit_opportunity_v94(
    row: pd.Series,
    votes,
    config: V94Config = V94Config(),
) -> ShadowOpportunity | None:
    """V9.4 admission: V9.3.1 core admission + volatility band + regime score gate.

    Delegates the base tier/regime/setup evaluation to the audited V9.3.1
    ``admit_opportunity`` (passing this config via duck typing), then layers the
    two new *tightening* filters on top. V9.4 only ever *narrows* admission
    relative to V9.3.1 -- it never loosens it.
    """
    # Stricter, regime-aware score threshold applied to the base admission.
    regime = str(getattr(row, "regime", "")).upper()
    gated_config = replace(config, min_score=effective_min_score(regime, config))

    opp = admit_opportunity(row, votes, gated_config)
    if opp is None:
        return None

    # Preserve explicit V9.3.1 rejections unchanged.
    if not opp.admitted:
        return opp

    # New V9.4 volatility-band gate (post-admission tightening).
    if not volatility_band_ok(opp.entry_price, opp.atr, config):
        natr = normalized_atr(opp.entry_price, opp.atr)
        return ShadowOpportunity(
            timestamp=opp.timestamp,
            symbol=opp.symbol,
            side=FLAT,
            setup="NONE",
            regime=opp.regime,
            score=0,
            confirmations=0,
            entry_price=0.0,
            stop_price=0.0,
            target_price=0.0,
            atr=opp.atr,
            admitted=False,
            rejection_reason=(
                f"Normalized ATR {natr:.4%} outside volatility band "
                f"[{config.atr_pct_floor:.4%}, {config.atr_pct_ceiling:.4%}]"
            ),
        )

    return opp


def backtest_frame_v94(
    df: pd.DataFrame,
    config: V94Config = V94Config(),
    friction_r: float = 0.026,
    max_hold_bars: int = 32,
) -> list[Trade]:
    """Next-bar execution simulation enforcing V9.4 admission + breakeven trailing.

    Trade accounting stays in normalized-R units identical to V9.3.1, so the
    shared ``summarize`` / ``BacktestStats`` machinery remains valid.
    """
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
        row, prev = data.iloc[i], data.iloc[i - 1]
        votes = setup_votes(row, prev)
        opp = admit_opportunity_v94(row, votes, config)
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

        risk_dist = max(abs(entry - stop), 1e-12)
        be_trigger_px = entry + side * config.breakeven_trigger_r * risk_dist
        be_armed = False

        exit_px, held = entry, 0
        end_bar = min(n, entry_idx + max_hold_bars)
        for j in range(entry_idx, end_bar):
            held += 1
            l_val, h_val = lows[j], highs[j]

            # Adverse-first intrabar evaluation against the CURRENT stop/target
            # (breakeven arming from THIS bar only affects SUBSEQUENT bars).
            stop_hit = (l_val <= stop) if side == LONG else (h_val >= stop)
            target_hit = (h_val >= target) if side == LONG else (l_val <= target)
            if stop_hit:
                exit_px = stop
                break
            if target_hit:
                exit_px = target
                break
            exit_px = closes[j]

            # Arm breakeven trail for the next bar once +breakeven_trigger_r hit.
            if config.enable_breakeven_trail and not be_armed:
                reached = (h_val >= be_trigger_px) if side == LONG else (l_val <= be_trigger_px)
                if reached:
                    be_armed = True
                    stop = entry  # ratchet stop to breakeven

        gross_r = side * (exit_px - entry) / risk_dist
        net_r = gross_r - friction_r
        trades.append(Trade(timestamps[entry_idx], symbol_str, side, setup, str(opp.regime), entry, exit_px, net_r, friction_r, held))
        i = entry_idx + max(1, held)
    return trades


def walk_forward_v94(
    df: pd.DataFrame,
    periods,
    config: V94Config = V94Config(),
    **kwargs,
) -> list[tuple[str, BacktestStats]]:
    res = []
    for label, start, end in periods:
        sub = df.loc[start:end]
        trades = backtest_frame_v94(sub, config=config, **kwargs)
        res.append((label, summarize(trades)))
    return res


def integration_audit_summary() -> dict[str, object]:
    return {
        "candidate": "V9.4",
        "role": "Adaptive Volatility & Breakeven-Trailing Shadow-Mode Layer",
        "parent_candidate": "V9.3.1",
        "live_orders_permitted": False,
        "main_py_authoritative": True,
        "active_setups": sorted(ACTIVE_SETUPS_V94),
        "disabled_setups": sorted(DISABLED_SETUPS_V94),
        "allowed_regimes": sorted(ALLOWED_REGIMES_V94),
        "gated_regimes": sorted(GATED_REGIMES_V94),
        "breakdown_gated": True,
        "pullback_gated": True,
        "vwap_trend_gated": True,
        "volatility_band_enabled": True,
        "atr_pct_band": [V94Config().atr_pct_floor, V94Config().atr_pct_ceiling],
        "mild_trend_min_score": V94Config().mild_trend_min_score,
        "regime_risk_scaling_enabled": True,
        "regime_risk_multipliers": dict(REGIME_RISK_MULTIPLIERS_V94),
        "breakeven_trail_enabled": True,
        "breakeven_trigger_r": V94Config().breakeven_trigger_r,
        "max_operating_leverage": 5.0,
        "leverage_75x_rejected": True,
        "tier_1_assets": list(TIER_1),
        "tier_2_assets": list(TIER_2),
        "tier_3_assets": list(TIER_3),
    }


def run_v9_4_audit(
    dataset: str = "4year",
    friction_r: float = 0.026,
    output: str = "backtests/v9_4_integration_report.json",
) -> dict:
    from backtests.run_v9_4_institutional_backtest import run_v9_4_institutional_audit
    return run_v9_4_institutional_audit(
        dataset_type=dataset,
        friction_r=friction_r,
        output_path=output,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Candidate V9.4 Adaptive Volatility & Breakeven-Trailing Backtester")
    parser.add_argument("--dataset", default="4year", choices=["1year", "4year"], help="Dataset range (default: 4year)")
    parser.add_argument("--friction-r", type=float, default=0.026, help="Base friction in R (default: 0.026)")
    parser.add_argument("--output", default="backtests/v9_4_integration_report.json", help="Output JSON path")
    args = parser.parse_args()

    run_v9_4_audit(dataset=args.dataset, friction_r=args.friction_r, output=args.output)
