"""Offline Strategy Candidate V9: 15m Multi-Setup Opportunity Engine.

Research-only. This module does not import main.py, access exchanges, or place orders.
It is designed to test a broader 15-minute opportunity layer while leaving Atlas'
production execution/safety framework unchanged.

The engine deliberately separates:
  * market regime detection;
  * independent 15m setup families;
  * confirmation/evidence scoring;
  * next-bar execution simulation.

Setup families:
  TREND_CONTINUATION, PULLBACK_CONTINUATION, FIB_OTE, MSS_SHIFT,
  LIQUIDITY_SWEEP, BREAKOUT_RETEST, VWAP_TREND, VWAP_REVERSION,
  BB_ATR_EXPANSION, EXHAUSTION_REVERSAL.

VWAP is intentionally dual-mode: it can trade trend pullbacks as well as
range mean reversion. The regime determines which interpretation is eligible.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from math import isfinite
from typing import Iterable, Sequence
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

LONG = 1
SHORT = -1
FLAT = 0

SETUPS = (
    "TREND_CONTINUATION",
    "PULLBACK_CONTINUATION",
    "FIB_OTE",
    "MSS_SHIFT",
    "LIQUIDITY_SWEEP",
    "BREAKOUT_RETEST",
    "VWAP_TREND",
    "VWAP_REVERSION",
    "BB_ATR_EXPANSION",
    "EXHAUSTION_REVERSAL",
)

REGIMES = ("STRONG_TREND", "MILD_TREND", "RANGE", "HIGH_VOL", "BREAKDOWN", "CHOP")

@dataclass(frozen=True)
class Signal:
    timestamp: str
    symbol: str
    side: int
    setup: str
    score: int
    regime: str
    entry: float
    stop: float
    target: float
    atr: float

@dataclass(frozen=True)
class Trade:
    timestamp: str
    symbol: str
    side: int
    setup: str
    regime: str
    entry: float
    exit: float
    r_multiple: float
    friction_r: float
    bars_held: int

@dataclass(frozen=True)
class BacktestStats:
    trades: int
    wins: int
    win_rate: float
    profit_factor: float
    net_r: float
    expectancy_r: float
    max_drawdown_r: float
    avg_bars_held: float


def _num(x: object, default: float = 0.0) -> float:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return default
    return y if isfinite(y) else default


def _pf(values: Sequence[float]) -> float:
    wins = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    if losses == 0:
        return 999.0 if wins else 0.0
    return wins / losses


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic 15m indicators without look-ahead."""
    out = df.copy()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {sorted(missing)}")
    for c in required:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=list(required)).copy()
    out = out.sort_index()
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]

    out["ema9"] = close.ewm(span=9, adjust=False).mean()
    out["ema20"] = close.ewm(span=20, adjust=False).mean()
    out["ema50"] = close.ewm(span=50, adjust=False).mean()
    out["ema100"] = close.ewm(span=100, adjust=False).mean()
    out["ema200"] = close.ewm(span=200, adjust=False).mean()
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    rs = gain.ewm(alpha=1/14, adjust=False).mean() / loss.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    out["rsi"] = (100 - (100/(1+rs))).fillna(50)
    out["vol_ma"] = volume.rolling(20).mean()
    out["vol_ratio"] = volume / out["vol_ma"].replace(0, np.nan)
    out["range_high20"] = high.shift(1).rolling(20).max()
    out["range_low20"] = low.shift(1).rolling(20).min()
    out["swing_high5"] = high.shift(1).rolling(5).max()
    out["swing_low5"] = low.shift(1).rolling(5).min()
    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    out["bb_mid"] = mid
    out["bb_upper"] = mid + 2*std
    out["bb_lower"] = mid - 2*std
    out["bb_width"] = (out["bb_upper"]-out["bb_lower"]) / mid.replace(0, np.nan)
    # Rolling VWAP is a stable offline proxy for intraday/session VWAP.
    pv = close * volume
    out["vwap"] = pv.rolling(96).sum() / volume.rolling(96).sum().replace(0, np.nan)
    out["vwap_dist_atr"] = (close-out["vwap"]) / out["atr"].replace(0, np.nan)
    out["atr_ratio"] = out["atr"] / out["atr"].rolling(50).mean().replace(0, np.nan)
    return out


