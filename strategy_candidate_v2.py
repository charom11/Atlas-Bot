"""Offline Strategy Candidate V2.

This module is intentionally NOT wired into live execution.
It adds stateful hysteresis, fixed-risk sizing, cost-aware entry filtering,
portfolio exposure controls, and walk-forward-friendly asset ranking helpers.
No network calls, exchange clients, or order placement are performed here.
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
    c = df["close"].astype(float)
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    price = float(c.iloc[-1])
    atr_pct = float(atr.iloc[-1] / price) if price else 0.0
    realized = float(c.pct_change().rolling(20).std().iloc[-1])
    if not math.isfinite(realized): realized = 0.0
    spread = float((e50.iloc[-1] - e200.iloc[-1]) / price)
    slope = float((e50.iloc[-1] - e50.iloc[-11]) / price)
    if atr_pct >= HIGH_VOL_ATR_PCT or realized >= HIGH_VOL_REALIZED: return "HIGH_VOL", realized, atr_pct
    if abs(spread) < RANGE_SPREAD and abs(slope) < RANGE_SLOPE: return "RANGE", realized, atr_pct
    if spread > 0 and slope > 0: return "BULL_TREND", realized, atr_pct
    if spread < 0 and slope < 0: return "BEAR_TREND", realized, atr_pct
    return "TRANSITION", realized, atr_pct


def _core_scores(df: pd.DataFrame, btc_close: Optional[pd.Series], funding_rate: object, oi_change: object):
    c = df["close"].astype(float); v = df["volume"].astype(float); a = _atr(df); ap = float(a.iloc[-1] / c.iloc[-1]) if c.iloc[-1] else 0.0
    e20 = c.ewm(span=20, adjust=False).mean(); e50 = c.ewm(span=50, adjust=False).mean(); e200 = c.ewm(span=200, adjust=False).mean()
    trend = .45*_dir((c.iloc[-1]-e50.iloc[-1])/c.iloc[-1], .0015) + .35*_dir((e50.iloc[-1]-e200.iloc[-1])/c.iloc[-1], .0020) + .20*_dir((e20.iloc[-1]-e50.iloc[-1])/c.iloc[-1], .0010)
    r5=float(c.pct_change(5).iloc[-1]); r20=float(c.pct_change(20).iloc[-1]); r60=float(c.pct_change(60).iloc[-1])
    momentum=.20*_dir(r5,max(ap*.45,.001))+.45*_dir(r20,max(ap*.75,.002))+.35*_dir(r60,max(ap*1.5,.004))
    hi=c.astype(float).rolling(20).max().shift(1).iloc[-1]; lo=df["low"].astype(float).rolling(20).min().shift(1).iloc[-1]; vm=v.rolling(20).median().iloc[-1]
    vr=float(v.iloc[-1]/vm) if vm > 0 else 0.0; breakout=1.0 if np.isfinite(hi) and c.iloc[-1]>hi and vr>=1.10 else -1.0 if np.isfinite(lo) and c.iloc[-1]<lo and vr>=1.10 else 0.0
    parts=[]
    if btc_close is not None:
        b=pd.Series(btc_close).astype(float); n=min(len(c),len(b))
        if n>=30:
            parts.append(_dir(float(c.iloc[-n:].pct_change(20).iloc[-1]-b.iloc[-n:].pct_change(20).iloc[-1]),max(ap*.5,.002)))
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
    return score,float(trend),float(momentum),float(breakout),deriv,ap,vr,r20,r60


def generate_strategy_signal(df: pd.DataFrame, *, position: str = FLAT, btc_close: Optional[pd.Series] = None,
                              funding_rate: object = None, oi_change: object = None,
                              taker_fee_pct: float = .045, slippage_pct: float = .015,
                              spread_pct: float = .005, funding_buffer_pct: float = .010) -> dict:
    """Return a state-aware signal. Entry is stricter than hold/exit."""
    if not _valid(df):
        return StrategyDecision(FLAT,0,0,0,0,0,"INSUFFICIENT_DATA",0,0,0,0,("insufficient OHLCV history",)).to_dict()
    a=_atr(df); regime,vol,ap=_regime(df,a)
    score,trend,mom,brk,deriv,ap,vr,r20,r60=_core_scores(df,btc_close,funding_rate,oi_change)
    # Conservative all-in round-trip budget; funding is a buffer, not a prediction.
    cost=2*taker_fee_pct+2*slippage_pct+spread_pct+funding_buffer_pct
    # Expected favorable move proxy: horizon return measured in ATR units.
    expected_move_atr=abs(r20)/(ap if ap>1e-9 else 1.0)
    reasons=[f"regime={regime}",f"volume_ratio={vr:.2f}",f"expected_move_atr={expected_move_atr:.2f}"]
    if position == LONG and score <= EXIT_THRESHOLD: return StrategyDecision(EXIT,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["long hysteresis exit"])).to_dict()
    if position == SHORT and score >= -EXIT_THRESHOLD: return StrategyDecision(EXIT,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["short hysteresis exit"])).to_dict()
    if position in (LONG,SHORT): return StrategyDecision(position,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["position held by hysteresis"])).to_dict()
    if regime in ("HIGH_VOL","RANGE"):
        return StrategyDecision(FLAT,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["regime entry gate"])).to_dict()
    edge_ok=expected_move_atr*ap > cost
    if not edge_ok: reasons.append("expected move does not clear conservative cost budget")
    if regime=="BULL_TREND" and score>=ENTRY_THRESHOLD and trend>=MIN_TREND_CONFIRM and mom>=MIN_MOMENTUM_CONFIRM and edge_ok:
        return StrategyDecision(LONG,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["long entry confirmed"])).to_dict()
    if regime=="BEAR_TREND" and score<=-ENTRY_THRESHOLD and trend<=-MIN_TREND_CONFIRM and mom<=-MIN_MOMENTUM_CONFIRM and edge_ok:
        return StrategyDecision(SHORT,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["short entry confirmed"])).to_dict()
    if regime=="TRANSITION" and abs(score)>=TRANSITION_ENTRY_THRESHOLD and abs(trend)>=.50 and abs(mom)>=.45 and edge_ok:
        return StrategyDecision(LONG if score>0 else SHORT,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["transition entry confirmed"])).to_dict()
    return StrategyDecision(FLAT,score,trend,mom,brk,deriv,regime,vol,ap,expected_move_atr,cost,tuple(reasons+["entry confirmation incomplete"])).to_dict()


def risk_based_notional(equity: float, risk_pct: float, entry_price: float, stop_price: float,
                        max_leverage: float = 50.0, max_notional_pct: float = 1.0) -> float:
    """Size by loss at stop, then cap leverage/exposure. No exchange calls."""
    if not all(math.isfinite(float(x)) for x in (equity,risk_pct,entry_price,stop_price)) or equity<=0 or risk_pct<=0 or entry_price<=0 or stop_price<=0: return 0.0
    distance=abs(entry_price-stop_price)/entry_price
    if distance<=1e-9: return 0.0
    risk_budget=equity*risk_pct
    notional=risk_budget/distance
    return max(0.0,min(notional,equity*max_leverage,equity*max_notional_pct))


def choose_leverage(atr_pct: float, target_risk_pct: float = .0035, stop_atr: float = 1.5,
                    max_leverage: float = 50.0, min_leverage: float = 1.0) -> float:
    """Return a conservative leverage cap implied by stop distance."""
    if not math.isfinite(atr_pct) or atr_pct<=0: return min_leverage
    lev=target_risk_pct/(atr_pct*stop_atr)
    return float(np.clip(lev,min_leverage,max_leverage))


def rank_assets(metrics: pd.DataFrame, *, min_trades: int = 30, lookback_col: str = "expectancy",
                stability_col: str = "profit_factor") -> pd.DataFrame:
    """Rank only information supplied by a walk-forward training window."""
    required={"symbol","trades",lookback_col,stability_col}
    if not required.issubset(metrics.columns): raise ValueError(f"missing columns: {sorted(required-metrics.columns)}")
    x=metrics.copy(); x=x[x["trades"]>=min_trades].copy()
    x["rank_score"]=x[lookback_col].rank(pct=True)*.60+x[stability_col].rank(pct=True)*.40
    return x.sort_values("rank_score",ascending=False).reset_index(drop=True)


def enforce_portfolio_limits(candidates: Sequence[dict], max_positions: int = 5, max_same_direction: int = 3,
                             max_correlated: int = 2) -> list[dict]:
    """Select highest-score candidates while limiting directional/concentration risk.

    Candidates may contain score, signal, and correlation_group. This is a
    deterministic portfolio layer intended for offline simulation.
    """
    selected=[]; dirs={LONG:0,SHORT:0}; groups={}
    for c in sorted(candidates,key=lambda x:abs(float(x.get("score",0))),reverse=True):
        sig=c.get("signal",FLAT); group=c.get("correlation_group",c.get("symbol",""))
        if sig not in (LONG,SHORT): continue
        if dirs[sig]>=max_same_direction: continue
        if groups.get(group,0)>=max_correlated: continue
        selected.append(c); dirs[sig]+=1; groups[group]=groups.get(group,0)+1
        if len(selected)>=max_positions: break
    return selected
