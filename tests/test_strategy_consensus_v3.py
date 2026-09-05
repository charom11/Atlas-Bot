import numpy as np
import pandas as pd

from strategy_consensus_v3 import evaluate_hardened_31_models
from strategy_models_v2 import BULLISH, BEARISH, NEUTRAL


def make_df(n=120, trend=0.001):
    close = 100 * np.exp(np.cumsum(np.full(n, trend)))
    return pd.DataFrame({
        'open': close * 0.999,
        'high': close * 1.002,
        'low': close * 0.998,
        'close': close,
        'volume': np.full(n, 1000.0),
    })


def test_returns_exactly_31_signals():
    signals = evaluate_hardened_31_models(make_df())
    assert len(signals) == 31
    assert all(s in {BULLISH, BEARISH, NEUTRAL} for s in signals)


def test_missing_external_data_stays_neutral():
    signals = evaluate_hardened_31_models(make_df())
    assert signals[8] == NEUTRAL
    assert signals[9] == NEUTRAL
    assert signals[10] == NEUTRAL
    assert signals[14] == NEUTRAL
    assert signals[15] == NEUTRAL
    assert signals[17] == NEUTRAL
    assert signals[18] == NEUTRAL
    assert signals[19] == NEUTRAL
    assert signals[23] == NEUTRAL


def test_cross_asset_signal_uses_supplied_benchmark():
    benchmark = pd.Series(np.linspace(100.0, 102.0, 120))
    asset = 100.0 + 1.8 * (benchmark - 100.0)
    asset.iloc[-1] += 2.0
    df = make_df(120, 0.0001)
    df['close'] = asset
    signals = evaluate_hardened_31_models(df, btc_close=benchmark)
    assert signals[8] == BULLISH

