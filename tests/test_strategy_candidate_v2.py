import numpy as np
import pandas as pd

from strategy_candidate_v2 import (
    EXIT_THRESHOLD, FLAT, LONG, SHORT,
    choose_leverage, enforce_portfolio_limits, generate_strategy_signal,
    rank_assets, risk_based_notional,
)


def make_ohlcv(n=260, trend=0.0005, vol=0.003):
    rng=np.random.default_rng(7)
    rets=trend+rng.normal(0,vol,n)
    close=100*np.exp(np.cumsum(rets))
    high=close*(1+rng.uniform(0.0005,0.003,n))
    low=close*(1-rng.uniform(0.0005,0.003,n))
    open_=close*(1+rng.normal(0,0.0005,n))
    volume=rng.integers(1000,5000,n).astype(float)
    return pd.DataFrame({"open":open_,"high":high,"low":low,"close":close,"volume":volume})


def test_invalid_data_is_flat():
    d=generate_strategy_signal(pd.DataFrame({"close":[1,2,3]}))
    assert d["signal"] == FLAT


def test_hysteresis_hold_does_not_exit_above_exit_threshold():
    d=generate_strategy_signal(make_ohlcv(), position=LONG)
    if d["score"] > EXIT_THRESHOLD:
        assert d["signal"] == LONG


def test_hysteresis_hold_does_not_exit_below_short_exit_threshold():
    d=generate_strategy_signal(make_ohlcv(trend=-0.0005), position=SHORT)
    if d["score"] < -EXIT_THRESHOLD:
        assert d["signal"] == SHORT


def test_risk_based_notional_is_stop_derived():
    n=risk_based_notional(1000,.0035,100,98,max_leverage=50,max_notional_pct=1)
    assert abs(n-175)<1e-9


def test_risk_based_notional_respects_caps():
    n=risk_based_notional(1000,.50,100,99,max_leverage=2,max_notional_pct=3)
    assert n == 2000


def test_choose_leverage_falls_with_volatility():
    low=choose_leverage(.005)
    high=choose_leverage(.02)
    assert low > high >= 1


def test_asset_ranking_uses_training_metrics_only():
    m=pd.DataFrame([
        {"symbol":"A","trades":100,"expectancy":1.0,"profit_factor":1.4},
        {"symbol":"B","trades":100,"expectancy":0.2,"profit_factor":1.1},
        {"symbol":"C","trades":10,"expectancy":9.0,"profit_factor":9.0},
    ])
    out=rank_assets(m)
    assert out.iloc[0]["symbol"]=="A"
    assert "C" not in out["symbol"].tolist()


def test_portfolio_limits_direction_and_correlation():
    candidates=[
        {"symbol":"A","signal":LONG,"score":.9,"correlation_group":"btc"},
        {"symbol":"B","signal":LONG,"score":.8,"correlation_group":"btc"},
        {"symbol":"C","signal":LONG,"score":.7,"correlation_group":"btc"},
        {"symbol":"D","signal":LONG,"score":.6,"correlation_group":"sol"},
        {"symbol":"E","signal":SHORT,"score":-.95,"correlation_group":"eth"},
    ]
    out=enforce_portfolio_limits(candidates,max_positions=5,max_same_direction=3,max_correlated=2)
    assert len(out)==4
    assert sum(x["signal"]==LONG for x in out)<=3
    assert sum(x["correlation_group"]=="btc" for x in out)<=2
