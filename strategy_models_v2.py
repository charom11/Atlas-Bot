"""Quant strategy hardening helpers for Atlas-Bot.

These helpers deliberately use explicit NEUTRAL regimes so correlated or tiny
moves do not manufacture directional votes. They are designed to be integrated
into the existing 31-model consensus layer without changing order execution.
"""
from __future__ import annotations

from typing import Optional
import math
import numpy as np
import pandas as pd

BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"


def atr(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    value = tr.rolling(period).mean().iloc[-1]
    if np.isfinite(value) and value > 0:
        return float(value)
    return float(max(abs(c.iloc[-1]) * 0.001, 1e-12))


def neutralized_move(current: float, reference: float, atr_value: float,
                     neutral_atr: float = 0.15) -> str:
    """Convert a price difference into BULLISH/BEARISH/NEUTRAL."""
    band = max(abs(atr_value) * neutral_atr, abs(current) * 0.0002)
    delta = current - reference
    if delta > band:
        return BULLISH
    if delta < -band:
        return BEARISH
    return NEUTRAL


def momentum_signal(df: pd.DataFrame, lookback: int = 20,
                    neutral_atr: float = 0.20) -> str:
    close = df["close"].astype(float)
    if len(close) <= lookback:
        return NEUTRAL
    return neutralized_move(float(close.iloc[-1]), float(close.iloc[-1-lookback]),
                            atr(df), neutral_atr)


def ema_signal(df: pd.DataFrame, span: int = 50,
                neutral_atr: float = 0.15) -> str:
    close = df["close"].astype(float)
    if len(close) < span:
        return NEUTRAL
    ema = float(close.ewm(span=span, adjust=False).mean().iloc[-1])
    return neutralized_move(float(close.iloc[-1]), ema, atr(df), neutral_atr)


def trend_forecast_signal(df: pd.DataFrame, fast: int = 8, slow: int = 21,
                          neutral_atr: float = 0.15) -> str:
    close = df["close"].astype(float)
    if len(close) < slow + 2:
        return NEUTRAL
    fast_ema = float(close.ewm(span=fast, adjust=False).mean().iloc[-1])
    slow_ema = float(close.ewm(span=slow, adjust=False).mean().iloc[-1])
    return neutralized_move(fast_ema, slow_ema, atr(df), neutral_atr)


def cross_asset_relative_strength(asset: pd.Series, benchmark: pd.Series,
                                   lookback: int = 20,
                                   neutral_z: float = 0.35) -> str:
    """Direction of asset residual returns versus a benchmark."""
    a = np.log(asset.astype(float)).diff().dropna()
    b = np.log(benchmark.astype(float)).diff().dropna()
    n = min(len(a), len(b), lookback)
    if n < 8:
        return NEUTRAL
    ar, br = a.iloc[-n:].to_numpy(), b.iloc[-n:].to_numpy()
    var_b = float(np.var(br))
    beta = float(np.cov(ar, br, ddof=1)[0, 1] / var_b) if var_b > 1e-12 else 0.0
    residual = ar - beta * br
    sigma = float(np.std(residual))
    if sigma <= 1e-12:
        return NEUTRAL
    z = float((residual[-1] - np.mean(residual)) / sigma)
    if z > neutral_z:
        return BULLISH
    if z < -neutral_z:
        return BEARISH
    return NEUTRAL


def funding_signal(funding_rate: Optional[float],
                   recent_change: Optional[float] = None,
                   neutral_rate: float = 0.0001) -> str:
    """Contrarian funding signal with a dead zone."""
    if funding_rate is None or not np.isfinite(funding_rate):
        return NEUTRAL
    rate = float(funding_rate)
    if abs(rate) <= neutral_rate:
        return NEUTRAL
    if rate > 0 and (recent_change is None or recent_change >= -neutral_rate):
        return BEARISH
    if rate < 0 and (recent_change is None or recent_change <= neutral_rate):
        return BULLISH
    return NEUTRAL


def open_interest_price_signal(price_returns: pd.Series,
                               oi_returns: pd.Series,
                               threshold: float = 0.0005) -> str:
    """Price/OI confirmation; falling OI is deliberately neutral."""
    if len(price_returns) < 5 or len(oi_returns) < 5:
        return NEUTRAL
    price_move = float(price_returns.iloc[-1])
    oi_move = float(oi_returns.iloc[-1])
    if abs(price_move) < threshold or abs(oi_move) < threshold:
        return NEUTRAL
    if price_move > 0 and oi_move > 0:
        return BULLISH
    if price_move < 0 and oi_move > 0:
        return BEARISH
    return NEUTRAL


def seasonality_signal(returns: Optional[pd.Series], hour_utc: int,
                       min_samples: int = 12) -> str:
    """Empirical hour-of-day seasonality; insufficient history stays neutral."""
    if returns is None or len(returns) < 40:
        return NEUTRAL
    if not isinstance(returns.index, pd.DatetimeIndex):
        return NEUTRAL
    hourly = returns.dropna().astype(float)
    hourly = hourly[hourly.index.hour == int(hour_utc)]
    if len(hourly) < min_samples:
        return NEUTRAL
    std = float(hourly.std(ddof=1))
    if std <= 1e-12:
        return NEUTRAL
    t_stat = float(hourly.mean()) / (std / math.sqrt(len(hourly)))
    if t_stat > 1.0:
        return BULLISH
    if t_stat < -1.0:
        return BEARISH
    return NEUTRAL
