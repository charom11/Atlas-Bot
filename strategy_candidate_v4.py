"""Offline Strategy Candidate V4: Adaptive Trend Capture.

Research-only. No exchange/network/order calls and deliberately not wired into
main.py. V4 separates entry confirmation from position management so winners
can be protected before a slow regime exit.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional, Sequence
import argparse
import math
import os
import time
import numpy as np
import pandas as pd

LONG="LONG"; SHORT="SHORT"; FLAT="FLAT"; EXIT="EXIT"
ENTRY=0.65; EXIT_SCORE=0.20
BASE_PULLBACK_ATR=0.60; STRONG_PULLBACK_ATR=0.90; BREAKOUT_PULLBACK_ATR=1.20
RISK_PCT=0.0035; MAX_LEVERAGE=10.0; MAX_STOP_ATR=4.5; MAX_STOP_PCT=0.06
LOOKBACK=20; BUFFER_ATR=0.25; MAX_HOLD_BARS=192; MAX_GIVEBACK_R=0.90

@dataclass(frozen=True)
class StrategyDecision:
    signal:str; score:float; trend_score:float; momentum_score:float; breakout_score:float
    derivatives_score:float; regime:str; atr_pct:float; pullback_distance_atr:float
    entry_price:float; stop_price:float; stop_distance_atr:float; stop_distance_pct:float
    expected_move_atr:float; estimated_round_trip_cost_pct:float; reasons:tuple[str,...]
    def to_dict(self): return asdict(self)

def _valid(df): return df is not None and {"open","high","low","close","volume"}.issubset(df.columns) and len(df)>=220

def _atr(df,p=14):
    h,l,c=(df[x].astype(float) for x in ("high","low","close"))
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/p,adjust=False,min_periods=p).mean()

def _dir(x,dz=0):
    return 1.0 if math.isfinite(float(x)) and x>dz else -1.0 if math.isfinite(float(x)) and x<-dz else 0.0

def _last(x):
    if isinstance(x,pd.Series): x=x.iloc[-1] if not x.empty else None
    try: x=float(x)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None

def _regime(df,a):
    c=df.close.astype(float); e50=c.ewm(span=50,adjust=False).mean(); e200=c.ewm(span=200,adjust=False).mean(); p=float(c.iloc[-1]); ap=float(a.iloc[-1]/p)
    rv=float(c.pct_change().rolling(20).std().iloc[-1]); rv=rv if math.isfinite(rv) else 0
    spread=float((e50.iloc[-1]-e200.iloc[-1])/p); slope=float((e50.iloc[-1]-e50.iloc[-11])/p)
    if ap>=.045 or rv>=.035:return "HIGH_VOL",rv,ap
    if abs(spread)<.0025 and abs(slope)<.0015:return "RANGE",rv,ap
    if spread>0 and slope>0:return "BULL_TREND",rv,ap
    if spread<0 and slope<0:return "BEAR_TREND",rv,ap
    return "TRANSITION",rv,ap

def _scores(df,btc_close=None,funding_rate=None,oi_change=None):
    c=df.close.astype(float); v=df.volume.astype(float); a=_atr(df); ap=float(a.iloc[-1]/c.iloc[-1]); e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean(); e200=c.ewm(span=200,adjust=False).mean()
    trend=.45*_dir((c.iloc[-1]-e50.iloc[-1])/c.iloc[-1],.0015)+.35*_dir((e50.iloc[-1]-e200.iloc[-1])/c.iloc[-1],.002)+.20*_dir((e20.iloc[-1]-e50.iloc[-1])/c.iloc[-1],.001)
    r5=float(c.pct_change(5).iloc[-1]); r20=float(c.pct_change(20).iloc[-1]); r60=float(c.pct_change(60).iloc[-1])
    mom=.20*_dir(r5,max(ap*.45,.001))+.45*_dir(r20,max(ap*.75,.002))+.35*_dir(r60,max(ap*1.5,.004))
    hi=c.rolling(20).max().shift(1).iloc[-1]; lo=df.low.astype(float).rolling(20).min().shift(1).iloc[-1]; med=v.rolling(20).median().iloc[-1]; vr=float(v.iloc[-1]/med) if med>0 else 0
    brk=1.0 if np.isfinite(hi) and c.iloc[-1]>hi and vr>=1.10 else -1.0 if np.isfinite(lo) and c.iloc[-1]<lo and vr>=1.10 else 0.0
    parts=[]
    if btc_close is not None:
        b=pd.Series(btc_close).astype(float); n=min(len(c),len(b))
        if n>=30: parts.append(_dir(float(c.iloc[-n:].pct_change(20).iloc[-1]-b.iloc[-n:].pct_change(20).iloc[-1]),max(ap*.5,.002)))
    fr=_last(funding_rate)
    if fr is not None and abs(fr)>.0001: parts.append(-1.0 if fr>0 else 1.0)
    oi=_last(oi_change)
    if oi is not None and abs(oi)>=.001:
        z=max(ap*.35,.001); parts.append(1.0 if r5>z and oi>0 else -1.0 if r5<-z and oi>0 else .25 if r5>z and oi<0 else -.25 if r5<-z and oi<0 else 0.0)
    deriv=float(np.mean([x for x in parts if x])) if any(parts) else 0.0
    return float(.35*trend+.30*mom+.20*brk+.15*deriv),float(trend),float(mom),float(brk),deriv,ap,vr,r20,r60,e20,e50

def structure_stop(df,side,atr=None,lookback=LOOKBACK,buffer_atr=BUFFER_ATR):
    if not _valid(df): return 0.0
    a=float(_atr(df).iloc[-1] if atr is None else atr); c=df.close.astype(float); e50=float(c.ewm(span=50,adjust=False).mean().iloc[-1])
    if not math.isfinite(a) or a<=0:return 0.0
    if side==LONG:return float(min(float(df.low.rolling(lookback).min().iloc[-1]),e50)-buffer_atr*a)
    if side==SHORT:return float(max(float(df.high.rolling(lookback).max().iloc[-1]),e50)+buffer_atr*a)
    return 0.0

def adaptive_pullback_limit(regime,score,breakout_score):
    if regime in ("BULL_TREND","BEAR_TREND") and abs(score)>=.75:
        return STRONG_PULLBACK_ATR if breakout_score==0 else BREAKOUT_PULLBACK_ATR
    return BASE_PULLBACK_ATR

def _decision(signal,score,trend,mom,brk,deriv,regime,ap,pull,entry,stop,expected,cost,reasons):
    dist=abs(entry-stop)/entry if entry>0 and stop>0 else 0; return StrategyDecision(signal,round(score,6),round(trend,6),round(mom,6),round(brk,6),round(deriv,6),regime,round(ap,8),round(pull,4),round(entry,8),round(stop,8),round(dist/(ap or 1),4),round(dist,8),round(expected,4),round(cost,8),tuple(reasons)).to_dict()

def generate_strategy_signal(df,*,position=FLAT,btc_close=None,funding_rate=None,oi_change=None,taker_fee_pct=.045,slippage_pct=.015,spread_pct=.005,funding_buffer_pct=.010):
    if not _valid(df): return {"signal":FLAT,"score":0.0,"reasons":["insufficient OHLCV history"]}
    a=_atr(df); regime,_,ap=_regime(df,a); score,trend,mom,brk,deriv,ap,vr,r20,r60,e20,e50=_scores(df,btc_close,funding_rate,oi_change); entry=float(df.close.iloc[-1]); atr=float(a.iloc[-1]); pull=abs(entry-float(e20.iloc[-1]))/atr
    tf,sl,sp,fb=(x/100 if x>.005 else x for x in (taker_fee_pct,slippage_pct,spread_pct,funding_buffer_pct)); cost=2*tf+2*sl+sp+fb; expected=abs(r20)/(ap or 1); side_for_stop=position if position in (LONG,SHORT) else (LONG if score>=0 else SHORT); stop=structure_stop(df,side_for_stop,atr); dist=abs(entry-stop)/entry if stop>0 else float('inf'); stop_atr=dist/(ap or 1e-9); reasons=[f"regime={regime}",f"volume_ratio={vr:.2f}",f"pullback_atr={pull:.2f}",f"expected_move_atr={expected:.2f}"]
    if position==LONG and score<=EXIT_SCORE:return _decision(EXIT,score,trend,mom,brk,deriv,regime,ap,pull,entry,stop,expected,cost,reasons+["momentum/regime exit"])
    if position==SHORT and score>=-EXIT_SCORE:return _decision(EXIT,score,trend,mom,brk,deriv,regime,ap,pull,entry,stop,expected,cost,reasons+["momentum/regime exit"])
    if position in (LONG,SHORT):return _decision(position,score,trend,mom,brk,deriv,regime,ap,pull,entry,stop,expected,cost,reasons+["position held"])
    limit=adaptive_pullback_limit(regime,score,brk); edge_ok=expected*ap>cost; stop_ok=((score>0 and stop<entry) or (score<0 and stop>entry)) and stop_atr<=MAX_STOP_ATR and dist<=MAX_STOP_PCT
    if pull>limit:reasons.append(f"pullback exceeds adaptive limit {limit:.2f} ATR")
    if not edge_ok:reasons.append("expected move does not clear cost budget")
    if not stop_ok:reasons.append("structure stop invalid or too wide")
    confirmed=(regime=="BULL_TREND" and score>=ENTRY and trend>=.30 and mom>=.25) or (regime=="BEAR_TREND" and score<=-ENTRY and trend<=-.30 and mom<=-.25) or (regime=="TRANSITION" and abs(score)>=.75 and abs(trend)>=.50 and abs(mom)>=.45)
    if confirmed and pull<=limit and edge_ok and stop_ok:return _decision(LONG if score>0 else SHORT,score,trend,mom,brk,deriv,regime,ap,pull,entry,stop,expected,cost,reasons+["adaptive pullback entry confirmed"])
    return _decision(FLAT,score,trend,mom,brk,deriv,regime,ap,pull,entry,stop,expected,cost,reasons+["entry confirmation incomplete"])

def risk_based_notional(equity,risk_pct,entry_price,stop_price,max_leverage=MAX_LEVERAGE,max_notional_pct=1.0):
    vals=(equity,risk_pct,entry_price,stop_price,max_leverage,max_notional_pct)
    if not all(math.isfinite(float(x)) for x in vals) or min(equity,risk_pct,entry_price,stop_price,max_leverage,max_notional_pct)<=0:return 0.0
    d=abs(entry_price-stop_price)/entry_price
    return float(min(equity*risk_pct/d,equity*max_leverage,equity*max_notional_pct)) if d>1e-9 else 0.0

def choose_leverage(atr_pct,target_risk_pct=RISK_PCT,stop_atr=2.0,max_leverage=MAX_LEVERAGE,min_leverage=1.0):
    if not math.isfinite(atr_pct) or atr_pct<=0:return min_leverage
    return float(np.clip(target_risk_pct/(atr_pct*stop_atr),min_leverage,max_leverage))

def trailing_stop(entry_price,current_stop,peak_price,side,atr,r_multiple,ema20=None,swing_price=None):
    if not all(math.isfinite(float(x)) for x in (entry_price,current_stop,peak_price,atr,r_multiple)) or atr<=0:return current_stop
    if side==LONG:
        c=max(current_stop,entry_price) if r_multiple>=1 else current_stop
        if r_multiple>=2:
            refs=[float(x) for x in (ema20,swing_price) if x is not None and math.isfinite(float(x))]
            if refs:c=max(c,min(refs)-.25*atr)
        return float(min(c,peak_price-.25*atr))
    if side==SHORT:
        c=min(current_stop,entry_price) if r_multiple>=1 else current_stop
        if r_multiple>=2:
            refs=[float(x) for x in (ema20,swing_price) if x is not None and math.isfinite(float(x))]
            if refs:c=min(c,max(refs)+.25*atr)
        return float(max(c,peak_price+.25*atr))
    return current_stop

def manage_position(side,entry_price,current_stop,peak_price,equity_bars,unrealized_r,score,atr,ema20=None,swing_price=None):
    """Separate exit model: protect profit before slow regime exhaustion."""
    if side not in (LONG,SHORT):return {"action":FLAT,"stop":current_stop,"reason":"flat"}
    if unrealized_r>=1.0 and ((side==LONG and score<=0.05) or (side==SHORT and score>=-0.05)):
        return {"action":EXIT,"stop":current_stop,"reason":"early momentum deterioration after 1R"}
    peak_r = (peak_price-entry_price)/(abs(entry_price-current_stop) or 1e-9) if side==LONG else (entry_price-peak_price)/(abs(entry_price-current_stop) or 1e-9)
    if peak_r>=1.5 and unrealized_r<=max(0.5,MAX_GIVEBACK_R):
        return {"action":EXIT,"stop":current_stop,"reason":"profit giveback protection"}
    if equity_bars>=MAX_HOLD_BARS and unrealized_r<0.5:return {"action":EXIT,"stop":current_stop,"reason":"maximum duration"}
    return {"action":side,"stop":trailing_stop(entry_price,current_stop,peak_price,side,atr,unrealized_r,ema20,swing_price),"reason":"managed runner"}

def enforce_portfolio_limits(candidates,max_positions=5,max_same_direction=3,max_correlated=2):
    out=[];dirs={LONG:0,SHORT:0};groups={}
    for c in sorted(candidates,key=lambda x:abs(float(x.get("score",0))),reverse=True):
        s=c.get("signal",FLAT);g=c.get("correlation_group",c.get("symbol",""))
        if s not in (LONG,SHORT) or dirs[s]>=max_same_direction or groups.get(g,0)>=max_correlated:continue
        out.append(c);dirs[s]+=1;groups[g]=groups.get(g,0)+1
        if len(out)>=max_positions:break
    return out

def rank_assets(metrics,min_trades=30,expectancy_col="expectancy",stability_col="profit_factor"):
    req={"symbol","trades",expectancy_col,stability_col}
    if not req.issubset(metrics.columns):raise ValueError(f"missing columns: {sorted(req-metrics.columns)}")
    x=metrics[metrics.trades>=min_trades].copy();x["rank_score"]=x[expectancy_col].rank(pct=True)*.6+x[stability_col].rank(pct=True)*.4
    return x.sort_values("rank_score",ascending=False).reset_index(drop=True)

def _dir_vec(series, dz=0.0):
    vals = series.values if hasattr(series, "values") else np.asarray(series)
    out = np.zeros(len(vals), dtype=np.float64)
    out[vals > dz] = 1.0
    out[vals < -dz] = -1.0
    return out


def _vectorized_backtest_frame(
    df: pd.DataFrame,
    *,
    btc_close: Optional[pd.Series] = None,
    funding_rate: Optional[pd.Series] = None,
    oi_change: Optional[pd.Series] = None,
    taker_fee_pct: float = .045,
    slippage_pct: float = .015,
    spread_pct: float = .005,
    funding_buffer_pct: float = .010,
) -> pd.DataFrame:
    n = len(df)
    if n < 220:
        out = pd.DataFrame({
            "signal": [FLAT] * n,
            "score": [0.0] * n,
            "trend_score": [0.0] * n,
            "momentum_score": [0.0] * n,
            "breakout_score": [0.0] * n,
            "derivatives_score": [0.0] * n,
            "regime": ["INSUFFICIENT_DATA"] * n,
            "atr_pct": [0.0] * n,
            "pullback_distance_atr": [0.0] * n,
            "adaptive_pullback_limit": [BASE_PULLBACK_ATR] * n,
            "entry_price": [0.0] * n,
            "stop_price": [0.0] * n,
            "expected_move_atr": [0.0] * n,
            "estimated_round_trip_cost_pct": [0.0] * n,
        }, index=df.index)
        out["execution_signal"] = out["signal"].shift(1).fillna(FLAT)
        return out

    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)

    # 1. ATR (14)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    atr_vals = a.values
    close_vals = c.values
    ap = np.divide(atr_vals, close_vals, out=np.zeros(n), where=(close_vals > 0))

    # 2. EMAs
    e20 = c.ewm(span=20, adjust=False).mean().values
    e50 = c.ewm(span=50, adjust=False).mean().values
    e200 = c.ewm(span=200, adjust=False).mean().values

    # 3. Regime
    rv = c.pct_change().rolling(20).std().fillna(0.0).values
    spread = np.divide(e50 - e200, close_vals, out=np.zeros(n), where=(close_vals > 0))
    e50_s = pd.Series(e50, index=df.index)
    slope = np.divide(e50 - e50_s.shift(10).values, close_vals, out=np.zeros(n), where=(close_vals > 0))

    regime = np.full(n, "TRANSITION", dtype=object)
    high_vol = (ap >= 0.045) | (rv >= 0.035)
    regime[high_vol] = "HIGH_VOL"

    range_mask = (~high_vol) & (np.abs(spread) < 0.0025) & (np.abs(slope) < 0.0015)
    regime[range_mask] = "RANGE"

    bull_mask = (~high_vol) & (~range_mask) & (spread > 0) & (slope > 0)
    regime[bull_mask] = "BULL_TREND"

    bear_mask = (~high_vol) & (~range_mask) & (spread < 0) & (slope < 0)
    regime[bear_mask] = "BEAR_TREND"

    # 4. Scores
    t1 = _dir_vec(c.subtract(e50).divide(close_vals), 0.0015)
    t2 = _dir_vec(pd.Series(e50 - e200, index=df.index).divide(close_vals), 0.002)
    t3 = _dir_vec(pd.Series(e20 - e50, index=df.index).divide(close_vals), 0.001)
    trend = 0.45 * t1 + 0.35 * t2 + 0.20 * t3

    r5 = c.pct_change(5).fillna(0.0).values
    r20 = c.pct_change(20).fillna(0.0).values
    r60 = c.pct_change(60).fillna(0.0).values

    m1 = np.where(r5 > np.maximum(ap * 0.45, 0.001), 1.0, np.where(r5 < -np.maximum(ap * 0.45, 0.001), -1.0, 0.0))
    m2 = np.where(r20 > np.maximum(ap * 0.75, 0.002), 1.0, np.where(r20 < -np.maximum(ap * 0.75, 0.002), -1.0, 0.0))
    m3 = np.where(r60 > np.maximum(ap * 1.5, 0.004), 1.0, np.where(r60 < -np.maximum(ap * 1.5, 0.004), -1.0, 0.0))
    momentum = 0.20 * m1 + 0.45 * m2 + 0.35 * m3

    hi_roll = c.rolling(20).max().shift(1).values
    lo_roll = l.rolling(20).min().shift(1).values
    v_med = v.rolling(20).median().values
    vr = np.divide(v.values, v_med, out=np.zeros(n), where=(v_med > 0))

    breakout = np.zeros(n, dtype=np.float64)
    breakout[(close_vals > hi_roll) & (vr >= 1.10)] = 1.0
    breakout[(close_vals < lo_roll) & (vr >= 1.10)] = -1.0

    # Cross asset / deriv
    deriv = np.zeros(n, dtype=np.float64)
    if btc_close is not None:
        b = pd.Series(btc_close).astype(float)
        b_r20 = b.pct_change(20).fillna(0.0).values
        rel_diff = r20 - b_r20
        thresh = np.maximum(ap * 0.5, 0.002)
        p_btc = np.where(rel_diff > thresh, 1.0, np.where(rel_diff < -thresh, -1.0, 0.0))
        deriv += p_btc

    score = 0.35 * trend + 0.30 * momentum + 0.20 * breakout + 0.15 * deriv

    # Pullback distance
    pull = np.divide(np.abs(close_vals - e20), atr_vals, out=np.zeros(n), where=(atr_vals > 0))

    # Adaptive pullback limit
    adaptive_limit = np.full(n, BASE_PULLBACK_ATR, dtype=np.float64)
    strong_regime_mask = ((regime == "BULL_TREND") | (regime == "BEAR_TREND")) & (np.abs(score) >= 0.75)
    adaptive_limit[strong_regime_mask & (breakout == 0)] = STRONG_PULLBACK_ATR
    adaptive_limit[strong_regime_mask & (breakout != 0)] = BREAKOUT_PULLBACK_ATR

    pull_ok = pull <= adaptive_limit

    # Structure stop
    roll_low = l.rolling(LOOKBACK).min().values
    roll_high = h.rolling(LOOKBACK).max().values
    stop_long = np.minimum(roll_low, e50) - BUFFER_ATR * atr_vals
    stop_short = np.maximum(roll_high, e50) + BUFFER_ATR * atr_vals

    dist_l = np.where(close_vals > 0, np.abs(close_vals - stop_long) / close_vals, 0.0)
    dist_s = np.where(close_vals > 0, np.abs(close_vals - stop_short) / close_vals, 0.0)
    stop_atr_l = np.divide(dist_l, ap, out=np.zeros(n), where=(ap > 1e-9))
    stop_atr_s = np.divide(dist_s, ap, out=np.zeros(n), where=(ap > 1e-9))

    stop_ok_l = (stop_long < close_vals) & (stop_atr_l <= MAX_STOP_ATR) & (dist_l <= MAX_STOP_PCT)
    stop_ok_s = (stop_short > close_vals) & (stop_atr_s <= MAX_STOP_ATR) & (dist_s <= MAX_STOP_PCT)

    # Cost / edge
    tf = taker_fee_pct / 100 if taker_fee_pct > 0.005 else taker_fee_pct
    sl = slippage_pct / 100 if slippage_pct > 0.005 else slippage_pct
    sp = spread_pct / 100 if spread_pct > 0.005 else spread_pct
    fb = funding_buffer_pct / 100 if funding_buffer_pct > 0.005 else funding_buffer_pct
    cost = 2 * tf + 2 * sl + sp + fb

    expected = np.divide(np.abs(r20), ap, out=np.zeros(n), where=(ap > 0))
    edge_ok = (expected * ap) > cost

    bull_entry = (regime == "BULL_TREND") & (score >= ENTRY) & (trend >= 0.30) & (momentum >= 0.25) & pull_ok & edge_ok & stop_ok_l
    bear_entry = (regime == "BEAR_TREND") & (score <= -ENTRY) & (trend <= -0.30) & (momentum <= -0.25) & pull_ok & edge_ok & stop_ok_s
    trans_bull = (regime == "TRANSITION") & (score >= 0.75) & (trend >= 0.50) & (momentum >= 0.45) & pull_ok & edge_ok & stop_ok_l
    trans_bear = (regime == "TRANSITION") & (score <= -0.75) & (trend <= -0.50) & (momentum <= -0.45) & pull_ok & edge_ok & stop_ok_s

    long_trigger = bull_entry | trans_bull
    short_trigger = bear_entry | trans_bear

    signal = np.full(n, FLAT, dtype=object)
    chosen_stop = np.zeros(n, dtype=np.float64)
    state = FLAT

    for i in range(n):
        if i < 219:
            signal[i] = FLAT
            continue
        sc = score[i]
        if state == LONG:
            if sc <= EXIT_SCORE:
                signal[i] = EXIT
                chosen_stop[i] = stop_long[i]
                state = FLAT
            else:
                signal[i] = LONG
                chosen_stop[i] = stop_long[i]
        elif state == SHORT:
            if sc >= -EXIT_SCORE:
                signal[i] = EXIT
                chosen_stop[i] = stop_short[i]
                state = FLAT
            else:
                signal[i] = SHORT
                chosen_stop[i] = stop_short[i]
        elif long_trigger[i]:
            signal[i] = LONG
            chosen_stop[i] = stop_long[i]
            state = LONG
        elif short_trigger[i]:
            signal[i] = SHORT
            chosen_stop[i] = stop_short[i]
            state = SHORT
        else:
            signal[i] = FLAT
            chosen_stop[i] = stop_long[i] if sc > 0 else stop_short[i]

    out = pd.DataFrame({
        "signal": signal,
        "score": np.round(score, 6),
        "trend_score": np.round(trend, 6),
        "momentum_score": np.round(momentum, 6),
        "breakout_score": np.round(breakout, 6),
        "derivatives_score": np.round(deriv, 6),
        "regime": regime,
        "atr_pct": np.round(ap, 8),
        "pullback_distance_atr": np.round(pull, 4),
        "adaptive_pullback_limit": np.round(adaptive_limit, 4),
        "entry_price": np.round(close_vals, 8),
        "stop_price": np.round(chosen_stop, 8),
        "expected_move_atr": np.round(expected, 4),
        "estimated_round_trip_cost_pct": cost,
    }, index=df.index)
    out["execution_signal"] = out["signal"].shift(1).fillna(FLAT)
    return out


def backtest_frame(
    df: pd.DataFrame,
    *,
    btc_close: Optional[pd.Series] = None,
    funding_rate: Optional[pd.Series] = None,
    oi_change: Optional[pd.Series] = None,
    taker_fee_pct: float = .045,
    slippage_pct: float = .015,
    spread_pct: float = .005,
    funding_buffer_pct: float = .010,
    fast: bool = True,
    **kwargs,
) -> pd.DataFrame:
    """Produce one decision row per candle for an offline four-year backtest.

    Signals are shifted one bar so a backtester executes on the next candle without lookahead.
    """
    if fast:
        return _vectorized_backtest_frame(
            df,
            btc_close=btc_close,
            funding_rate=funding_rate,
            oi_change=oi_change,
            taker_fee_pct=taker_fee_pct,
            slippage_pct=slippage_pct,
            spread_pct=spread_pct,
            funding_buffer_pct=funding_buffer_pct,
        )

    rows = []
    position = FLAT
    for i in range(len(df)):
        if i < 219:
            rows.append({"signal": FLAT, "execution_signal": FLAT, "score": 0.0, "regime": "INSUFFICIENT_DATA"})
            continue
        d = generate_strategy_signal(
            df.iloc[: i + 1],
            position=position,
            btc_close=btc_close.iloc[: i + 1] if btc_close is not None else None,
            funding_rate=funding_rate.iloc[i] if funding_rate is not None and i < len(funding_rate) else None,
            oi_change=oi_change.iloc[i] if oi_change is not None and i < len(oi_change) else None,
            taker_fee_pct=taker_fee_pct,
            slippage_pct=slippage_pct,
            spread_pct=spread_pct,
            funding_buffer_pct=funding_buffer_pct,
            **kwargs,
        )
        sig = d["signal"]
        rows.append({
            "signal": sig,
            "execution_signal": FLAT if i == 0 else rows[-1]["signal"],
            "score": d.get("score", 0.0),
            "regime": d.get("regime", "UNKNOWN"),
        })
        if sig == EXIT:
            position = FLAT
        elif sig in (LONG, SHORT):
            position = sig
    return pd.DataFrame(rows, index=df.index)


def run_backtest(
    cache_dir: str = "backtests/historical_data_cache",
    symbols: Optional[list[str]] = None,
    initial_balance: float = 1000.0,
    leverage: float = MAX_LEVERAGE,
    margin_pct: float = 0.035,
    max_positions: int = 5,
    cooldown_bars: int = 12,
    dynamic_leverage: bool = True,
) -> dict:
    """Execute the full 4-year institutional audit and backtest for Strategy Candidate V4.

    Evaluates both:
    1. Pure Signal Alpha Audit (V4 Adaptive Pullback vs V3 vs V2 vs V1 Baselines).
    2. Institutional Multi-Asset Portfolio Simulation with Separate Position Management,
       Early Momentum Deterioration Exit, Profit Giveback Protection, and R-Multiple Trailing.
    """
    if not os.path.exists(cache_dir):
        alt_path = os.path.join(os.path.dirname(__file__), cache_dir)
        if os.path.exists(alt_path):
            cache_dir = alt_path
        else:
            raise FileNotFoundError(f"Cache directory not found: {cache_dir}")

    fee_schedule = {
        "maker": 0.00018,
        "taker": 0.00045,
        "slippage": 0.00015,
        "funding_8h": 0.00010,
    }

    corr_groups = {
        "BTCUSDT": "major",
        "ETHUSDT": "major",
        "SOLUSDT": "layer1",
        "AVAXUSDT": "layer1",
        "ADAUSDT": "layer1",
        "SUIUSDT": "layer1",
        "NEARUSDT": "layer1",
        "LINKUSDT": "infra",
        "BNBUSDT": "exchange",
        "XRPUSDT": "payment",
        "DOGEUSDT": "meme",
    }

    v1_baseline = {
        "BTCUSDT": {"turns": 13940, "gross": 21.9, "net": -814.5},
        "ETHUSDT": {"turns": 13792, "gross": 121.8, "net": -705.7},
        "SOLUSDT": {"turns": 15073, "gross": 102.5, "net": -801.8},
        "LINKUSDT": {"turns": 15403, "gross": -134.6, "net": -1058.7},
        "AVAXUSDT": {"turns": 14989, "gross": 120.8, "net": -778.5},
        "XRPUSDT": {"turns": 14217, "gross": -50.4, "net": -903.5},
        "ADAUSDT": {"turns": 15285, "gross": 52.0, "net": -865.1},
        "DOGEUSDT": {"turns": 14409, "gross": 85.4, "net": -779.1},
        "NEARUSDT": {"turns": 15501, "gross": -172.1, "net": -1102.2},
        "BNBUSDT": {"turns": 13516, "gross": -14.4, "net": -825.4},
        "SUIUSDT": {"turns": 12299, "gross": 2.2, "net": -735.8},
    }
    v2_baseline = {
        "BTCUSDT": {"turns": 2778, "gross": 46.7, "net": -120.0},
        "ETHUSDT": {"turns": 4224, "gross": 53.4, "net": -200.0},
        "SOLUSDT": {"turns": 5483, "gross": 203.2, "net": -125.8},
        "LINKUSDT": {"turns": 5568, "gross": -94.0, "net": -428.1},
        "AVAXUSDT": {"turns": 5459, "gross": 147.5, "net": -180.0},
        "XRPUSDT": {"turns": 4863, "gross": -41.4, "net": -333.1},
        "ADAUSDT": {"turns": 5405, "gross": 25.1, "net": -299.2},
        "DOGEUSDT": {"turns": 5224, "gross": -32.0, "net": -345.4},
        "NEARUSDT": {"turns": 5949, "gross": -83.3, "net": -440.2},
        "BNBUSDT": {"turns": 4026, "gross": -55.0, "net": -296.6},
        "SUIUSDT": {"turns": 4991, "gross": -56.5, "net": -356.0},
    }
    v3_baseline = {
        "BTCUSDT": {"turns": 0, "gross": 0.0, "net": 0.0},
        "ETHUSDT": {"turns": 1922, "gross": 5.7, "net": -109.7},
        "SOLUSDT": {"turns": 3367, "gross": 73.7, "net": -128.3},
        "LINKUSDT": {"turns": 3192, "gross": -0.3, "net": -191.8},
        "AVAXUSDT": {"turns": 3116, "gross": 20.2, "net": -166.8},
        "XRPUSDT": {"turns": 2544, "gross": 41.2, "net": -111.5},
        "ADAUSDT": {"turns": 3102, "gross": 87.2, "net": -98.9},
        "DOGEUSDT": {"turns": 2970, "gross": -3.5, "net": -181.7},
        "NEARUSDT": {"turns": 3743, "gross": -12.9, "net": -237.5},
        "BNBUSDT": {"turns": 1570, "gross": -59.4, "net": -153.6},
        "SUIUSDT": {"turns": 3114, "gross": -67.0, "net": -253.9},
    }

    all_symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
        "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
    ]
    target_symbols = symbols if symbols else all_symbols

    print("\n" + "=" * 110)
    print(" [AUDIT] STRATEGY CANDIDATE V4: 4-YEAR INSTITUTIONAL AUDIT & ADAPTIVE TREND CAPTURE")
    print("=" * 110)
    print(" * Period:                  September 2022 -> September 2026 (15-minute bars)")
    print(f" * Fee Schedule:            Maker: {fee_schedule['maker']*100:.3f}%, Taker: {fee_schedule['taker']*100:.3f}%, Slip: {fee_schedule['slippage']*100:.3f}%, 8h Fund: {fee_schedule['funding_8h']*100:.3f}%")
    print(" * Adaptive Pullback Gate:  Base: 0.60 ATR | Strong: 0.90 ATR | Breakout: 1.20 ATR")
    print(f" * Risk & Structure Stops:  Lookback: {LOOKBACK} | Buffer: {BUFFER_ATR}x ATR | Max Leverage: {leverage}x | Risk Pct: {margin_pct*100:.2f}%")
    print(" * Position Management:     1R Early Momentum Exit | 1.5R Giveback Protection | 192-bar Max Duration | 2R Swing Trail")
    print("-" * 110)

    # 1. Load Data and Compute Signals
    t0 = time.time()
    btc_file = os.path.join(cache_dir, "BTCUSDT_15m_4year_2022-09-01.csv")
    if not os.path.exists(btc_file):
        raise FileNotFoundError(f"BTC benchmark cache missing: {btc_file}")
    df_btc = pd.read_csv(btc_file)
    df_btc["open_time"] = pd.to_datetime(df_btc["open_time"])
    btc_series = df_btc.set_index("open_time")["close"].astype(float)

    data_map = {}
    signals_map = {}

    print(" Precomputing candidate V4 signals across assets...")
    for sym in target_symbols:
        cache_file = os.path.join(cache_dir, f"{sym}_15m_4year_2022-09-01.csv")
        if not os.path.exists(cache_file):
            continue
        df = pd.read_csv(cache_file)
        df["open_time"] = pd.to_datetime(df["open_time"])
        df = df.sort_values("open_time").reset_index(drop=True)
        b_close = df["open_time"].map(btc_series).ffill().bfill() if sym != "BTCUSDT" else None

        sig_df = backtest_frame(df, btc_close=b_close, fast=True)
        data_map[sym] = df
        signals_map[sym] = sig_df

        l_cnt = int(np.sum(sig_df["signal"] == LONG))
        s_cnt = int(np.sum(sig_df["signal"] == SHORT))
        f_cnt = int(np.sum((sig_df["signal"] == FLAT) | (sig_df["signal"] == EXIT)))
        cov = (l_cnt + s_cnt) / len(df) * 100.0
        print(f"   * {sym:<9}: {len(df):>7,} bars | Longs: {l_cnt:>6,} | Shorts: {s_cnt:>6,} | Flat/Exit: {f_cnt:>6,} ({cov:4.1f}% active)")

    print(f" Signals precomputed in {time.time()-t0:.2f}s.")

    # 2. Pure Signal Alpha Audit (Four Generations)
    print("\n" + "=" * 115)
    print(" [AUDIT 1] PURE UNLEVERAGED ALPHA AUDIT (V1 vs. V2 vs. V3 vs. V4)")
    print("=" * 115)
    print(f" {'Symbol':<9} | {'Bars':>7} | {'V1 Turns':>8} | {'V3 Turns':>8} | {'V4 Turns':>8} | {'Gross V1':>8} | {'Gross V2':>8} | {'Gross V3':>8} | {'Gross V4':>8} | {'Net V4':>8}")
    print("-" * 115)

    alpha_summary = []
    for sym in target_symbols:
        if sym not in data_map:
            continue
        df = data_map[sym]
        sig_df = signals_map[sym]
        close_vals = df["close"].astype(float).values
        pos = np.where(sig_df["execution_signal"] == LONG, 1,
              np.where(sig_df["execution_signal"] == SHORT, -1, 0))
        ret = np.diff(close_vals, prepend=close_vals[0]) / np.where(close_vals > 0, np.roll(close_vals, 1), 1.0)
        ret[0] = 0.0
        turns = int(np.sum(np.abs(np.diff(pos, prepend=0))))
        gross_alpha = float(np.sum(pos * ret) * 100.0)
        friction_drag = float(turns * (fee_schedule["taker"] + fee_schedule["slippage"]) * 100.0)
        net_alpha = gross_alpha - friction_drag
        bh_ret = float((close_vals[-1] - close_vals[0]) / close_vals[0] * 100.0)

        v1 = v1_baseline.get(sym, {"turns": turns, "gross": gross_alpha, "net": net_alpha})
        v2 = v2_baseline.get(sym, {"turns": turns, "gross": gross_alpha, "net": net_alpha})
        v3 = v3_baseline.get(sym, {"turns": turns, "gross": gross_alpha, "net": net_alpha})

        alpha_summary.append({
            "symbol": sym,
            "bars": len(df),
            "turns": turns,
            "v1_turns": v1["turns"],
            "v3_turns": v3["turns"],
            "gross_alpha": gross_alpha,
            "v1_gross": v1["gross"],
            "v2_gross": v2["gross"],
            "v3_gross": v3["gross"],
            "net_alpha": net_alpha,
        })
        print(f" {sym:<9} | {len(df):>7,} | {v1['turns']:>8,} | {v3['turns']:>8,} | {turns:>8,} | {v1['gross']:>+7.1f}% | {v2['gross']:>+7.1f}% | {v3['gross']:>+7.1f}% | {gross_alpha:>+7.1f}% | {net_alpha:>+7.1f}%")
    print("=" * 115)

    # 3. Fast Timeline Multi-Asset Portfolio Simulation
    time_sets = [set(df["open_time"]) for df in data_map.values()]
    timeline = sorted(list(set.union(*time_sets)))

    sym_arrays = {}
    for sym, df in data_map.items():
        sig_df = signals_map[sym]
        df_sorted = df.set_index("open_time")
        sig_sorted = sig_df.set_index(df["open_time"])
        aligned = pd.DataFrame({
            "open": df_sorted["open"].astype(float),
            "high": df_sorted["high"].astype(float),
            "low": df_sorted["low"].astype(float),
            "close": df_sorted["close"].astype(float),
            "atr": sig_sorted["atr_pct"].values * df_sorted["close"].astype(float).values,
            "atr_pct": sig_sorted["atr_pct"].values,
            "score": sig_sorted["score"].values,
            "signal": sig_sorted["execution_signal"].values,
            "stop_price": sig_sorted["stop_price"].values,
            "regime": sig_sorted["regime"].values,
        }).reindex(timeline)

        sym_arrays[sym] = {
            "open": aligned["open"].values,
            "high": aligned["high"].values,
            "low": aligned["low"].values,
            "close": aligned["close"].values,
            "atr": aligned["atr"].values,
            "atr_pct": aligned["atr_pct"].values,
            "score": aligned["score"].values,
            "signal": aligned["signal"].values,
            "stop_price": aligned["stop_price"].values,
            "regime": aligned["regime"].values,
        }

    balance = float(initial_balance)
    peak_balance = float(initial_balance)
    max_dd = 0.0
    active_positions = {}
    closed_trades = []
    cooldowns = {sym: 0 for sym in target_symbols}

    tot_maker_fees = 0.0
    tot_taker_fees = 0.0
    tot_slippage = 0.0
    tot_funding = 0.0

    trade_pnl_by_symbol = {sym: [] for sym in target_symbols}
    regime_trades = {}
    yearly_trades = {}
    exit_reasons = {}

    t_sim = time.time()
    for idx, ts in enumerate(timeline):
        yr = ts.year
        if yr not in yearly_trades:
            yearly_trades[yr] = {"trades": 0, "wins": 0, "pnl": 0.0}

        for sym in cooldowns:
            if cooldowns[sym] > 0:
                cooldowns[sym] -= 1

        to_close = []
        for sym, pos in list(active_positions.items()):
            arr = sym_arrays[sym]
            o = arr["open"][idx]
            if np.isnan(o):
                continue
            h, l, c = arr["high"][idx], arr["low"][idx], arr["close"][idx]
            atr = arr["atr"][idx]
            sig = arr["signal"][idx]
            sc = arr["score"][idx]

            pos["bars_held"] += 1
            if pos["bars_held"] % 32 == 0:
                fund = pos["notional"] * fee_schedule["funding_8h"]
                balance -= fund
                tot_funding += fund

            exit_price = None
            exit_reason = None

            if pos["side"] == LONG:
                if h > pos["peak_price"]:
                    pos["peak_price"] = h

                risk_dist = pos["entry_price"] - pos["initial_stop"]
                unrealized_r = (c - pos["entry_price"]) / risk_dist if risk_dist > 0 else 0.0
                peak_r = (pos["peak_price"] - pos["entry_price"]) / risk_dist if risk_dist > 0 else 0.0

                mgmt = manage_position(
                    LONG, pos["entry_price"], pos["stop_loss"], pos["peak_price"],
                    pos["bars_held"], unrealized_r, sc, atr
                )

                if mgmt["action"] == EXIT:
                    exit_price = o
                    exit_reason = mgmt["reason"]
                else:
                    pos["stop_loss"] = mgmt["stop"]

                if exit_reason is None and l <= pos["stop_loss"]:
                    exit_price = min(o, pos["stop_loss"])
                    exit_reason = "R_TRAILING_STOP" if peak_r >= 1.0 else "STRUCTURE_STOP"

                if exit_reason is None and sig in (EXIT, SHORT):
                    exit_price = o
                    exit_reason = "STRAT_EXIT"

            else:  # SHORT
                if l < pos["peak_price"]:
                    pos["peak_price"] = l

                risk_dist = pos["initial_stop"] - pos["entry_price"]
                unrealized_r = (pos["entry_price"] - c) / risk_dist if risk_dist > 0 else 0.0
                peak_r = (pos["entry_price"] - pos["peak_price"]) / risk_dist if risk_dist > 0 else 0.0

                mgmt = manage_position(
                    SHORT, pos["entry_price"], pos["stop_loss"], pos["peak_price"],
                    pos["bars_held"], unrealized_r, sc, atr
                )

                if mgmt["action"] == EXIT:
                    exit_price = o
                    exit_reason = mgmt["reason"]
                else:
                    pos["stop_loss"] = mgmt["stop"]

                if exit_reason is None and h >= pos["stop_loss"]:
                    exit_price = max(o, pos["stop_loss"])
                    exit_reason = "R_TRAILING_STOP" if peak_r >= 1.0 else "STRUCTURE_STOP"

                if exit_reason is None and sig in (EXIT, LONG):
                    exit_price = o
                    exit_reason = "STRAT_EXIT"

            if exit_reason is not None:
                pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"] if pos["side"] == LONG else (pos["entry_price"] - exit_price) / pos["entry_price"]
                gross_pnl = pos["notional"] * pnl_pct
                slip = pos["notional"] * fee_schedule["slippage"]
                fee = pos["notional"] * fee_schedule["taker"]
                tot_slippage += slip
                tot_taker_fees += fee
                realized_pnl = gross_pnl - slip - fee
                balance += pos["margin"] + realized_pnl
                cooldowns[sym] = cooldown_bars

                exit_reasons[exit_reason] = exit_reasons.get(exit_reason, 0) + 1
                trade_record = {
                    "symbol": sym,
                    "side": pos["side"],
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "notional": pos["notional"],
                    "leverage": pos["leverage"],
                    "net_pnl": realized_pnl,
                    "reason": exit_reason,
                    "regime": pos["entry_regime"],
                    "bars_held": pos["bars_held"],
                    "win": realized_pnl > 0,
                    "year": yr,
                }
                closed_trades.append(trade_record)
                trade_pnl_by_symbol[sym].append(realized_pnl)

                reg = pos["entry_regime"]
                if reg not in regime_trades:
                    regime_trades[reg] = {"trades": 0, "wins": 0, "pnl": 0.0}
                regime_trades[reg]["trades"] += 1
                if realized_pnl > 0:
                    regime_trades[reg]["wins"] += 1
                regime_trades[reg]["pnl"] += realized_pnl

                yearly_trades[yr]["trades"] += 1
                if realized_pnl > 0:
                    yearly_trades[yr]["wins"] += 1
                yearly_trades[yr]["pnl"] += realized_pnl

                to_close.append(sym)

        for sym in to_close:
            del active_positions[sym]

        if balance > peak_balance:
            peak_balance = balance
        dd = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

        # Open new candidate positions
        if len(active_positions) < max_positions and balance > 10.0:
            candidates = []
            for sym in target_symbols:
                if sym in active_positions or cooldowns[sym] > 0:
                    continue
                arr = sym_arrays[sym]
                o = arr["open"][idx]
                if np.isnan(o):
                    continue
                sig = arr["signal"][idx]
                if sig in (LONG, SHORT):
                    candidates.append({
                        "symbol": sym,
                        "signal": sig,
                        "score": arr["score"][idx],
                        "atr": arr["atr"][idx],
                        "atr_pct": arr["atr_pct"][idx],
                        "entry_price": o,
                        "stop_price": arr["stop_price"][idx],
                        "regime": arr["regime"][idx],
                        "correlation_group": corr_groups.get(sym, "other")
                    })

            selected = enforce_portfolio_limits(
                candidates,
                max_positions=max_positions - len(active_positions),
                max_same_direction=3,
                max_correlated=2
            )

            for cand in selected:
                sym = cand["symbol"]
                sig = cand["signal"]
                atr = cand["atr"]
                atr_pct = cand["atr_pct"]
                entry_price = cand["entry_price"]
                st_price = cand["stop_price"]
                if entry_price <= 0 or st_price <= 0 or atr <= 0:
                    continue

                if dynamic_leverage:
                    lev = choose_leverage(atr_pct, target_risk_pct=margin_pct, stop_atr=2.0, max_leverage=float(leverage), min_leverage=1.0)
                else:
                    lev = float(leverage)

                notional = risk_based_notional(balance, margin_pct, entry_price, st_price, max_leverage=lev, max_notional_pct=0.30)
                if notional <= 0:
                    continue
                margin = notional / lev
                if margin > balance * 0.30 or balance - margin < 5.0:
                    continue

                fee_entry = notional * fee_schedule["maker"]
                balance -= (margin + fee_entry)
                tot_maker_fees += fee_entry

                active_positions[sym] = {
                    "symbol": sym,
                    "side": sig,
                    "entry_price": entry_price,
                    "initial_stop": st_price,
                    "stop_loss": st_price,
                    "notional": notional,
                    "margin": margin,
                    "leverage": lev,
                    "peak_price": entry_price,
                    "bars_held": 0,
                    "entry_regime": cand["regime"]
                }

    total_trades = len(closed_trades)
    winning_trades = [t for t in closed_trades if t["win"]]
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    gross_gains = sum(t["net_pnl"] for t in winning_trades)
    gross_losses = abs(sum(t["net_pnl"] for t in closed_trades if not t["win"]))
    profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else (999.0 if gross_gains > 0 else 0.0)

    total_net_pnl = balance - initial_balance
    total_roi_pct = (total_net_pnl / initial_balance) * 100.0

    print("\n" + "=" * 110)
    print(" [AUDIT 2] MULTI-ASSET PORTFOLIO SIMULATION SCORECARD (CANDIDATE V4)")
    print("=" * 110)
    print(f" * Initial Balance:         ${initial_balance:,.2f} USDT")
    print(f" * Final Portfolio Balance:  ${balance:,.2f} USDT")
    print(f" * Net Realized Profit:      ${total_net_pnl:,.2f} USDT ({total_roi_pct:+.2f}% Total ROI)")
    print(f" * Net Profit Factor (PF):   {profit_factor:.2f}")
    print(f" * Overall Win Rate:         {win_rate:.1f}% ({len(winning_trades):,} Wins / {total_trades - len(winning_trades):,} Losses)")
    print(f" * Total Closed Trades:      {total_trades:,}")
    print(f" * Max Portfolio Drawdown:   {max_dd*100:.2f}%")
    print(f" * Total Friction Deducted:  ${tot_maker_fees + tot_taker_fees + tot_slippage + tot_funding:,.2f} USDT")
    print(f"    - Maker Entry Fees:      ${tot_maker_fees:,.2f} USDT")
    print(f"    - Taker Exit/Stop Fees:  ${tot_taker_fees:,.2f} USDT")
    print(f"    - Slippage Deductions:   ${tot_slippage:,.2f} USDT")
    print(f"    - 8h Funding Holding:    ${tot_funding:,.2f} USDT")
    print("-" * 110)

    print(f" {'Asset':<10} | {'Trades':>8} | {'Win Rate':>9} | {'Net Realized PnL':>18} | {'Avg Trade PnL':>15}")
    print("-" * 80)
    for sym in target_symbols:
        pnls = trade_pnl_by_symbol[sym]
        t_cnt = len(pnls)
        if t_cnt == 0:
            continue
        w_cnt = sum(1 for p in pnls if p > 0)
        wr = w_cnt / t_cnt * 100.0
        tot_p = sum(pnls)
        avg_p = tot_p / t_cnt
        print(f" {sym:<10} | {t_cnt:>8,} | {wr:>8.1f}% | ${tot_p:>17.2f} | ${avg_p:>14.2f}")
    print("-" * 80)

    print("\n Trade Exit Mechanics:")
    for r_name, r_cnt in sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"   * {r_name:<38}: {r_cnt:>6,} ({r_cnt/total_trades*100:5.1f}%)" if total_trades else f"   * {r_name}: 0")

    print("\n Regime Entry Distribution:")
    for reg, stats in sorted(regime_trades.items(), key=lambda x: x[1]["trades"], reverse=True):
        wr = (stats["wins"] / stats["trades"] * 100.0) if stats["trades"] > 0 else 0.0
        print(f"   * {reg:<16}: {stats['trades']:>6,} trades | WR: {wr:5.1f}% | Net PnL: ${stats['pnl']:>10.2f}")

    print("\n Yearly Realized PnL:")
    for yr, stats in sorted(yearly_trades.items()):
        wr = (stats["wins"] / stats["trades"] * 100.0) if stats["trades"] > 0 else 0.0
        print(f"   * {yr}: {stats['trades']:>6,} trades | Win Rate: {wr:5.1f}% | Realized PnL: ${stats['pnl']:>10.2f}")
    print("=" * 110 + "\n")

    return {
        "balance": balance,
        "roi_pct": total_roi_pct,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "max_drawdown": max_dd,
        "alpha_summary": alpha_summary,
        "closed_trades": closed_trades,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 4-year institutional backtest for Strategy Candidate V4.")
    parser.add_argument("--cache-dir", type=str, default="backtests/historical_data_cache", help="Path to historical cache directory")
    parser.add_argument("--symbols", type=str, default=None, help="Comma-separated list of symbols (e.g. BTCUSDT,ETHUSDT,SOLUSDT)")
    parser.add_argument("--balance", type=float, default=1000.0, help="Initial portfolio balance (USDT)")
    parser.add_argument("--leverage", type=float, default=MAX_LEVERAGE, help="Maximum leverage cap (default: 10.0)")
    parser.add_argument("--margin-pct", type=float, default=0.035, help="Risk fraction per trade (default: 0.035 = 3.5%)")
    parser.add_argument("--max-positions", type=int, default=5, help="Maximum concurrent positions across portfolio (default: 5)")
    parser.add_argument("--cooldown", type=int, default=12, help="Cooldown bars after trade exit (default: 12 bars = 3 hours)")
    parser.add_argument("--fixed-leverage", action="store_true", help="Disable dynamic ATR leverage and use fixed leverage cap")

    args = parser.parse_args()
    sym_list = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    run_backtest(
        cache_dir=args.cache_dir,
        symbols=sym_list,
        initial_balance=args.balance,
        leverage=args.leverage,
        margin_pct=args.margin_pct,
        max_positions=args.max_positions,
        cooldown_bars=args.cooldown,
        dynamic_leverage=not args.fixed_leverage,
    )

