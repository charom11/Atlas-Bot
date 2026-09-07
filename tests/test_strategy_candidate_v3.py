import numpy as np
import pandas as pd

from strategy_candidate_v3 import (
    EXIT_THRESHOLD, FLAT, LONG, SHORT,
    choose_leverage, enforce_portfolio_limits, generate_strategy_signal,
    rank_assets, risk_based_notional, structure_stop, trailing_stop,
    backtest_frame,
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
    assert generate_strategy_signal(pd.DataFrame({"close":[1,2,3]}))["signal"] == FLAT


def test_risk_sizing_is_stop_derived_and_capped():
    n=risk_based_notional(1000,.0035,100,98,max_leverage=10,max_notional_pct=1)
    assert abs(n-175)<1e-9
    assert risk_based_notional(1000,.50,100,99,max_leverage=2,max_notional_pct=3)==2000


def test_leverage_falls_with_volatility():
    assert choose_leverage(.005)>choose_leverage(.02)>=1


def test_structure_stop_is_on_correct_side():
    df=make_ohlcv()
    close=float(df.close.iloc[-1]); atr=float((df.high-df.low).rolling(14).mean().iloc[-1])
    assert structure_stop(df,LONG,atr)<close
    assert structure_stop(df,SHORT,atr)>close


def test_pullback_candidate_is_not_allowed_when_price_is_extended():
    df=make_ohlcv()
    d=generate_strategy_signal(df)
    assert "pullback_atr" in " ".join(d["reasons"])


def test_hysteresis_hold():
    d=generate_strategy_signal(make_ohlcv(),position=LONG)
    if d["score"]>EXIT_THRESHOLD: assert d["signal"]==LONG


def test_trailing_stop_only_moves_protectively():
    long=trailing_stop(100,95,110,LONG,2,2,ema20=106,swing_price=104)
    short=trailing_stop(100,105,90,SHORT,2,2,ema20=94,swing_price=96)
    assert long>=95 and long<=109.5
    assert short<=105 and short>=90.5


def test_portfolio_limits():
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


def test_rank_assets_training_only():
    m=pd.DataFrame([
        {"symbol":"A","trades":100,"expectancy":1.0,"profit_factor":1.4},
        {"symbol":"B","trades":100,"expectancy":.2,"profit_factor":1.1},
        {"symbol":"C","trades":10,"expectancy":9.0,"profit_factor":9.0},
    ])
    out=rank_assets(m)
    assert out.iloc[0].symbol=="A"
    assert "C" not in out.symbol.tolist()


def test_backtest_frame_execution_signal_shifted():
    df = make_ohlcv(n=250)
    res = backtest_frame(df, fast=True)
    assert "execution_signal" in res.columns
    assert res["execution_signal"].iloc[0] == FLAT
    assert (res["execution_signal"].iloc[1:].values == res["signal"].iloc[:-1].values).all()


def test_backtest_frame_vectorized_equivalence():
    df = make_ohlcv(n=235)
    fast_res = backtest_frame(df, fast=True)
    slow_res = backtest_frame(df, fast=False)
    assert (fast_res["signal"].values == slow_res["signal"].values).all()
    assert (fast_res["regime"].values == slow_res["regime"].values).all()
    assert np.allclose(fast_res["score"].values, slow_res["score"].values, atol=1e-5)

