#!/usr/bin/env python3
"""Conservative 75x integrity backtest for Atlas.

This intentionally leaves the original 4-year optimizer untouched. It reuses its
historical-data loader and signal generation, but changes execution semantics:

* signals confirmed on bar i are entered at bar i+1 open;
* liquidation is checked before ordinary exits;
* if TP and stop are both touched in one candle, the adverse event wins;
* trailing stops are updated after a candle and cannot react to that candle's
  opposite extreme;
* equity/drawdown are marked to market;
* final exits pay an exit fee;
* funding is configurable and can be stressed across multiple rates.

75x leverage is fixed by the CLI default/profile and is not optimized here.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtests.backtest_4year_atlas_perfect_synergy import (  # noqa: E402
    FEE_SCHEDULE,
    get_precomputed_data_4y,
)

LEVERAGE = 75
MAINTENANCE_MARGIN_RATE = 0.005
MARGIN_PCT = 0.03
MAX_POSITIONS = 5
MAX_DIRECTIONAL = 5
MAX_POSITION_NOTIONAL = 1000.0
MIN_POSITION_NOTIONAL = 5.0
TP1_ATR = 2.2
TRAIL_ATR = 0.8
MIN_RR = 1.8
COOLDOWN_BARS = 12


@dataclass
class Position:
    symbol: str
    side: str
    entry_price: float
    qty: float
    remaining_qty: float
    margin: float
    tp1_price: float
    stop_price: float
    atr: float
    channel: str
    entry_bar: int
    entry_time: pd.Timestamp
    realized_pnl: float
    tp1_hit: bool = False
    high_water: float = 0.0
    low_water: float = 0.0


def liquidation_price(entry: float, side: str, leverage: int, mmr: float) -> float:
    """Conservative simplified isolated-margin liquidation proxy."""
    if side == "LONG":
        return entry * (1.0 - 1.0 / leverage + mmr)
    return entry * (1.0 + 1.0 / leverage - mmr)


def exit_fee(price: float, qty: float) -> float:
    return price * qty * (FEE_SCHEDULE["taker_fee"] + FEE_SCHEDULE["slippage"])


def unrealized(pos: Position, mark: float) -> float:
    if pos.side == "LONG":
        return (mark - pos.entry_price) * pos.remaining_qty
    return (pos.entry_price - mark) * pos.remaining_qty


def close_position(
    pos: Position,
    exit_price: float,
    close_qty: float,
    reason: str,
    balance: float,
    release_margin: float,
) -> tuple[float, float]:
    if pos.side == "LONG":
        pnl = (exit_price - pos.entry_price) * close_qty
    else:
        pnl = (pos.entry_price - exit_price) * close_qty
    fee = exit_fee(exit_price, close_qty)
    net = pnl - fee
    balance += release_margin + net
    pos.realized_pnl += net
    pos.remaining_qty -= close_qty
    if reason == "LIQUIDATION":
        # The simplified model treats liquidation as consuming the remaining
        # isolated margin. Do not return margin after a liquidation event.
        balance -= release_margin
        pos.realized_pnl -= release_margin
    return balance, net


def choose_signal(sig: dict, price: float, atr: float, not_btc_dump: bool,
                  long_count: int, short_count: int) -> Optional[dict]:
    """Mirror the original strategy's three signal priorities."""
    action = None
    tp1 = 0.0
    sl = 0.0
    channel = None

    if sig["mss_long"] and not_btc_dump and long_count < MAX_DIRECTIONAL:
        tp1 = price + TP1_ATR * atr
        sl = sig["last_sl"] - 0.5 * atr
        if abs(tp1 - price) / (abs(price - sl) + 1e-9) >= MIN_RR:
            action, channel = "LONG", "MSS_SHIFT"
    elif sig["mss_short"] and short_count < MAX_DIRECTIONAL:
        tp1 = price - TP1_ATR * atr
        sl = sig["last_sh"] + 0.5 * atr
        if abs(price - tp1) / (abs(sl - price) + 1e-9) >= MIN_RR:
            action, channel = "SHORT", "MSS_SHIFT"
    elif sig["cons_long"] and not_btc_dump and long_count < MAX_DIRECTIONAL:
        tp1 = price + TP1_ATR * atr
        sl = price - 1.5 * atr
        action, channel = "LONG", "5MA_CONSENSUS"
    elif sig["cons_short"] and short_count < MAX_DIRECTIONAL:
        tp1 = price - TP1_ATR * atr
        sl = price + 1.5 * atr
        action, channel = "SHORT", "5MA_CONSENSUS"
    elif sig["fib_long"] and not_btc_dump and long_count < MAX_DIRECTIONAL:
        tp1 = price + TP1_ATR * atr
        sl = sig["last_sl"] - 0.5 * atr
        if abs(tp1 - price) / (abs(price - sl) + 1e-9) >= MIN_RR:
            action, channel = "LONG", "FIBONACCI"
    elif sig["fib_short"] and short_count < MAX_DIRECTIONAL:
        tp1 = price - TP1_ATR * atr
        sl = sig["last_sh"] + 0.5 * atr
        if abs(price - tp1) / (abs(sl - price) + 1e-9) >= MIN_RR:
            action, channel = "SHORT", "FIBONACCI"

    if action is None:
        return None
    return {"side": action, "tp1": tp1, "sl": sl, "channel": channel}


