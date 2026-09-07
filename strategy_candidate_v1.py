"""Regime-aware strategy candidate for offline backtesting.

This module is intentionally NOT wired into live execution. It is a candidate
strategy for a four-year historical backtest. It returns LONG, SHORT, or
NEUTRAL plus diagnostics so the backtest report can explain why a trade would
have been taken.

Design goals:
- reduce correlated votes from the existing consensus layer
- require confirmation from independent signal families
- adapt entry thresholds to volatility and market regime
- use derivatives data when available, but fail neutral when unavailable
- avoid look-ahead: every calculation uses data available through the last row
- no network calls, order placement, or execution/risk changes

Expected OHLCV columns: open, high, low, close, volume.
Optional aligned series/columns may be supplied for BTC benchmark, funding,
and open interest.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional
import math

import numpy as np
import pandas as pd

LONG = "LONG"
SHORT = "SHORT"
NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class StrategyDecision:
    signal: str
    score: float
    trend_score: float
    momentum_score: float
    breakout_score: float
    derivatives_score: float
    regime: str
    volatility_pct: float
    atr_pct: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _valid_ohlcv(df: pd.DataFrame) -> bool:
    required = {"open", "high", "low", "close", "volume"}
    return df is not None and required.issubset(df.columns) and len(df) >= 220


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    tr = pd.concat(
        [(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _zscore(series: pd.Series, window: int) -> float:
    s = series.astype(float).dropna()
    if len(s) < window:
        return 0.0
    x = s.iloc[-window:]
    sd = float(x.std(ddof=0))
    if sd <= 1e-12:
        return 0.0
    return float((x.iloc[-1] - x.mean()) / sd)


def _direction(value: float, deadzone: float = 0.0) -> float:
    if value > deadzone:
        return 1.0
    if value < -deadzone:
        return -1.0
    return 0.0


def _series_last(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, pd.Series):
        if value.empty:
            return None
        value = value.iloc[-1]
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _regime(df: pd.DataFrame, atr: pd.Series) -> tuple[str, float, float]:
    close = df["close"].astype(float)
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr_pct = float(atr.iloc[-1] / close.iloc[-1]) if close.iloc[-1] else 0.0
    realized = close.pct_change().rolling(20).std().iloc[-1]
    vol_pct = float(realized) if np.isfinite(realized) else 0.0

    spread = float((ema50.iloc[-1] - ema200.iloc[-1]) / close.iloc[-1])
    slope = float((ema50.iloc[-1] - ema50.iloc[-11]) / close.iloc[-1]) if len(close) >= 11 else 0.0

    # Avoid trading in both extreme volatility and very compressed/noisy states.
    if atr_pct >= 0.045 or vol_pct >= 0.035:
        return "HIGH_VOL", vol_pct, atr_pct
    if abs(spread) < 0.0025 and abs(slope) < 0.0015:
        return "RANGE", vol_pct, atr_pct
    return ("BULL_TREND" if spread > 0 and slope > 0 else
            "BEAR_TREND" if spread < 0 and slope < 0 else "TRANSITION"), vol_pct, atr_pct


def generate_strategy_signal(
    df: pd.DataFrame,
    *,
    btc_close: Optional[pd.Series] = None,
    funding_rate: Optional[float] = None,
    funding_change: Optional[float] = None,
    oi_change: Optional[float] = None,
) -> dict:
    """Generate a conservative candidate signal from historical market data.

    The final score is a weighted combination of independent families rather
    than a raw count of highly correlated indicators.
    """
    if not _valid_ohlcv(df):
        return StrategyDecision(
            NEUTRAL, 0.0, 0.0, 0.0, 0.0, 0.0, "INSUFFICIENT_DATA", 0.0, 0.0,
            ("insufficient OHLCV history",),
        ).to_dict()

    d = df.copy()
    close = d["close"].astype(float)
    volume = d["volume"].astype(float)
    atr = _atr(d)
    regime, vol_pct, atr_pct = _regime(d, atr)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    # 1) Trend family: one medium trend state, not many duplicate EMA votes.
    trend_raw = (
        0.45 * _direction(float(close.iloc[-1] - ema50.iloc[-1]) / close.iloc[-1], 0.0015)
        + 0.35 * _direction(float(ema50.iloc[-1] - ema200.iloc[-1]) / close.iloc[-1], 0.0020)
        + 0.20 * _direction(float(ema20.iloc[-1] - ema50.iloc[-1]) / close.iloc[-1], 0.0010)
    )
    trend_score = float(np.clip(trend_raw, -1.0, 1.0))

    # 2) Momentum family: multiple horizons are combined into one family.
    ret_5 = float(close.pct_change(5).iloc[-1])
    ret_20 = float(close.pct_change(20).iloc[-1])
    ret_60 = float(close.pct_change(60).iloc[-1])
    momentum_raw = (
        0.20 * _direction(ret_5, max(atr_pct * 0.45, 0.001))
        + 0.45 * _direction(ret_20, max(atr_pct * 0.75, 0.002))
        + 0.35 * _direction(ret_60, max(atr_pct * 1.50, 0.004))
    )
    momentum_score = float(np.clip(momentum_raw, -1.0, 1.0))

    # 3) Breakout/participation family. Breakouts only count with volume.
    high20 = d["high"].astype(float).rolling(20).max().shift(1).iloc[-1]
    low20 = d["low"].astype(float).rolling(20).min().shift(1).iloc[-1]
    vol_med = volume.rolling(20).median().iloc[-1]
    vol_ratio = float(volume.iloc[-1] / vol_med) if vol_med > 0 else 0.0
    breakout_score = 0.0
    if np.isfinite(high20) and close.iloc[-1] > high20 and vol_ratio >= 1.10:
        breakout_score = 1.0
    elif np.isfinite(low20) and close.iloc[-1] < low20 and vol_ratio >= 1.10:
        breakout_score = -1.0

    # 4) Derivatives/cross-asset family. Missing evidence contributes zero.
    deriv_parts = []
    if btc_close is not None:
        b = pd.Series(btc_close, index=btc_close.index if isinstance(btc_close, pd.Series) else None).astype(float)
        n = min(len(close), len(b))
        if n >= 30:
            asset_ret = close.iloc[-n:].pct_change(20).iloc[-1]
            btc_ret = b.iloc[-n:].pct_change(20).iloc[-1]
            deriv_parts.append(_direction(float(asset_ret - btc_ret), max(atr_pct * 0.5, 0.002)))

    fr = _series_last(funding_rate)
    fc = _series_last(funding_change)
    if fr is not None:
        # Crowded positive funding is bearish; crowded negative funding bullish.
        funding_deadzone = 0.0001
        if abs(fr) > funding_deadzone:
            if fr > 0 and (fc is None or fc >= -funding_deadzone):
                deriv_parts.append(-1.0)
            elif fr < 0 and (fc is None or fc <= funding_deadzone):
                deriv_parts.append(1.0)

    oi = _series_last(oi_change)
    if oi is not None:
        # OI confirmation is directional only when the current price move agrees.
        if abs(oi) >= 0.001:
            if ret_5 > max(atr_pct * 0.35, 0.001) and oi > 0:
                deriv_parts.append(1.0)
            elif ret_5 < -max(atr_pct * 0.35, 0.001) and oi > 0:
                deriv_parts.append(-1.0)
            elif ret_5 > max(atr_pct * 0.35, 0.001) and oi < 0:
                deriv_parts.append(0.25)  # short-covering, weak confirmation
            elif ret_5 < -max(atr_pct * 0.35, 0.001) and oi < 0:
                deriv_parts.append(-0.25)  # long liquidation, weak confirmation

    derivatives_score = float(np.mean(deriv_parts)) if deriv_parts else 0.0

    # Family weights deliberately avoid double-counting trend/momentum evidence.
    score = (
        0.35 * trend_score
        + 0.30 * momentum_score
        + 0.20 * breakout_score
        + 0.15 * derivatives_score
    )

    reasons: list[str] = [f"regime={regime}", f"volume_ratio={vol_ratio:.2f}"]
    if trend_score > 0.35:
        reasons.append("trend confirmation bullish")
    elif trend_score < -0.35:
        reasons.append("trend confirmation bearish")
    if momentum_score > 0.35:
        reasons.append("multi-horizon momentum bullish")
    elif momentum_score < -0.35:
        reasons.append("multi-horizon momentum bearish")
    if breakout_score > 0:
        reasons.append("volume-confirmed upside breakout")
    elif breakout_score < 0:
        reasons.append("volume-confirmed downside breakout")
    if derivatives_score > 0.35:
        reasons.append("derivatives/cross-asset confirmation bullish")
    elif derivatives_score < -0.35:
        reasons.append("derivatives/cross-asset confirmation bearish")

    # Regime gates: no entries in high volatility or weak transition conditions.
    if regime == "HIGH_VOL":
        signal = NEUTRAL
        reasons.append("high-volatility entry gate")
    elif regime == "RANGE":
        signal = NEUTRAL
        reasons.append("range-regime entry gate")
    elif regime == "BULL_TREND" and score >= 0.55 and trend_score > 0.30 and momentum_score > 0.20:
        signal = LONG
    elif regime == "BEAR_TREND" and score <= -0.55 and trend_score < -0.30 and momentum_score < -0.20:
        signal = SHORT
    elif regime == "TRANSITION" and abs(score) >= 0.72 and abs(trend_score) > 0.50 and abs(momentum_score) > 0.45:
        signal = LONG if score > 0 else SHORT
    else:
        signal = NEUTRAL

    return StrategyDecision(
        signal=signal,
        score=round(float(score), 6),
        trend_score=round(trend_score, 6),
        momentum_score=round(momentum_score, 6),
        breakout_score=round(breakout_score, 6),
        derivatives_score=round(derivatives_score, 6),
        regime=regime,
        volatility_pct=round(vol_pct, 8),
        atr_pct=round(atr_pct, 8),
        reasons=tuple(reasons),
    ).to_dict()


def backtest_frame(
    df: pd.DataFrame,
    *,
    btc_close: Optional[pd.Series] = None,
    funding_rate: Optional[pd.Series] = None,
    funding_change: Optional[pd.Series] = None,
    oi_change: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Produce one decision row per candle for an offline four-year backtest.

    Signals are shifted one bar so a backtester can execute on the next candle,
    preventing accidental same-candle look-ahead in a simple vectorized test.
    """
    rows = []
    for i in range(len(df)):
        window = df.iloc[: i + 1]
        decision = generate_strategy_signal(
            window,
            btc_close=btc_close.iloc[: i + 1] if btc_close is not None else None,
            funding_rate=funding_rate.iloc[i] if funding_rate is not None and i < len(funding_rate) else None,
            funding_change=funding_change.iloc[i] if funding_change is not None and i < len(funding_change) else None,
            oi_change=oi_change.iloc[i] if oi_change is not None and i < len(oi_change) else None,
        )
        decision["timestamp"] = df.index[i]
        rows.append(decision)
    out = pd.DataFrame(rows).set_index("timestamp")
    out["execution_signal"] = out["signal"].shift(1).fillna(NEUTRAL)
    return out
