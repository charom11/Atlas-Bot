"""Offline Strategy Candidate V8.1: Production Alpha Optimizer.

Research-only. This module never imports main.py and never places orders.

V8.1 answers a narrower question than V8: which of the five existing Atlas
production channels add *incremental* net expectancy, and under which market
conditions? It deliberately avoids inventing new indicators or hard-coding
asset blacklists before the evidence supports them.

Input is a normalized event table. Each row represents a candidate opportunity
and may contain one or more channel votes plus realized net R. The engine can
also evaluate an already-labelled channel result table where each row has a
single channel.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from itertools import combinations, permutations
from math import isfinite
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import argparse
import csv
import json
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CHANNELS = ("5MA_CONSENSUS", "MSS_SHIFT", "FIBONACCI", "POTATO_SR", "DIVERGENCE")
SIDES = ("LONG", "SHORT")
REGIMES = ("RISK_ON", "NEUTRAL", "RISK_OFF", "EXTREME_VOL", "BREAKDOWN", "UNAVAILABLE")

DEFAULT_MIN_TRADES = 50
DEFAULT_MIN_EXPECTANCY = 0.0


@dataclass(frozen=True)
class AlphaEvent:
    symbol: str
    timestamp: str
    regime: str
    side: str
    realized_net_r: float
    friction_r: float = 0.0
    channels: tuple[str, ...] = ()

    @property
    def gross_r(self) -> float:
        return self.realized_net_r + self.friction_r


@dataclass(frozen=True)
class ChannelStats:
    label: str
    trades: int
    wins: int
    win_rate: float
    profit_factor: float
    net_r: float
    expectancy_r: float
    avg_friction_r: float


@dataclass(frozen=True)
class IncrementalResult:
    baseline: str
    added: str
    baseline_trades: int
    combined_trades: int
    baseline_expectancy_r: float
    combined_expectancy_r: float
    incremental_expectancy_r: float
    baseline_profit_factor: float
    combined_profit_factor: float
    useful: bool


@dataclass(frozen=True)
class SliceResult:
    dimension: str
    value: str
    trades: int
    net_r: float
    expectancy_r: float
    profit_factor: float
    win_rate: float


def _finite(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if isfinite(x) else default


def _pf(values: Sequence[float]) -> float:
    gross_win = sum(x for x in values if x > 0)
    gross_loss = -sum(x for x in values if x < 0)
    if gross_loss == 0:
        return 999.0 if gross_win > 0 else 0.0
    return round(gross_win / gross_loss, 4)


def _stats(label: str, events: Sequence[AlphaEvent]) -> ChannelStats:
    values = [e.realized_net_r for e in events]
    return ChannelStats(
        label=label,
        trades=len(values),
        wins=sum(v > 0 for v in values),
        win_rate=(sum(v > 0 for v in values) / len(values)) if values else 0.0,
        profit_factor=_pf(values),
        net_r=round(sum(values), 6),
        expectancy_r=round((sum(values) / len(values)), 6) if values else 0.0,
        avg_friction_r=round((sum(e.friction_r for e in events) / len(events)), 6) if events else 0.0,
    )


def normalize_channels(channels: Iterable[str]) -> tuple[str, ...]:
    allowed = set(CHANNELS)
    return tuple(dict.fromkeys(c.strip().upper() for c in channels if c.strip().upper() in allowed))


def evaluate_channels(events: Sequence[AlphaEvent]) -> dict[str, ChannelStats]:
    """Evaluate each production channel without assigning arbitrary weights."""
    result: dict[str, ChannelStats] = {}
    for channel in CHANNELS:
        selected = [e for e in events if channel in e.channels]
        result[channel] = _stats(channel, selected)
    return result


def evaluate_slices(events: Sequence[AlphaEvent]) -> list[SliceResult]:
    """Attribute realized results by regime, asset, and direction."""
    slices: list[SliceResult] = []
    dimensions = {
        "regime": lambda e: e.regime,
        "symbol": lambda e: e.symbol,
        "side": lambda e: e.side,
    }
    for dimension, key_fn in dimensions.items():
        values = sorted({key_fn(e) for e in events})
        for value in values:
            subset = [e for e in events if key_fn(e) == value]
            s = _stats(value, subset)
            slices.append(SliceResult(dimension, value, s.trades, s.net_r, s.expectancy_r, s.profit_factor, s.win_rate))
    return slices


def evaluate_channel_slices(events: Sequence[AlphaEvent]) -> list[SliceResult]:
    """Evaluate each channel inside each regime/asset/direction slice."""
    result: list[SliceResult] = []
    for channel in CHANNELS:
        channel_events = [e for e in events if channel in e.channels]
        for row in evaluate_slices(channel_events):
            result.append(SliceResult(f"{channel}:{row.dimension}", row.value, row.trades, row.net_r, row.expectancy_r, row.profit_factor, row.win_rate))
    return result


def evaluate_incremental_pairs(
    events: Sequence[AlphaEvent],
    min_trades: int = DEFAULT_MIN_TRADES,
) -> list[IncrementalResult]:
    """Measure whether one channel adds expectancy when another is present.

    This is intentionally descriptive, not a fitted model: the same realized
    event outcome is used for both the baseline and combined cohorts, so no
    future information is introduced.
    """
    result: list[IncrementalResult] = []
    for baseline, added in permutations(CHANNELS, 2):
        base_events = [e for e in events if baseline in e.channels]
        combined = [e for e in base_events if added in e.channels]
        if len(base_events) < min_trades or len(combined) < min_trades:
            continue
        base = _stats(baseline, base_events)
        both = _stats(f"{baseline}+{added}", combined)
        result.append(IncrementalResult(
            baseline=baseline,
            added=added,
            baseline_trades=base.trades,
            combined_trades=both.trades,
            baseline_expectancy_r=base.expectancy_r,
            combined_expectancy_r=both.expectancy_r,
            incremental_expectancy_r=both.expectancy_r - base.expectancy_r,
            baseline_profit_factor=base.profit_factor,
            combined_profit_factor=both.profit_factor,
            useful=both.expectancy_r > base.expectancy_r and both.profit_factor >= base.profit_factor,
        ))
    return result


def evaluate_combinations(
    events: Sequence[AlphaEvent],
    max_size: int = 3,
    min_trades: int = DEFAULT_MIN_TRADES,
) -> dict[str, ChannelStats]:
    """Return only sufficiently-sampled 2- and 3-channel cohorts."""
    result: dict[str, ChannelStats] = {}
    for size in range(2, min(max_size, len(CHANNELS)) + 1):
        for combo in combinations(CHANNELS, size):
            label = "+".join(combo)
            subset = [e for e in events if all(c in e.channels for c in combo)]
            if len(subset) >= min_trades:
                result[label] = _stats(label, subset)
    return result


def walk_forward(
    events: Sequence[AlphaEvent],
    cutoffs: Sequence[tuple[str, str]],
) -> list[ChannelStats]:
    """Score explicit non-overlapping periods using ISO timestamp strings."""
    result: list[ChannelStats] = []
    for label, start_end in cutoffs:
        start, end = start_end.split("/", 1)
        subset = [e for e in events if start <= e.timestamp < end]
        result.append(_stats(label, subset))
    return result


def rank_channels(stats: Mapping[str, ChannelStats], min_trades: int = DEFAULT_MIN_TRADES) -> list[ChannelStats]:
    """Rank by expectancy, then PF, while excluding under-sampled channels."""
    return sorted(
        (s for s in stats.values() if s.trades >= min_trades),
        key=lambda s: (s.expectancy_r, s.profit_factor, s.net_r),
        reverse=True,
    )


def recommend_gates(
    channel_stats: Mapping[str, ChannelStats],
    pair_results: Sequence[IncrementalResult],
    min_trades: int = DEFAULT_MIN_TRADES,
) -> dict[str, object]:
    """Produce evidence-based research recommendations, never live settings."""
    leaders = rank_channels(channel_stats, min_trades)
    useful_pairs = [asdict(x) for x in pair_results if x.useful]
    return {
        "anchor_candidates": [s.label for s in leaders],
        "useful_confirmations": useful_pairs,
        "warning": "Research output only; do not wire these gates into main.py without OOS validation.",
    }


def _parse_bool_channels(raw: str) -> tuple[str, ...]:
    return normalize_channels(raw.replace("|", ",").split(","))


def load_events_csv(path: str | Path) -> list[AlphaEvent]:
    """Load normalized event CSV.

    Required columns: symbol,timestamp,regime,side,realized_net_r,channels.
    Optional column: friction_r.
    """
    events: list[AlphaEvent] = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            side = str(row.get("side", "")).upper()
            if side not in SIDES:
                continue
            events.append(AlphaEvent(
                symbol=str(row.get("symbol", "UNKNOWN")).upper(),
                timestamp=str(row.get("timestamp", "")),
                regime=str(row.get("regime", "UNAVAILABLE")).upper(),
                side=side,
                realized_net_r=_finite(row.get("realized_net_r")),
                friction_r=_finite(row.get("friction_r")),
                channels=_parse_bool_channels(str(row.get("channels", ""))),
            ))
    return events


def build_report(events: Sequence[AlphaEvent], min_trades: int = DEFAULT_MIN_TRADES) -> dict[str, object]:
    channels = evaluate_channels(events)
    pairs = evaluate_incremental_pairs(events, min_trades=min_trades)
    combos = evaluate_combinations(events, max_size=3, min_trades=min_trades)
    return {
        "events": len(events),
        "channels": {k: asdict(v) for k, v in channels.items()},
        "slices": [asdict(x) for x in evaluate_slices(events)],
        "channel_slices": [asdict(x) for x in evaluate_channel_slices(events)],
        "incremental_pairs": [asdict(x) for x in pairs],
        "combinations": {k: asdict(v) for k, v in combos.items()},
        "recommendation": recommend_gates(channels, pairs, min_trades=min_trades),
    }


def generate_events_from_v8_cache(
    cache_dir: str = "backtests/historical_data_cache",
    timeframe: str = "1h",
) -> list[AlphaEvent]:
    """Extract normalized AlphaEvents across 11 perpetual assets from 4-year V8 simulation."""
    from strategy_candidate_v8 import (
        load_v8_historical_cache,
        compute_v8_asset_metrics,
        simulate_v8_portfolio,
    )
    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
        "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT"
    ]
    print("Loading 4-year historical cache and synchronizing timeline...", flush=True)
    data_map, channel_map, timeline = load_v8_historical_cache(cache_dir, symbols, timeframe=timeframe)
    print("Computing walk-forward asset baselines...", flush=True)
    asset_metrics_map = compute_v8_asset_metrics(data_map, channel_map)
    print("Simulating multi-channel candidate activations across universe...", flush=True)
    sim = simulate_v8_portfolio(
        data_map=data_map,
        channel_map=channel_map,
        timeline=timeline,
        target_symbols=symbols,
        asset_metrics_map=asset_metrics_map,
        mode="UNWEIGHTED_ENSEMBLE",
        cost_multiplier=1.0,
    )
    events = []
    for t in sim["closed_trades"]:
        chans = t.get("channels", (t["channel"],))
        events.append(AlphaEvent(
            symbol=str(t["symbol"]),
            timestamp=str(t["timestamp"]),
            regime=str(t.get("regime", "NEUTRAL")),
            side=str(t["side"]),
            realized_net_r=_finite(t["r_multiple"]),
            friction_r=_finite(t.get("friction_r", 0.05)),
            channels=tuple(chans),
        ))
    return events


def export_events_csv(events: Sequence[AlphaEvent], path: str | Path) -> None:
    """Save normalized events to CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["symbol", "timestamp", "regime", "side", "realized_net_r", "friction_r", "channels"])
        for e in events:
            writer.writerow([e.symbol, e.timestamp, e.regime, e.side, f"{e.realized_net_r:.4f}", f"{e.friction_r:.4f}", "|".join(e.channels)])


