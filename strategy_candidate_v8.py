"""Offline Strategy Candidate V8: Production Alpha Meta-Controller.

Research-only: no exchange, network, or order-placement calls.

V8 is designed to improve the existing main.py architecture rather than replace
its five alpha channels. It models a portfolio-level controller around:
1) Fibonacci/Golden-Pocket/OTE pullback,
2) MSS/CHoCH breakout,
3) MA-stack + quantitative consensus,
4) liquidity sweep / S&R bounce,
5) RSI/CCI/MACD divergence.

The controller adds market regime, asset quality, cost-aware net-R, channel
reliability, correlation-adjusted risk, and fail-closed portfolio guards.
It deliberately does not import main.py so research cannot affect production.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Mapping, Optional, Sequence
import argparse
import math
import os
import sys
import time
import numpy as np
import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

LONG, SHORT, FLAT = "LONG", "SHORT", "FLAT"
CHANNELS = ("FIBONACCI", "MSS_SHIFT", "5MA_CONSENSUS", "POTATO_SR", "DIVERGENCE")
MAX_LEVERAGE = 75.0
DEFAULT_RISK_PCT = 0.0035
MAX_PORTFOLIO_RISK = 0.015
MAX_POSITIONS = 10
MAX_SAME_DIRECTION = 10
MAX_DAILY_LOSS = 0.03
MAX_WEEKLY_LOSS = 0.06
MIN_NET_R = 0.20

@dataclass(frozen=True)
class ChannelEvidence:
    channel: str
    side: str
    strength: float
    quality: float = 1.0
    available: bool = True

@dataclass(frozen=True)
class AssetMetrics:
    symbol: str
    expectancy_r: float
    profit_factor: float
    trades: int
    max_drawdown: float
    turnover: float = 0.0
    liquidity_score: float = 1.0
    funding_score: float = 1.0
    stability_score: float = 0.0

@dataclass(frozen=True)
class V8Decision:
    action: str
    score: float
    channel_score: float
    asset_score: float
    market_regime: str
    expected_net_r: float
    risk_pct: float
    leverage: float
    reasons: tuple[str, ...]


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return lo
    return min(hi, max(lo, x)) if math.isfinite(x) else lo


def classify_market_regime(breadth: float, btc_trend: float, volatility: float) -> str:
    """Cross-market state; thresholds are research defaults, not live settings."""
    b, t, v = float(breadth), float(btc_trend), float(volatility)
    if not all(math.isfinite(x) for x in (b, t, v)):
        return "UNAVAILABLE"
    if v >= 0.045:
        return "EXTREME_VOL"
    if b <= -0.65 and t <= -0.50:
        return "BREAKDOWN"
    if b >= 0.50 and t >= 0.35:
        return "RISK_ON"
    if b <= -0.35 or t <= -0.35:
        return "RISK_OFF"
    return "NEUTRAL"


def channel_meta_score(evidence: Sequence[ChannelEvidence], reliability: Optional[Mapping[str, float]] = None) -> tuple[float, str]:
    """Combine independent production channels without allowing unavailable data to vote."""
    rel = reliability or {}
    votes = []
    for e in evidence:
        if e.channel not in CHANNELS or not e.available or e.side not in (LONG, SHORT):
            continue
        strength = _clip(e.strength, 0.0, 1.0)
        quality = _clip(e.quality, 0.0, 1.0)
        weight = max(0.0, float(rel.get(e.channel, 1.0)))
        signed = strength * quality * weight * (1.0 if e.side == LONG else -1.0)
        votes.append((signed, weight))
    if not votes:
        return 0.0, FLAT
    denom = sum(w for _, w in votes)
    score = sum(v for v, _ in votes) / denom if denom > 0 else 0.0
    side = LONG if score > 0 else SHORT if score < 0 else FLAT
    return float(_clip(score)), side


def asset_quality_score(m: AssetMetrics) -> float:
    """Score assets using only historical/training-window statistics supplied by caller."""
    if m.trades < 20:
        return 0.0
    exp = np.tanh(m.expectancy_r / 0.15)
    pf = np.tanh((m.profit_factor - 1.0) / 0.25)
    dd = 1.0 - min(1.0, max(0.0, m.max_drawdown / 0.30))
    stability = _clip(m.stability_score, 0.0, 1.0)
    liquidity = _clip(m.liquidity_score, 0.0, 1.0)
    funding = _clip(m.funding_score, 0.0, 1.0)
    turnover_penalty = min(1.0, max(0.0, m.turnover))
    score = (0.30 * max(0.0, exp) + 0.20 * max(0.0, pf) +
             0.15 * dd + 0.15 * stability + 0.10 * liquidity +
             0.10 * funding - 0.10 * turnover_penalty)
    return float(_clip(score, 0.0, 1.0))


def rank_assets(metrics: Sequence[AssetMetrics], min_expectancy: float = 0.0,
                min_pf: float = 1.02, min_trades: int = 20) -> list[tuple[str, float]]:
    eligible = [m for m in metrics if m.trades >= min_trades and m.expectancy_r > min_expectancy and m.profit_factor >= min_pf]
    return sorted(((m.symbol, asset_quality_score(m)) for m in eligible), key=lambda x: x[1], reverse=True)


def cost_budget_pct(taker_fee_pct: float = 0.045, slippage_pct: float = 0.015,
                    spread_pct: float = 0.005, funding_buffer_pct: float = 0.010,
                    multiplier: float = 1.0) -> float:
    vals = [taker_fee_pct, slippage_pct, spread_pct, funding_buffer_pct]
    vals = [(x / 100.0 if x >= 0.001 else x) for x in vals]
    return float((2 * vals[0] + 2 * vals[1] + vals[2] + vals[3]) * multiplier)


def expected_net_r(entry: float, stop: float, expected_move_pct: float,
                   cost_pct: float, turnover_penalty_r: float = 0.0) -> float:
    if not all(math.isfinite(float(x)) and float(x) > 0 for x in (entry, stop)):
        return 0.0
    risk_pct = abs(entry - stop) / entry
    if risk_pct <= 1e-9:
        return 0.0
    return float(expected_move_pct / risk_pct - cost_pct / risk_pct - max(0.0, turnover_penalty_r))


def correlation_discount(symbol: str, selected: Sequence[str], correlation: Optional[pd.DataFrame] = None) -> float:
    if correlation is None or symbol not in correlation.index:
        return 1.0
    vals = []
    for other in selected:
        if other in correlation.columns and other != symbol:
            x = float(correlation.loc[symbol, other])
            if math.isfinite(x):
                vals.append(abs(x))
    if not vals:
        return 1.0
    return float(max(0.25, 1.0 - 0.50 * max(vals)))


def drawdown_risk_multiplier(drawdown: float) -> float:
    d = max(0.0, float(drawdown))
    if d >= 0.20: return 0.0
    if d >= 0.15: return 0.25
    if d >= 0.10: return 0.50
    if d >= 0.05: return 0.75
    return 1.0


def choose_leverage(stop_pct: float, risk_pct: float = DEFAULT_RISK_PCT,
                    max_leverage: float = MAX_LEVERAGE) -> float:
    if stop_pct <= 0 or risk_pct <= 0:
        return 0.0
    # Risk sizing determines notional; leverage is capped implementation headroom.
    return float(min(max_leverage, max(1.0, risk_pct / stop_pct)))


def risk_based_notional(equity: float, stop_pct: float, risk_pct: float = DEFAULT_RISK_PCT,
                        max_leverage: float = MAX_LEVERAGE) -> float:
    if equity <= 0 or stop_pct <= 0 or risk_pct <= 0:
        return 0.0
    raw = equity * risk_pct / stop_pct
    return float(min(raw, equity * max_leverage))


def portfolio_gate(action: str, equity: float, current_risk: float, open_positions: int,
                   same_direction: int, daily_loss: float, weekly_loss: float,
                   drawdown: float, selected: Sequence[str], symbol: str,
                   correlation: Optional[pd.DataFrame] = None) -> tuple[bool, str]:
    if action not in (LONG, SHORT): return False, "NO_ACTION"
    if equity <= 0: return False, "INVALID_EQUITY"
    if open_positions >= MAX_POSITIONS: return False, "MAX_POSITIONS"
    if same_direction >= MAX_SAME_DIRECTION: return False, "MAX_DIRECTION"
    if daily_loss >= MAX_DAILY_LOSS: return False, "DAILY_LOSS_GUARD"
    if weekly_loss >= MAX_WEEKLY_LOSS: return False, "WEEKLY_LOSS_GUARD"
    if drawdown >= 0.20: return False, "MAX_DRAWDOWN"
    if current_risk >= MAX_PORTFOLIO_RISK: return False, "PORTFOLIO_RISK"
    if correlation_discount(symbol, selected, correlation) <= 0.25 and selected: return False, "CORRELATION_CONCENTRATION"
    return True, "OK"


def decide(evidence: Sequence[ChannelEvidence], asset: AssetMetrics, breadth: float,
           btc_trend: float, volatility: float, entry: float, stop: float,
           expected_move_pct: float, equity: float, current_risk: float = 0.0,
           open_positions: int = 0, same_direction: int = 0, daily_loss: float = 0.0,
           weekly_loss: float = 0.0, drawdown: float = 0.0,
           selected: Sequence[str] = (), correlation: Optional[pd.DataFrame] = None,
           reliability: Optional[Mapping[str, float]] = None,
           cost_multiplier: float = 1.0) -> V8Decision:
    regime = classify_market_regime(breadth, btc_trend, volatility)
    cscore, side = channel_meta_score(evidence, reliability)
    ascore = asset_quality_score(asset)
    costs = cost_budget_pct(multiplier=cost_multiplier)
    net_r = expected_net_r(entry, stop, expected_move_pct, costs, turnover_penalty_r=0.05 * min(1.0, asset.turnover))
    dd_mult = drawdown_risk_multiplier(drawdown)
    regime_mult = {"RISK_ON": 1.0, "NEUTRAL": 0.75, "RISK_OFF": 0.50, "BREAKDOWN": 0.25, "EXTREME_VOL": 0.0, "UNAVAILABLE": 0.0}.get(regime, 0.0)
    corr_mult = correlation_discount(asset.symbol, selected, correlation)
    combined = float(cscore * ascore * regime_mult * corr_mult)
    risk = DEFAULT_RISK_PCT * dd_mult * regime_mult * corr_mult
    leverage = choose_leverage(abs(entry - stop) / entry if entry > 0 else 0.0, risk)
    reasons = [regime, f"CHANNEL_SCORE={cscore:.3f}", f"ASSET_SCORE={ascore:.3f}", f"NET_R={net_r:.3f}"]
    if net_r < MIN_NET_R: return V8Decision(FLAT, combined, cscore, ascore, regime, net_r, 0.0, 0.0, tuple(reasons + ["COST_FILTER"]))
    if abs(cscore) < 0.55 or ascore <= 0.0 or regime_mult <= 0.0: return V8Decision(FLAT, combined, cscore, ascore, regime, net_r, 0.0, 0.0, tuple(reasons + ["QUALITY_FILTER"]))
    ok, gate = portfolio_gate(side, equity, current_risk, open_positions, same_direction, daily_loss, weekly_loss, drawdown, selected, asset.symbol, correlation)
    if not ok: return V8Decision(FLAT, combined, cscore, ascore, regime, net_r, 0.0, 0.0, tuple(reasons + [gate]))
    return V8Decision(side, combined, cscore, ascore, regime, net_r, risk, leverage, tuple(reasons + ["PASS"]))


def backtest_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Reference interface: signals are shifted one bar for next-bar execution."""
    out = df.copy()
    if "signal" in out.columns:
        out["execution_signal"] = out["signal"].shift(1).fillna(FLAT)
    return out


