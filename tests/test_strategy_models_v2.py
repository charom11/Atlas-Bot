import numpy as np
import pandas as pd

from strategy_models_v2 import (
    BULLISH,
    BEARISH,
    NEUTRAL,
    cross_asset_relative_strength,
    ema_signal,
    funding_signal,
    momentum_signal,
    open_interest_price_signal,
    seasonality_signal,
    trend_forecast_signal,
)


def make_frame(n=100, slope=0.1):
    close = 100 + np.arange(n) * slope
    return pd.DataFrame({
        'open': close - 0.1,
        'high': close + 0.2,
        'low': close - 0.2,
        'close': close,
        'volume': np.full(n, 100.0),
    })


def test_flat_market_is_neutral_for_momentum_and_ema():
    df = make_frame(slope=0.0)
    assert momentum_signal(df) == NEUTRAL
    assert ema_signal(df) == NEUTRAL


def test_trend_forecast_has_direction_on_clear_trend():
    df = make_frame(slope=0.5)
    assert trend_forecast_signal(df) == BULLISH


def test_funding_is_contrarian_with_dead_zone():
    assert funding_signal(0.001) == BEARISH
    assert funding_signal(-0.001) == BULLISH
    assert funding_signal(0.0) == NEUTRAL


def test_price_and_open_interest_confirmation():
    price = pd.Series([0.0, 0.01, 0.01, 0.01, 0.01])
    oi = pd.Series([0.0, 0.01, 0.01, 0.01, 0.01])
    assert open_interest_price_signal(price, oi) == BULLISH


def test_cross_asset_relative_strength_detects_residual_direction():
    benchmark = np.linspace(100.0, 102.0, 25)
    asset_bull = 100.0 + 1.8 * (benchmark - 100.0)
    asset_bull[-1] += 2.0
    asset_bear = 100.0 + 1.8 * (benchmark - 100.0)
    asset_bear[-1] -= 2.0

    assert cross_asset_relative_strength(pd.Series(asset_bull), pd.Series(benchmark)) == BULLISH
    assert cross_asset_relative_strength(pd.Series(asset_bear), pd.Series(benchmark)) == BEARISH


def test_cross_asset_requires_enough_history():
    short = pd.Series(np.linspace(100.0, 101.0, 7))
    assert cross_asset_relative_strength(short, short) == NEUTRAL


def test_price_and_open_interest_neutral_when_oi_falls():
    price = pd.Series([0.0, 0.01, 0.01, 0.01, 0.01])
    oi = pd.Series([0.0, -0.01, -0.01, -0.01, -0.01])
    assert open_interest_price_signal(price, oi) == NEUTRAL


def test_seasonality_requires_sufficient_history():
    assert seasonality_signal(None, 12) == NEUTRAL
    short = pd.Series([0.01] * 10, index=pd.date_range('2026-01-01', periods=10, freq='h'))
    assert seasonality_signal(short, 12) == NEUTRAL
