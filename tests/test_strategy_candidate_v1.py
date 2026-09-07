import pytest
import pandas as pd
import numpy as np
from strategy_candidate_v1 import (
    LONG, SHORT, NEUTRAL, StrategyDecision,
    generate_strategy_signal, backtest_frame, _vectorized_backtest_frame
)

def make_test_df(n=250):
    np.random.seed(42)
    base = 100.0
    returns = np.random.normal(0.0005, 0.01, n)
    prices = base * np.cumprod(1 + returns)
    highs = prices * (1 + np.random.uniform(0.001, 0.01, n))
    lows = prices * (1 - np.random.uniform(0.001, 0.01, n))
    volumes = np.random.uniform(1000, 5000, n)
    dates = pd.date_range("2024-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "open": prices,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    }, index=dates)

def test_strategy_decision_dataclass():
    d = StrategyDecision(
        signal=LONG,
        score=0.65,
        trend_score=0.45,
        momentum_score=0.35,
        breakout_score=1.0,
        derivatives_score=0.0,
        regime="BULL_TREND",
        volatility_pct=0.012,
        atr_pct=0.008,
        reasons=("test_reason",)
    )
    d_dict = d.to_dict()
    assert d_dict["signal"] == LONG
    assert d_dict["score"] == 0.65
    assert d_dict["regime"] == "BULL_TREND"

def test_generate_strategy_signal_insufficient_data():
    short_df = make_test_df(50)
    decision = generate_strategy_signal(short_df)
    assert decision["signal"] == NEUTRAL
    assert decision["regime"] == "INSUFFICIENT_DATA"

def test_fast_vs_slow_equivalence():
    df = make_test_df(240)
    fast_df = backtest_frame(df, fast=True)
    slow_df = backtest_frame(df, fast=False)

    assert len(fast_df) == len(slow_df)
    for col in ["signal", "score", "trend_score", "momentum_score", "breakout_score", "regime", "execution_signal"]:
        pd.testing.assert_series_equal(fast_df[col], slow_df[col], check_names=False, check_freq=False)

def test_no_lookahead_execution_signal():
    df = make_test_df(230)
    res = backtest_frame(df, fast=True)
    # execution_signal at row i must be signal at row i - 1
    assert res["execution_signal"].iloc[0] == NEUTRAL
    assert res["execution_signal"].iloc[1] == res["signal"].iloc[0]
    assert res["execution_signal"].iloc[225] == res["signal"].iloc[224]