def run_integrity(funding_8h: float = 0.00010) -> dict:
    cached = get_precomputed_data_4y()
    signals_map = cached["signals_map"]
    highs_map = cached["highs_map"]
    lows_map = cached["lows_map"]
    closes_map = cached["closes_map"]
    data_map = cached["data_map"]
    time_index = cached["time_index"]
    idx_maps = cached["idx_maps"]
    btc_dump_arr = cached["btc_dump_arr"]
    active_symbols = cached["active_symbols"]
    n_bars = cached["n_bars"]

    initial = 9.79
    balance = initial
    positions: Dict[str, Position] = {}
    last_trade = {s: -999 for s in active_symbols}
    trades: List[dict] = []
    equity_curve: List[float] = []
    liquidation_count = 0
    liquidation_losses = 0.0
    total_fees = 0.0
    total_funding = 0.0
    peak_equity = initial
    max_dd = 0.0

    # Pending entries are created from a fully closed signal bar and executed
    # at the following bar's OPEN. This prevents same-close execution.
    pending: Dict[str, dict] = {}

    for bar_i in range(50, n_bars):
        cur_time = pd.Timestamp(time_index[bar_i])

        # --------------------------- exits / funding ----------------------
        to_remove = []
        for sym, pos in list(positions.items()):
            s_idx = idx_maps[sym][bar_i]
            if s_idx < 0:
                continue
            row = data_map[sym].iloc[s_idx]
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])

            # Binance-style funding timestamps are approximated by 00/08/16 UTC.
            # The cached data is expected to be UTC-aligned 15m candles.
            if cur_time.minute == 0 and cur_time.hour in (0, 8, 16):
                notional_mark = c * pos.remaining_qty
                fee = notional_mark * funding_8h
                balance -= fee
                pos.realized_pnl -= fee
                total_funding += fee

            liq = liquidation_price(pos.entry_price, pos.side, LEVERAGE, MAINTENANCE_MARGIN_RATE)
            hit_liq = l <= liq if pos.side == "LONG" else h >= liq
            hit_stop = l <= pos.stop_price if pos.side == "LONG" else h >= pos.stop_price
            hit_tp = (h >= pos.tp1_price) if pos.side == "LONG" else (l <= pos.tp1_price)

            # Conservative intrabar policy: liquidation first; if TP and stop
            # share a candle, assume the adverse stop happened first.
            if hit_liq:
                qty = pos.remaining_qty
                balance, _ = close_position(pos, liq, qty, "LIQUIDATION", balance, pos.margin * (0.5 if pos.tp1_hit else 1.0))
                liquidation_count += 1
                liquidation_losses += abs(pos.realized_pnl)
                total_fees += exit_fee(liq, qty)
                pos.exit_time = cur_time
                trades.append({"position": pos, "reason": "LIQUIDATION"})
                to_remove.append(sym)
                continue

            if hit_stop and hit_tp:
                hit_tp = False

            if hit_stop:
                qty = pos.remaining_qty
                release = pos.margin * (0.5 if pos.tp1_hit else 1.0)
                balance, _ = close_position(pos, pos.stop_price, qty, "STOP", balance, release)
                total_fees += exit_fee(pos.stop_price, qty)
                pos.exit_time = cur_time
                trades.append({"position": pos, "reason": "STOP"})
                to_remove.append(sym)
                continue

            if hit_tp and not pos.tp1_hit:
                half = pos.remaining_qty * 0.5
                balance, _ = close_position(pos, pos.tp1_price, half, "TP1", balance, pos.margin * 0.5)
                fee = exit_fee(pos.tp1_price, half)
                total_fees += fee
                pos.tp1_hit = True
                pos.stop_price = pos.entry_price * (1.0005 if pos.side == "LONG" else 0.9995)
                pos.high_water = max(pos.high_water, h)
                pos.low_water = min(pos.low_water, l)

            # Trailing is deliberately updated only AFTER all decisions on the
            # current candle. The new stop can therefore only affect bar i+1.
            if pos.tp1_hit and sym not in to_remove:
                if pos.side == "LONG":
                    pos.high_water = max(pos.high_water, h)
                    pos.stop_price = max(pos.stop_price, pos.high_water - TRAIL_ATR * pos.atr)
                else:
                    pos.low_water = min(pos.low_water, l)
                    pos.stop_price = min(pos.stop_price, pos.low_water + TRAIL_ATR * pos.atr)

        for sym in to_remove:
            pos = positions.pop(sym)
            last_trade[sym] = bar_i

        # --------------------------- mark-to-market -----------------------
        equity = balance
        for sym, pos in positions.items():
            s_idx = idx_maps[sym][bar_i]
            if s_idx >= 0:
                equity += pos.margin * (0.5 if pos.tp1_hit else 1.0)
                equity += unrealized(pos, float(closes_map[sym][s_idx]))
        equity_curve.append(equity)
        peak_equity = max(peak_equity, equity)
        max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)

        # --------------------------- execute pending ---------------------
        if pending and len(positions) < MAX_POSITIONS and balance > 0:
            for sym, setup in list(pending.items()):
                pending.pop(sym, None)
                if sym in positions or bar_i - last_trade[sym] < COOLDOWN_BARS:
                    continue
                s_idx = idx_maps[sym][bar_i]
                if s_idx < 0:
                    continue
                open_price = float(data_map[sym].iloc[s_idx]["open"])
                atr = setup["atr"]
                side = setup["side"]
                tp1 = setup["tp1"]
                sl = setup["sl"]
                # Re-price distances at next-open execution while preserving
                # the strategy's original absolute levels conservatively.
                if side == "LONG" and (open_price <= sl or open_price >= tp1):
                    continue
                if side == "SHORT" and (open_price >= sl or open_price <= tp1):
                    continue

                base_margin = balance * MARGIN_PCT
                margin_alloc = base_margin
                notional = min(margin_alloc * LEVERAGE, MAX_POSITION_NOTIONAL)
                notional = max(notional, MIN_POSITION_NOTIONAL)
                margin_alloc = notional / LEVERAGE
                entry_fee = notional * (FEE_SCHEDULE["maker_fee"] + FEE_SCHEDULE["slippage"])
                if balance < margin_alloc + entry_fee:
                    continue

                qty = notional / open_price
                balance -= margin_alloc + entry_fee
                total_fees += entry_fee
                positions[sym] = Position(
                    symbol=sym,
                    side=side,
                    entry_price=open_price,
                    qty=qty,
                    remaining_qty=qty,
                    margin=margin_alloc,
                    tp1_price=tp1,
                    stop_price=sl,
                    atr=atr,
                    channel=setup["channel"],
                    entry_bar=bar_i,
                    entry_time=cur_time,
                    realized_pnl=-entry_fee,
                    high_water=open_price,
                    low_water=open_price,
                )
                last_trade[sym] = bar_i
                if len(positions) >= MAX_POSITIONS:
                    break

        # --------------------------- generate next-bar entries ------------
        if len(positions) >= MAX_POSITIONS or balance <= 0:
            continue

        long_count = sum(p.side == "LONG" for p in positions.values())
        short_count = sum(p.side == "SHORT" for p in positions.values())
        for sym in active_symbols:
            if sym in positions or sym in pending:
                continue
            if bar_i - last_trade[sym] < COOLDOWN_BARS:
                continue
            s_idx = idx_maps[sym][bar_i]
            if s_idx < 0:
                continue
            sig = signals_map[sym][s_idx]
            close_price = float(closes_map[sym][s_idx])
            setup = choose_signal(
                sig, close_price, float(sig["atr"]),
                not btc_dump_arr[bar_i], long_count, short_count,
            )
            if setup:
                setup["atr"] = float(sig["atr"])
                pending[sym] = setup
                if setup["side"] == "LONG":
                    long_count += 1
                else:
                    short_count += 1
            if len(positions) + len(pending) >= MAX_POSITIONS:
                break

    # Close anything still open at the final CLOSE with a proper exit fee.
    final_time = pd.Timestamp(time_index[-1])
    for sym, pos in list(positions.items()):
        s_idx = idx_maps[sym][-1]
        mark = float(closes_map[sym][s_idx]) if s_idx >= 0 else pos.entry_price
        qty = pos.remaining_qty
        if pos.side == "LONG":
            pnl = (mark - pos.entry_price) * qty
        else:
            pnl = (pos.entry_price - mark) * qty
        fee = exit_fee(mark, qty)
        release = pos.margin * (0.5 if pos.tp1_hit else 1.0)
        balance += release + pnl - fee
        pos.realized_pnl += pnl - fee
        total_fees += fee
        pos.exit_time = final_time
        trades.append({"position": pos, "reason": "FINAL_CLOSE"})

    final_equity = balance
    pnls = [x["position"].realized_pnl for x in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    years = max((final_time - pd.Timestamp(time_index[50])).total_seconds() / (365.25 * 86400), 1 / 365.25)
    cagr = ((final_equity / initial) ** (1 / years) - 1) * 100 if final_equity > 0 else -100.0

    result = {
        "funding_8h": funding_8h,
        "leverage": LEVERAGE,
        "initial_balance": initial,
        "final_balance": final_equity,
        "net_profit": final_equity - initial,
        "roi_pct": (final_equity / initial - 1) * 100,
        "cagr_pct": cagr,
        "trades": len(trades),
        "win_rate_pct": len(wins) / len(pnls) * 100 if pnls else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else math.inf,
        "max_drawdown_pct": max_dd,
        "liquidations": liquidation_count,
        "liquidation_losses": liquidation_losses,
        "total_fees": total_fees,
        "total_funding": total_funding,
        "max_simultaneous_positions": MAX_POSITIONS,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas 75x integrity backtest")
    parser.add_argument(
        "--funding",
        type=float,
        nargs="+",
        default=[0.00010, 0.00030, 0.00050],
        help="8h funding rates to stress-test (decimal, e.g. 0.0001)",
    )
    args = parser.parse_args()

    rows = []
    for rate in args.funding:
        print(f"\n=== ATLAS 75x INTEGRITY | funding={rate:.5%} ===")
        result = run_integrity(rate)
        rows.append(result)
        for key in (
            "final_balance", "net_profit", "roi_pct", "cagr_pct", "trades",
            "win_rate_pct", "profit_factor", "max_drawdown_pct",
            "liquidations", "liquidation_losses", "total_fees", "total_funding",
        ):
            print(f"{key:24s}: {result[key]:,.6f}" if isinstance(result[key], float) else f"{key:24s}: {result[key]}")

    pd.DataFrame(rows).to_csv(os.path.join(HERE, "atlas_75x_integrity_results.csv"), index=False)
    print("\nWrote backtests/atlas_75x_integrity_results.csv")


if __name__ == "__main__":
    main()
