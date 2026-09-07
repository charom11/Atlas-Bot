"""Offline Strategy Candidate V8: Production Alpha Meta-Controller.

Research-only: no exchange, network, or order-placement calls.

V8 is designed to improve the existing main.py architecture rather than replace
its five alpha channels. It models a portfolio-level controller around:
1) Fibonacci/Golden-Pocket/OTE pullback,
2) MSS/CHoCH breakout,
3) MA-stack + quantitative consensus,
4) liquidity sweep / S&R bounce,
5) RSI/CCI/MACD divergence.

The controller adds market regime, asset quality, cost-aware net-R, channel
reliability, correlation-adjusted risk, and fail-closed portfolio guards.
It deliberately does not import main.py so research cannot affect production.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Mapping, Optional, Sequence
import math
import numpy as np
import pandas as pd

LONG, SHORT, FLAT = "LONG", "SHORT", "FLAT"
CHANNELS = ("FIBONACCI", "MSS_SHIFT", "5MA_CONSENSUS", "POTATO_SR", "DIVERGENCE")
MAX_LEVERAGE = 75.0
DEFAULT_RISK_PCT = 0.0035
MAX_PORTFOLIO_RISK = 0.015
MAX_POSITIONS = 10
MAX_SAME_DIRECTION = 10
MAX_DAILY_LOSS = 0.03
MAX_WEEKLY_LOSS = 0.06
MIN_NET_R = 0.20

@dataclass(frozen=True)
class ChannelEvidence:
    channel: str
    side: str
    strength: float
    quality: float = 1.0
    available: bool = True

@dataclass(frozen=True)
class AssetMetrics:
    symbol: str
    expectancy_r: float
    profit_factor: float
    trades: int
    max_drawdown: float
    turnover: float = 0.0
    liquidity_score: float = 1.0
    funding_score: float = 1.0
    stability_score: float = 0.0

@dataclass(frozen=True)
class V8Decision:
    action: str
    score: float
    channel_score: float
    asset_score: float
    market_regime: str
    expected_net_r: float
    risk_pct: float
    leverage: float
    reasons: tuple[str, ...]


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return lo
    return min(hi, max(lo, x)) if math.isfinite(x) else lo


def classify_market_regime(breadth: float, btc_trend: float, volatility: float) -> str:
    """Cross-market state; thresholds are research defaults, not live settings."""
    b, t, v = float(breadth), float(btc_trend), float(volatility)
    if not all(math.isfinite(x) for x in (b, t, v)):
        return "UNAVAILABLE"
    if v >= 0.045:
        return "EXTREME_VOL"
    if b <= -0.65 and t <= -0.50:
        return "BREAKDOWN"
    if b >= 0.50 and t >= 0.35:
        return "RISK_ON"
    if b <= -0.35 or t <= -0.35:
        return "RISK_OFF"
    return "NEUTRAL"


def channel_meta_score(evidence: Sequence[ChannelEvidence], reliability: Optional[Mapping[str, float]] = None) -> tuple[float, str]:
    """Combine independent production channels without allowing unavailable data to vote."""
    rel = reliability or {}
    votes = []
    for e in evidence:
        if e.channel not in CHANNELS or not e.available or e.side not in (LONG, SHORT):
            continue
        strength = _clip(e.strength, 0.0, 1.0)
        quality = _clip(e.quality, 0.0, 1.0)
        weight = max(0.0, float(rel.get(e.channel, 1.0)))
        signed = strength * quality * weight * (1.0 if e.side == LONG else -1.0)
        votes.append((signed, weight))
    if not votes:
        return 0.0, FLAT
    denom = sum(w for _, w in votes)
    score = sum(v for v, _ in votes) / denom if denom > 0 else 0.0
    side = LONG if score > 0 else SHORT if score < 0 else FLAT
    return float(_clip(score)), side


def asset_quality_score(m: AssetMetrics) -> float:
    """Score assets using only historical/training-window statistics supplied by caller."""
    if m.trades < 20:
        return 0.0
    exp = np.tanh(m.expectancy_r / 0.15)
    pf = np.tanh((m.profit_factor - 1.0) / 0.25)
    dd = 1.0 - min(1.0, max(0.0, m.max_drawdown / 0.30))
    stability = _clip(m.stability_score, 0.0, 1.0)
    liquidity = _clip(m.liquidity_score, 0.0, 1.0)
    funding = _clip(m.funding_score, 0.0, 1.0)
    turnover_penalty = min(1.0, max(0.0, m.turnover))
    score = (0.30 * max(0.0, exp) + 0.20 * max(0.0, pf) +
             0.15 * dd + 0.15 * stability + 0.10 * liquidity +
             0.10 * funding - 0.10 * turnover_penalty)
    return float(_clip(score, 0.0, 1.0))


def rank_assets(metrics: Sequence[AssetMetrics], min_expectancy: float = 0.0,
                min_pf: float = 1.02, min_trades: int = 20) -> list[tuple[str, float]]:
    eligible = [m for m in metrics if m.trades >= min_trades and m.expectancy_r > min_expectancy and m.profit_factor >= min_pf]
    return sorted(((m.symbol, asset_quality_score(m)) for m in eligible), key=lambda x: x[1], reverse=True)


def cost_budget_pct(taker_fee_pct: float = 0.045, slippage_pct: float = 0.015,
                    spread_pct: float = 0.005, funding_buffer_pct: float = 0.010,
                    multiplier: float = 1.0) -> float:
    vals = [taker_fee_pct, slippage_pct, spread_pct, funding_buffer_pct]
    vals = [(x / 100.0 if x >= 0.001 else x) for x in vals]
    return float((2 * vals[0] + 2 * vals[1] + vals[2] + vals[3]) * multiplier)


def expected_net_r(entry: float, stop: float, expected_move_pct: float,
                   cost_pct: float, turnover_penalty_r: float = 0.0) -> float:
    if not all(math.isfinite(float(x)) and float(x) > 0 for x in (entry, stop)):
        return 0.0
    risk_pct = abs(entry - stop) / entry
    if risk_pct <= 1e-9:
        return 0.0
    return float(expected_move_pct / risk_pct - cost_pct / risk_pct - max(0.0, turnover_penalty_r))


def correlation_discount(symbol: str, selected: Sequence[str], correlation: Optional[pd.DataFrame] = None) -> float:
    if correlation is None or symbol not in correlation.index:
        return 1.0
    vals = []
    for other in selected:
        if other in correlation.columns and other != symbol:
            x = float(correlation.loc[symbol, other])
            if math.isfinite(x):
                vals.append(abs(x))
    if not vals:
        return 1.0
    return float(max(0.25, 1.0 - 0.50 * max(vals)))


def drawdown_risk_multiplier(drawdown: float) -> float:
    d = max(0.0, float(drawdown))
    if d >= 0.20: return 0.0
    if d >= 0.15: return 0.25
    if d >= 0.10: return 0.50
    if d >= 0.05: return 0.75
    return 1.0


def choose_leverage(stop_pct: float, risk_pct: float = DEFAULT_RISK_PCT,
                    max_leverage: float = MAX_LEVERAGE) -> float:
    if stop_pct <= 0 or risk_pct <= 0:
        return 0.0
    # Risk sizing determines notional; leverage is capped implementation headroom.
    return float(min(max_leverage, max(1.0, risk_pct / stop_pct)))


def risk_based_notional(equity: float, stop_pct: float, risk_pct: float = DEFAULT_RISK_PCT,
                        max_leverage: float = MAX_LEVERAGE) -> float:
    if equity <= 0 or stop_pct <= 0 or risk_pct <= 0:
        return 0.0
    raw = equity * risk_pct / stop_pct
    return float(min(raw, equity * max_leverage))


def portfolio_gate(action: str, equity: float, current_risk: float, open_positions: int,
                   same_direction: int, daily_loss: float, weekly_loss: float,
                   drawdown: float, selected: Sequence[str], symbol: str,
                   correlation: Optional[pd.DataFrame] = None) -> tuple[bool, str]:
    if action not in (LONG, SHORT): return False, "NO_ACTION"
    if equity <= 0: return False, "INVALID_EQUITY"
    if open_positions >= MAX_POSITIONS: return False, "MAX_POSITIONS"
    if same_direction >= MAX_SAME_DIRECTION: return False, "MAX_DIRECTION"
    if daily_loss >= MAX_DAILY_LOSS: return False, "DAILY_LOSS_GUARD"
    if weekly_loss >= MAX_WEEKLY_LOSS: return False, "WEEKLY_LOSS_GUARD"
    if drawdown >= 0.20: return False, "MAX_DRAWDOWN"
    if current_risk >= MAX_PORTFOLIO_RISK: return False, "PORTFOLIO_RISK"
    if correlation_discount(symbol, selected, correlation) <= 0.25 and selected: return False, "CORRELATION_CONCENTRATION"
    return True, "OK"


def decide(evidence: Sequence[ChannelEvidence], asset: AssetMetrics, breadth: float,
           btc_trend: float, volatility: float, entry: float, stop: float,
           expected_move_pct: float, equity: float, current_risk: float = 0.0,
           open_positions: int = 0, same_direction: int = 0, daily_loss: float = 0.0,
           weekly_loss: float = 0.0, drawdown: float = 0.0,
           selected: Sequence[str] = (), correlation: Optional[pd.DataFrame] = None,
           reliability: Optional[Mapping[str, float]] = None,
           cost_multiplier: float = 1.0) -> V8Decision:
    regime = classify_market_regime(breadth, btc_trend, volatility)
    cscore, side = channel_meta_score(evidence, reliability)
    ascore = asset_quality_score(asset)
    costs = cost_budget_pct(multiplier=cost_multiplier)
    net_r = expected_net_r(entry, stop, expected_move_pct, costs, turnover_penalty_r=0.05 * min(1.0, asset.turnover))
    dd_mult = drawdown_risk_multiplier(drawdown)
    regime_mult = {"RISK_ON": 1.0, "NEUTRAL": 0.75, "RISK_OFF": 0.50, "BREAKDOWN": 0.25, "EXTREME_VOL": 0.0, "UNAVAILABLE": 0.0}.get(regime, 0.0)
    corr_mult = correlation_discount(asset.symbol, selected, correlation)
    combined = float(cscore * ascore * regime_mult * corr_mult)
    risk = DEFAULT_RISK_PCT * dd_mult * regime_mult * corr_mult
    leverage = choose_leverage(abs(entry - stop) / entry if entry > 0 else 0.0, risk)
    reasons = [regime, f"CHANNEL_SCORE={cscore:.3f}", f"ASSET_SCORE={ascore:.3f}", f"NET_R={net_r:.3f}"]
    if net_r < MIN_NET_R: return V8Decision(FLAT, combined, cscore, ascore, regime, net_r, 0.0, 0.0, tuple(reasons + ["COST_FILTER"]))
    if abs(cscore) < 0.55 or ascore <= 0.0 or regime_mult <= 0.0: return V8Decision(FLAT, combined, cscore, ascore, regime, net_r, 0.0, 0.0, tuple(reasons + ["QUALITY_FILTER"]))
    ok, gate = portfolio_gate(side, equity, current_risk, open_positions, same_direction, daily_loss, weekly_loss, drawdown, selected, asset.symbol, correlation)
    if not ok: return V8Decision(FLAT, combined, cscore, ascore, regime, net_r, 0.0, 0.0, tuple(reasons + [gate]))
    return V8Decision(side, combined, cscore, ascore, regime, net_r, risk, leverage, tuple(reasons + ["PASS"]))


def backtest_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Reference interface: signals are shifted one bar for next-bar execution."""
    out = df.copy()
    if "signal" in out.columns:
        out["execution_signal"] = out["signal"].shift(1).fillna(FLAT)
    return out
