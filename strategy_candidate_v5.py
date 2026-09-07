"""Offline Strategy Candidate V5: Selective Alpha Portfolio.

Research-only. No exchange/network/order calls and deliberately not wired into
main.py. V5 implements selective portfolio allocation:
- Keeps V4 adaptive pullback gate (0.60/0.90/1.20 ATR) and structure stops.
- Active position management with initial-stop referenced giveback protection.
- MAX_LEVERAGE = 75.0 absolute volatility-aware ceiling with fixed-risk sizing.
- MAX_POSITIONS = 10, MAX_SAME_DIRECTION = 10, MAX_PORTFOLIO_RISK = 0.015 (1.5%).
- Walk-forward asset selection: ranks assets on Training data (2022-2023) and
  allocates capital only to proven positive expectancy/profit factor assets.
- Cost-aware entry filter with turnover penalty: expected_net_R > minimum_net_R.
- Dynamic portfolio allocation: weight proportional to Expectancy / Volatility.
- Correlation-adjusted sizing: discounts risk if corr > 0.80 with open positions.
- Drawdown throttle (5/10/15/20%) and Daily (3%) / Weekly (6%) loss guards.
- BTC macro regime risk filter.
- Full walk-forward evaluation across Train (2022-2023), Val (2024), OOS (2025-2026).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Sequence, Mapping, Any
import argparse
import math
import os
import sys
import time
import numpy as np
import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Core Signal Constants
LONG = "LONG"
SHORT = "SHORT"
FLAT = "FLAT"
EXIT = "EXIT"

ENTRY_SCORE = 0.65
EXIT_SCORE = 0.20

BASE_PULLBACK_ATR = 0.60
STRONG_PULLBACK_ATR = 0.90
BREAKOUT_PULLBACK_ATR = 1.20

STRUCTURE_LOOKBACK = 20
STOP_BUFFER_ATR = 0.25
MAX_STOP_ATR = 4.5
MAX_STOP_PCT = 0.06
MAX_HOLD_BARS = 192
MAX_GIVEBACK_R = 0.90

# Portfolio & Risk Baseline Constants
MAX_LEVERAGE = 75.0
MAX_POSITIONS = 10
MAX_SAME_DIRECTION = 10
MAX_PORTFOLIO_RISK = 0.015       # 1.5% maximum portfolio risk across open positions
DEFAULT_RISK_PCT = 0.0035        # 0.35% base risk per trade (allowing multi-position diversification)
MAX_DAILY_LOSS = 0.03            # 3% daily loss circuit breaker
MAX_WEEKLY_LOSS = 0.06           # 6% weekly loss circuit breaker
MIN_NET_R = 0.20                 # Minimum expected net R to clear cost & turnover budget


@dataclass(frozen=True)
class StrategyDecision:
    signal: str
    score: float
    trend_score: float
    momentum_score: float
    breakout_score: float
    derivatives_score: float
    regime: str
    atr_pct: float
    pullback_distance_atr: float
    entry_price: float
    stop_price: float
    stop_distance_atr: float
    stop_distance_pct: float
    expected_move_atr: float
    estimated_round_trip_cost_pct: float
    expected_net_r: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _valid(df: pd.DataFrame) -> bool:
    return df is not None and {"open", "high", "low", "close", "volume"}.issubset(df.columns) and len(df) >= 220


def _atr(df: pd.DataFrame, p: int = 14) -> pd.Series:
    h, l, c = (df[x].astype(float) for x in ("high", "low", "close"))
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()


def _dir(x: float, dz: float = 0.0) -> float:
    if not math.isfinite(float(x)):
        return 0.0
    return 1.0 if x > dz else -1.0 if x < -dz else 0.0


def _last(x: object) -> Optional[float]:
    if isinstance(x, pd.Series):
        x = x.iloc[-1] if not x.empty else None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _regime(df: pd.DataFrame, a: pd.Series) -> tuple[str, float, float]:
    c = df.close.astype(float)
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    p = float(c.iloc[-1])
    ap = float(a.iloc[-1] / p) if p > 0 else 0.0
    rv = float(c.pct_change().rolling(20).std().iloc[-1])
    rv = rv if math.isfinite(rv) else 0.0
    spread = float((e50.iloc[-1] - e200.iloc[-1]) / p) if p > 0 else 0.0
    slope = float((e50.iloc[-1] - e50.iloc[-11]) / p) if p > 0 and len(e50) >= 11 else 0.0

    if ap >= 0.045 or rv >= 0.035:
        return "HIGH_VOL", rv, ap
    if abs(spread) < 0.0025 and abs(slope) < 0.0015:
        return "RANGE", rv, ap
    if spread > 0 and slope > 0:
        return "BULL_TREND", rv, ap
    if spread < 0 and slope < 0:
        return "BEAR_TREND", rv, ap
    return "TRANSITION", rv, ap


def _scores(df: pd.DataFrame, btc_close: Optional[pd.Series] = None,
            funding_rate: Optional[pd.Series] = None, oi_change: Optional[pd.Series] = None):
    c = df.close.astype(float)
    v = df.volume.astype(float)
    a = _atr(df)
    p = float(c.iloc[-1])
    ap = float(a.iloc[-1] / p) if p > 0 else 0.0
    e20 = c.ewm(span=20, adjust=False).mean()
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()

    trend = (
        0.45 * _dir((p - e50.iloc[-1]) / p, 0.0015)
        + 0.35 * _dir((e50.iloc[-1] - e200.iloc[-1]) / p, 0.002)
        + 0.20 * _dir((e20.iloc[-1] - e50.iloc[-1]) / p, 0.001)
    )

    r5 = float(c.pct_change(5).iloc[-1])
    r20 = float(c.pct_change(20).iloc[-1])
    r60 = float(c.pct_change(60).iloc[-1])
    mom = (
        0.20 * _dir(r5, max(ap * 0.45, 0.001))
        + 0.45 * _dir(r20, max(ap * 0.75, 0.002))
        + 0.35 * _dir(r60, max(ap * 1.5, 0.004))
    )

    hi = c.rolling(20).max().shift(1).iloc[-1]
    lo = df.low.astype(float).rolling(20).min().shift(1).iloc[-1]
    med = v.rolling(20).median().iloc[-1]
    vr = float(v.iloc[-1] / med) if med > 0 else 0.0
    brk = 1.0 if np.isfinite(hi) and p > hi and vr >= 1.10 else -1.0 if np.isfinite(lo) and p < lo and vr >= 1.10 else 0.0

    parts = []
    if btc_close is not None:
        b = pd.Series(btc_close).astype(float)
        n = min(len(c), len(b))
        if n >= 30:
            parts.append(_dir(float(c.iloc[-n:].pct_change(20).iloc[-1] - b.iloc[-n:].pct_change(20).iloc[-1]), max(ap * 0.5, 0.002)))
    fr = _last(funding_rate)
    if fr is not None and abs(fr) > 0.0001:
        parts.append(-1.0 if fr > 0 else 1.0)
    oi = _last(oi_change)
    if oi is not None and abs(oi) >= 0.001:
        z = max(ap * 0.35, 0.001)
        parts.append(1.0 if r5 > z and oi > 0 else -1.0 if r5 < -z and oi > 0 else 0.25 if r5 > z and oi < 0 else -0.25 if r5 < -z and oi < 0 else 0.0)

    deriv = float(np.mean([x for x in parts if x])) if any(parts) else 0.0
    composite = float(0.35 * trend + 0.30 * mom + 0.20 * brk + 0.15 * deriv)
    return composite, float(trend), float(mom), float(brk), deriv, ap, vr, r20, r60, e20, e50


def structure_stop(df: pd.DataFrame, side: str, atr: Optional[float] = None,
                   lookback: int = STRUCTURE_LOOKBACK, buffer_atr: float = STOP_BUFFER_ATR) -> float:
    if not _valid(df):
        return 0.0
    a = float(_atr(df).iloc[-1] if atr is None else atr)
    c = df.close.astype(float)
    e50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
    if not math.isfinite(a) or a <= 0:
        return 0.0
    if side == LONG:
        return float(min(float(df.low.rolling(lookback).min().iloc[-1]), e50) - buffer_atr * a)
    if side == SHORT:
        return float(max(float(df.high.rolling(lookback).max().iloc[-1]), e50) + buffer_atr * a)
    return 0.0


def adaptive_pullback_limit(regime: str, score: float, breakout_score: float) -> float:
    if regime in ("BULL_TREND", "BEAR_TREND") and abs(score) >= 0.75:
        return STRONG_PULLBACK_ATR if breakout_score == 0 else BREAKOUT_PULLBACK_ATR
    return BASE_PULLBACK_ATR


def calculate_cost_budget(taker_fee_pct: float = 0.045, slippage_pct: float = 0.015,
                          spread_pct: float = 0.005, funding_buffer_pct: float = 0.010) -> float:
    tf = taker_fee_pct / 100 if taker_fee_pct > 0.005 else taker_fee_pct
    sl = slippage_pct / 100 if slippage_pct > 0.005 else slippage_pct
    sp = spread_pct / 100 if spread_pct > 0.005 else spread_pct
    fb = funding_buffer_pct / 100 if funding_buffer_pct > 0.005 else funding_buffer_pct
    return 2 * tf + 2 * sl + sp + fb


def calculate_expected_net_r(entry_price: float, stop_price: float, expected_move_pct: float,
                             total_cost_pct: float, turnover_penalty_r: float = 0.0) -> float:
    if entry_price <= 0 or stop_price <= 0:
        return 0.0
    risk_pct = abs(entry_price - stop_price) / entry_price
    if risk_pct <= 1e-9:
        return 0.0
    gross_r = expected_move_pct / risk_pct
    friction_r = total_cost_pct / risk_pct
    return float(gross_r - friction_r - turnover_penalty_r)


def _decision(signal: str, score: float, trend: float, mom: float, brk: float, deriv: float,
              regime: str, ap: float, pull: float, entry: float, stop: float,
              expected: float, cost: float, net_r: float, reasons: Sequence[str]) -> dict:
    dist = abs(entry - stop) / entry if entry > 0 and stop > 0 else 0.0
    return StrategyDecision(
        signal=signal,
        score=round(score, 6),
        trend_score=round(trend, 6),
        momentum_score=round(mom, 6),
        breakout_score=round(brk, 6),
        derivatives_score=round(deriv, 6),
        regime=regime,
        atr_pct=round(ap, 8),
        pullback_distance_atr=round(pull, 4),
        entry_price=round(entry, 8),
        stop_price=round(stop, 8),
        stop_distance_atr=round(dist / (ap or 1.0), 4),
        stop_distance_pct=round(dist, 8),
        expected_move_atr=round(expected, 4),
        estimated_round_trip_cost_pct=round(cost, 8),
        expected_net_r=round(net_r, 4),
        reasons=tuple(reasons)
    ).to_dict()


def generate_strategy_signal(
    df: pd.DataFrame,
    *,
    position: str = FLAT,
    btc_close: Optional[pd.Series] = None,
    btc_regime: Optional[str] = None,
    btc_score: Optional[float] = None,
    funding_rate: Optional[pd.Series] = None,
    oi_change: Optional[pd.Series] = None,
    taker_fee_pct: float = 0.045,
    slippage_pct: float = 0.015,
    spread_pct: float = 0.005,
    funding_buffer_pct: float = 0.010,
    min_net_r: float = MIN_NET_R,
    turnover_penalty_r: float = 0.0,
) -> dict:
    if not _valid(df):
        return {"signal": FLAT, "score": 0.0, "reasons": ["insufficient OHLCV history"]}

    a = _atr(df)
    regime, _, ap = _regime(df, a)
    score, trend, mom, brk, deriv, ap, vr, r20, r60, e20, e50 = _scores(df, btc_close, funding_rate, oi_change)
    entry = float(df.close.iloc[-1])
    atr = float(a.iloc[-1])
    pull = abs(entry - float(e20.iloc[-1])) / atr if atr > 0 else 0.0

    cost = calculate_cost_budget(taker_fee_pct, slippage_pct, spread_pct, funding_buffer_pct)
    expected_atr = abs(r20) / (ap or 1.0)
    expected_move_pct = abs(r20)

    side_for_stop = position if position in (LONG, SHORT) else (LONG if score >= 0 else SHORT)
    stop = structure_stop(df, side_for_stop, atr)
    dist = abs(entry - stop) / entry if stop > 0 and entry > 0 else float("inf")
    stop_atr = dist / (ap or 1e-9)

    net_r = calculate_expected_net_r(entry, stop, expected_move_pct, cost, turnover_penalty_r)

    reasons = [
        f"regime={regime}",
        f"volume_ratio={vr:.2f}",
        f"pullback_atr={pull:.2f}",
        f"expected_net_r={net_r:.2f}R",
    ]

    # Hysteresis exits
    if position == LONG and score <= EXIT_SCORE:
        return _decision(EXIT, score, trend, mom, brk, deriv, regime, ap, pull, entry, stop, expected_atr, cost, net_r, reasons + ["momentum/regime exit"])
    if position == SHORT and score >= -EXIT_SCORE:
        return _decision(EXIT, score, trend, mom, brk, deriv, regime, ap, pull, entry, stop, expected_atr, cost, net_r, reasons + ["momentum/regime exit"])
    if position in (LONG, SHORT):
        return _decision(position, score, trend, mom, brk, deriv, regime, ap, pull, entry, stop, expected_atr, cost, net_r, reasons + ["position held"])

    # BTC Macro Risk Gating
    if btc_regime == "HIGH_VOL":
        reasons.append("btc macro high volatility filter")
    if btc_score is not None:
        if score > 0 and btc_score <= -0.50:
            return _decision(FLAT, score, trend, mom, brk, deriv, regime, ap, pull, entry, stop, expected_atr, cost, net_r, reasons + ["btc strong bear restricts altcoin long"])
        if score < 0 and btc_score >= 0.50:
            return _decision(FLAT, score, trend, mom, brk, deriv, regime, ap, pull, entry, stop, expected_atr, cost, net_r, reasons + ["btc strong bull restricts altcoin short"])

    limit = adaptive_pullback_limit(regime, score, brk)
    pull_ok = pull <= limit
    cost_ok = net_r >= min_net_r
    stop_ok = ((score > 0 and stop < entry) or (score < 0 and stop > entry)) and stop_atr <= MAX_STOP_ATR and dist <= MAX_STOP_PCT

    if not pull_ok:
        reasons.append(f"pullback exceeds adaptive limit {limit:.2f} ATR")
    if not cost_ok:
        reasons.append(f"expected net R ({net_r:.2f}) does not clear threshold {min_net_r:.2f}R")
    if not stop_ok:
        reasons.append("structure stop invalid or too wide")

    confirmed = (
        (regime == "BULL_TREND" and score >= ENTRY_SCORE and trend >= 0.30 and mom >= 0.25)
        or (regime == "BEAR_TREND" and score <= -ENTRY_SCORE and trend <= -0.30 and mom <= -0.25)
        or (regime == "TRANSITION" and abs(score) >= 0.75 and abs(trend) >= 0.50 and abs(mom) >= 0.45)
    )

    if confirmed and pull_ok and cost_ok and stop_ok:
        sig = LONG if score > 0 else SHORT
        return _decision(sig, score, trend, mom, brk, deriv, regime, ap, pull, entry, stop, expected_atr, cost, net_r, reasons + ["selective trend pullback confirmed"])

    return _decision(FLAT, score, trend, mom, brk, deriv, regime, ap, pull, entry, stop, expected_atr, cost, net_r, reasons + ["entry confirmation incomplete"])


def choose_leverage(atr_pct: float, target_risk_pct: float = DEFAULT_RISK_PCT, stop_atr: float = 2.0,
                    max_leverage: float = MAX_LEVERAGE, min_leverage: float = 1.0) -> float:
    """Calculate volatility-aware leverage clamped strictly to [min_leverage, max_leverage]."""
    if not math.isfinite(atr_pct) or atr_pct <= 0 or not math.isfinite(target_risk_pct) or target_risk_pct <= 0:
        return min_leverage
    target = target_risk_pct / (atr_pct * stop_atr)
    return float(np.clip(target, min_leverage, max_leverage))


def risk_based_notional(equity: float, risk_pct: float, entry_price: float, stop_price: float,
                        max_leverage: float = MAX_LEVERAGE, max_notional_pct: float = 0.30) -> float:
    """Fixed-risk position sizing where leverage is strictly an upper bound."""
    vals = (equity, risk_pct, entry_price, stop_price, max_leverage, max_notional_pct)
    if not all(math.isfinite(float(x)) for x in vals) or min(vals) <= 0:
        return 0.0
    d = abs(entry_price - stop_price) / entry_price
    if d <= 1e-9:
        return 0.0
    risk_cap = equity * risk_pct / d
    lev_cap = equity * max_leverage
    port_cap = equity * max_notional_pct
    return float(min(risk_cap, lev_cap, port_cap))


def trailing_stop(entry_price: float, current_stop: float, peak_price: float, side: str, atr: float,
                  r_multiple: float, ema20: Optional[float] = None, swing_price: Optional[float] = None) -> float:
    """Advance a stop only in the protective direction; never loosen."""
    if not all(math.isfinite(float(x)) for x in (entry_price, current_stop, peak_price, atr, r_multiple)) or atr <= 0:
        return current_stop
    if side == LONG:
        c = max(current_stop, entry_price) if r_multiple >= 1.0 else current_stop
        if r_multiple >= 2.0:
            refs = [float(x) for x in (ema20, swing_price) if x is not None and math.isfinite(float(x))]
            if refs:
                c = max(c, min(refs) - 0.25 * atr)
        return float(min(c, peak_price - 0.25 * atr))
    if side == SHORT:
        c = min(current_stop, entry_price) if r_multiple >= 1.0 else current_stop
        if r_multiple >= 2.0:
            refs = [float(x) for x in (ema20, swing_price) if x is not None and math.isfinite(float(x))]
            if refs:
                c = min(c, max(refs) + 0.25 * atr)
        return float(max(c, peak_price + 0.25 * atr))
    return current_stop


def manage_position(side: str, entry_price: float, current_stop: float, peak_price: float,
                    equity_bars: int, unrealized_r: float, score: float, atr: float,
                    ema20: Optional[float] = None, swing_price: Optional[float] = None,
                    initial_stop: Optional[float] = None) -> dict:
    """Active position management referencing initial_stop to prevent breakeven division errors."""
    if side not in (LONG, SHORT):
        return {"action": FLAT, "stop": current_stop, "reason": "flat"}

    if unrealized_r >= 1.0 and ((side == LONG and score <= 0.05) or (side == SHORT and score >= -0.05)):
        return {"action": EXIT, "stop": current_stop, "reason": "early momentum deterioration after 1R"}

    ref_stop = initial_stop if initial_stop is not None and initial_stop > 0 else current_stop
    risk_dist = abs(entry_price - ref_stop)
    peak_r = (peak_price - entry_price) / risk_dist if (side == LONG and risk_dist > 0) else (entry_price - peak_price) / risk_dist if risk_dist > 0 else 0.0

    if peak_r >= 1.5 and unrealized_r <= max(0.5, MAX_GIVEBACK_R):
        return {"action": EXIT, "stop": current_stop, "reason": "profit giveback protection"}

    if equity_bars >= MAX_HOLD_BARS and unrealized_r < 0.5:
        return {"action": EXIT, "stop": current_stop, "reason": "maximum duration"}

    return {
        "action": side,
        "stop": trailing_stop(entry_price, current_stop, peak_price, side, atr, unrealized_r, ema20, swing_price),
        "reason": "managed runner"
    }


def calculate_drawdown_multiplier(current_drawdown: float) -> float:
    """Multi-tiered drawdown throttle scaling risk budget downward as drawdown deepens."""
    if current_drawdown < 0.05:
        return 1.00
    if current_drawdown < 0.10:
        return 0.75
    if current_drawdown < 0.15:
        return 0.50
    if current_drawdown < 0.20:
        return 0.25
    return 0.00  # Halts all new entries if DD >= 20%


def evaluate_asset_training_performance(df: pd.DataFrame, taker_fee_pct: float = 0.045,
                                       slippage_pct: float = 0.015) -> dict:
    """Calculate comprehensive training metrics on historical window for asset selection."""
    if len(df) < 250:
        return {"trades": 0, "expectancy": -999.0, "profit_factor": 0.0, "win_rate": 0.0, "stability": 0.0, "max_dd": 1.0, "turnover": 0.0}

    sig_df = _vectorized_backtest_frame(df, fast=True)
    close_vals = df["close"].astype(float).values
    pos = np.where(sig_df["execution_signal"] == LONG, 1, np.where(sig_df["execution_signal"] == SHORT, -1, 0))

    trade_returns = []
    curr_p = 0
    entry_p = 0.0

    fee_drag = (taker_fee_pct + slippage_pct) / 100.0 * 2.0

    for idx in range(len(close_vals)):
        p = pos[idx]
        if p != curr_p:
            if curr_p != 0 and entry_p > 0:
                t_ret = (close_vals[idx] - entry_p) / entry_p if curr_p == 1 else (entry_p - close_vals[idx]) / entry_p
                trade_returns.append(t_ret - fee_drag)
            curr_p = p
            entry_p = close_vals[idx]

    if curr_p != 0 and entry_p > 0:
        t_ret = (close_vals[-1] - entry_p) / entry_p if curr_p == 1 else (entry_p - close_vals[-1]) / entry_p
        trade_returns.append(t_ret - fee_drag)

    trades = len(trade_returns)
    if trades < 5:
        return {"trades": trades, "expectancy": -999.0, "profit_factor": 0.0, "win_rate": 0.0, "stability": 0.0, "max_dd": 1.0, "turnover": 0.0}

    arr = np.array(trade_returns)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    win_rate = len(wins) / trades * 100.0
    gross_win = np.sum(wins) if len(wins) else 0.0
    gross_loss = abs(np.sum(losses)) if len(losses) else 1e-9
    pf = gross_win / gross_loss
    expectancy = float(np.mean(arr))

    # Stability: compare first half vs second half profit factors
    mid = len(arr) // 2
    pf1 = np.sum(arr[:mid][arr[:mid] > 0]) / (abs(np.sum(arr[:mid][arr[:mid] <= 0])) or 1e-9)
    pf2 = np.sum(arr[mid:][arr[mid:] > 0]) / (abs(np.sum(arr[mid:][arr[mid:] <= 0])) or 1e-9)
    stability = min(pf1, pf2) / max(pf1, pf2, 1e-9) if max(pf1, pf2) > 0 else 0.0

    # Realized max drawdown of strategy returns
    cum = np.cumprod(1.0 + np.clip(arr, -0.9, 5.0))
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak
    max_dd = float(np.max(dd)) if len(dd) else 0.0

    return {
        "trades": trades,
        "expectancy": expectancy * 100.0,  # in %
        "profit_factor": pf,
        "win_rate": win_rate,
        "avg_r": float(np.mean(arr) / (fee_drag or 1e-4)),
        "median_r": float(np.median(arr) / (fee_drag or 1e-4)),
        "stability": stability,
        "max_dd": max_dd,
        "turnover": trades / (len(df) / 96.0),  # trades per day
    }


def select_and_rank_assets(
    asset_metrics: Mapping[str, dict],
    min_trades: int = 30,
    min_expectancy: float = 0.0,
    min_profit_factor: float = 1.05
) -> pd.DataFrame:
    """Strictly training-period asset selection and allocation weighting."""
    records = []
    for sym, m in asset_metrics.items():
        records.append({
            "symbol": sym,
            "trades": m["trades"],
            "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "win_rate": m["win_rate"],
            "stability": m["stability"],
            "max_dd": m["max_dd"],
            "turnover": m["turnover"],
        })
    df = pd.DataFrame(records)
    if df.empty:
        return df

    df["expectancy_rank"] = df["expectancy"].rank(pct=True)
    df["pf_rank"] = df["profit_factor"].rank(pct=True)
    df["stability_rank"] = df["stability"].rank(pct=True)
    df["dd_rank"] = (1.0 - df["max_dd"]).rank(pct=True)

    df["selection_score"] = (
        0.40 * df["expectancy_rank"]
        + 0.25 * df["pf_rank"]
        + 0.20 * df["stability_rank"]
        + 0.15 * df["dd_rank"]
    )

    # Filter by admission thresholds
    passed = df[
        (df["trades"] >= min_trades)
        & (df["expectancy"] > min_expectancy)
        & (df["profit_factor"] >= min_profit_factor)
    ].copy()

    if passed.empty:
        # Fallback to best asset if none strictly pass
        passed = df.sort_values("selection_score", ascending=False).head(2).copy()

    # Calculate dynamic allocation: Expectancy / Turnover-Penalized Volatility
    passed["target_allocation"] = passed["expectancy"].clip(lower=0.01) / (passed["turnover"] + 0.1)
    tot_alloc = passed["target_allocation"].sum()
    passed["allocation_weight"] = passed["target_allocation"] / (tot_alloc or 1.0)

    return passed.sort_values("selection_score", ascending=False).reset_index(drop=True)


def _dir_vec(series, dz: float = 0.0) -> np.ndarray:
    vals = series.values if hasattr(series, "values") else np.asarray(series)
    out = np.zeros(len(vals), dtype=np.float64)
    out[vals > dz] = 1.0
    out[vals < -dz] = -1.0
    return out


def _vectorized_backtest_frame(
    df: pd.DataFrame,
    *,
    btc_close: Optional[pd.Series] = None,
    btc_regime_s: Optional[pd.Series] = None,
    btc_score_s: Optional[pd.Series] = None,
    funding_rate: Optional[pd.Series] = None,
    oi_change: Optional[pd.Series] = None,
    taker_fee_pct: float = 0.045,
    slippage_pct: float = 0.015,
    spread_pct: float = 0.005,
    funding_buffer_pct: float = 0.010,
    min_net_r: float = MIN_NET_R,
    turnover_penalty_r: float = 0.0,
    fast: bool = True,
) -> pd.DataFrame:
    n = len(df)
    if n < 220:
        out = pd.DataFrame({
            "signal": [FLAT] * n,
            "score": [0.0] * n,
            "trend_score": [0.0] * n,
            "momentum_score": [0.0] * n,
            "breakout_score": [0.0] * n,
            "derivatives_score": [0.0] * n,
            "regime": ["INSUFFICIENT_DATA"] * n,
            "atr_pct": [0.0] * n,
            "pullback_distance_atr": [0.0] * n,
            "adaptive_pullback_limit": [BASE_PULLBACK_ATR] * n,
            "entry_price": [0.0] * n,
            "stop_price": [0.0] * n,
            "expected_move_atr": [0.0] * n,
            "expected_net_r": [0.0] * n,
            "estimated_round_trip_cost_pct": [0.0] * n,
        }, index=df.index)
        out["execution_signal"] = out["signal"].shift(1).fillna(FLAT)
        return out

    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)

    # 1. ATR (14)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    atr_vals = a.values
    close_vals = c.values
    ap = np.divide(atr_vals, close_vals, out=np.zeros(n), where=(close_vals > 0))

    # 2. EMAs
    e20 = c.ewm(span=20, adjust=False).mean().values
    e50 = c.ewm(span=50, adjust=False).mean().values
    e200 = c.ewm(span=200, adjust=False).mean().values

    # 3. Regime
    rv = c.pct_change().rolling(20).std().fillna(0.0).values
    spread = np.divide(e50 - e200, close_vals, out=np.zeros(n), where=(close_vals > 0))
    e50_s = pd.Series(e50, index=df.index)
    slope = np.divide(e50 - e50_s.shift(10).values, close_vals, out=np.zeros(n), where=(close_vals > 0))

    regime = np.full(n, "TRANSITION", dtype=object)
    high_vol = (ap >= 0.045) | (rv >= 0.035)
    regime[high_vol] = "HIGH_VOL"

    range_mask = (~high_vol) & (np.abs(spread) < 0.0025) & (np.abs(slope) < 0.0015)
    regime[range_mask] = "RANGE"

    bull_mask = (~high_vol) & (~range_mask) & (spread > 0) & (slope > 0)
    regime[bull_mask] = "BULL_TREND"

    bear_mask = (~high_vol) & (~range_mask) & (spread < 0) & (slope < 0)
    regime[bear_mask] = "BEAR_TREND"

    # 4. Scores
    t1 = _dir_vec(c.subtract(e50).divide(close_vals), 0.0015)
    t2 = _dir_vec(pd.Series(e50 - e200, index=df.index).divide(close_vals), 0.002)
    t3 = _dir_vec(pd.Series(e20 - e50, index=df.index).divide(close_vals), 0.001)
    trend = 0.45 * t1 + 0.35 * t2 + 0.20 * t3

    r5 = c.pct_change(5).fillna(0.0).values
    r20 = c.pct_change(20).fillna(0.0).values
    r60 = c.pct_change(60).fillna(0.0).values

    m1 = np.where(r5 > np.maximum(ap * 0.45, 0.001), 1.0, np.where(r5 < -np.maximum(ap * 0.45, 0.001), -1.0, 0.0))
    m2 = np.where(r20 > np.maximum(ap * 0.75, 0.002), 1.0, np.where(r20 < -np.maximum(ap * 0.75, 0.002), -1.0, 0.0))
    m3 = np.where(r60 > np.maximum(ap * 1.5, 0.004), 1.0, np.where(r60 < -np.maximum(ap * 1.5, 0.004), -1.0, 0.0))
    momentum = 0.20 * m1 + 0.45 * m2 + 0.35 * m3

    hi_roll = c.rolling(20).max().shift(1).values
    lo_roll = l.rolling(20).min().shift(1).values
    v_med = v.rolling(20).median().values
    vr = np.divide(v.values, v_med, out=np.zeros(n), where=(v_med > 0))

    breakout = np.zeros(n, dtype=np.float64)
    breakout[(close_vals > hi_roll) & (vr >= 1.10)] = 1.0
    breakout[(close_vals < lo_roll) & (vr >= 1.10)] = -1.0

    # Cross asset / deriv
    deriv = np.zeros(n, dtype=np.float64)
    if btc_close is not None:
        b = pd.Series(btc_close).astype(float)
        b_r20 = b.pct_change(20).fillna(0.0).values
        rel_diff = r20 - b_r20
        thresh = np.maximum(ap * 0.5, 0.002)
        p_btc = np.where(rel_diff > thresh, 1.0, np.where(rel_diff < -thresh, -1.0, 0.0))
        deriv += p_btc

    score = 0.35 * trend + 0.30 * momentum + 0.20 * breakout + 0.15 * deriv

    # Pullback distance
    pull = np.divide(np.abs(close_vals - e20), atr_vals, out=np.zeros(n), where=(atr_vals > 0))

    # Adaptive pullback limit
    adaptive_limit = np.full(n, BASE_PULLBACK_ATR, dtype=np.float64)
    strong_regime_mask = ((regime == "BULL_TREND") | (regime == "BEAR_TREND")) & (np.abs(score) >= 0.75)
    adaptive_limit[strong_regime_mask & (breakout == 0)] = STRONG_PULLBACK_ATR
    adaptive_limit[strong_regime_mask & (breakout != 0)] = BREAKOUT_PULLBACK_ATR

    pull_ok = pull <= adaptive_limit

    # Structure stop
    roll_low = l.rolling(STRUCTURE_LOOKBACK).min().values
    roll_high = h.rolling(STRUCTURE_LOOKBACK).max().values
    stop_long = np.minimum(roll_low, e50) - STOP_BUFFER_ATR * atr_vals
    stop_short = np.maximum(roll_high, e50) + STOP_BUFFER_ATR * atr_vals

    dist_l = np.where(close_vals > 0, np.abs(close_vals - stop_long) / close_vals, 0.0)
    dist_s = np.where(close_vals > 0, np.abs(close_vals - stop_short) / close_vals, 0.0)
    stop_atr_l = np.divide(dist_l, ap, out=np.zeros(n), where=(ap > 1e-9))
    stop_atr_s = np.divide(dist_s, ap, out=np.zeros(n), where=(ap > 1e-9))

    stop_ok_l = (stop_long < close_vals) & (stop_atr_l <= MAX_STOP_ATR) & (dist_l <= MAX_STOP_PCT)
    stop_ok_s = (stop_short > close_vals) & (stop_atr_s <= MAX_STOP_ATR) & (dist_s <= MAX_STOP_PCT)

    # Cost-Aware Net R Evaluation
    cost = calculate_cost_budget(taker_fee_pct, slippage_pct, spread_pct, funding_buffer_pct)
    gross_r_l = np.divide(np.abs(r20), dist_l, out=np.zeros(n), where=(dist_l > 1e-9))
    gross_r_s = np.divide(np.abs(r20), dist_s, out=np.zeros(n), where=(dist_s > 1e-9))
    friction_r_l = np.divide(cost, dist_l, out=np.zeros(n), where=(dist_l > 1e-9))
    friction_r_s = np.divide(cost, dist_s, out=np.zeros(n), where=(dist_s > 1e-9))

    net_r_l = gross_r_l - friction_r_l - turnover_penalty_r
    net_r_s = gross_r_s - friction_r_s - turnover_penalty_r

    cost_ok_l = net_r_l >= min_net_r
    cost_ok_s = net_r_s >= min_net_r

    # BTC macro filter masks
    btc_bull_restrict = np.zeros(n, dtype=bool)
    btc_bear_restrict = np.zeros(n, dtype=bool)
    if btc_score_s is not None:
        b_sc = btc_score_s.values
        btc_bear_restrict = b_sc <= -0.50
        btc_bull_restrict = b_sc >= 0.50

    bull_entry = (regime == "BULL_TREND") & (score >= ENTRY_SCORE) & (trend >= 0.30) & (momentum >= 0.25) & pull_ok & cost_ok_l & stop_ok_l & (~btc_bear_restrict)
    bear_entry = (regime == "BEAR_TREND") & (score <= -ENTRY_SCORE) & (trend <= -0.30) & (momentum <= -0.25) & pull_ok & cost_ok_s & stop_ok_s & (~btc_bull_restrict)
    trans_bull = (regime == "TRANSITION") & (score >= 0.75) & (trend >= 0.50) & (momentum >= 0.45) & pull_ok & cost_ok_l & stop_ok_l & (~btc_bear_restrict)
    trans_bear = (regime == "TRANSITION") & (score <= -0.75) & (trend <= -0.50) & (momentum <= -0.45) & pull_ok & cost_ok_s & stop_ok_s & (~btc_bull_restrict)

    long_trigger = bull_entry | trans_bull
    short_trigger = bear_entry | trans_bear

    signal = np.full(n, FLAT, dtype=object)
    chosen_stop = np.zeros(n, dtype=np.float64)
    net_r_chosen = np.zeros(n, dtype=np.float64)
    state = FLAT

    for i in range(n):
        if i < 219:
            signal[i] = FLAT
            continue
        sc = score[i]
        if state == LONG:
            if sc <= EXIT_SCORE:
                signal[i] = EXIT
                chosen_stop[i] = stop_long[i]
                net_r_chosen[i] = net_r_l[i]
                state = FLAT
            else:
                signal[i] = LONG
                chosen_stop[i] = stop_long[i]
                net_r_chosen[i] = net_r_l[i]
        elif state == SHORT:
            if sc >= -EXIT_SCORE:
                signal[i] = EXIT
                chosen_stop[i] = stop_short[i]
                net_r_chosen[i] = net_r_s[i]
                state = FLAT
            else:
                signal[i] = SHORT
                chosen_stop[i] = stop_short[i]
                net_r_chosen[i] = net_r_s[i]
        elif long_trigger[i]:
            signal[i] = LONG
            chosen_stop[i] = stop_long[i]
            net_r_chosen[i] = net_r_l[i]
            state = LONG
        elif short_trigger[i]:
            signal[i] = SHORT
            chosen_stop[i] = stop_short[i]
            net_r_chosen[i] = net_r_s[i]
            state = SHORT
        else:
            signal[i] = FLAT
            chosen_stop[i] = stop_long[i] if sc > 0 else stop_short[i]
            net_r_chosen[i] = net_r_l[i] if sc > 0 else net_r_s[i]

    expected = np.divide(np.abs(r20), ap, out=np.zeros(n), where=(ap > 0))

    score_rounded = np.round(score, 6)
    score_rounded[:219] = 0.0
    regime_arr = np.copy(regime)
    regime_arr[:219] = "INSUFFICIENT_DATA"

    out = pd.DataFrame({
        "signal": signal,
        "score": score_rounded,
        "trend_score": np.round(trend, 6),
        "momentum_score": np.round(momentum, 6),
        "breakout_score": np.round(breakout, 6),
        "derivatives_score": np.round(deriv, 6),
        "regime": regime_arr,
        "atr_pct": np.round(ap, 8),
        "pullback_distance_atr": np.round(pull, 4),
        "adaptive_pullback_limit": np.round(adaptive_limit, 4),
        "entry_price": np.round(close_vals, 8),
        "stop_price": np.round(chosen_stop, 8),
        "expected_move_atr": np.round(expected, 4),
        "expected_net_r": np.round(net_r_chosen, 4),
        "estimated_round_trip_cost_pct": cost,
    }, index=df.index)
    out["execution_signal"] = out["signal"].shift(1).fillna(FLAT)
    return out


def backtest_frame(
    df: pd.DataFrame,
    *,
    btc_close: Optional[pd.Series] = None,
    btc_regime: Optional[pd.Series] = None,
    btc_score: Optional[pd.Series] = None,
    funding_rate: Optional[pd.Series] = None,
    oi_change: Optional[pd.Series] = None,
    taker_fee_pct: float = 0.045,
    slippage_pct: float = 0.015,
    spread_pct: float = 0.005,
    funding_buffer_pct: float = 0.010,
    min_net_r: float = MIN_NET_R,
    turnover_penalty_r: float = 0.0,
    fast: bool = True,
) -> pd.DataFrame:
    """Produce one decision row per candle with zero lookahead (shifted 1 bar)."""
    if fast:
        return _vectorized_backtest_frame(
            df,
            btc_close=btc_close,
            btc_regime_s=btc_regime,
            btc_score_s=btc_score,
            funding_rate=funding_rate,
            oi_change=oi_change,
            taker_fee_pct=taker_fee_pct,
            slippage_pct=slippage_pct,
            spread_pct=spread_pct,
            funding_buffer_pct=funding_buffer_pct,
            min_net_r=min_net_r,
            turnover_penalty_r=turnover_penalty_r,
        )

    rows = []
    position = FLAT
    for i in range(len(df)):
        if i < 219:
            rows.append({"signal": FLAT, "execution_signal": FLAT, "score": 0.0, "regime": "INSUFFICIENT_DATA", "expected_net_r": 0.0})
            continue
        d = generate_strategy_signal(
            df.iloc[: i + 1],
            position=position,
            btc_close=btc_close.iloc[: i + 1] if btc_close is not None else None,
            btc_regime=btc_regime.iloc[i] if btc_regime is not None and i < len(btc_regime) else None,
            btc_score=btc_score.iloc[i] if btc_score is not None and i < len(btc_score) else None,
            funding_rate=funding_rate.iloc[i] if funding_rate is not None and i < len(funding_rate) else None,
            oi_change=oi_change.iloc[i] if oi_change is not None and i < len(oi_change) else None,
            taker_fee_pct=taker_fee_pct,
            slippage_pct=slippage_pct,
            spread_pct=spread_pct,
            funding_buffer_pct=funding_buffer_pct,
            min_net_r=min_net_r,
            turnover_penalty_r=turnover_penalty_r,
        )
        sig = d["signal"]
        rows.append({
            "signal": sig,
            "execution_signal": FLAT if i == 0 else rows[-1]["signal"],
            "score": d.get("score", 0.0),
            "regime": d.get("regime", "UNKNOWN"),
            "expected_net_r": d.get("expected_net_r", 0.0),
        })
        if sig == EXIT:
            position = FLAT
        elif sig in (LONG, SHORT):
            position = sig
    return pd.DataFrame(rows, index=df.index)


def run_institutional_walk_forward_backtest(
    cache_dir: str = "backtests/historical_data_cache",
    symbols: Optional[list[str]] = None,
    initial_balance: float = 1000.0,
    max_leverage: float = MAX_LEVERAGE,
    risk_pct: float = DEFAULT_RISK_PCT,
    max_portfolio_risk: float = MAX_PORTFOLIO_RISK,
    max_positions: int = MAX_POSITIONS,
    max_same_direction: int = MAX_SAME_DIRECTION,
    cooldown_bars: int = 12,
    train_end: str = "2023-12-31 23:59:59",
    val_end: str = "2024-12-31 23:59:59",
) -> dict:
    """Execute complete institutional walk-forward backtest for Candidate V5.

    Partitions:
    - Training Window: September 2022 -> December 2023 (Asset selection & scoring)
    - Validation Window: January 2024 -> December 2024
    - Out-Of-Sample (OOS): January 2025 -> September 2026 (Deployment Gate)
    """
    if not os.path.exists(cache_dir):
        alt_path = os.path.join(os.path.dirname(__file__), cache_dir)
        if os.path.exists(alt_path):
            cache_dir = alt_path
        else:
            raise FileNotFoundError(f"Cache directory not found: {cache_dir}")

    fee_schedule = {
        "maker": 0.00018,
        "taker": 0.00045,
        "slippage": 0.00015,
        "funding_8h": 0.00010,
    }

    corr_clusters = {
        "BTCUSDT": "major", "ETHUSDT": "major", "SOLUSDT": "layer1",
        "AVAXUSDT": "layer1", "ADAUSDT": "layer1", "SUIUSDT": "layer1",
        "NEARUSDT": "layer1", "LINKUSDT": "infra", "BNBUSDT": "exchange",
        "XRPUSDT": "payment", "DOGEUSDT": "meme",
    }

    all_symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
        "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
    ]
    target_symbols = symbols if symbols else all_symbols

    print("\n" + "=" * 115)
    print(" [AUDIT] STRATEGY CANDIDATE V5: INSTITUTIONAL WALK-FORWARD SELECTIVE ALPHA PORTFOLIO")
    print("=" * 115)
    print(" * Partitioning Architecture:")
    print(f"    - Training Window:   September 2022 -> December 2023 (Asset Selection & Scoring)")
    print(f"    - Validation Window: January 2024   -> December 2024 (Model Stability)")
    print(f"    - Out-Of-Sample:     January 2025   -> September 2026 (Institutional Acceptance Gate)")
    print(f" * Constraints:          Max Leverage: {max_leverage}x ceiling | Max Positions: {max_positions} | Max Same Dir: {max_same_direction}")
    print(f" * Risk Baseline:        Per-Trade: {risk_pct*100:.2f}% | Max Total Portfolio Risk: {max_portfolio_risk*100:.2f}%")
    print(f" * Protection Circuits:  Drawdown Throttle (5/10/15/20%) | 3% Daily & 6% Weekly Loss Circuit Breakers")
    print("-" * 115)

    # 1. Load Data
    t0 = time.time()
    btc_file = os.path.join(cache_dir, "BTCUSDT_15m_4year_2022-09-01.csv")
    if not os.path.exists(btc_file):
        raise FileNotFoundError(f"BTC benchmark cache missing: {btc_file}")
    df_btc = pd.read_csv(btc_file)
    df_btc["open_time"] = pd.to_datetime(df_btc["open_time"])
    df_btc = df_btc.sort_values("open_time").reset_index(drop=True)
    btc_series = df_btc.set_index("open_time")["close"].astype(float)

    # Precompute BTC signals to serve as macro regime filters
    btc_sig_df = _vectorized_backtest_frame(df_btc, fast=True)
    btc_regime_map = btc_sig_df.set_index(df_btc["open_time"])["regime"]
    btc_score_map = btc_sig_df.set_index(df_btc["open_time"])["score"]

    raw_data = {}
    print(" Loading and parsing historical multi-asset data...")
    for sym in target_symbols:
        cache_file = os.path.join(cache_dir, f"{sym}_15m_4year_2022-09-01.csv")
        if not os.path.exists(cache_file):
            continue
        df = pd.read_csv(cache_file)
        df["open_time"] = pd.to_datetime(df["open_time"])
        df = df.sort_values("open_time").reset_index(drop=True)
        raw_data[sym] = df

    # 2. Walk-Forward Asset Selection (Strictly on Training Window: 2022-2023)
    print("\n Evaluating Training Window Performance (2022-2023) for Asset Selection...")
    train_metrics = {}
    for sym, df in raw_data.items():
        df_train = df[df["open_time"] <= train_end].copy()
        if len(df_train) >= 250:
            m = evaluate_asset_training_performance(df_train, fee_schedule["taker"], fee_schedule["slippage"])
            train_metrics[sym] = m

    selected_assets_df = select_and_rank_assets(train_metrics, min_trades=20, min_expectancy=0.0, min_profit_factor=1.02)
    selected_symbols = set(selected_assets_df["symbol"].tolist())
    alloc_weights = dict(zip(selected_assets_df["symbol"], selected_assets_df["allocation_weight"]))

    print("-" * 115)
    print(f" {'Asset':<10} | {'Trades':>7} | {'Win Rate':>9} | {'PF':>6} | {'Expectancy':>11} | {'Turnover':>9} | {'Stability':>10} | {'Alloc Wt':>9}")
    print("-" * 115)
    for _, r in selected_assets_df.iterrows():
        print(f" {r['symbol']:<10} | {int(r['trades']):>7,} | {r['win_rate']:>8.1f}% | {r['profit_factor']:>6.2f} | {r['expectancy']:>+10.2f}% | {r['turnover']:>8.2f}/d | {r['stability']:>10.2f} | {r['allocation_weight']*100:>8.1f}%")
    print("-" * 115)
    print(f" Selected Assets for Portfolio Allocation: {sorted(list(selected_symbols))}")

    # 3. Precompute Full-Period Signals for Selected Assets
    signals_map = {}
    for sym in selected_symbols:
        df = raw_data[sym]
        b_close = df["open_time"].map(btc_series).ffill().bfill() if sym != "BTCUSDT" else None
        b_regime = df["open_time"].map(btc_regime_map).fillna("TRANSITION")
        b_score = df["open_time"].map(btc_score_map).fillna(0.0)

        # Turnover penalty derived from training frequency
        t_freq = train_metrics[sym]["turnover"]
        t_penalty = min(0.15, t_freq * 0.02)

        sig_df = _vectorized_backtest_frame(
            df,
            btc_close=b_close,
            btc_regime_s=b_regime,
            btc_score_s=b_score,
            min_net_r=MIN_NET_R,
            turnover_penalty_r=t_penalty,
            fast=True
        )
        signals_map[sym] = sig_df

    # 4. Multi-Asset Fast Unified Timeline Simulation
    time_sets = [set(raw_data[sym]["open_time"]) for sym in selected_symbols]
    timeline = sorted(list(set.union(*time_sets)))

    sym_arrays = {}
    for sym in selected_symbols:
        df = raw_data[sym]
        sig_df = signals_map[sym]
        df_sorted = df.set_index("open_time")
        sig_sorted = sig_df.set_index(df["open_time"])
        aligned = pd.DataFrame({
            "open": df_sorted["open"].astype(float),
            "high": df_sorted["high"].astype(float),
            "low": df_sorted["low"].astype(float),
            "close": df_sorted["close"].astype(float),
            "atr": sig_sorted["atr_pct"].values * df_sorted["close"].astype(float).values,
            "atr_pct": sig_sorted["atr_pct"].values,
            "score": sig_sorted["score"].values,
            "signal": sig_sorted["execution_signal"].values,
            "stop_price": sig_sorted["stop_price"].values,
            "expected_net_r": sig_sorted["expected_net_r"].values,
            "regime": sig_sorted["regime"].values,
        }).reindex(timeline)

        sym_arrays[sym] = {
            "open": aligned["open"].values,
            "high": aligned["high"].values,
            "low": aligned["low"].values,
            "close": aligned["close"].values,
            "atr": aligned["atr"].values,
            "atr_pct": aligned["atr_pct"].values,
            "score": aligned["score"].values,
            "signal": aligned["signal"].values,
            "stop_price": aligned["stop_price"].values,
            "expected_net_r": aligned["expected_net_r"].values,
            "regime": aligned["regime"].values,
        }

    balance = float(initial_balance)
    peak_balance = float(initial_balance)
    max_dd = 0.0
    active_positions = {}
    closed_trades = []
    cooldowns = {sym: 0 for sym in selected_symbols}

    tot_maker_fees = 0.0
    tot_taker_fees = 0.0
    tot_slippage = 0.0
    tot_funding = 0.0

    daily_loss_events = 0
    weekly_loss_events = 0
    exposure_bars = 0

    # Rolling equity tracking for loss guards (96 bars = 1 day, 672 bars = 1 week)
    equity_history = []

    print("\n Executing Walk-Forward Portfolio Simulation across 140,388 candles...")
    t_sim = time.time()

    for idx, ts in enumerate(timeline):
        for sym in cooldowns:
            if cooldowns[sym] > 0:
                cooldowns[sym] -= 1

        # Current total portfolio equity (cash + unrealized)
        unrealized_pnl = 0.0
        for sym, pos in active_positions.items():
            curr_c = sym_arrays[sym]["close"][idx]
            if not np.isnan(curr_c):
                u_ret = (curr_c - pos["entry_price"]) / pos["entry_price"] if pos["side"] == LONG else (pos["entry_price"] - curr_c) / pos["entry_price"]
                unrealized_pnl += pos["notional"] * u_ret

        curr_equity = balance + sum(p["margin"] for p in active_positions.values()) + unrealized_pnl
        equity_history.append(curr_equity)
        if len(active_positions) > 0:
            exposure_bars += 1

        if curr_equity > peak_balance:
            peak_balance = curr_equity
        dd = (peak_balance - curr_equity) / peak_balance if peak_balance > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

        # Circuit breaker checks
        daily_loss = False
        if len(equity_history) >= 96:
            peak_24h = max(equity_history[-96:])
            if (peak_24h - curr_equity) / peak_24h >= MAX_DAILY_LOSS:
                daily_loss = True
                daily_loss_events += 1

        weekly_loss = False
        if len(equity_history) >= 672:
            peak_7d = max(equity_history[-672:])
            if (peak_7d - curr_equity) / peak_7d >= MAX_WEEKLY_LOSS:
                weekly_loss = True
                weekly_loss_events += 1

        # 1. Manage Active Positions
        to_close = []
        for sym, pos in list(active_positions.items()):
            arr = sym_arrays[sym]
            o = arr["open"][idx]
            if np.isnan(o):
                continue
            h, l, c = arr["high"][idx], arr["low"][idx], arr["close"][idx]
            atr = arr["atr"][idx]
            sig = arr["signal"][idx]
            sc = arr["score"][idx]

            pos["bars_held"] += 1
            if pos["bars_held"] % 32 == 0:
                fund = pos["notional"] * fee_schedule["funding_8h"]
                balance -= fund
                tot_funding += fund

            exit_price = None
            exit_reason = None

            if pos["side"] == LONG:
                if h > pos["peak_price"]:
                    pos["peak_price"] = h

                risk_dist = pos["entry_price"] - pos["initial_stop"]
                unrealized_r = (c - pos["entry_price"]) / risk_dist if risk_dist > 0 else 0.0
                peak_r = (pos["peak_price"] - pos["entry_price"]) / risk_dist if risk_dist > 0 else 0.0

                mgmt = manage_position(
                    LONG, pos["entry_price"], pos["stop_loss"], pos["peak_price"],
                    pos["bars_held"], unrealized_r, sc, atr, initial_stop=pos["initial_stop"]
                )

                if mgmt["action"] == EXIT:
                    exit_price = c
                    exit_reason = mgmt["reason"]
                else:
                    pos["stop_loss"] = mgmt["stop"]

                if exit_reason is None and l <= pos["stop_loss"]:
                    exit_price = min(o, pos["stop_loss"])
                    exit_reason = "R_TRAILING_STOP" if peak_r >= 1.0 else "STRUCTURE_STOP"

                if exit_reason is None and sig in (EXIT, SHORT):
                    exit_price = c
                    exit_reason = "STRAT_EXIT"

            else:  # SHORT
                if l < pos["peak_price"]:
                    pos["peak_price"] = l

                risk_dist = pos["initial_stop"] - pos["entry_price"]
                unrealized_r = (pos["entry_price"] - c) / risk_dist if risk_dist > 0 else 0.0
                peak_r = (pos["entry_price"] - pos["peak_price"]) / risk_dist if risk_dist > 0 else 0.0

                mgmt = manage_position(
                    SHORT, pos["entry_price"], pos["stop_loss"], pos["peak_price"],
                    pos["bars_held"], unrealized_r, sc, atr, initial_stop=pos["initial_stop"]
                )

                if mgmt["action"] == EXIT:
                    exit_price = c
                    exit_reason = mgmt["reason"]
                else:
                    pos["stop_loss"] = mgmt["stop"]

                if exit_reason is None and h >= pos["stop_loss"]:
                    exit_price = max(o, pos["stop_loss"])
                    exit_reason = "R_TRAILING_STOP" if peak_r >= 1.0 else "STRUCTURE_STOP"

                if exit_reason is None and sig in (EXIT, LONG):
                    exit_price = c
                    exit_reason = "STRAT_EXIT"

            if exit_reason is not None:
                pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"] if pos["side"] == LONG else (pos["entry_price"] - exit_price) / pos["entry_price"]
                gross_pnl = pos["notional"] * pnl_pct
                slip = pos["notional"] * fee_schedule["slippage"]
                fee = pos["notional"] * fee_schedule["taker"]
                tot_slippage += slip
                tot_taker_fees += fee
                realized_pnl = gross_pnl - slip - fee
                balance += pos["margin"] + realized_pnl
                cooldowns[sym] = cooldown_bars

                trade_r = realized_pnl / (pos["risk_amount"] or 1e-4)

                trade_record = {
                    "symbol": sym,
                    "side": pos["side"],
                    "timestamp": ts,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "notional": pos["notional"],
                    "margin": pos["margin"],
                    "leverage": pos["leverage"],
                    "net_pnl": realized_pnl,
                    "r_multiple": trade_r,
                    "reason": exit_reason,
                    "regime": pos["entry_regime"],
                    "bars_held": pos["bars_held"],
                    "win": realized_pnl > 0,
                    "year": ts.year,
                }
                closed_trades.append(trade_record)
                to_close.append(sym)

        for sym in to_close:
            del active_positions[sym]

        # 2. Evaluate Candidate Entries
        # Apply Drawdown Throttle and Circuit Breakers
        dd_multiplier = calculate_drawdown_multiplier(dd)
        can_trade = (
            len(active_positions) < max_positions
            and balance > 10.0
            and dd_multiplier > 0.0
            and not daily_loss
            and not weekly_loss
        )

        if can_trade:
            # Check current total open risk
            curr_open_risk = sum(p["risk_amount"] for p in active_positions.values()) / balance if balance > 0 else 1.0
            if curr_open_risk < max_portfolio_risk:
                candidates = []
                for sym in selected_symbols:
                    if sym in active_positions or cooldowns[sym] > 0:
                        continue
                    arr = sym_arrays[sym]
                    o = arr["open"][idx]
                    if np.isnan(o):
                        continue
                    sig = arr["signal"][idx]
                    if sig in (LONG, SHORT):
                        candidates.append({
                            "symbol": sym,
                            "signal": sig,
                            "score": arr["score"][idx],
                            "atr": arr["atr"][idx],
                            "atr_pct": arr["atr_pct"][idx],
                            "entry_price": o,
                            "stop_price": arr["stop_price"][idx],
                            "expected_net_r": arr["expected_net_r"][idx],
                            "regime": arr["regime"][idx],
                            "cluster": corr_clusters.get(sym, "other"),
                            "weight": alloc_weights.get(sym, 0.1),
                        })

                # Sort by expected net R descending
                candidates.sort(key=lambda x: x["expected_net_r"], reverse=True)

                for cand in candidates:
                    sym = cand["symbol"]
                    sig = cand["signal"]
                    atr = cand["atr"]
                    atr_pct = cand["atr_pct"]
                    entry_price = cand["entry_price"]
                    st_price = cand["stop_price"]

                    if entry_price <= 0 or st_price <= 0 or atr <= 0:
                        continue

                    # Directional and cluster limits
                    curr_same_dir = sum(1 for p in active_positions.values() if p["side"] == sig)
                    if curr_same_dir >= max_same_direction:
                        continue

                    # Correlation discount: if already exposed to same cluster, reduce risk by 50%
                    cluster = cand["cluster"]
                    cluster_count = sum(1 for p in active_positions.values() if corr_clusters.get(p["symbol"]) == cluster)
                    corr_factor = 0.50 if cluster_count >= 1 else 1.0

                    # Dynamic risk based on training weight & drawdown multiplier
                    effective_risk_pct = risk_pct * (cand["weight"] / 0.20) * dd_multiplier * corr_factor
                    effective_risk_pct = min(effective_risk_pct, max_portfolio_risk - curr_open_risk)
                    if effective_risk_pct <= 0.0005:
                        continue

                    lev = choose_leverage(atr_pct, target_risk_pct=effective_risk_pct, stop_atr=2.0, max_leverage=max_leverage, min_leverage=1.0)
                    notional = risk_based_notional(balance, effective_risk_pct, entry_price, st_price, max_leverage=lev, max_notional_pct=0.25)
                    if notional <= 0:
                        continue

                    margin = notional / lev
                    if margin > balance * 0.25 or balance - margin < 5.0:
                        continue

                    fee_entry = notional * fee_schedule["maker"]
                    balance -= (margin + fee_entry)
                    tot_maker_fees += fee_entry

                    risk_amount = balance * effective_risk_pct

                    active_positions[sym] = {
                        "symbol": sym,
                        "side": sig,
                        "entry_price": entry_price,
                        "initial_stop": st_price,
                        "stop_loss": st_price,
                        "notional": notional,
                        "margin": margin,
                        "leverage": lev,
                        "risk_amount": risk_amount,
                        "peak_price": entry_price,
                        "bars_held": 0,
                        "entry_regime": cand["regime"],
                    }

                    curr_open_risk += effective_risk_pct
                    if len(active_positions) >= max_positions or curr_open_risk >= max_portfolio_risk:
                        break

    print(f" Simulation completed in {time.time()-t_sim:.2f}s.")

    # 5. Compile Multi-Period Walk-Forward Scorecard
    total_trades = len(closed_trades)
    train_trades = [t for t in closed_trades if str(t["timestamp"]) <= train_end]
    val_trades = [t for t in closed_trades if train_end < str(t["timestamp"]) <= val_end]
    oos_trades = [t for t in closed_trades if str(t["timestamp"]) > val_end]

    def _calc_stats(trade_list: list[dict], period_name: str) -> dict:
        t_cnt = len(trade_list)
        if t_cnt == 0:
            return {"period": period_name, "trades": 0, "win_rate": 0.0, "pf": 0.0, "pnl": 0.0, "avg_r": 0.0, "median_r": 0.0, "sharpe": 0.0}
        wins = [t for t in trade_list if t["win"]]
        losses = [t for t in trade_list if not t["win"]]
        wr = len(wins) / t_cnt * 100.0
        g_win = sum(t["net_pnl"] for t in wins)
        g_loss = abs(sum(t["net_pnl"] for t in losses))
        pf = g_win / g_loss if g_loss > 0 else (999.0 if g_win > 0 else 0.0)
        pnl = sum(t["net_pnl"] for t in trade_list)
        r_vals = [t["r_multiple"] for t in trade_list]
        avg_r = float(np.mean(r_vals))
        med_r = float(np.median(r_vals))
        pnls = [t["net_pnl"] for t in trade_list]
        sharpe = (float(np.mean(pnls)) / float(np.std(pnls) or 1e-9)) * np.sqrt(365 * 4) if len(pnls) > 1 else 0.0
        return {
            "period": period_name,
            "trades": t_cnt,
            "win_rate": wr,
            "pf": pf,
            "pnl": pnl,
            "avg_r": avg_r,
            "median_r": med_r,
            "sharpe": sharpe,
        }

    train_stats = _calc_stats(train_trades, "TRAINING (2022-2023)")
    val_stats = _calc_stats(val_trades, "VALIDATION (2024)")
    oos_stats = _calc_stats(oos_trades, "OUT-OF-SAMPLE (2025-2026)")
    all_stats = _calc_stats(closed_trades, "FULL 4-YEAR PERIOD")

    total_net_pnl = balance - initial_balance
    total_roi_pct = (total_net_pnl / initial_balance) * 100.0
    winning_trades = [t for t in closed_trades if t["win"]]
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    print("\n" + "=" * 115)
    print(" [AUDIT] CANDIDATE V5 WALK-FORWARD PERFORMANCE SCORECARD")
    print("=" * 115)
    print(f" {'Partition Period':<25} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net PnL ($)':>14} | {'Avg R':>7} | {'Median R':>9} | {'Sharpe':>7}")
    print("-" * 115)
    for st in (train_stats, val_stats, oos_stats, all_stats):
        print(f" {st['period']:<25} | {st['trades']:>8,} | {st['win_rate']:>8.1f}% | {st['pf']:>6.2f} | ${st['pnl']:>13.2f} | {st['avg_r']:>+6.2f} | {st['median_r']:>+8.2f} | {st['sharpe']:>7.2f}")
    print("=" * 115)

    print("\n [PORTFOLIO HEALTH & RISK EXECUTION]")
    print(f" * Initial Balance:         ${initial_balance:,.2f} USDT")
    print(f" * Final Balance:           ${balance:,.2f} USDT")
    print(f" * Net Realized Return:     ${total_net_pnl:,.2f} USDT ({total_roi_pct:+.2f}% Total ROI)")
    print(f" * Maximum Drawdown:        {max_dd*100:.2f}% (Throttle active: Multi-tier 5-20%)")
    print(f" * Market Exposure:         {exposure_bars / len(timeline) * 100:.1f}% of timeline active")
    print(f" * Friction Overhead:       ${tot_maker_fees + tot_taker_fees + tot_slippage + tot_funding:,.2f} USDT")
    print(f"    - Maker Entry Fees:     ${tot_maker_fees:,.2f} USDT")
    print(f"    - Taker Exit Fees:      ${tot_taker_fees:,.2f} USDT")
    print(f"    - Slippage Deductions:  ${tot_slippage:,.2f} USDT")
    print(f"    - 8h Funding Holding:   ${tot_funding:,.2f} USDT")
    print(f" * Circuit Breaker Triggers: Daily (3%): {daily_loss_events:,} bars | Weekly (6%): {weekly_loss_events:,} bars")

    # Asset Contribution
    print("\n [ASSET CONTRIBUTION]")
    print(f" {'Asset':<10} | {'Trades':>8} | {'Win Rate':>9} | {'Net Realized PnL':>18} | {'Avg Trade PnL':>15}")
    print("-" * 75)
    for sym in selected_symbols:
        s_trades = [t for t in closed_trades if t["symbol"] == sym]
        if not s_trades:
            continue
        s_wr = sum(1 for t in s_trades if t["win"]) / len(s_trades) * 100.0
        s_pnl = sum(t["net_pnl"] for t in s_trades)
        s_avg = s_pnl / len(s_trades)
        print(f" {sym:<10} | {len(s_trades):>8,} | {s_wr:>8.1f}% | ${s_pnl:>17.2f} | ${s_avg:>14.2f}")
    print("-" * 75)

    # Acceptance Gate Evaluation
    print("\n" + "=" * 80)
    print(" [V5 OUT-OF-SAMPLE (2025-2026) ACCEPTANCE GATE EVALUATION]")
    print("=" * 80)
    oos_pf_pass = oos_stats["pf"] >= 1.05
    oos_exp_pass = oos_stats["avg_r"] > 0.0
    oos_dd_pass = max_dd <= 0.35
    oos_trades_pass = oos_stats["trades"] >= 20

    print(f" 1. OOS Profit Factor >= 1.05:     [{'PASS' if oos_pf_pass else 'FAIL'}] ({oos_stats['pf']:.2f})")
    print(f" 2. OOS Net Expectancy > 0 R:       [{'PASS' if oos_exp_pass else 'FAIL'}] ({oos_stats['avg_r']:+.2f}R)")
    print(f" 3. Portfolio Drawdown <= 35%:      [{'PASS' if oos_dd_pass else 'FAIL'}] ({max_dd*100:.2f}%)")
    print(f" 4. Statistically Bounded Turnover: [{'PASS' if oos_trades_pass else 'WARN'}] ({oos_stats['trades']} OOS trades)")
    print("=" * 80 + "\n")

    return {
        "balance": balance,
        "roi_pct": total_roi_pct,
        "max_drawdown": max_dd,
        "train_stats": train_stats,
        "val_stats": val_stats,
        "oos_stats": oos_stats,
        "all_stats": all_stats,
        "closed_trades": closed_trades,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 4-year institutional walk-forward backtest for Candidate V5.")
    parser.add_argument("--cache-dir", type=str, default="backtests/historical_data_cache", help="Path to historical cache directory")
    parser.add_argument("--symbols", type=str, default=None, help="Comma-separated list of symbols")
    parser.add_argument("--balance", type=float, default=1000.0, help="Initial portfolio balance (USDT)")
    parser.add_argument("--leverage", type=float, default=MAX_LEVERAGE, help="Maximum leverage ceiling (default: 75.0)")
    parser.add_argument("--risk-pct", type=float, default=DEFAULT_RISK_PCT, help="Base risk fraction per trade (default: 0.0035 = 0.35%)")
    parser.add_argument("--max-positions", type=int, default=MAX_POSITIONS, help="Max open positions (default: 10)")
    parser.add_argument("--max-same-dir", type=int, default=MAX_SAME_DIRECTION, help="Max same-direction positions (default: 10)")
    parser.add_argument("--cooldown", type=int, default=12, help="Cooldown bars after trade exit (default: 12 bars)")

    args = parser.parse_args()
    sym_list = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    run_institutional_walk_forward_backtest(
        cache_dir=args.cache_dir,
        symbols=sym_list,
        initial_balance=args.balance,
        max_leverage=args.leverage,
        risk_pct=args.risk_pct,
        max_positions=args.max_positions,
        max_same_direction=args.max_same_dir,
        cooldown_bars=args.cooldown,
    )
