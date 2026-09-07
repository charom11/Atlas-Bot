"""Offline Strategy Candidate V4: Adaptive Trend Capture.

Research-only. No exchange/network/order calls and deliberately not wired into
main.py. V4 separates entry confirmation from position management so winners
can be protected before a slow regime exit.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional, Sequence
import math
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
    if unrealized_r>=1.5:
        giveback = (peak_price-entry_price)/(abs(entry_price-current_stop) or 1e-9) if side==LONG else (entry_price-peak_price)/(abs(entry_price-current_stop) or 1e-9)
        if giveback>0 and unrealized_r<=max(0.5,unrealized_r*0+MAX_GIVEBACK_R):
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

def backtest_frame(df,**kwargs):
    """Reference backtest interface. Each bar's signal is executed on next bar."""
    rows=[];position=FLAT
    for i in range(len(df)):
        if i<219: rows.append({"signal":FLAT,"execution_signal":FLAT,"score":0.0,"regime":"INSUFFICIENT_DATA"});continue
        d=generate_strategy_signal(df.iloc[:i+1],position=position,**kwargs);sig=d["signal"]
        rows.append({"signal":sig,"execution_signal":FLAT if i==0 else rows[-1]["signal"],"score":d.get("score",0.0),"regime":d.get("regime","UNKNOWN")})
        if sig==EXIT:position=FLAT
        elif sig in (LONG,SHORT):position=sig
    return pd.DataFrame(rows,index=df.index)
