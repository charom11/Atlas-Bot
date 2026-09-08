#!/usr/bin/env python3
"""V9.3.1 Shadow Telemetry Daemon: Live 15M Opportunity & Outcome Observer.

Runs concurrently alongside the live production bot (main.py):
- Zero live execution: strictly observer-only forward telemetry.
- Polls Binance 15m closed klines for all Tier 1 and Tier 2 universe assets.
- Evaluates candidate opportunities against committed V9.3.1 policy.
- Tracks shadow forward positions and records resolved trade outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from strategy_candidate_v9_3_1 import (
    TIER_1,
    TIER_2,
    V931Config,
    ACTIVE_SETUPS_V931,
    GATED_REGIMES_V931,
)
from v9_3_1_shadow_engine import V931ShadowEngine

SHADOW_SYMBOLS = list(TIER_1) + list(TIER_2)
BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


def fetch_market_friction_context() -> dict[str, dict]:
    """Fetch live bookTicker (bid, ask, spread, depth) and premiumIndex (funding, mark price) across universe."""
    context = {}
    try:
        resp = requests.get("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=5)
        if resp.status_code == 200:
            for item in resp.json():
                sym = item.get("symbol")
                if sym in SHADOW_SYMBOLS:
                    bid = float(item["bidPrice"])
                    ask = float(item["askPrice"])
                    bid_qty = float(item.get("bidQty", 0.0))
                    ask_qty = float(item.get("askQty", 0.0))
                    mid = (bid + ask) / 2.0 if (bid + ask) > 0 else 1.0
                    spread_usd = ask - bid
                    spread_bps = (spread_usd / mid) * 10000.0
                    context[sym] = {
                        "bid": bid,
                        "ask": ask,
                        "bid_qty": bid_qty,
                        "ask_qty": ask_qty,
                        "spread_usd": spread_usd,
                        "spread_bps": spread_bps,
                        "mark_price": mid,
                        "funding_rate_8h": 0.0001,
                        "latency_ms": 0.0,
                    }
        resp_f = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5)
        if resp_f.status_code == 200:
            for item in resp_f.json():
                sym = item.get("symbol")
                if sym in context:
                    context[sym]["funding_rate_8h"] = float(item.get("lastFundingRate", 0.0001))
                    context[sym]["mark_price"] = float(item.get("markPrice", context[sym]["mark_price"]))
    except Exception as e:
        pass
    return context


def fetch_closed_15m_klines(symbol: str, limit: int = 250) -> pd.DataFrame | None:
    """Fetch completed 15m candles from Binance public REST API."""
    params = {"symbol": symbol, "interval": "15m", "limit": limit}
    try:
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=8)
        if resp.status_code != 200:
            print(f"[SHADOW API WARN] {symbol} HTTP {resp.status_code}: {resp.text[:100]}", flush=True)
            return None

        raw = resp.json()
        now_ms = int(time.time() * 1000)
        # Exclude the currently forming live candle
        closed_bars = [k for k in raw if len(k) > 6 and int(k[6]) <= now_ms]
        if not closed_bars:
            return None

        dates = []
        data = []
        for k in closed_bars:
            ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            dates.append(ts)
            data.append({
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "symbol": symbol,
            })

        df = pd.DataFrame(data, index=dates)
        df.attrs["last_bar_close_ms"] = int(closed_bars[-1][6])
        return df
    except Exception as e:
        print(f"[SHADOW FETCH ERROR] Failed to fetch klines for {symbol}: {e}", flush=True)
        return None


def run_shadow_cycle(engine: V931ShadowEngine, verbose: bool = True) -> dict:
    """Execute one scan across all monitored universe symbols with empirical friction telemetry."""
    cycle_stats = {"evaluated": 0, "admitted": 0, "outcomes": 0}
    market_contexts = fetch_market_friction_context()

    for symbol in SHADOW_SYMBOLS:
        df = fetch_closed_15m_klines(symbol, limit=250)
        if df is None or len(df) <= 201:
            continue

        sym_ctx = market_contexts.get(symbol, {
            "bid": 0.0, "ask": 0.0, "bid_qty": 0.0, "ask_qty": 0.0,
            "spread_usd": 0.0, "spread_bps": 0.0, "mark_price": 0.0,
            "funding_rate_8h": 0.0001, "latency_ms": 0.0,
        })
        close_ms = df.attrs.get("last_bar_close_ms")
        if close_ms:
            sym_ctx["latency_ms"] = max(0, int(time.time() * 1000) - close_ms)

        opp, outcomes = engine.evaluate_bar(symbol, df, market_context=sym_ctx)
        cycle_stats["evaluated"] += 1

        if opp:
            if opp.admitted:
                cycle_stats["admitted"] += 1
                side_str = "LONG 🟢" if opp.side == 1 else "SHORT 🔴"
                print(
                    f"[SHADOW ADMITTED] 🎯 [{opp.timestamp}] [{symbol}] {opp.setup} {side_str} "
                    f"@ ${opp.entry_price:,.4f} | ATR: {opp.atr:.4f} | Score: {opp.score} | Conf: {opp.confirmations} "
                    f"| Spread: {sym_ctx['spread_bps']:.1f}bps | Funding: {sym_ctx['funding_rate_8h']*100:.4f}% | Latency: {sym_ctx['latency_ms']}ms "
                    f"-> SL: ${opp.stop_price:,.4f} | TP: ${opp.target_price:,.4f}",
                    flush=True,
                )
            elif verbose and opp.rejection_reason and "No candidate" not in opp.rejection_reason:
                print(
                    f"  [SHADOW GATED] 🛡️ [{symbol}] {opp.regime} - {opp.rejection_reason}",
                    flush=True,
                )

        for outcome in outcomes:
            cycle_stats["outcomes"] += 1
            status_icon = "🟢" if outcome.net_r > 0 else "🔴"
            print(
                f"[SHADOW OUTCOME] 🏁 [{outcome.symbol}] {outcome.setup} {outcome.outcome_type} {status_icon} "
                f"-> Net R: {outcome.net_r:+.2f} R (Empirical Net: {outcome.empirical_net_r:+.2f} R, Slip: {outcome.realized_slippage_r:+.3f}R, Funding: {outcome.realized_funding_r:+.3f}R) "
                f"Entry: ${outcome.entry_price:,.4f} | Exit: ${outcome.exit_price:,.4f} | Held: {outcome.bars_held} bars",
                flush=True,
            )

        time.sleep(0.3)  # Gentle rate limiting between symbols

    return cycle_stats


def print_telemetry_status(engine: V931ShadowEngine):
    """Print current open positions and summary metrics."""
    summary = engine.update_summary()
    print("\n" + "=" * 90, flush=True)
    print(" 📡 V9.3.1 SHADOW TELEMETRY STATUS", flush=True)
    print("=" * 90, flush=True)
    print(f" Active Candidate:     V9.3.1 (Refined Conservative 15M Layer)", flush=True)
    print(f" Monitored Universe:   Tier 1 {list(TIER_1)} & Tier 2 {list(TIER_2)}", flush=True)
    print(f" Active Setups:        {sorted(list(ACTIVE_SETUPS_V931))}", flush=True)
    print(f" Open Shadow Trades:   {len(engine.open_positions)}", flush=True)
    print(f" Completed Trades:     {summary.get('total_outcomes', 0)}", flush=True)
    print(f" Win Rate:             {summary.get('win_rate', 0.0)*100:.1f}% ({summary.get('wins', 0)} wins / {summary.get('losses', 0)} losses)", flush=True)
    print(f" Profit Factor:        {summary.get('profit_factor', 0.0):.2f}", flush=True)
    print(f" Net Realized R:       {summary.get('net_realized_r', 0.0):+.2f} R", flush=True)
    print(f" Expectancy / Trade:   {summary.get('expectancy_r', 0.0):+.4f} R", flush=True)
    print("-" * 90, flush=True)

    if engine.open_positions:
        print(" Currently Open Shadow Positions:", flush=True)
        for sym, pos in engine.open_positions.items():
            side_str = "LONG" if pos.side == 1 else "SHORT"
            print(f"  -> {sym:<10} | {pos.setup:<20} | {side_str} @ ${pos.entry_price:,.4f} | SL: ${pos.stop_price:,.4f} | TP: ${pos.target_price:,.4f} | Held: {pos.bars_held} bars", flush=True)
    else:
        print(" (No active shadow positions currently open)", flush=True)
    print("=" * 90 + "\n", flush=True)


def main():
    parser = argparse.ArgumentParser(description="V9.3.1 Live Shadow Layer Observer Daemon")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background observer loop")
    parser.add_argument("--once", action="store_true", help="Execute single scan cycle across universe and exit")
    parser.add_argument("--status", action="store_true", help="Display current telemetry status summary and exit")
    parser.add_argument("--poll-interval", type=int, default=15, help="Polling interval in seconds (default: 15)")
    parser.add_argument("--data-dir", default="data/shadow_v9_3_1", help="Telemetry storage path")
    args = parser.parse_args()

    engine = V931ShadowEngine(data_dir=args.data_dir)

    if args.status:
        print_telemetry_status(engine)
        return

    if args.once:
        print("[V9.3.1 SHADOW] Executing single universe scan...")
        stats = run_shadow_cycle(engine, verbose=True)
        print(f"[V9.3.1 SHADOW] Single scan complete: Evaluated {stats['evaluated']} symbols, Admitted {stats['admitted']}, Resolved {stats['outcomes']} outcomes.")
        print_telemetry_status(engine)
        return

    print("=" * 90, flush=True)
    print(" 🚀 CANDIDATE V9.3.1 SHADOW TELEMETRY OBSERVER DAEMON INITIALIZED", flush=True)
    print("=" * 90, flush=True)
    print(f" Safety Guarantee:     STRICTLY OBSERVER ONLY (Zero Execution / Read-Only)", flush=True)
    print(f" Monitored Symbols:    {', '.join(SHADOW_SYMBOLS)}", flush=True)
    print(f" Polling Interval:     Every {args.poll_interval}s", flush=True)
    print(f" Storage Directory:    {args.data_dir}", flush=True)
    print("=" * 90 + "\n", flush=True)

    last_status_print = 0.0
    last_heartbeat_print = time.time()
    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            stats = run_shadow_cycle(engine, verbose=False)

            now = time.time()
            if now - last_heartbeat_print >= 60:
                t_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                print(
                    f"[{t_str}] [SHADOW HEARTBEAT] Cycle #{cycle_count} | Evaluated: {stats['evaluated']} | "
                    f"Open Positions: {len(engine.open_positions)} | Admitted Pending: {len(engine.pending_admissions)}",
                    flush=True,
                )
                last_heartbeat_print = now

            if now - last_status_print >= 300:  # Full status every 5 minutes
                print_telemetry_status(engine)
                last_status_print = now

            time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            print("\n🛑 Shadow daemon stopped cleanly by user.", flush=True)
            engine.save_state()
            break
        except Exception as e:
            print(f"[SHADOW DAEMON RECOVERED EXCEPTION] {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
