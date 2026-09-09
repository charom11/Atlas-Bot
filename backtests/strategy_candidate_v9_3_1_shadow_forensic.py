#!/usr/bin/env python3
"""Offline forensic analyzer for V9.3.1 shadow telemetry.

Research-only: reads local text/JSON files only. No exchange, network, or
order-placement imports. Compares resolved forward shadow outcomes with the
stored V9.3.1 historical audit and highlights where the forward sample differs.

This is deliberately descriptive rather than adaptive: it does not change
strategy thresholds, disable setups, or produce trading commands.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

OUTCOME_RE = re.compile(
    r"\[SHADOW OUTCOME\].*?\[([A-Z0-9]+USDT)\] ([A-Z_]+) "
    r"(TARGET|STOP|TIMEOUT).*?Net R: ([+-]?\d+\.\d+) R "
    r"\(Empirical Net: ([+-]?\d+\.\d+) R, Slip: ([+-]?\d+\.\d+)R, "
    r"Funding: ([+-]?\d+\.\d+)R\).*?Held: (\d+) bars"
)
SUMMARY_RE = re.compile(
    r"Completed Trades:\s*(\d+).*?Win Rate:\s*([\d.]+)% "
    r"\((\d+) wins / (\d+) losses\).*?Profit Factor:\s*([\d.]+).*?"
    r"Net Realized R:\s*([+-]?\d+\.\d+) R.*?Expectancy / Trade:\s*([+-]?\d+\.\d+) R",
    re.S,
)

@dataclass(frozen=True)
class ForwardOutcome:
    symbol: str
    setup: str
    result: str
    net_r: float
    empirical_r: float
    slippage_r: float
    funding_r: float
    held_bars: int


def parse_outcomes(text: str) -> list[ForwardOutcome]:
    rows = []
    for m in OUTCOME_RE.finditer(text):
        rows.append(ForwardOutcome(
            symbol=m.group(1), setup=m.group(2), result=m.group(3),
            net_r=float(m.group(4)), empirical_r=float(m.group(5)),
            slippage_r=float(m.group(6)), funding_r=float(m.group(7)),
            held_bars=int(m.group(8)),
        ))
    return rows


def parse_latest_summary(text: str) -> dict[str, object] | None:
    matches = list(SUMMARY_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    return {
        "completed_trades": int(m.group(1)),
        "win_rate_pct": float(m.group(2)),
        "wins": int(m.group(3)),
        "losses": int(m.group(4)),
        "profit_factor": float(m.group(5)),
        "net_realized_r": float(m.group(6)),
        "expectancy_r": float(m.group(7)),
    }


def grouped(rows: list[ForwardOutcome], key: str) -> list[dict[str, object]]:
    groups = defaultdict(list)
    for row in rows:
        groups[getattr(row, key)].append(row)
    result = []
    for name, items in sorted(groups.items()):
        wins = sum(x.result == "TARGET" for x in items)
        net = sum(x.net_r for x in items)
        empirical = sum(x.empirical_r for x in items)
        gross_win = sum(x.net_r for x in items if x.net_r > 0)
        gross_loss = -sum(x.net_r for x in items if x.net_r < 0)
        pf = gross_win / gross_loss if gross_loss else (999.0 if gross_win else 0.0)
        result.append({
            key: name, "trades": len(items), "wins": wins,
            "win_rate_pct": round(100 * wins / len(items), 2),
            "net_r": round(net, 4), "empirical_net_r": round(empirical, 4),
            "profit_factor": round(pf, 4),
            "slippage_r": round(sum(x.slippage_r for x in items), 4),
            "funding_r": round(sum(x.funding_r for x in items), 4),
            "avg_hold_bars": round(sum(x.held_bars for x in items) / len(items), 3),
        })
    return result


def analyze(shadow_log: Path, historical_report: Path | None = None) -> dict[str, object]:
    text = shadow_log.read_text(encoding="utf-8", errors="replace")
    rows = parse_outcomes(text)
    summary = parse_latest_summary(text)
    report = None
    if historical_report and historical_report.exists():
        report = json.loads(historical_report.read_text(encoding="utf-8"))

    theoretical = sum(x.net_r for x in rows)
    empirical = sum(x.empirical_r for x in rows)
    slippage = sum(x.slippage_r for x in rows)
    funding = sum(x.funding_r for x in rows)
    wins = sum(x.result == "TARGET" for x in rows)
    losses = sum(x.result == "STOP" for x in rows)
    gross_win = sum(x.net_r for x in rows if x.net_r > 0)
    gross_loss = -sum(x.net_r for x in rows if x.net_r < 0)
    pf = gross_win / gross_loss if gross_loss else (999.0 if gross_win else 0.0)

    historical = None
    if report:
        historical = {
            "dataset": report.get("dataset"),
            "portfolio": report.get("portfolio"),
            "asset_results": report.get("asset_results", report.get("assets")),
        }

    return {
        "candidate": "V9.3.1",
        "test": "offline_shadow_forensic",
        "inputs": {
            "shadow_log": str(shadow_log),
            "historical_report": str(historical_report) if historical_report else None,
        },
        "forward": {
            "parsed_outcomes": len(rows),
            "latest_daemon_summary": summary,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(100 * wins / len(rows), 2) if rows else 0.0,
            "profit_factor_from_resolved_outcomes": round(pf, 4),
            "theoretical_net_r": round(theoretical, 4),
            "empirical_net_r": round(empirical, 4),
            "slippage_r": round(slippage, 4),
            "funding_r": round(funding, 4),
            "avg_hold_bars": round(sum(x.held_bars for x in rows) / len(rows), 3) if rows else 0.0,
        },
        "by_setup": grouped(rows, "setup"),
        "by_asset": grouped(rows, "symbol"),
        "historical_reference": historical,
        "diagnostic_flags": {
            "small_sample": len(rows) < 50,
            "mss_dominant": bool(rows) and sum(x.setup == "MSS_SHIFT" for x in rows) / len(rows) >= 0.75,
            "large_slippage_drag": slippage >= 2.0,
            "forward_net_negative": theoretical < 0,
            "execution_gap": abs(empirical - theoretical) >= 2.0,
            "correlated_mss_cluster_possible": sum(x.setup == "MSS_SHIFT" for x in rows) >= 4,
        },
        "interpretation": [
            "Descriptive only; no strategy parameters are modified.",
            "OHLCV historical replay cannot reproduce live bid/ask, order-book, latency, or funding telemetry.",
            "Forward shadow outcomes must remain separate from production trading results.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline V9.3.1 shadow forensic analyzer")
    parser.add_argument("--shadow-log", required=True)
    parser.add_argument("--historical-report", default=None)
    parser.add_argument("--output", default="backtests/v9_3_1_shadow_forensic_report.json")
    args = parser.parse_args()
    result = analyze(Path(args.shadow_log), Path(args.historical_report) if args.historical_report else None)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    f = result["forward"]
    print(f"Resolved outcomes: {f['parsed_outcomes']}")
    print(f"Win rate:          {f['win_rate_pct']:.2f}%")
    print(f"PF:                {f['profit_factor_from_resolved_outcomes']:.2f}")
    print(f"Theoretical net:   {f['theoretical_net_r']:+.2f} R")
    print(f"Empirical net:     {f['empirical_net_r']:+.2f} R")
    print(f"Slippage drag:     {f['slippage_r']:+.2f} R")
    print(f"Funding:           {f['funding_r']:+.2f} R")
    print(f"Report:            {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