def classify_regime(row: pd.Series) -> str:
    """Classify the 15m environment from trend alignment, ATR and VWAP behavior."""
    close, atr = _num(row.close), _num(row.atr)
    if atr <= 0:
        return "CHOP"
    trend_gap = abs(_num(row.ema20)-_num(row.ema50)) / atr
    stack_up = row.ema20 > row.ema50 > row.ema100
    stack_dn = row.ema20 < row.ema50 < row.ema100
    high_vol = _num(row.atr_ratio, 1.0) >= 1.45 or _num(row.vol_ratio, 1.0) >= 1.8
    if stack_dn and close < _num(row.ema200) and trend_gap >= 1.2:
        return "BREAKDOWN"
    if high_vol:
        return "HIGH_VOL"
    if (stack_up or stack_dn) and trend_gap >= 2.0:
        return "STRONG_TREND"
    if (stack_up or stack_dn) and trend_gap >= 0.8:
        return "MILD_TREND"
    if abs(_num(row.vwap_dist_atr, 9.0)) <= 1.2 and trend_gap < 0.6:
        return "RANGE"
    return "CHOP"


def _side_from_trend(row: pd.Series) -> int:
    if row.ema20 > row.ema50 > row.ema100 > row.ema200:
        return LONG
    if row.ema20 < row.ema50 < row.ema100 < row.ema200:
        return SHORT
    return FLAT


def setup_votes(row: pd.Series, prev: pd.Series | None = None) -> dict[str, int]:
    """Return independent setup directions. No setup is allowed to trade on score alone."""
    votes = {s: FLAT for s in SETUPS}
    regime = str(row.regime)
    trend = _side_from_trend(row)
    close, atr = _num(row.close), _num(row.atr)
    if atr <= 0:
        return votes

    # 1) Trend continuation: only aligned trends, not ranges.
    if trend and regime in {"STRONG_TREND", "MILD_TREND", "BREAKDOWN"}:
        pull = abs(close-_num(row.ema20)) <= 0.55*atr
        if pull and _num(row.vol_ratio, 1) >= 0.9:
            votes["TREND_CONTINUATION"] = trend

    # 2) Pullback continuation: reclaim EMA20 in direction of EMA50.
    if trend and prev is not None:
        if trend == LONG and prev.close <= prev.ema20 < close:
            votes["PULLBACK_CONTINUATION"] = LONG
        elif trend == SHORT and prev.close >= prev.ema20 > close:
            votes["PULLBACK_CONTINUATION"] = SHORT

    # 3) Fibonacci/OTE proxy: retracement into 0.618-0.886 of prior 20-bar impulse.
    hi, lo = _num(row.range_high20), _num(row.range_low20)
    if hi > lo and trend:
        span = hi-lo
        retr = (hi-close)/span if trend == LONG else (close-lo)/span
        if 0.618 <= retr <= 0.886:
            votes["FIB_OTE"] = trend

    # 4) MSS/CHoCH: break of recent 5-bar structure with volume confirmation.
    if close > _num(row.swing_high5) and _num(row.vol_ratio, 0) >= 1.25:
        votes["MSS_SHIFT"] = LONG
    elif close < _num(row.swing_low5) and _num(row.vol_ratio, 0) >= 1.25:
        votes["MSS_SHIFT"] = SHORT

    # 5) Liquidity sweep: wick through prior structure, close back inside.
    if row.low < _num(row.range_low20) and close > _num(row.range_low20):
        votes["LIQUIDITY_SWEEP"] = LONG
    elif row.high > _num(row.range_high20) and close < _num(row.range_high20):
        votes["LIQUIDITY_SWEEP"] = SHORT

    # 6) Breakout/retest proxy: close beyond structure after a prior near-level bar.
    if close > _num(row.range_high20) and _num(row.vol_ratio, 0) >= 1.2:
        votes["BREAKOUT_RETEST"] = LONG
    elif close < _num(row.range_low20) and _num(row.vol_ratio, 0) >= 1.2:
        votes["BREAKOUT_RETEST"] = SHORT

    # 7) VWAP trend mode: trend pullback/rejection at VWAP.
    vd = _num(row.vwap_dist_atr, 99)
    if trend == LONG and regime in {"STRONG_TREND", "MILD_TREND"} and -0.35 <= vd <= 0.35:
        votes["VWAP_TREND"] = LONG
    elif trend == SHORT and regime in {"STRONG_TREND", "BREAKDOWN", "MILD_TREND"} and -0.35 <= vd <= 0.35:
        votes["VWAP_TREND"] = SHORT

    # 8) VWAP range mode: stretch away from VWAP and revert.
    if regime == "RANGE" and vd <= -1.25 and row.rsi <= 42:
        votes["VWAP_REVERSION"] = LONG
    elif regime == "RANGE" and vd >= 1.25 and row.rsi >= 58:
        votes["VWAP_REVERSION"] = SHORT

    # 9) Bollinger/ATR expansion: directional expansion with volume.
    if _num(row.atr_ratio, 0) >= 1.15 and _num(row.vol_ratio, 0) >= 1.3:
        if close > _num(row.bb_upper):
            votes["BB_ATR_EXPANSION"] = LONG
        elif close < _num(row.bb_lower):
            votes["BB_ATR_EXPANSION"] = SHORT

    # 10) Exhaustion reversal: extreme RSI + volatility extension.
    if row.rsi <= 25 and vd <= -1.5 and regime in {"RANGE", "HIGH_VOL"}:
        votes["EXHAUSTION_REVERSAL"] = LONG
    elif row.rsi >= 75 and vd >= 1.5 and regime in {"RANGE", "HIGH_VOL"}:
        votes["EXHAUSTION_REVERSAL"] = SHORT
    return votes