def print_institutional_report(report: dict[str, object]) -> None:
    """Display comprehensive institutional alpha attribution report."""
    print("\n" + "=" * 95)
    print(" [AUDIT] STRATEGY CANDIDATE V8.1: PRODUCTION ALPHA OPTIMIZATION & ATTRIBUTION REPORT")
    print("=" * 95)
    print(f" Total Evaluated Trade Events: {report['events']:,}\n")

    # 1. Standalone Channel Attribution
    print(" [1. STANDALONE PRODUCTION CHANNEL ATTRIBUTION]")
    print(f" {'Channel':<16} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9} | {'Avg Frict':>10}")
    print("-" * 80)
    for ch, s in report["channels"].items():
        print(f" {ch:<16} | {s['trades']:>8,} | {s['win_rate']*100:>8.1f}% | {s['profit_factor']:>6.2f} | {s['net_r']:>+10.2f} | {s['expectancy_r']:>+9.4f} | {s['avg_friction_r']:>10.4f}")
    print("-" * 80 + "\n")

    # 2. Incremental Pairwise Confirmations
    print(" [2. INCREMENTAL PAIRWISE ATTRIBUTION (Does B add expectancy over Baseline A?)]")
    print(f" {'Baseline':<16} + {'Added':<16} | {'Trades':>8} | {'Base Exp':>9} | {'Comb Exp':>9} | {'Inc Exp (R)':>11} | {'Useful':>7}")
    print("-" * 88)
    for p in report["incremental_pairs"]:
        u_str = "YES" if p["useful"] else "NO"
        print(f" {p['baseline']:<16} + {p['added']:<16} | {p['combined_trades']:>8,} | {p['baseline_expectancy_r']:>+9.4f} | {p['combined_expectancy_r']:>+9.4f} | {p['incremental_expectancy_r']:>+11.4f} | {u_str:>7}")
    print("-" * 88 + "\n")

    # 3. Top Multi-Channel Confluences
    print(" [3. MULTI-CHANNEL CONFLUENCE COHORTS (2- and 3-Channel Combinations)]")
    print(f" {'Cohort Combination':<36} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9}")
    print("-" * 90)
    combos = sorted(report["combinations"].values(), key=lambda c: c["expectancy_r"], reverse=True)
    for c in combos[:12]:
        print(f" {c['label']:<36} | {c['trades']:>8,} | {c['win_rate']*100:>8.1f}% | {c['profit_factor']:>6.2f} | {c['net_r']:>+10.2f} | {c['expectancy_r']:>+9.4f}")
    print("-" * 90 + "\n")

    # 4. Regime Slicing
    print(" [4. MARKET REGIME ATTRIBUTION]")
    print(f" {'Regime':<16} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9}")
    print("-" * 70)
    regimes = [s for s in report["slices"] if s["dimension"] == "regime"]
    for s in regimes:
        print(f" {s['value']:<16} | {s['trades']:>8,} | {s['win_rate']*100:>8.1f}% | {s['profit_factor']:>6.2f} | {s['net_r']:>+10.2f} | {s['expectancy_r']:>+9.4f}")
    print("-" * 70 + "\n")

    # 5. Asset Slicing
    print(" [5. ASSET ATTRIBUTION]")
    print(f" {'Asset':<12} | {'Trades':>8} | {'Win Rate':>9} | {'PF':>6} | {'Net R':>10} | {'Exp (R)':>9}")
    print("-" * 65)
    assets = sorted([s for s in report["slices"] if s["dimension"] == "symbol"], key=lambda s: s["net_r"], reverse=True)
    for s in assets:
        print(f" {s['value']:<12} | {s['trades']:>8,} | {s['win_rate']*100:>8.1f}% | {s['profit_factor']:>6.2f} | {s['net_r']:>+10.2f} | {s['expectancy_r']:>+9.4f}")
    print("-" * 65 + "\n")

    # 6. Recommendation
    rec = report["recommendation"]
    print("=" * 95)
    print(" [6. EVIDENCE-BASED RESEARCH RECOMMENDATIONS]")
    print("=" * 95)
    print(f" Anchor Candidates (Highest Standalone Net Expectancy): {', '.join(rec['anchor_candidates'])}")
    print(f" Statistically Useful Confirmations: {len(rec['useful_confirmations'])} detected")
    for u in rec['useful_confirmations']:
        print(f"   * {u['baseline']} + {u['added']}: Baseline Exp = {u['baseline_expectancy_r']:+.4f} -> Combined Exp = {u['combined_expectancy_r']:+.4f} (Inc: {u['incremental_expectancy_r']:+.4f} R, PF {u['combined_profit_factor']:.2f})")
    print(f"\n [WARNING] {rec['warning']}")
    print("=" * 95 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline V8.1 production alpha attribution audit")
    parser.add_argument("--events", help="Normalized channel-event CSV (optional; if omitted, generates from 4-year cache)")
    parser.add_argument("--cache-dir", default="backtests/historical_data_cache", help="Path to 4-year historical cache")
    parser.add_argument("--timeframe", default="1h", choices=["1h", "15m"], help="Evaluation timeframe (default: 1h)")
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    parser.add_argument("--output", default="backtests/v8_1_report.json")
    parser.add_argument("--export-events", default="backtests/v8_1_events_4year.csv")
    args = parser.parse_args()

    if args.events and Path(args.events).exists():
        print(f"Loading events from {args.events}...", flush=True)
        events = load_events_csv(args.events)
    else:
        print("Extracting events from 4-year historical cache via V8 engine...", flush=True)
        events = generate_events_from_v8_cache(cache_dir=args.cache_dir, timeframe=args.timeframe)
        if args.export_events:
            export_events_csv(events, args.export_events)
            print(f"Exported {len(events):,} normalized events to {args.export_events}", flush=True)

    report = build_report(events, min_trades=max(1, args.min_trades))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print_institutional_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