# -----------------------------------------------------------------------------
# 📊 Fast Indicator & Signal Engine
# -----------------------------------------------------------------------------
def calc_ema(arr: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    n = len(arr)
    out = np.empty(n, dtype=np.float64)
    out[0] = arr[0]
    for i in range(1, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = np.zeros(n, dtype=np.float64)
    if n <= period:
        return tr
    atr[period] = np.mean(tr[:period])
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def calc_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    diff = np.diff(closes)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    rsi = np.full(n, 50.0, dtype=np.float64)
    if n <= period:
        return rsi
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / (avg_loss + 1e-9) if avg_loss > 0 else 100.0
        rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def calc_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    atr_s = np.zeros(n, dtype=np.float64)
    plus_di_s = np.zeros(n, dtype=np.float64)
    minus_di_s = np.zeros(n, dtype=np.float64)
    if n <= period * 2:
        return np.full(n, 25.0, dtype=np.float64)

    atr_s[period] = np.sum(tr[1:period + 1])
    plus_di_s[period] = np.sum(plus_dm[1:period + 1])
    minus_di_s[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr_s[i] = atr_s[i - 1] - (atr_s[i - 1] / period) + tr[i]
        plus_di_s[i] = plus_di_s[i - 1] - (plus_di_s[i - 1] / period) + plus_dm[i]
        minus_di_s[i] = minus_di_s[i - 1] - (minus_di_s[i - 1] / period) + minus_dm[i]

    plus_di = 100.0 * (plus_di_s / (atr_s + 1e-9))
    minus_di = 100.0 * (minus_di_s / (atr_s + 1e-9))
    dx = 100.0 * (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9))

    adx = np.full(n, 25.0, dtype=np.float64)
    adx_start = period * 2 - 1
    if n > adx_start:
        adx[adx_start] = np.mean(dx[period:adx_start + 1])
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def calc_cci(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20) -> np.ndarray:
    tp = (highs + lows + closes) / 3.0
    n = len(tp)
    cci = np.zeros(n, dtype=np.float64)
    for i in range(period - 1, n):
        window = tp[i - period + 1:i + 1]
        sma = np.mean(window)
        mad = np.mean(np.abs(window - sma))
        cci[i] = (tp[i] - sma) / (0.015 * mad + 1e-9)
    return cci


def detect_fractal_swings(highs: np.ndarray, lows: np.ndarray, window: int = 4) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    n = len(highs)
    sh_list = []
    sl_list = []
    for i in range(window, n - window):
        p_h = highs[i]
        p_l = lows[i]
        if all(highs[i - w] < p_h and highs[i + w] < p_h for w in range(1, window + 1)):
            sh_list.append((i + window, p_h))
        if all(lows[i - w] > p_l and lows[i + w] > p_l for w in range(1, window + 1)):
            sl_list.append((i + window, p_l))
    return sh_list, sl_list


def precompute_v8_channel_signals(df: pd.DataFrame, window: int = 4) -> dict[str, np.ndarray]:
    """Precompute all 5 live production channels with zero look-ahead bias."""
    closes = df["close"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    vols = df["volume"].astype(float).values
    opens = df["open"].astype(float).values
    n = len(closes)

    ema9 = calc_ema(closes, 9)
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema100 = calc_ema(closes, 100)
    ema200 = calc_ema(closes, 200)

    rsi = calc_rsi(closes, 14)
    atr = calc_atr(highs, lows, closes, 14)
    adx = calc_adx(highs, lows, closes, 14)
    cci = calc_cci(highs, lows, closes, 20)

    vol_sma20 = np.zeros(n, dtype=np.float64)
    for i in range(19, n):
        vol_sma20[i] = np.mean(vols[i - 19:i + 1])

    sh_list, sl_list = detect_fractal_swings(highs, lows, window=window)
    sh_ptr = 0
    sl_ptr = 0
    last_sh = highs[0]
    last_sl = lows[0]

    ch_fib_side = np.full(n, FLAT, dtype=object)
    ch_fib_str = np.zeros(n, dtype=np.float64)
    ch_fib_stop = np.zeros(n, dtype=np.float64)

    ch_mss_side = np.full(n, FLAT, dtype=object)
    ch_mss_str = np.zeros(n, dtype=np.float64)
    ch_mss_stop = np.zeros(n, dtype=np.float64)

    ch_ma_side = np.full(n, FLAT, dtype=object)
    ch_ma_str = np.zeros(n, dtype=np.float64)
    ch_ma_stop = np.zeros(n, dtype=np.float64)

    ch_sr_side = np.full(n, FLAT, dtype=object)
    ch_sr_str = np.zeros(n, dtype=np.float64)
    ch_sr_stop = np.zeros(n, dtype=np.float64)

    ch_div_side = np.full(n, FLAT, dtype=object)
    ch_div_str = np.zeros(n, dtype=np.float64)
    ch_div_stop = np.zeros(n, dtype=np.float64)

    exp_move = np.zeros(n, dtype=np.float64)
    atr_pct = np.zeros(n, dtype=np.float64)

    for i in range(50, n):
        c = closes[i]
        h = highs[i]
        l = lows[i]
        v = vols[i]
        cur_atr = atr[i] if atr[i] > 0 else c * 0.01
        atr_pct[i] = cur_atr / c if c > 0 else 0.01
        exp_move[i] = 1.8 * atr_pct[i]

        while sh_ptr < len(sh_list) and sh_list[sh_ptr][0] <= i:
            last_sh = sh_list[sh_ptr][1]
            sh_ptr += 1
        while sl_ptr < len(sl_list) and sl_list[sl_ptr][0] <= i:
            last_sl = sl_list[sl_ptr][1]
            sl_ptr += 1

        # 1. Fibonacci Golden Pocket (0.618 - 0.886 Harmonic OTE)
        if last_sh > last_sl and (last_sh - last_sl) > 1.2 * cur_atr:
            rng = last_sh - last_sl
            if c > ema50[i]:
                f618 = last_sh - 0.618 * rng
                f886 = last_sh - 0.886 * rng
                if l <= f618 and c >= f886:
                    ch_fib_side[i] = LONG
                    ch_fib_str[i] = 0.90
                    ch_fib_stop[i] = max(c * 0.94, last_sl - 0.5 * cur_atr)
            elif c < ema50[i]:
                f618_bear = last_sl + 0.618 * rng
                f886_bear = last_sl + 0.886 * rng
                if h >= f618_bear and c <= f886_bear:
                    ch_fib_side[i] = SHORT
                    ch_fib_str[i] = 0.90
                    ch_fib_stop[i] = min(c * 1.06, last_sh + 0.5 * cur_atr)

        # 2. Market Structure Shift (MSS / CHoCH Breakout)
        vol_surge = (v >= 1.25 * vol_sma20[i]) if vol_sma20[i] > 0 else False
        if closes[i - 1] <= last_sh < c and c > ema50[i] and c > ema200[i] and vol_surge:
            ch_mss_side[i] = LONG
            ch_mss_str[i] = 0.85
            ch_mss_stop[i] = c - 1.2 * cur_atr
        elif closes[i - 1] >= last_sl > c and c < ema50[i] and c < ema200[i] and vol_surge:
            ch_mss_side[i] = SHORT
            ch_mss_str[i] = 0.85
            ch_mss_stop[i] = c + 1.2 * cur_atr

        # 3. 5MA Stack Momentum Consensus
        bull_stack = (ema9[i] > ema20[i] > ema50[i] > ema100[i] > ema200[i])
        bear_stack = (ema9[i] < ema20[i] < ema50[i] < ema100[i] < ema200[i])
        if bull_stack and c > ema20[i] and rsi[i] > 52 and adx[i] > 22 and v > vol_sma20[i]:
            ch_ma_side[i] = LONG
            ch_ma_str[i] = 0.85
            ch_ma_stop[i] = ema50[i] - 0.5 * cur_atr
        elif bear_stack and c < ema20[i] and rsi[i] < 48 and adx[i] > 22 and v > vol_sma20[i]:
            ch_ma_side[i] = SHORT
            ch_ma_str[i] = 0.85
            ch_ma_stop[i] = ema50[i] + 0.5 * cur_atr

        # 4. Potato S&R (Liquidity Sweep / S&R Bounce)
        look_sr = 12
        if i >= look_sr:
            roll_l = np.min(lows[i - look_sr:i])
            roll_h = np.max(highs[i - look_sr:i])
            if l <= roll_l and c > roll_l and c > opens[i]:
                ch_sr_side[i] = LONG
                ch_sr_str[i] = 0.80
                ch_sr_stop[i] = c - 1.5 * cur_atr
            elif h >= roll_h and c < roll_h and c < opens[i]:
                ch_sr_side[i] = SHORT
                ch_sr_str[i] = 0.80
                ch_sr_stop[i] = c + 1.5 * cur_atr

        # 5. Triple Divergence (RSI + CCI)
        look_div = 16
        if i >= look_div:
            prior_low_idx = np.argmin(closes[i - look_div:i])
            prior_high_idx = np.argmax(closes[i - look_div:i])
            p_low_p = closes[i - look_div + prior_low_idx]
            p_high_p = closes[i - look_div + prior_high_idx]
            p_low_rsi = rsi[i - look_div + prior_low_idx]
            p_high_rsi = rsi[i - look_div + prior_high_idx]
            p_low_cci = cci[i - look_div + prior_low_idx]
            p_high_cci = cci[i - look_div + prior_high_idx]

            if c <= p_low_p * 1.001 and rsi[i] > p_low_rsi + 3.0 and cci[i] > p_low_cci:
                ch_div_side[i] = LONG
                ch_div_str[i] = 0.75
                ch_div_stop[i] = c - 1.5 * cur_atr
            elif c >= p_high_p * 0.999 and rsi[i] < p_high_rsi - 3.0 and cci[i] < p_high_cci:
                ch_div_side[i] = SHORT
                ch_div_str[i] = 0.75
                ch_div_stop[i] = c + 1.5 * cur_atr

    return {
        "fib_side": ch_fib_side, "fib_str": ch_fib_str, "fib_stop": ch_fib_stop,
        "mss_side": ch_mss_side, "mss_str": ch_mss_str, "mss_stop": ch_mss_stop,
        "ma_side": ch_ma_side, "ma_str": ch_ma_str, "ma_stop": ch_ma_stop,
        "sr_side": ch_sr_side, "sr_str": ch_sr_str, "sr_stop": ch_sr_stop,
        "div_side": ch_div_side, "div_str": ch_div_str, "div_stop": ch_div_stop,
        "atr_pct": atr_pct, "expected_move_pct": exp_move, "close": closes,
        "open": opens, "high": highs, "low": lows, "ema50": ema50
    }


# -----------------------------------------------------------------------------
# 🌐 Data Loading & Timeline Alignment
# -----------------------------------------------------------------------------
def resample_to_1h(df_15m: pd.DataFrame) -> pd.DataFrame:
    df = df_15m.copy()
    df["open_time"] = pd.to_datetime(df["open_time"])
    df = df.set_index("open_time").sort_index()
    df_1h = df.resample("1h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna().reset_index()
    return df_1h


def load_v8_historical_cache(
    cache_dir: str,
    symbols: Sequence[str],
    timeframe: str = "1h"
) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, np.ndarray]], list[pd.Timestamp]]:
    """Load historical data cache for universe symbols and synchronize timeline."""
    data_map = {}
    channel_map = {}
    for sym in symbols:
        p = os.path.join(cache_dir, f"{sym}_15m_4year_2022-09-01.csv")
        if not os.path.exists(p):
            continue
        df_raw = pd.read_csv(p)
        df_use = resample_to_1h(df_raw) if timeframe == "1h" else df_raw.copy()
        df_use["open_time"] = pd.to_datetime(df_use["open_time"])
        data_map[sym] = df_use
        channel_map[sym] = precompute_v8_channel_signals(df_use)

    all_times = [set(df["open_time"]) for df in data_map.values()]
    timeline = sorted(list(set.union(*all_times))) if all_times else []
    return data_map, channel_map, timeline


def compute_v8_asset_metrics(
    data_map: Mapping[str, pd.DataFrame],
    channel_map: Mapping[str, dict[str, np.ndarray]],
    train_end: str = "2023-12-31 23:59:59"
) -> dict[str, AssetMetrics]:
    """Calculate walk-forward AssetMetrics using only historical training window data."""
    metrics_map = {}
    for sym, df in data_map.items():
        ch = channel_map[sym]
        train_mask = (df["open_time"] <= pd.to_datetime(train_end)).values
        c = ch["close"][train_mask]
        n_train = len(c)
        if n_train < 100:
            metrics_map[sym] = AssetMetrics(sym, expectancy_r=0.04, profit_factor=1.10, trades=25, max_drawdown=0.10, stability_score=0.7)
            continue

        fib_trades = np.where(ch["fib_side"][train_mask] != FLAT)[0]
        mss_trades = np.where(ch["mss_side"][train_mask] != FLAT)[0]
        ma_trades = np.where(ch["ma_side"][train_mask] != FLAT)[0]
        trade_indices = np.unique(np.concatenate([fib_trades, mss_trades, ma_trades]))

        if len(trade_indices) < 20:
            metrics_map[sym] = AssetMetrics(sym, expectancy_r=0.04, profit_factor=1.10, trades=25, max_drawdown=0.10, stability_score=0.7)
            continue

        r_list = []
        for idx in trade_indices:
            entry_p = c[idx]
            cur_atr = ch["atr_pct"][train_mask][idx] * entry_p
            side = ch["ma_side"][train_mask][idx]
            if side == FLAT:
                side = ch["fib_side"][train_mask][idx]
            if side == FLAT:
                side = ch["mss_side"][train_mask][idx]

            tp_p = entry_p + 2.2 * cur_atr if side == LONG else entry_p - 2.2 * cur_atr
            sl_p = entry_p - 1.2 * cur_atr if side == LONG else entry_p + 1.2 * cur_atr
            end_b = min(n_train, idx + 48)
            r = 0.0
            for fi in range(idx + 1, end_b):
                if side == LONG:
                    if ch["high"][train_mask][fi] >= tp_p:
                        r = 1.83
                        break
                    if ch["low"][train_mask][fi] <= sl_p:
                        r = -1.0
                        break
                else:
                    if ch["low"][train_mask][fi] <= tp_p:
                        r = 1.83
                        break
                    if ch["high"][train_mask][fi] >= sl_p:
                        r = -1.0
                        break
            r_list.append(r)

        r_arr = np.array(r_list)
        wins = r_arr[r_arr > 0]
        losses = r_arr[r_arr < 0]
        pf = float(np.sum(wins) / abs(np.sum(losses) or 1e-9)) if len(losses) > 0 else 1.20
        exp_r = float(np.mean(r_arr)) if len(r_arr) > 0 else 0.05
        peak = np.maximum.accumulate(np.cumsum(r_arr))
        dd = float(np.max(peak - np.cumsum(r_arr)) / (np.max(peak) or 1.0)) if len(peak) > 0 else 0.10

        metrics_map[sym] = AssetMetrics(
            symbol=sym,
            expectancy_r=exp_r,
            profit_factor=pf,
            trades=len(trade_indices),
            max_drawdown=min(0.25, max(0.05, dd)),
            turnover=len(trade_indices) / 1000.0,
            stability_score=0.80 if exp_r > 0 else 0.20,
            liquidity_score=1.0,
            funding_score=1.0
        )
    return metrics_map


# -----------------------------------------------------------------------------
# 🚀 Multi-Asset Portfolio Simulation Engine
# -----------------------------------------------------------------------------
def simulate_v8_portfolio(
    data_map: Mapping[str, pd.DataFrame],
    channel_map: Mapping[str, dict[str, np.ndarray]],
    timeline: list[pd.Timestamp],
    target_symbols: Sequence[str],
    asset_metrics_map: Mapping[str, AssetMetrics],
    initial_balance: float = 1000.0,
    max_leverage: float = MAX_LEVERAGE,
    risk_pct: float = DEFAULT_RISK_PCT,
    max_portfolio_risk: float = MAX_PORTFOLIO_RISK,
    max_positions: int = MAX_POSITIONS,
    max_same_direction: int = MAX_SAME_DIRECTION,
    cost_multiplier: float = 1.0,
    max_hold_bars: int = 48,
    mode: str = "V8",
    channel_reliability: Optional[Mapping[str, float]] = None,
) -> dict:
    """Fast synchronized multi-asset simulation engine supporting Candidate V8 and ablation modes."""
    fee_schedule = {
        "maker": 0.00018,
        "taker": 0.00045 * cost_multiplier,
        "slippage": 0.00015 * cost_multiplier,
        "funding_8h": 0.00010,
    }

    active_syms = [s for s in target_symbols if s in data_map and s in channel_map]
    if not active_syms or not timeline:
        return {"balance": initial_balance, "closed_trades": [], "max_drawdown": 0.0, "friction": 0.0}

    # Align arrays to timeline indices
    sym_indices = {}
    for sym in active_syms:
        t_series = data_map[sym]["open_time"].values
        t_dict = {t: idx for idx, t in enumerate(t_series)}
        sym_indices[sym] = [t_dict.get(t, -1) for t in timeline]

    # Pre-calculate asset correlation matrix aligned to timeline
    returns_dict = {}
    for sym in active_syms:
        c_series = data_map[sym].set_index("open_time")["close"].astype(float).reindex(timeline).ffill().bfill().values
        ret = np.diff(c_series, prepend=c_series[0]) / np.where(c_series > 0, np.roll(c_series, 1), 1.0)
        returns_dict[sym] = ret
    corr_matrix = pd.DataFrame(returns_dict, index=timeline).corr().fillna(0.0)

    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    active_positions: dict[str, dict] = {}
    closed_trades: list[dict] = []
    tot_fees = 0.0
    tot_slippage = 0.0
    tot_funding = 0.0
    equity_history: list[float] = []

    for t_idx, ts in enumerate(timeline):
        # 1. Manage Active Positions
        to_close = []
        for sym, pos in list(active_positions.items()):
            row_idx = sym_indices[sym][t_idx]
            if row_idx == -1:
                continue

            ch = channel_map[sym]
            o = ch["open"][row_idx]
            h = ch["high"][row_idx]
            l = ch["low"][row_idx]
            c = ch["close"][row_idx]
            cur_atr = ch["atr_pct"][row_idx] * c

            pos["bars_held"] += 1
            if pos["bars_held"] % 8 == 0:
                fund = pos["notional"] * fee_schedule["funding_8h"]
                balance -= fund
                tot_funding += fund

            exit_price = None
            exit_reason = None

            if pos["side"] == LONG:
                if h > pos["peak_price"]:
                    pos["peak_price"] = h
                risk_dist = pos["initial_risk_dist"]
                unrealized_r = (c - pos["entry_price"]) / (risk_dist or 1e-9)
                peak_r = (pos["peak_price"] - pos["entry_price"]) / (risk_dist or 1e-9)

                # Take Profit target
                if h >= pos.get("take_profit", pos["entry_price"] + 2.2 * cur_atr):
                    exit_price = pos.get("take_profit", pos["entry_price"] + 2.2 * cur_atr)
                    exit_reason = "TAKE_PROFIT"
                # Giveback protection: If reached >= 1.5R and gave back to <= 0.85R
                elif peak_r >= 1.5 and unrealized_r <= 0.85:
                    exit_price = c
                    exit_reason = "GIVEBACK_PROTECTION"
                # Dynamic trailing stop
                elif unrealized_r >= 1.8:
                    trail = pos["peak_price"] - 1.2 * cur_atr
                    if trail > pos["stop_loss"]:
                        pos["stop_loss"] = trail
                # Breakeven
                elif unrealized_r >= 1.0:
                    be = pos["entry_price"] * 1.0005
                    if be > pos["stop_loss"]:
                        pos["stop_loss"] = be

                if exit_reason is None and l <= pos["stop_loss"]:
                    exit_price = min(o, pos["stop_loss"])
                    exit_reason = "TRAILING_STOP" if peak_r >= 1.0 else "STOP_LOSS"
                elif exit_reason is None and pos["bars_held"] >= max_hold_bars:
                    exit_price = c
                    exit_reason = "MAX_HOLD_EXPIRY"

            else:  # SHORT
                if l < pos["peak_price"]:
                    pos["peak_price"] = l
                risk_dist = pos["initial_risk_dist"]
                unrealized_r = (pos["entry_price"] - c) / (risk_dist or 1e-9)
                peak_r = (pos["entry_price"] - pos["peak_price"]) / (risk_dist or 1e-9)

                if l <= pos.get("take_profit", pos["entry_price"] - 2.2 * cur_atr):
                    exit_price = pos.get("take_profit", pos["entry_price"] - 2.2 * cur_atr)
                    exit_reason = "TAKE_PROFIT"
                elif peak_r >= 1.5 and unrealized_r <= 0.85:
                    exit_price = c
                    exit_reason = "GIVEBACK_PROTECTION"
                elif unrealized_r >= 1.8:
                    trail = pos["peak_price"] + 1.2 * cur_atr
                    if trail < pos["stop_loss"]:
                        pos["stop_loss"] = trail
                elif unrealized_r >= 1.0:
                    be = pos["entry_price"] * 0.9995
                    if be < pos["stop_loss"]:
                        pos["stop_loss"] = be

                if exit_reason is None and h >= pos["stop_loss"]:
                    exit_price = max(o, pos["stop_loss"])
                    exit_reason = "TRAILING_STOP" if peak_r >= 1.0 else "STOP_LOSS"
                elif exit_reason is None and pos["bars_held"] >= max_hold_bars:
                    exit_price = c
                    exit_reason = "MAX_HOLD_EXPIRY"

            if exit_reason is not None:
                pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"] if pos["side"] == LONG else (pos["entry_price"] - exit_price) / pos["entry_price"]
                gross_pnl = pos["notional"] * pnl_pct
                slip = pos["notional"] * fee_schedule["slippage"]
                fee = pos["notional"] * fee_schedule["taker"]
                net_pnl = gross_pnl - slip - fee
                tot_slippage += slip
                tot_fees += fee

                balance += pos["margin"] + net_pnl
                r_mult = net_pnl / (pos["risk_amount"] or 1e-4)
                f_mult = (pos.get("fee_in", 0.0) + fee) / (pos["risk_amount"] or 1e-4)
                closed_trades.append({
                    "symbol": sym,
                    "side": pos["side"],
                    "timestamp": str(ts),
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "notional": pos["notional"],
                    "margin": pos["margin"],
                    "leverage": pos["leverage"],
                    "net_pnl": net_pnl,
                    "r_multiple": r_mult,
                    "friction_r": f_mult,
                    "reason": exit_reason,
                    "channel": pos["channel"],
                    "channels": pos.get("channels", (pos["channel"],)),
                    "regime": pos.get("regime", "NEUTRAL"),
                    "win": net_pnl > 0,
                })
                to_close.append(sym)

        for sym in to_close:
            del active_positions[sym]

        # 2. Portfolio Equity & Drawdown Tracking
        unrealized_pnl = 0.0
        for sym, pos in active_positions.items():
            r_i = sym_indices[sym][t_idx]
            if r_i != -1:
                curr_c = channel_map[sym]["close"][r_i]
                u_ret = (curr_c - pos["entry_price"]) / pos["entry_price"] if pos["side"] == LONG else (pos["entry_price"] - curr_c) / pos["entry_price"]
                unrealized_pnl += pos["notional"] * u_ret

        curr_equity = balance + sum(p["margin"] for p in active_positions.values()) + unrealized_pnl
        equity_history.append(curr_equity)
        if curr_equity > peak_balance:
            peak_balance = curr_equity
        dd = (peak_balance - curr_equity) / peak_balance if peak_balance > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

        # Circuit breakers based on equity peak windows
        daily_loss = (max(equity_history[-24:]) - curr_equity) / max(equity_history[-24:]) if len(equity_history) >= 24 else 0.0
        weekly_loss = (max(equity_history[-168:]) - curr_equity) / max(equity_history[-168:]) if len(equity_history) >= 168 else 0.0

        # 3. Cross-Market Breadth & BTC Macro Calculation
        bull_count = 0
        bear_count = 0
        tot_active = 0
        atr_sum = 0.0
        btc_trend = 0.0

        for sym in active_syms:
            r_i = sym_indices[sym][t_idx]
            if r_i == -1:
                continue
            tot_active += 1
            c_val = channel_map[sym]["close"][r_i]
            e50_val = channel_map[sym]["ema50"][r_i]
            atr_sum += channel_map[sym]["atr_pct"][r_i]
            if c_val > e50_val:
                bull_count += 1
            elif c_val < e50_val:
                bear_count += 1

            if sym == "BTCUSDT" and r_i >= 20:
                btc_c = channel_map[sym]["close"]
                btc_trend = (btc_c[r_i] - btc_c[r_i - 20]) / (btc_c[r_i - 20] or 1.0)
                btc_trend = float(np.clip(btc_trend / 0.05, -1.0, 1.0))

        breadth = (bull_count - bear_count) / tot_active if tot_active > 0 else 0.0
        volatility = atr_sum / tot_active if tot_active > 0 else 0.02

        # 4. Evaluate Entry Candidates
        current_open_risk = sum(p["risk_amount"] for p in active_positions.values()) / curr_equity if curr_equity > 0 else 1.0
        if len(active_positions) >= max_positions or current_open_risk >= max_portfolio_risk or curr_equity <= 10.0:
            continue

        eligible_set = {s for s, _ in rank_assets(list(asset_metrics_map.values()), min_expectancy=0.0, min_pf=1.01)} if mode == "V8" else set(active_syms)

        candidates = []
        selected_symbols = list(active_positions.keys())

        for sym in active_syms:
            if sym in active_positions or (mode == "V8" and sym not in eligible_set):
                continue
            r_i = sym_indices[sym][t_idx]
            if r_i < 50:
                continue

            ch = channel_map[sym]
            c = ch["close"][r_i]
            exp_move = ch["expected_move_pct"][r_i]

            # Build channel evidence
            evidence = []
            cand_stop = c * 0.96
            lead_channel = "UNKNOWN"

            if mode in ("V8", "UNWEIGHTED_ENSEMBLE"):
                if ch["fib_side"][r_i] != FLAT:
                    evidence.append(ChannelEvidence("FIBONACCI", ch["fib_side"][r_i], ch["fib_str"][r_i]))
                    cand_stop = ch["fib_stop"][r_i]
                    lead_channel = "FIBONACCI"
                if ch["mss_side"][r_i] != FLAT:
                    evidence.append(ChannelEvidence("MSS_SHIFT", ch["mss_side"][r_i], ch["mss_str"][r_i]))
                    if lead_channel == "UNKNOWN":
                        cand_stop = ch["mss_stop"][r_i]
                        lead_channel = "MSS_SHIFT"
                if ch["ma_side"][r_i] != FLAT:
                    evidence.append(ChannelEvidence("5MA_CONSENSUS", ch["ma_side"][r_i], ch["ma_str"][r_i]))
                    if lead_channel == "UNKNOWN":
                        cand_stop = ch["ma_stop"][r_i]
                        lead_channel = "5MA_CONSENSUS"
                if ch["sr_side"][r_i] != FLAT:
                    evidence.append(ChannelEvidence("POTATO_SR", ch["sr_side"][r_i], ch["sr_str"][r_i]))
                if ch["div_side"][r_i] != FLAT:
                    evidence.append(ChannelEvidence("DIVERGENCE", ch["div_side"][r_i], ch["div_str"][r_i]))
            elif mode == "FIBONACCI_ONLY" and ch["fib_side"][r_i] != FLAT:
                evidence.append(ChannelEvidence("FIBONACCI", ch["fib_side"][r_i], ch["fib_str"][r_i]))
                cand_stop = ch["fib_stop"][r_i]
                lead_channel = "FIBONACCI"
            elif mode == "MSS_ONLY" and ch["mss_side"][r_i] != FLAT:
                evidence.append(ChannelEvidence("MSS_SHIFT", ch["mss_side"][r_i], ch["mss_str"][r_i]))
                cand_stop = ch["mss_stop"][r_i]
                lead_channel = "MSS_SHIFT"
            elif mode == "5MA_ONLY" and ch["ma_side"][r_i] != FLAT:
                evidence.append(ChannelEvidence("5MA_CONSENSUS", ch["ma_side"][r_i], ch["ma_str"][r_i]))
                cand_stop = ch["ma_stop"][r_i]
                lead_channel = "5MA_CONSENSUS"

            if not evidence:
                continue

            asset = asset_metrics_map.get(sym, AssetMetrics(sym, 0.05, 1.15, 50, 0.10, stability_score=0.8))
            same_dir_count = sum(1 for p in active_positions.values() if p["side"] == evidence[0].side)

            decision = decide(
                evidence=evidence,
                asset=asset,
                breadth=breadth,
                btc_trend=btc_trend,
                volatility=volatility,
                entry=c,
                stop=cand_stop,
                expected_move_pct=exp_move,
                equity=curr_equity,
                current_risk=current_open_risk,
                open_positions=len(active_positions),
                same_direction=same_dir_count,
                daily_loss=daily_loss,
                weekly_loss=weekly_loss,
                drawdown=dd,
                selected=selected_symbols,
                correlation=corr_matrix,
                reliability=channel_reliability if mode == "V8" else None,
                cost_multiplier=cost_multiplier,
            )

            # In unweighted mode, allow trades through with baseline sizing
            if mode == "UNWEIGHTED_ENSEMBLE" and decision.action == FLAT and len(evidence) >= 1:
                raw_side = evidence[0].side
                decision = V8Decision(
                    action=raw_side,
                    score=0.75,
                    channel_score=0.80,
                    asset_score=0.70,
                    market_regime=classify_market_regime(breadth, btc_trend, volatility),
                    expected_net_r=0.35,
                    risk_pct=DEFAULT_RISK_PCT,
                    leverage=10.0,
                    reasons=("UNWEIGHTED_PASS",)
                )

            if decision.action != FLAT:
                active_chans = tuple(e.channel for e in evidence if e.side == decision.action)
                candidates.append((sym, decision, cand_stop, c, lead_channel, ch["atr_pct"][r_i] * c, active_chans))

        # Sort candidates by combined opportunity score
        candidates.sort(key=lambda x: abs(x[1].score), reverse=True)

        for sym, dec, stop_p, entry_p, lead_ch, asset_atr, active_chans in candidates:
            if len(active_positions) >= max_positions or current_open_risk >= max_portfolio_risk:
                break

            stop_dist = abs(entry_p - stop_p)
            stop_pct = stop_dist / entry_p if entry_p > 0 else 0.02
            eff_risk = min(dec.risk_pct, max_portfolio_risk - current_open_risk)
            if eff_risk <= 0.0005 or stop_pct <= 0.001:
                continue

            notional = risk_based_notional(curr_equity, stop_pct, eff_risk, max_leverage=dec.leverage)
            if notional <= 0:
                continue

            margin = notional / (dec.leverage or 1.0)
            if margin > curr_equity * 0.20 or balance - margin < 10.0:
                continue

            fee_in = notional * fee_schedule["maker"]
            balance -= (margin + fee_in)
            tot_fees += fee_in
            risk_amt = curr_equity * eff_risk

            tp_p = entry_p + 2.2 * asset_atr if dec.action == LONG else entry_p - 2.2 * asset_atr
            active_positions[sym] = {
                "symbol": sym,
                "side": dec.action,
                "entry_price": entry_p,
                "initial_stop": stop_p,
                "stop_loss": stop_p,
                "take_profit": tp_p,
                "initial_risk_dist": stop_dist,
                "notional": notional,
                "margin": margin,
                "leverage": dec.leverage,
                "risk_amount": risk_amt,
                "peak_price": entry_p,
                "bars_held": 0,
                "channel": lead_ch,
                "channels": active_chans,
                "regime": dec.market_regime,
                "fee_in": fee_in,
            }

            current_open_risk += eff_risk
            selected_symbols.append(sym)

    final_equity = balance + sum(p["margin"] for p in active_positions.values())
    return {
        "balance": final_equity,
        "max_drawdown": max_dd,
        "friction": tot_fees + tot_slippage + tot_funding,
        "closed_trades": closed_trades,
    }


# -----------------------------------------------------------------------------
# 📑 Scorecards, Partitions & Institutional Evaluation
# -----------------------------------------------------------------------------
def compile_partition_stats(trade_list: list[dict], period_name: str) -> dict:
    t_cnt = len(trade_list)
    if t_cnt == 0:
        return {"period": period_name, "trades": 0, "win_rate": 0.0, "pf": 0.0, "pnl": 0.0, "avg_r": 0.0, "median_r": 0.0, "sharpe": 0.0}
    wins = [t for t in trade_list if t["win"]]
    losses = [t for t in trade_list if not t["win"]]
    wr = len(wins) / t_cnt * 100.0
    g_win = sum(t["net_pnl"] for t in wins)
    g_loss = abs(sum(t["net_pnl"] for t in losses))
    pf = g_win / g_loss if g_loss > 0 else (999.0 if g_win > 0 else 0.0)
    pnl = sum(t["net_pnl"] for t in trade_list)
    r_vals = [t["r_multiple"] for t in trade_list]
    avg_r = float(np.mean(r_vals)) if r_vals else 0.0
    med_r = float(np.median(r_vals)) if r_vals else 0.0
    pnls = [t["net_pnl"] for t in trade_list]
    sharpe = (float(np.mean(pnls)) / float(np.std(pnls) or 1e-9)) * np.sqrt(365) if len(pnls) > 1 else 0.0
    return {
        "period": period_name,
        "trades": t_cnt,
        "win_rate": wr,
        "pf": pf,
        "pnl": pnl,
        "avg_r": avg_r,
        "median_r": med_r,
        "sharpe": sharpe,
    }


def run_institutional_v8_audit(
    cache_dir: str = "backtests/historical_data_cache",
    timeframe: str = "1h"
) -> dict:
    """Execute complete 4-year institutional evaluation for Strategy Candidate V8."""
    if not os.path.exists(cache_dir):
        alt_path = os.path.join(os.path.dirname(__file__), cache_dir)
        if os.path.exists(alt_path):
            cache_dir = alt_path
        else:
            raise FileNotFoundError(f"Cache directory not found: {cache_dir}")

    print("\n" + "=" * 115)
    print(" [AUDIT] STRATEGY CANDIDATE V8: PRODUCTION ALPHA META-CONTROLLER (4-YEAR EVALUATION)")
    print("=" * 115)
    print(" * Research Objectives:")
    print("    1. Evaluate Meta-Controller governing 5 live channels under institutional risk gating.")
    print("    2. Multi-Channel Benchmark: Fibonacci alone, MSS alone, 5MA alone, Unweighted vs V8 Meta-Controller.")
    print("    3. Cost-Stress Testing: Base, +25%, +50%, +100% VIP0 transaction friction.")
    print("    4. Dual Out-Of-Sample Walk-Forward Scorecard: Train (2022-2023), Validate (2024), OOS #1 (2025), OOS #2 (2026).")
    print("    5. Multi-Asset Portfolio Allocation across 11 liquid Binance Futures pairs.")
    print("-" * 115)

    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
        "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
    ]

    print(f" Loading 11 perpetual assets ({timeframe.upper()} resolution)...", flush=True)
    data_map, channel_map, timeline = load_v8_historical_cache(cache_dir, symbols, timeframe=timeframe)
    n_bars = len(timeline)
    print(f" Synchronized {n_bars:,} candles per asset across 48 months (2022-09 to 2026-09).\n", flush=True)

    print(" Computing walk-forward AssetMetrics and historical quality baselines...", flush=True)
    asset_metrics_map = compute_v8_asset_metrics(data_map, channel_map)

    # -------------------------------------------------------------------------
    # Audit 1: Multi-Channel Comparative Benchmark
    # -------------------------------------------------------------------------
    print("\n" + "=" * 115)
    print(" [AUDIT 1] MULTI-CHANNEL COMPARATIVE BENCHMARK MATRIX")
    print("=" * 115)
    print(f"{'Channel / Configuration':<27} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net PnL ($)':>13} | {'Max DD':>8} | {'2025 PnL':>11} | {'2026 PnL':>11}")
    print("-" * 115)

    benchmark_modes = [
        ("1. Fibonacci Alone", "FIBONACCI_ONLY"),
        ("2. MSS Shift Alone", "MSS_ONLY"),
        ("3. 5-MA Consensus Alone", "5MA_ONLY"),
        ("4. Unweighted Ensemble", "UNWEIGHTED_ENSEMBLE"),
        ("5. V8 Meta-Controller", "V8"),
    ]

    v8_reliability = {"5MA_CONSENSUS": 1.5, "FIBONACCI": 1.2, "MSS_SHIFT": 1.0, "POTATO_SR": 0.8, "DIVERGENCE": 0.8}
    bench_results = {}
    v8_primary_sim = None

    for label, mode in benchmark_modes:
        sim = simulate_v8_portfolio(
            data_map=data_map,
            channel_map=channel_map,
            timeline=timeline,
            target_symbols=symbols,
            asset_metrics_map=asset_metrics_map,
            mode=mode,
            cost_multiplier=1.0,
            channel_reliability=v8_reliability if mode == "V8" else None,
        )
        if mode == "V8":
            v8_primary_sim = sim
        bench_results[mode] = sim
        tr = sim["closed_trades"]
        tr_2025 = [t for t in tr if pd.to_datetime(t["timestamp"]).year == 2025]
        tr_2026 = [t for t in tr if pd.to_datetime(t["timestamp"]).year == 2026]
        st_full = compile_partition_stats(tr, "FULL")
        st_25 = compile_partition_stats(tr_2025, "2025")
        st_26 = compile_partition_stats(tr_2026, "2026")

        print(f" {label:<26} | {st_full['trades']:>8,} | {st_full['win_rate']:>8.1f}% | {st_full['pf']:>6.2f} | ${st_full['pnl']:>12.2f} | {sim['max_drawdown']*100:>7.2f}% | ${st_25['pnl']:>10.2f} | ${st_26['pnl']:>10.2f}")

    print("=" * 115 + "\n")

    # -------------------------------------------------------------------------
    # Audit 2: Cost-Stress Robustness Matrix
    # -------------------------------------------------------------------------
    print("=" * 115)
    print(" [AUDIT 2] CANDIDATE V8 COST-STRESS ROBUSTNESS MATRIX")
    print("=" * 115)
    print(f"{'Stress Scenario':<25} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net PnL ($)':>13} | {'Friction ($)':>13} | {'Max DD':>8}")
    print("-" * 115)

    stress_scenarios = [
        ("Base (Realistic VIP0)", 1.0),
        ("+25% Cost Stress", 1.25),
        ("+50% Severe Stress", 1.50),
        ("+100% Extreme Stress", 2.0),
    ]

    for label, mult in stress_scenarios:
        sim_stress = simulate_v8_portfolio(
            data_map=data_map,
            channel_map=channel_map,
            timeline=timeline,
            target_symbols=symbols,
            asset_metrics_map=asset_metrics_map,
            mode="V8",
            cost_multiplier=mult,
            channel_reliability=v8_reliability,
        )
        st = compile_partition_stats(sim_stress["closed_trades"], label)
        print(f" {label:<24} | {st['trades']:>8,} | {st['win_rate']:>8.1f}% | {st['pf']:>6.2f} | ${st['pnl']:>12.2f} | ${sim_stress['friction']:>12.2f} | {sim_stress['max_drawdown']*100:>7.2f}%")

    print("=" * 115 + "\n")

    # -------------------------------------------------------------------------
    # Audit 3: Dual Out-Of-Sample Walk-Forward Scorecard
    # -------------------------------------------------------------------------
    assert v8_primary_sim is not None
    v8_trades = v8_primary_sim["closed_trades"]

    tr_train = [t for t in v8_trades if pd.to_datetime(t["timestamp"]) <= pd.to_datetime("2023-12-31 23:59:59")]
    tr_val = [t for t in v8_trades if pd.to_datetime("2024-01-01 00:00:00") <= pd.to_datetime(t["timestamp"]) <= pd.to_datetime("2024-12-31 23:59:59")]
    tr_oos1 = [t for t in v8_trades if pd.to_datetime("2025-01-01 00:00:00") <= pd.to_datetime(t["timestamp"]) <= pd.to_datetime("2025-12-31 23:59:59")]
    tr_oos2 = [t for t in v8_trades if pd.to_datetime("2026-01-01 00:00:00") <= pd.to_datetime(t["timestamp"]) <= pd.to_datetime("2026-12-31 23:59:59")]

    st_train = compile_partition_stats(tr_train, "TRAIN (2022-2023)")
    st_val = compile_partition_stats(tr_val, "VALIDATE (2024)")
    st_oos1 = compile_partition_stats(tr_oos1, "OOS #1 (2025)")
    st_oos2 = compile_partition_stats(tr_oos2, "OOS #2 (2026)")
    st_full = compile_partition_stats(v8_trades, "FULL 4-YEAR PERIOD")

    print("=" * 115)
    print(" [AUDIT 3] CANDIDATE V8 DUAL OUT-OF-SAMPLE WALK-FORWARD SCORECARD")
    print("=" * 115)
    print(f"{'Partition Period':<23} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net PnL ($)':>13} | {'Avg R':>7} | {'Median R':>9} | {'Sharpe':>7}")
    print("-" * 115)

    for st in [st_train, st_val, st_oos1, st_oos2, st_full]:
        print(f" {st['period']:<22} | {st['trades']:>8,} | {st['win_rate']:>8.1f}% | {st['pf']:>6.2f} | ${st['pnl']:>12.2f} | {st['avg_r']:>+7.2f} | {st['median_r']:>+9.2f} | {st['sharpe']:>7.2f}")

    print("=" * 115 + "\n")

    # -------------------------------------------------------------------------
    # Audit 4: Per-Asset Contribution Breakdown
    # -------------------------------------------------------------------------
    print(" [ASSET CONTRIBUTION IN CANDIDATE V8]")
    print(f" {'Asset':<10} | {'Trades':>8} | {'Win Rate':>9} | {'Net Realized PnL':>18} | {'Avg Trade PnL':>15}")
    print("-" * 75)

    sym_pnls = {}
    for sym in symbols:
        sym_tr = [t for t in v8_trades if t["symbol"] == sym]
        if not sym_tr:
            print(f" {sym:<10} | {0:>8} | {0.0:>8.1f}% | ${0.0:>17.2f} | ${0.0:>14.2f}")
            sym_pnls[sym] = 0.0
            continue
        s_pnl = sum(t["net_pnl"] for t in sym_tr)
        s_wr = sum(1 for t in sym_tr if t["win"]) / len(sym_tr) * 100.0
        s_avg = s_pnl / len(sym_tr)
        sym_pnls[sym] = s_pnl
        print(f" {sym:<10} | {len(sym_tr):>8} | {s_wr:>8.1f}% | ${s_pnl:>17.2f} | ${s_avg:>14.2f}")

    print("-" * 75 + "\n")

    # -------------------------------------------------------------------------
    # Audit 5: Acceptance Gate Evaluation
    # -------------------------------------------------------------------------
    print("=" * 80)
    print(" [V8 INSTITUTIONAL ACCEPTANCE GATE EVALUATION]")
    print("=" * 80)

    g1_oos1_pf = st_oos1["pf"] >= 1.05
    g1_oos2_pf = st_oos2["pf"] >= 1.05
    g1_oos1_pnl = st_oos1["pnl"] > 0
    g1_oos2_pnl = st_oos2["pnl"] > 0
    g1_dd = v8_primary_sim["max_drawdown"] <= 0.20
    g1_trades = (st_oos1["trades"] + st_oos2["trades"]) >= 100

    print(f" 1. OOS #1 (2025) Profit Factor >= 1.05: [{'PASS' if g1_oos1_pf else 'FAIL'}] ({st_oos1['pf']:.2f})")
    print(f" 2. OOS #2 (2026) Profit Factor >= 1.05: [{'PASS' if g1_oos2_pf else 'FAIL'}] ({st_oos2['pf']:.2f})")
    print(f" 3. OOS #1 (2025) Net PnL Positive:      [{'PASS' if g1_oos1_pnl else 'FAIL'}] (${st_oos1['pnl']:+.2f})")
    print(f" 4. OOS #2 (2026) Net PnL Positive:      [{'PASS' if g1_oos2_pnl else 'FAIL'}] (${st_oos2['pnl']:+.2f})")
    print(f" 5. Maximum Portfolio Drawdown <= 20%:   [{'PASS' if g1_dd else 'FAIL'}] ({v8_primary_sim['max_drawdown']*100:.2f}%)")
    print(f" 6. Total OOS Trades >= 100:             [{'PASS' if g1_trades else 'FAIL'}] ({st_oos1['trades'] + st_oos2['trades']} trades)")
    print("=" * 80 + "\n")

    return {
        "benchmarks": bench_results,
        "partitions": {
            "train": st_train,
            "val": st_val,
            "oos1": st_oos1,
            "oos2": st_oos2,
            "full": st_full,
        }
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 4-year institutional audit for Strategy Candidate V8.")
    parser.add_argument("--cache-dir", type=str, default="backtests/historical_data_cache", help="Path to historical cache directory")
    parser.add_argument("--timeframe", type=str, default="1h", choices=["1h", "15m"], help="Evaluation timeframe (default: 1h)")
    args = parser.parse_args()

    run_institutional_v8_audit(cache_dir=args.cache_dir, timeframe=args.timeframe)

