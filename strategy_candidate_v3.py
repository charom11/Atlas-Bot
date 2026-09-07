"""Offline Strategy Candidate V3: Structure-Aware Trend Pullback.

Research-only module. It is deliberately NOT imported by main.py and performs
no exchange, network, or order-placement operations.

V3 changes versus V2:
- stateful entry/hold hysteresis without direct reversal;
- trend-aligned EMA20 pullback/retest entries;
- structure + EMA50 ATR-buffered protective stops;
- fixed-risk sizing, with leverage treated as a cap;
- R-based trailing logic that gives trends more room;
- conservative cost-aware entry filter;
- deterministic portfolio concentration controls.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Sequence
import math

import numpy as np
import pandas as pd

LONG = "LONG"
SHORT = "SHORT"
FLAT = "FLAT"
EXIT = "EXIT"

ENTRY_THRESHOLD = 0.65
EXIT_THRESHOLD = 0.20
TRANSITION_ENTRY_THRESHOLD = 0.75
MIN_TREND_CONFIRM = 0.30
MIN_MOMENTUM_CONFIRM = 0.25
HIGH_VOL_ATR_PCT = 0.045
HIGH_VOL_REALIZED = 0.035
RANGE_SPREAD = 0.0025
RANGE_SLOPE = 0.0015
PULLBACK_MAX_ATR = 0.60
STRUCTURE_LOOKBACK = 20
STOP_ATR_BUFFER = 0.25
MAX_STOP_ATR = 4.5
MAX_STOP_PCT = 0.06
DEFAULT_RISK_PCT = 0.035
DEFAULT_MAX_LEVERAGE = 10.0

@dataclass(frozen=True)
class StrategyDecision:
    signal: str
    score: float
    trend_score: float
    momentum_score: float
    breakout_score: float
    derivatives_score: float
    regime: str
    volatility_pct: float
    atr_pct: float
    pullback_distance_atr: float
    entry_price: float
    stop_price: float
    stop_distance_atr: float
    stop_distance_pct: float
    expected_move_atr: float
    estimated_round_trip_cost_pct: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _valid(df: pd.DataFrame) -> bool:
    return df is not None and {"open", "high", "low", "close", "volume"}.issubset(df.columns) and len(df) >= 220


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = (df[x].astype(float) for x in ("high", "low", "close"))
    tr = pd.concat([(h-l), (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()


def _dir(x: float, deadzone: float = 0.0) -> float:
    if not math.isfinite(x): return 0.0
    return 1.0 if x > deadzone else -1.0 if x < -deadzone else 0.0


def _last(x: object) -> Optional[float]:
    if x is None: return None
    if isinstance(x, pd.Series):
        if x.empty: return None
        x = x.iloc[-1]
    try: v = float(x)
    except (TypeError, ValueError): return None
    return v if math.isfinite(v) else None


def _regime(df: pd.DataFrame, atr: pd.Series) -> tuple[str, float, float]:
    c=df["close"].astype(float); e50=c.ewm(span=50,adjust=False).mean(); e200=c.ewm(span=200,adjust=False).mean(); price=float(c.iloc[-1])
    ap=float(atr.iloc[-1]/price) if price else 0.0
    realized=float(c.pct_change().rolling(20).std().iloc[-1]); realized=realized if math.isfinite(realized) else 0.0
    spread=float((e50.iloc[-1]-e200.iloc[-1])/price); slope=float((e50.iloc[-1]-e50.iloc[-11])/price)
    if ap>=HIGH_VOL_ATR_PCT or realized>=HIGH_VOL_REALIZED: return "HIGH_VOL",realized,ap
    if abs(spread)<RANGE_SPREAD and abs(slope)<RANGE_SLOPE: return "RANGE",realized,ap
    if spread>0 and slope>0: return "BULL_TREND",realized,ap
    if spread<0 and slope<0: return "BEAR_TREND",realized,ap
    return "TRANSITION",realized,ap


def _scores(df: pd.DataFrame, btc_close: Optional[pd.Series], funding_rate: object, oi_change: object):
    c=df["close"].astype(float); v=df["volume"].astype(float); a=_atr(df); ap=float(a.iloc[-1]/c.iloc[-1]) if c.iloc[-1] else 0.0
    e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean(); e200=c.ewm(span=200,adjust=False).mean()
    trend=.45*_dir((c.iloc[-1]-e50.iloc[-1])/c.iloc[-1],.0015)+.35*_dir((e50.iloc[-1]-e200.iloc[-1])/c.iloc[-1],.002)+.20*_dir((e20.iloc[-1]-e50.iloc[-1])/c.iloc[-1],.001)
    r5=float(c.pct_change(5).iloc[-1]); r20=float(c.pct_change(20).iloc[-1]); r60=float(c.pct_change(60).iloc[-1])
    momentum=.20*_dir(r5,max(ap*.45,.001))+.45*_dir(r20,max(ap*.75,.002))+.35*_dir(r60,max(ap*1.5,.004))
    hi=c.rolling(20).max().shift(1).iloc[-1]; lo=df["low"].astype(float).rolling(20).min().shift(1).iloc[-1]; med=v.rolling(20).median().iloc[-1]; vr=float(v.iloc[-1]/med) if med>0 else 0.0
    breakout=1.0 if np.isfinite(hi) and c.iloc[-1]>hi and vr>=1.10 else -1.0 if np.isfinite(lo) and c.iloc[-1]<lo and vr>=1.10 else 0.0
    parts=[]
    if btc_close is not None:
        b=pd.Series(btc_close).astype(float); n=min(len(c),len(b))
        if n>=30: parts.append(_dir(float(c.iloc[-n:].pct_change(20).iloc[-1]-b.iloc[-n:].pct_change(20).iloc[-1]),max(ap*.5,.002)))
    fr=_last(funding_rate)
    if fr is not None and abs(fr)>.0001: parts.append(-1.0 if fr>0 else 1.0)
    oi=_last(oi_change)
    if oi is not None and abs(oi)>=.001:
        z=max(ap*.35,.001)
        if r5>z and oi>0: parts.append(1.0)
        elif r5<-z and oi>0: parts.append(-1.0)
        elif r5>z and oi<0: parts.append(.25)
        elif r5<-z and oi<0: parts.append(-.25)
    deriv=float(np.mean(parts)) if parts else 0.0
    score=float(.35*trend+.30*momentum+.20*breakout+.15*deriv)
    return score,float(trend),float(momentum),float(breakout),deriv,ap,vr,r20,r60,e20,e50


def _pct(v: float) -> float:
    return v/100.0 if v>0.005 else v


def structure_stop(df: pd.DataFrame, side: str, atr: Optional[float] = None, lookback: int = STRUCTURE_LOOKBACK, buffer_atr: float = STOP_ATR_BUFFER) -> float:
    """Return a stop beyond recent structure and EMA50; no exchange calls."""
    if not _valid(df): return 0.0
    c=df["close"].astype(float); a=float(_atr(df).iloc[-1] if atr is None else atr); e50=float(c.ewm(span=50,adjust=False).mean().iloc[-1])
    if not math.isfinite(a) or a<=0: return 0.0
    if side==LONG:
        swing=float(df["low"].astype(float).rolling(lookback).min().iloc[-1])
        return float(min(swing,e50)-buffer_atr*a)
    if side==SHORT:
        swing=float(df["high"].astype(float).rolling(lookback).max().iloc[-1])
        return float(max(swing,e50)+buffer_atr*a)
    return 0.0


def _decision(df, signal, score, trend, mom, brk, deriv, regime, vol, ap, pull, entry, stop, expected, cost, reasons):
    dist=abs(entry-stop)/entry if entry>0 and stop>0 else 0.0
    return StrategyDecision(signal,round(score,6),round(trend,6),round(mom,6),round(brk,6),round(deriv,6),regime,round(vol,8),round(ap,8),round(pull,4),round(entry,8),round(stop,8),round(dist/(ap or 1),4),round(dist,8),round(expected,4),cost,tuple(reasons)).to_dict()


def generate_strategy_signal(df: pd.DataFrame, *, position: str=FLAT, btc_close: Optional[pd.Series]=None,
                              funding_rate: object=None, oi_change: object=None, taker_fee_pct: float=.045,
                              slippage_pct: float=.015, spread_pct: float=.005, funding_buffer_pct: float=.010,
                              pullback_max_atr: float=PULLBACK_MAX_ATR) -> dict:
    if not _valid(df):
        return StrategyDecision(FLAT,0,0,0,0,0,"INSUFFICIENT_DATA",0,0,0,0,0,0,0,0,0,("insufficient OHLCV history",)).to_dict()
    a=_atr(df); regime,vol,ap=_regime(df,a); score,trend,mom,brk,deriv,ap,vr,r20,r60,e20,e50=_scores(df,btc_close,funding_rate,oi_change)
    entry=float(df["close"].iloc[-1]); atr=float(a.iloc[-1]); pull=abs(entry-float(e20.iloc[-1]))/atr if atr>0 else float("inf")
    stop=structure_stop(df,LONG,atr) if score>0 else structure_stop(df,SHORT,atr)
    dist=abs(entry-stop)/entry if stop>0 else float("inf"); stop_atr=dist/ap if ap>0 else float("inf")
    tf,sl,sp,fb=map(_pct,(taker_fee_pct,slippage_pct,spread_pct,funding_buffer_pct)); cost=2*tf+2*sl+sp+fb
    expected=abs(r20)/(ap if ap>1e-9 else 1.0); reasons=[f"regime={regime}",f"volume_ratio={vr:.2f}",f"pullback_atr={pull:.2f}",f"expected_move_atr={expected:.2f}"]
    if position==LONG and score<=EXIT_THRESHOLD: return _decision(df,EXIT,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,structure_stop(df,LONG,atr),expected,cost,reasons+["long hysteresis exit"])
    if position==SHORT and score>=-EXIT_THRESHOLD: return _decision(df,EXIT,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,structure_stop(df,SHORT,atr),expected,cost,reasons+["short hysteresis exit"])
    if position in (LONG,SHORT): return _decision(df,position,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,structure_stop(df,position,atr),expected,cost,reasons+["position held by hysteresis"])
    if regime in ("HIGH_VOL","RANGE"):
        return _decision(df,FLAT,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,stop,expected,cost,reasons+["regime entry gate"])
    edge_ok=expected*ap>cost
    pullback_ok=pull<=pullback_max_atr
    stop_ok=0<stop<entry if score>0 else stop>entry
    stop_ok=stop_ok and stop_atr<=MAX_STOP_ATR and dist<=MAX_STOP_PCT
    if not pullback_ok: reasons.append("price is too extended from EMA20")
    if not edge_ok: reasons.append("expected move does not clear conservative cost budget")
    if not stop_ok: reasons.append("structure stop is too wide or invalid")
    if regime=="BULL_TREND" and score>=ENTRY_THRESHOLD and trend>=MIN_TREND_CONFIRM and mom>=MIN_MOMENTUM_CONFIRM and pullback_ok and edge_ok and stop_ok:
        return _decision(df,LONG,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,structure_stop(df,LONG,atr),expected,cost,reasons+["EMA20 pullback long confirmed"])
    if regime=="BEAR_TREND" and score<=-ENTRY_THRESHOLD and trend<=-MIN_TREND_CONFIRM and mom<=-MIN_MOMENTUM_CONFIRM and pullback_ok and edge_ok and stop_ok:
        return _decision(df,SHORT,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,structure_stop(df,SHORT,atr),expected,cost,reasons+["EMA20 pullback short confirmed"])
    if regime=="TRANSITION" and abs(score)>=TRANSITION_ENTRY_THRESHOLD and abs(trend)>=.50 and abs(mom)>=.45 and pullback_ok and edge_ok and stop_ok:
        side=LONG if score>0 else SHORT
        return _decision(df,side,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,structure_stop(df,side,atr),expected,cost,reasons+["transition pullback confirmed"])
    return _decision(df,FLAT,score,trend,mom,brk,deriv,regime,vol,ap,pull,entry,stop,expected,cost,reasons+["entry confirmation incomplete"])


def risk_based_notional(equity: float, risk_pct: float, entry_price: float, stop_price: float,
                        max_leverage: float=DEFAULT_MAX_LEVERAGE, max_notional_pct: float=1.0) -> float:
    vals=(equity,risk_pct,entry_price,stop_price,max_leverage,max_notional_pct)
    if not all(math.isfinite(float(x)) for x in vals) or equity<=0 or risk_pct<=0 or entry_price<=0 or stop_price<=0 or max_leverage<=0 or max_notional_pct<=0: return 0.0
    distance=abs(entry_price-stop_price)/entry_price
    if distance<=1e-9: return 0.0
    return float(max(0.0,min(equity*risk_pct/distance,equity*max_leverage,equity*max_notional_pct)))


def choose_leverage(atr_pct: float, target_risk_pct: float=DEFAULT_RISK_PCT, stop_atr: float=2.0,
                    max_leverage: float=DEFAULT_MAX_LEVERAGE, min_leverage: float=1.0) -> float:
    if not math.isfinite(atr_pct) or atr_pct<=0: return min_leverage
    return float(np.clip(target_risk_pct/(atr_pct*stop_atr),min_leverage,max_leverage))


def trailing_stop(entry_price: float, current_stop: float, peak_price: float, side: str, atr: float,
                  r_multiple: float, ema20: Optional[float]=None, swing_price: Optional[float]=None) -> float:
    """Advance a stop only in the protective direction; never loosen it."""
    if not all(math.isfinite(float(x)) for x in (entry_price,current_stop,peak_price,atr,r_multiple)) or atr<=0: return current_stop
    if side==LONG:
        candidate=current_stop
        if r_multiple>=1.0: candidate=max(candidate,entry_price)
        if r_multiple>=2.0:
            refs=[x for x in (ema20,swing_price) if x is not None and math.isfinite(float(x))]
            if refs: candidate=max(candidate,min(refs)-0.25*atr)
        return float(min(candidate,peak_price-0.25*atr))
    if side==SHORT:
        candidate=current_stop
        if r_multiple>=1.0: candidate=min(candidate,entry_price)
        if r_multiple>=2.0:
            refs=[x for x in (ema20,swing_price) if x is not None and math.isfinite(float(x))]
            if refs: candidate=min(candidate,max(refs)+0.25*atr)
        return float(max(candidate,peak_price+0.25*atr))
    return current_stop


def enforce_portfolio_limits(candidates: Sequence[dict], max_positions: int=5, max_same_direction: int=3, max_correlated: int=2) -> list[dict]:
    selected=[]; dirs={LONG:0,SHORT:0}; groups={}
    for c in sorted(candidates,key=lambda x:abs(float(x.get("score",0))),reverse=True):
        sig=c.get("signal",FLAT); group=c.get("correlation_group",c.get("symbol",""))
        if sig not in (LONG,SHORT) or dirs[sig]>=max_same_direction or groups.get(group,0)>=max_correlated: continue
        selected.append(c); dirs[sig]+=1; groups[group]=groups.get(group,0)+1
        if len(selected)>=max_positions: break
    return selected


def rank_assets(metrics: pd.DataFrame, *, min_trades: int=30, expectancy_col: str="expectancy", stability_col: str="profit_factor") -> pd.DataFrame:
    required={"symbol","trades",expectancy_col,stability_col}
    if not required.issubset(metrics.columns): raise ValueError(f"missing columns: {sorted(required-metrics.columns)}")
    x=metrics[metrics["trades"]>=min_trades].copy()
    x["rank_score"]=x[expectancy_col].rank(pct=True)*.60+x[stability_col].rank(pct=True)*.40
    return x.sort_values("rank_score",ascending=False).reset_index(drop=True)
