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
from itertools import combinations
from math import isfinite
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import argparse
import csv
import json

CHANNELS = ("FIBONACCI", "MSS_SHIFT", "5MA_CONSENSUS", "POTATO_SR", "DIVERGENCE")
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
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _stats(label: str, events: Sequence[AlphaEvent]) -> ChannelStats:
    values = [e.realized_net_r for e in events]
    return ChannelStats(
        label=label,
        trades=len(values),
        wins=sum(v > 0 for v in values),
        win_rate=(sum(v > 0 for v in values) / len(values)) if values else 0.0,
        profit_factor=_pf(values),
        net_r=sum(values),
        expectancy_r=(sum(values) / len(values)) if values else 0.0,
        avg_friction_r=(sum(e.friction_r for e in events) / len(events)) if events else 0.0,
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
    for baseline, added in combinations(CHANNELS, 2):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline V8.1 production alpha attribution audit")
    parser.add_argument("--events", required=True, help="Normalized channel-event CSV")
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    parser.add_argument("--output", default="v8_1_report.json")
    args = parser.parse_args()
    events = load_events_csv(args.events)
    report = build_report(events, min_trades=max(1, args.min_trades))
    Path(args.output).write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report["recommendation"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