def allowed_setups(regime: str) -> set[str]:
    return {
        "STRONG_TREND": {"TREND_CONTINUATION", "PULLBACK_CONTINUATION", "FIB_OTE", "MSS_SHIFT", "BREAKOUT_RETEST", "VWAP_TREND", "BB_ATR_EXPANSION"},
        "MILD_TREND": {"TREND_CONTINUATION", "PULLBACK_CONTINUATION", "FIB_OTE", "MSS_SHIFT", "VWAP_TREND"},
        "RANGE": {"LIQUIDITY_SWEEP", "VWAP_REVERSION", "EXHAUSTION_REVERSAL"},
        "HIGH_VOL": {"MSS_SHIFT", "LIQUIDITY_SWEEP", "BREAKOUT_RETEST", "BB_ATR_EXPANSION", "EXHAUSTION_REVERSAL"},
        "BREAKDOWN": {"TREND_CONTINUATION", "PULLBACK_CONTINUATION", "MSS_SHIFT", "BREAKOUT_RETEST", "VWAP_TREND"},
        "CHOP": set(),
    }.get(regime, set())


def opportunity_score(row: pd.Series, votes: dict[str, int], setup: str) -> tuple[int, int]:
    """Score a setup and return (score, confirmation_count)."""
    side = votes.get(setup, FLAT)
    if side == FLAT or setup not in allowed_setups(str(row.regime)):
        return 0, 0
    score = 2
    confirmations = 0
    trend = _side_from_trend(row)
    if trend == side:
        score += 2; confirmations += 1
    if votes.get("MSS_SHIFT") == side:
        score += 1; confirmations += 1
    if votes.get("LIQUIDITY_SWEEP") == side:
        score += 1; confirmations += 1
    if votes.get("PULLBACK_CONTINUATION") == side:
        score += 1; confirmations += 1
    if _num(row.vol_ratio, 0) >= 1.2:
        score += 1
    if _num(row.atr_ratio, 1) >= 1.05:
        score += 1
    if str(row.regime) in {"RANGE", "CHOP"} and setup in {"VWAP_REVERSION", "EXHAUSTION_REVERSAL"}:
        confirmations += 1
    return score, confirmations


def generate_signals(df: pd.DataFrame, min_score: int = 5, min_confirmations: int = 1) -> list[Signal]:
    """Generate at most one highest-quality opportunity per bar."""
    data = add_indicators(df)
    data["regime"] = data.apply(classify_regime, axis=1)
    signals: list[Signal] = []
    for i in range(201, len(data)):
        row, prev = data.iloc[i], data.iloc[i-1]
        votes = setup_votes(row, prev)
        candidates = []
        for setup in SETUPS:
            score, confirmations = opportunity_score(row, votes, setup)
            if score >= min_score and confirmations >= min_confirmations:
                candidates.append((score, confirmations, setup, votes[setup]))
        if not candidates:
            continue
        score, confirmations, setup, side = max(candidates, key=lambda x: (x[0], x[1]))
        atr = _num(row.atr)
        if side == LONG:
            entry, stop, target = _num(row.close), _num(row.close)-1.25*atr, _num(row.close)+2.0*atr
        else:
            entry, stop, target = _num(row.close), _num(row.close)+1.25*atr, _num(row.close)-2.0*atr
        signals.append(Signal(str(data.index[i]), str(row.get("symbol", "UNKNOWN")), side, setup, score, str(row.regime), entry, stop, target, atr))
    return signals


