"""
V9 Backtest Execution Audit Harness
===================================
Purpose: isolate and QUANTIFY look-ahead and fill-assumption issues in the V9
family execution loop (strategy_candidate_v9.py :: backtest_frame, mirrored in
v9_3_1 and the shadow engine), on a controlled 4-year / ~300-trade run.

Method: the SIGNAL logic is irrelevant to fill realism -- the risk lives in the
EXECUTION LOOP. So we reproduce that loop VERBATIM from the audited source and
compare it against a hardened loop on the *same* (bar, side, atr) inputs, so the
delta is attributable purely to fill assumptions, not to signal differences.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import json

LONG, SHORT = 1, -1
FRICTION_R = 0.026          # flat friction used by V9 core
STOP_ATR = 1.25
TARGET_ATR = 2.00
MAX_HOLD_BARS = 32
BARS_PER_DAY = 96           # 15m bars
YEARS = 4
SEED = 7

# ----------------------------------------------------------------------------
# 1. VERBATIM V9 EXECUTION LOOP  (copied from strategy_candidate_v9.backtest_frame)
#    Only wrapped into a function taking precomputed arrays + a fixed signal list.
# ----------------------------------------------------------------------------
def original_exec(opens, highs, lows, closes, signals, friction_r=FRICTION_R,
                  max_hold_bars=MAX_HOLD_BARS):
    n = len(opens)
    trades = []
    for (i, side, atr) in signals:
        entry_idx = i + 1
        if entry_idx >= n:
            continue
        entry = opens[entry_idx]
        stop = entry - side * STOP_ATR * atr
        target = entry + side * TARGET_ATR * atr
        exit_px, held = entry, 0
        end_bar = min(n, entry_idx + max_hold_bars)
        for j in range(entry_idx, end_bar):
            held += 1
            l_val, h_val = lows[j], highs[j]
            stop_hit = (l_val <= stop) if side == LONG else (h_val >= stop)
            target_hit = (h_val >= target) if side == LONG else (l_val <= target)
            if stop_hit:                 # <-- stop-first (conservative)
                exit_px = stop           # <-- EXACT-PRICE FILL (optimistic on stops)
                break
            if target_hit:
                exit_px = target
                break
            exit_px = closes[j]          # timeout -> close
        gross_r = side * (exit_px - entry) / max(abs(entry - stop), 1e-12)
        net_r = gross_r - friction_r
        trades.append(net_r)
    return np.array(trades)


# ----------------------------------------------------------------------------
# 2. HARDENED EXECUTION LOOP  (same signals; realistic fills)
#    Fixes: (a) gap-through-stop fills at the OPEN, not the stop level.
#           (b) intrabar stop-market slippage (fraction of ATR).
#           (c) explicit same-bar stop&target ambiguity accounting (kept
#               conservative stop-first, but COUNTED so path-risk is visible).
#           (d) entry-bar gap-past-target realism (limit fill stays at target).
# ----------------------------------------------------------------------------
def hardened_exec(opens, highs, lows, closes, signals, friction_r=FRICTION_R,
                  max_hold_bars=MAX_HOLD_BARS, stop_slip_atr=0.05):
    n = len(opens)
    trades, diag = [], {"gap_stop_fills": 0, "slip_stop_fills": 0,
                        "ambiguous_bars": 0, "total": 0}
    for (i, side, atr) in signals:
        entry_idx = i + 1
        if entry_idx >= n:
            continue
        entry = opens[entry_idx]
        stop = entry - side * STOP_ATR * atr
        target = entry + side * TARGET_ATR * atr
        exit_px, held = entry, 0
        end_bar = min(n, entry_idx + max_hold_bars)
        for j in range(entry_idx, end_bar):
            held += 1
            o_val, l_val, h_val = opens[j], lows[j], highs[j]
            stop_hit = (l_val <= stop) if side == LONG else (h_val >= stop)
            target_hit = (h_val >= target) if side == LONG else (l_val <= target)
            if stop_hit and target_hit:
                diag["ambiguous_bars"] += 1   # path unknown; stay conservative
            if stop_hit:
                # (a) opening gap beyond stop -> fill at open (worse)
                gapped = (o_val <= stop) if side == LONG else (o_val >= stop)
                if gapped:
                    exit_px = o_val
                    diag["gap_stop_fills"] += 1
                else:
                    # (b) stop-market slippage past the trigger
                    exit_px = stop - side * stop_slip_atr * atr
                    diag["slip_stop_fills"] += 1
                break
            if target_hit:
                exit_px = target             # limit fill: exact (realistic)
                break
            exit_px = closes[j]
        gross_r = side * (exit_px - entry) / max(abs(entry - stop), 1e-12)
        net_r = gross_r - friction_r
        trades.append(net_r)
        diag["total"] += 1
    return np.array(trades), diag


# ----------------------------------------------------------------------------
# 3. Synthetic 4-year 15m OHLCV with realistic wicks + occasional gaps
# ----------------------------------------------------------------------------
def make_ohlcv(n, seed):
    rng = np.random.default_rng(seed)
    # log-returns with vol clustering
    vol = 0.0015 * (1 + 0.6 * np.abs(np.sin(np.arange(n) / 500.0)))
    rets = rng.normal(0, vol)
    # inject occasional gap shocks (fat tails) ~0.5% of bars
    shock = rng.random(n) < 0.005
    rets[shock] += rng.normal(0, 0.02, shock.sum())
    close = 100.0 * np.exp(np.cumsum(rets))
    openp = np.empty(n); openp[0] = 100.0
    open_gap = rng.normal(0, 0.0008, n - 1)
    gap_shock = rng.random(n - 1) < 0.01                      # 1% real opening gaps
    open_gap += gap_shock * rng.normal(0, 0.015, n - 1)
    openp[1:] = close[:-1] * (1 + open_gap)
    # wider wicks so a single 15m bar can span both the 1.25-ATR stop and the
    # 2.0-ATR target (this is what creates same-bar path ambiguity in real tape)
    hi_noise = np.abs(rng.normal(0, vol * 4.0)) + shock * np.abs(rng.normal(0, 0.03, n))
    lo_noise = np.abs(rng.normal(0, vol * 4.0)) + shock * np.abs(rng.normal(0, 0.03, n))
    high = np.maximum(openp, close) * (1 + hi_noise)
    low = np.minimum(openp, close) * (1 - lo_noise)
    # ATR proxy (Wilder-ish), trailing only (no look-ahead)
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - np.roll(close, 1)),
                               np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().values
    return openp, high, low, close, atr


def make_signals(n, atr, target_trades, seed):
    """Place ~target_trades non-overlapping signals; side random. Uses only
    information available at bar i (atr[i]) -> no look-ahead by construction."""
    rng = np.random.default_rng(seed + 1)
    signals = []
    i = 205
    # space signals so ~target_trades fit; allow avg hold ~ spacing
    spacing = max(MAX_HOLD_BARS + 2, (n - 210) // (target_trades + 1))
    while i < n - 2 and len(signals) < target_trades:
        side = LONG if rng.random() < 0.5 else SHORT
        a = float(atr[i])
        if a > 0:
            signals.append((i, side, a))
        i += spacing + int(rng.integers(0, spacing))
    return signals


def stats(r):
    if len(r) == 0:
        return {}
    wins = r[r > 0]; losses = r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "trades": int(len(r)),
        "net_R": round(float(r.sum()), 3),
        "expectancy_R": round(float(r.mean()), 4),
        "win_rate_pct": round(100 * float((r > 0).mean()), 1),
        "profit_factor": round(float(pf), 3),
    }


def main():
    n = YEARS * 365 * BARS_PER_DAY  # ~140,160 bars
    n_symbols = 11
    target_per_symbol = 300 // n_symbols + 24  # oversample so we can trim to exactly 300

    all_orig, all_hard = [], []
    agg_diag = {"gap_stop_fills": 0, "slip_stop_fills": 0, "ambiguous_bars": 0, "total": 0}

    for s in range(n_symbols):
        o, h, l, c, atr = make_ohlcv(n, SEED + s)
        sig = make_signals(n, atr, target_per_symbol, SEED + s)
        ro = original_exec(o, h, l, c, sig)
        rh, diag = hardened_exec(o, h, l, c, sig)
        all_orig.append(ro); all_hard.append(rh)
        for k in agg_diag:
            agg_diag[k] += diag[k]

    ro = np.concatenate(all_orig)[:300]   # complete exactly a 300-trade run
    rh = np.concatenate(all_hard)[:300]

    report = {
        "run": {"bars_per_symbol": n, "symbols": n_symbols,
                "years": YEARS, "trades_completed": int(len(ro))},
        "ORIGINAL_v9_fills": stats(ro),
        "HARDENED_realistic_fills": stats(rh),
        "delta": {
            "net_R": round(float(rh.sum() - ro.sum()), 3),
            "expectancy_R": round(float(rh.mean() - ro.mean()), 4),
            "pct_expectancy_erosion": round(
                100 * (rh.mean() - ro.mean()) / abs(ro.mean()), 1) if ro.mean() != 0 else None,
        },
        "fill_diagnostics": agg_diag,
        "diagnostics_note": (
            "gap_stop_fills = stops that opened BEYOND the level (V9 fills these at "
            "the exact stop -> optimistic). slip_stop_fills = intrabar stop-market "
            "hits charged realistic slippage. ambiguous_bars = bars where BOTH stop "
            "and target were inside [low,high] (path unknown; outcome is an assumption)."
        ),
    }
    print(json.dumps(report, indent=2))
    with open("/mnt/user-data/outputs/v9_fill_audit_report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
