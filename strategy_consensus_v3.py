"""Safe adapter for Atlas-Bot's 31-model consensus layer.

This module does not place orders and does not change execution/risk plumbing. It
provides a drop-in signal list with explicit NEUTRAL states for models that do
not have the required external data or a validated trained model.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from strategy_models_v2 import (
    BULLISH, BEARISH, NEUTRAL,
    atr, momentum_signal, ema_signal, trend_forecast_signal,
    cross_asset_relative_strength, funding_signal,
    open_interest_price_signal, seasonality_signal, neutralized_move,
)


def _directional_move(df: pd.DataFrame, lookback: int, threshold_atr: float = 0.20) -> str:
    if len(df) <= lookback:
        return NEUTRAL
    a = atr(df)
    return neutralized_move(float(df['close'].iloc[-1]),
                            float(df['close'].iloc[-1-lookback]), a,
                            threshold_atr)


def _adx_signal(df: pd.DataFrame, period: int = 14, threshold: float = 22.0) -> str:
    if len(df) < period * 2 + 2:
        return NEUTRAL
    h, l, c = df['high'].astype(float), df['low'].astype(float), df['close'].astype(float)
    up = h.diff()
    down = -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr_s = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr_s.replace(0, np.nan)
    dx = (100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)).dropna()
    if len(dx) < period:
        return NEUTRAL
    adx = float(dx.ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    if adx < threshold:
        return NEUTRAL
    return BULLISH if plus_di.iloc[-1] > minus_di.iloc[-1] else BEARISH


def _bb_signal(df: pd.DataFrame, period: int = 20) -> str:
    if len(df) < period:
        return NEUTRAL
    c = df['close'].astype(float)
    mean = c.rolling(period).mean().iloc[-1]
    std = c.rolling(period).std(ddof=0).iloc[-1]
    if not np.isfinite(std) or std <= 0:
        return NEUTRAL
    z = (float(c.iloc[-1]) - float(mean)) / float(std)
    if z > 2.0:
        return BEARISH
    if z < -2.0:
        return BULLISH
    return NEUTRAL


def evaluate_hardened_31_models(
    df: pd.DataFrame,
    *,
    btc_close: Optional[pd.Series] = None,
    benchmark_close: Optional[pd.Series] = None,
    gold_close: Optional[pd.Series] = None,
    funding_rate: Optional[float] = None,
    funding_change: Optional[float] = None,
    price_returns: Optional[pd.Series] = None,
    oi_returns: Optional[pd.Series] = None,
    seasonality_returns: Optional[pd.Series] = None,
    hour_utc: Optional[int] = None,
) -> list[str]:
    """Return exactly 31 validated signals; unavailable evidence stays NEUTRAL."""
    if df is None or len(df) < 35:
        return [NEUTRAL] * 31

    signals = [
        momentum_signal(df, 5, 0.15),
        trend_forecast_signal(df, 8, 21, 0.15),
        _directional_move(df, 3, 0.15),
        _directional_move(df, 10, 0.20),
        _bb_signal(df),
        _directional_move(df, 20, 0.20),
        ema_signal(df, 20, 0.20),
        _adx_signal(df),
        cross_asset_relative_strength(df['close'], btc_close) if btc_close is not None else NEUTRAL,
        cross_asset_relative_strength(df['close'], benchmark_close) if benchmark_close is not None else NEUTRAL,
        cross_asset_relative_strength(df['close'], gold_close) if gold_close is not None else NEUTRAL,
        _directional_move(df, 3, 0.30),
        _directional_move(df, 1, 0.35),
        _directional_move(df, 10, 0.30),
        funding_signal(funding_rate, funding_change),
        open_interest_price_signal(price_returns, oi_returns) if price_returns is not None and oi_returns is not None else NEUTRAL,
        _directional_move(df, 2, 0.25),
        NEUTRAL,  # Q18: no trained gradient-boosted model supplied
        NEUTRAL,  # Q19: no trained LSTM model supplied
        NEUTRAL,  # Q20: no fitted Markov transition model supplied
        _directional_move(df, 9, 0.25),
        trend_forecast_signal(df, 8, 21, 0.20),
        trend_forecast_signal(df, 3, 13, 0.20),
        NEUTRAL,  # Q24: no validated spectral forecast supplied
        momentum_signal(df, 20, 0.20),
        NEUTRAL,  # Q26: quality/low-vol factor requires validated factor inputs
        _adx_signal(df, threshold=22.0),
        ema_signal(df, 200, 0.20),
        seasonality_signal(seasonality_returns, hour_utc) if seasonality_returns is not None and hour_utc is not None else NEUTRAL,
        NEUTRAL,  # Q30: funding-window drift requires a validated event study
        seasonality_signal(seasonality_returns, hour_utc) if seasonality_returns is not None and hour_utc is not None else NEUTRAL,
    ]
    assert len(signals) == 31
    return signals