def backtest_frame(df: pd.DataFrame, min_score: int = 5, min_confirmations: int = 1, friction_r: float = 0.026, max_hold_bars: int = 32) -> list[Trade]:
    """Next-bar execution simulation with conservative stop-first handling."""
    data = add_indicators(df)
    if "symbol" not in data.columns:
        data["symbol"] = "UNKNOWN"
    data["regime"] = data.apply(classify_regime, axis=1)
    trades: list[Trade] = []
    i = 201
    while i < len(data)-1:
        row, prev = data.iloc[i], data.iloc[i-1]
        votes = setup_votes(row, prev)
        candidates = []
        for setup in SETUPS:
            score, confirmations = opportunity_score(row, votes, setup)
            if score >= min_score and confirmations >= min_confirmations:
                candidates.append((score, confirmations, setup, votes[setup]))
        if not candidates:
            i += 1; continue
        score, confirmations, setup, side = max(candidates, key=lambda x: (x[0], x[1]))
        atr = _num(row.atr)
        if atr <= 0:
            i += 1; continue
        entry_idx = i + 1
        entry = _num(data.iloc[entry_idx].open)
        stop = entry - side*1.25*atr
        target = entry + side*2.0*atr
        exit_px, held = entry, 0
        for j in range(entry_idx, min(len(data), entry_idx+max_hold_bars)):
            bar = data.iloc[j]; held += 1
            stop_hit = (_num(bar.low) <= stop) if side == LONG else (_num(bar.high) >= stop)
            target_hit = (_num(bar.high) >= target) if side == LONG else (_num(bar.low) <= target)
            if stop_hit:
                exit_px = stop; break
            if target_hit:
                exit_px = target; break
            exit_px = _num(bar.close)
        gross_r = side*(exit_px-entry)/max(abs(entry-stop), 1e-12)
        net_r = gross_r-friction_r
        trades.append(Trade(str(data.index[entry_idx]), str(row.symbol), side, setup, str(row.regime), entry, exit_px, net_r, friction_r, held))
        i = entry_idx + max(1, held)
    return trades


def summarize(trades: Sequence[Trade]) -> BacktestStats:
    vals = [t.r_multiple for t in trades]
    if not vals:
        return BacktestStats(0,0,0.0,0.0,0.0,0.0,0.0,0.0)
    equity = peak = 0.0
    max_dd = 0.0
    for v in vals:
        equity += v
        peak = max(peak, equity)
        max_dd = max(max_dd, peak-equity)
    return BacktestStats(
        trades=len(vals), wins=sum(v>0 for v in vals), win_rate=sum(v>0 for v in vals)/len(vals),
        profit_factor=_pf(vals), net_r=sum(vals), expectancy_r=sum(vals)/len(vals),
        max_drawdown_r=max_dd, avg_bars_held=sum(t.bars_held for t in trades)/len(trades),
    )


def walk_forward(df: pd.DataFrame, periods: Sequence[tuple[str, str, str]], **kwargs: object) -> dict[str, BacktestStats]:
    """Run explicit non-overlapping train/validation/OOS periods."""
    out: dict[str, BacktestStats] = {}
    for label, start, end in periods:
        idx = pd.to_datetime(df.index)
        mask = (idx >= pd.Timestamp(start)) & (idx < pd.Timestamp(end))
        out[label] = summarize(backtest_frame(df.loc[mask], **kwargs))
    return out


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    time_col = next((c for c in ("timestamp", "datetime", "time", "date") if c in df.columns), None)
    if time_col is None:
        raise ValueError("CSV requires timestamp, datetime, time, or date column")
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.set_index(time_col)
    rename = {c: c.lower() for c in df.columns}
    return df.rename(columns=rename)


def report(df: pd.DataFrame, **kwargs: object) -> dict[str, object]:
    trades = backtest_frame(df, **kwargs)
    stats = summarize(trades)
    by_setup = {}
    for setup in SETUPS:
        by_setup[setup] = asdict(summarize([t for t in trades if t.setup == setup]))
    by_regime = {}
    for regime in REGIMES:
        by_regime[regime] = asdict(summarize([t for t in trades if t.regime == regime]))
    return {"stats": asdict(stats), "by_setup": by_setup, "by_regime": by_regime, "trades": [asdict(t) for t in trades]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas V9 offline 15m multi-setup research engine")
    parser.add_argument("--csv", required=True, help="15m OHLCV CSV")
    parser.add_argument("--output", default="backtests/v9_report.json")
    parser.add_argument("--min-score", type=int, default=5)
    parser.add_argument("--min-confirmations", type=int, default=1)
    parser.add_argument("--friction-r", type=float, default=0.026)
    args = parser.parse_args()
    df = load_ohlcv_csv(args.csv)
    result = report(df, min_score=args.min_score, min_confirmations=args.min_confirmations, friction_r=args.friction_r)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["stats"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
