import numpy as np
import pandas as pd
from strategy_candidate_v4 import *
from strategy_candidate_v4 import _atr

def make_ohlcv(n=260, trend=0.0005, vol=0.003):
    rng=np.random.default_rng(7); rets=trend+rng.normal(0,vol,n); close=100*np.exp(np.cumsum(rets))
    high=close*(1+rng.uniform(.0005,.003,n)); low=close*(1-rng.uniform(.0005,.003,n)); open_=close*(1+rng.normal(0,.0005,n)); volume=rng.integers(1000,5000,n).astype(float)
    return pd.DataFrame({'open':open_,'high':high,'low':low,'close':close,'volume':volume})

def test_invalid_data_flat(): assert generate_strategy_signal(pd.DataFrame({'close':[1,2,3]}))['signal']==FLAT

def test_adaptive_pullback_limits():
    assert adaptive_pullback_limit('BULL_TREND',.70,0)==.60
    assert adaptive_pullback_limit('BULL_TREND',.80,0)==.90
    assert adaptive_pullback_limit('BULL_TREND',.80,1)==1.20

def test_structure_stop_correct_side():
    d=make_ohlcv(); p=float(d.close.iloc[-1]); a=float(_atr(d).iloc[-1])
    assert structure_stop(d,LONG,a)<p and structure_stop(d,SHORT,a)>p

def test_risk_sizing_and_leverage_cap():
    assert abs(risk_based_notional(1000,.0035,100,98,max_leverage=10)-175)<1e-9
    assert choose_leverage(.0001,max_leverage=10)==10

def test_trailing_never_loosened():
    assert trailing_stop(100,95,110,LONG,2,2,106,104)>=95
    assert trailing_stop(100,105,90,SHORT,2,2,94,96)<=105

def test_manage_position_has_early_profit_exit():
    x=manage_position(LONG,100,95,110,20,1.5,0,2)
    assert x['action']==EXIT and 'deterioration' in x['reason']

def test_duration_exit():
    x=manage_position(LONG,100,95,100,MAX_HOLD_BARS,0.2,.5,2)
    assert x['action']==EXIT

def test_portfolio_limits():
    c=[{'symbol':'A','signal':LONG,'score':.9,'correlation_group':'btc'},{'symbol':'B','signal':LONG,'score':.8,'correlation_group':'btc'},{'symbol':'C','signal':LONG,'score':.7,'correlation_group':'btc'},{'symbol':'D','signal':LONG,'score':.6,'correlation_group':'sol'},{'symbol':'E','signal':SHORT,'score':-.95,'correlation_group':'eth'}]
    o=enforce_portfolio_limits(c); assert len(o)==4 and sum(x['signal']==LONG for x in o)<=3 and sum(x['correlation_group']=='btc' for x in o)<=2

def test_rank_assets():
    m=pd.DataFrame([{'symbol':'A','trades':100,'expectancy':1,'profit_factor':1.4},{'symbol':'B','trades':100,'expectancy':.2,'profit_factor':1.1},{'symbol':'C','trades':10,'expectancy':9,'profit_factor':9}])
    assert rank_assets(m).iloc[0].symbol=='A' and 'C' not in rank_assets(m).symbol.tolist()

def test_backtest_execution_is_shifted():
    d=make_ohlcv(); r=backtest_frame(d); assert len(r)==len(d); assert r.execution_signal.iloc[0]==FLAT
    assert (r.execution_signal.iloc[1:].values==r.signal.iloc[:-1].values).all()

def test_manage_position_giveback_protection():
    x=manage_position(LONG,100,95,110,20,0.8,0.4,2)
    assert x['action']==EXIT and 'giveback' in x['reason']

def test_vectorized_equivalence():
    d=make_ohlcv(n=250)
    fast_df = backtest_frame(d, fast=True)
    slow_df = backtest_frame(d, fast=False)
    assert (fast_df["signal"].values == slow_df["signal"].values).all()
    assert (fast_df["execution_signal"].values == slow_df["execution_signal"].values).all()

