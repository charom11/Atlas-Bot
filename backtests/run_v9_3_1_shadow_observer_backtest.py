#!/usr/bin/env python3
"""Historical replay of the V9.3.1 shadow observer policy.

Research-only: no exchange client, network, or order-placement imports.
Uses the same V9.3.1 admission policy and shadow outcome convention while
precomputing indicators once per asset for practical 15m replay.
Historical OHLCV cannot reproduce bid/ask, order-book, latency, or funding;
those fields are explicitly reported unavailable rather than invented.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_candidate_v9 import (  # noqa: E402
    LONG, SHORT, FLAT, SETUPS, REGIMES, Trade,
    add_indicators, classify_regime, setup_votes, summarize, load_ohlcv_csv,
)
from strategy_candidate_v9_3_1 import (  # noqa: E402
    V931Config, ACTIVE_SETUPS_V931, DISABLED_SETUPS_V931,
    ALLOWED_REGIMES_V931, GATED_REGIMES_V931, asset_allowed,
    admit_opportunity, target_stop_atr, TIER_1, TIER_2, TIER_3,
)

CACHE_DIR = ROOT / "backtests" / "historical_data_cache"
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT",
]

@dataclass(frozen=True)
class ReplayConfig:
    friction_r: float = 0.026
    max_hold_bars: int = 32
    warmup_bars: int = 201

@dataclass(frozen=True)
class ReplayResult:
    symbol: str
    bars: int
    opportunities_evaluated: int
    admitted: int
    resolved: int
    trades: list[Trade]


def _prepare(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    data = add_indicators(df.copy())
    data["symbol"] = symbol
    data["regime"] = data.apply(classify_regime, axis=1)
    return data


def replay_symbol(df: pd.DataFrame, symbol: str,
                   config: V931Config = V931Config(),
                   replay: ReplayConfig = ReplayConfig()) -> ReplayResult:
    """Replay the shadow observer bar state machine against historical OHLCV."""
    if df.empty or len(df) <= replay.warmup_bars + 1 or not asset_allowed(symbol, config):
        return ReplayResult(symbol, len(df), 0, 0, 0, [])

    data = _prepare(df, symbol)
    opens = data["open"].to_numpy()
    highs = data["high"].to_numpy()
    lows = data["low"].to_numpy()
    closes = data["close"].to_numpy()
    timestamps = [str(x) for x in data.index]

    trades: list[Trade] = []
    pending = None
    position = None
    evaluated = 0
    admitted = 0

    # Same order as V931ShadowEngine.evaluate_bar:
    # update -> open pending at current open -> evaluate current closed bar.
    for i in range(replay.warmup_bars, len(data)):
        row, prev = data.iloc[i], data.iloc[i - 1]

        if position is not None:
            position["bars_held"] += 1
            side, stop, target = position["side"], position["stop"], position["target"]
            stop_hit = (lows[i] <= stop) if side == LONG else (highs[i] >= stop)
            target_hit = (highs[i] >= target) if side == LONG else (lows[i] <= target)
            timeout_hit = position["bars_held"] >= replay.max_hold_bars
            if stop_hit or target_hit or timeout_hit:
                exit_px = stop if stop_hit else target if target_hit else closes[i]
                denom = max(abs(position["entry"] - stop), 1e-12)
                gross_r = side * (exit_px - position["entry"]) / denom
                net_r = gross_r - replay.friction_r
                trades.append(Trade(
                    timestamps[i], symbol, side, position["setup"], position["regime"],
                    position["entry"], exit_px, net_r, replay.friction_r,
                    position["bars_held"],
                ))
                position = None

        if pending is not None and position is None:
            opp, signal_index = pending
            entry = float(opens[i])
            stop_mult, target_mult = target_stop_atr(opp.setup, config)
            stop = entry - opp.side * stop_mult * opp.atr
            target = entry + opp.side * target_mult * opp.atr
            position = {
                "side": opp.side, "setup": opp.setup, "regime": opp.regime,
                "entry": entry, "stop": stop, "target": target,
                "bars_held": 0, "signal_index": signal_index,
            }
            pending = None

        evaluated += 1
        votes = setup_votes(row, prev)
        opp = admit_opportunity(row, votes, config)
        if opp is not None and opp.admitted:
            admitted += 1
            if position is None and pending is None:
                pending = (opp, i)

    return ReplayResult(symbol, len(data), evaluated, admitted, len(trades), trades)


def _dataset_path(cache_dir: Path, symbol: str, dataset: str) -> Path:
    if dataset == "4year":
        return cache_dir / f"{symbol}_15m_4year_2022-09-01.csv"
    candidates = [
        cache_dir / f"{symbol}_15m_from_2025-07-01.csv",
        cache_dir / f"{symbol}_15m_from_2024-08-25.csv",
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


def load_assets(cache_dir: Path, dataset: str) -> dict[str, pd.DataFrame]:
    assets = {}
    for symbol in SYMBOLS:
        path = _dataset_path(cache_dir, symbol, dataset)
        if not path.exists():
            print(f"[SKIP] {symbol}: missing {path}")
            continue
        df = load_ohlcv_csv(str(path))
        df["symbol"] = symbol
        assets[symbol] = df
    return assets


def _stats_dict(trades: Iterable[Trade]) -> dict:
    return asdict(summarize(list(trades)))


def run(dataset: str, cache_dir: Path, output: Path, friction_r: float = 0.026) -> dict:
    config = V931Config()
    replay = ReplayConfig(friction_r=friction_r)
    assets = load_assets(cache_dir, dataset)
    all_trades: list[Trade] = []
    asset_rows = []

    for symbol, df in assets.items():
        result = replay_symbol(df, symbol, config, replay)
        all_trades.extend(result.trades)
        st = summarize(result.trades)
        asset_rows.append({
            "symbol": symbol, "bars": result.bars,
            "opportunities_evaluated": result.opportunities_evaluated,
            "admitted": result.admitted, "resolved": result.resolved,
            "stats": _stats_dict(result.trades),
        })
        print(f"{symbol:<10} bars={result.bars:>8,} evaluated={result.opportunities_evaluated:>8,} admitted={result.admitted:>6,} resolved={result.resolved:>6,} PF={st.profit_factor:.2f} NetR={st.net_r:+.2f} DD={st.max_drawdown_r:.2f}")

    portfolio = summarize(all_trades)
    result = {
        "candidate": "V9.3.1",
        "test": "shadow_observer_historical_replay",
        "dataset": dataset, "timeframe": "15m", "universe": SYMBOLS,
        "eligible_assets": [s for s in SYMBOLS if asset_allowed(s, config)],
        "config": asdict(config), "replay_config": asdict(replay),
        "observer_policy": {
            "active_setups": sorted(ACTIVE_SETUPS_V931),
            "disabled_setups": sorted(DISABLED_SETUPS_V931),
            "allowed_regimes": sorted(ALLOWED_REGIMES_V931),
            "gated_regimes": sorted(GATED_REGIMES_V931),
            "tier_1": list(TIER_1), "tier_2": list(TIER_2), "tier_3": list(TIER_3),
        },
        "portfolio": _stats_dict(all_trades), "assets": asset_rows,
        "historical_market_context": {
            "bid_ask": "unavailable_from_ohlcv",
            "order_book": "unavailable_from_ohlcv",
            "latency": "unavailable_from_ohlcv",
            "funding": "not_invented; use separate sensitivity test",
        },
        "parity_note": "Uses the same V9.3.1 admission functions and shadow outcome convention; OHLCV cannot reproduce live market microstructure telemetry.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("\n" + "=" * 90)
    print("V9.3.1 SHADOW OBSERVER HISTORICAL REPLAY")
    print("=" * 90)
    print(f"Dataset:       {dataset} / 15m")
    print(f"Resolved:      {portfolio.trades:,}")
    print(f"Win rate:      {portfolio.win_rate * 100:.1f}%")
    print(f"Profit factor: {portfolio.profit_factor:.2f}")
    print(f"Net R:         {portfolio.net_r:+.2f} R")
    print(f"Expectancy:    {portfolio.expectancy_r:+.4f} R")
    print(f"Max DD:        {portfolio.max_drawdown_r:.2f} R")
    print(f"Report:        {output}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical V9.3.1 shadow observer replay")
    parser.add_argument("--dataset", choices=("1year", "4year"), default="4year")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR))
    parser.add_argument("--output", default="backtests/v9_3_1_shadow_observer_backtest_report.json")
    parser.add_argument("--friction-r", type=float, default=0.026)
    args = parser.parse_args()
    run(args.dataset, Path(args.cache_dir), Path(args.output), args.friction_r)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
