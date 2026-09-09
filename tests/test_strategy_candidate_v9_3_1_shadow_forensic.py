from __future__ import annotations

import json
from pathlib import Path

from backtests.strategy_candidate_v9_3_1_shadow_forensic import (
    analyze,
    parse_latest_summary,
    parse_outcomes,
)


def sample_log() -> str:
    return """
[SHADOW OUTCOME] [ETHUSDT] MSS_SHIFT STOP -> Net R: -1.03 R (Empirical Net: -1.50 R, Slip: +0.470R, Funding: +0.001R) Entry: $1 | Exit: $2 | Held: 3 bars
[SHADOW OUTCOME] [XRPUSDT] MSS_SHIFT TARGET -> Net R: +1.57 R (Empirical Net: +1.40 R, Slip: +0.170R, Funding: +0.001R) Entry: $1 | Exit: $2 | Held: 2 bars
[SHADOW OUTCOME] [SOLUSDT] TREND_CONTINUATION STOP -> Net R: -1.03 R (Empirical Net: -1.20 R, Slip: +0.170R, Funding: +0.000R) Entry: $1 | Exit: $2 | Held: 5 bars
Completed Trades: 3
Win Rate: 33.3% (1 wins / 2 losses)
Profit Factor: 0.76
Net Realized R: -0.49 R
Expectancy / Trade: -0.1633 R
"""


def test_parse_outcomes_and_summary():
    rows = parse_outcomes(sample_log())
    assert len(rows) == 3
    assert rows[0].symbol == "ETHUSDT"
    assert rows[1].result == "TARGET"
    summary = parse_latest_summary(sample_log())
    assert summary["completed_trades"] == 3
    assert summary["wins"] == 1


def test_analyze_is_descriptive_and_flags_small_mss_sample(tmp_path: Path):
    log = tmp_path / "shadow.log"
    log.write_text(sample_log(), encoding="utf-8")
    historical = tmp_path / "historical.json"
    historical.write_text(json.dumps({"candidate": "V9.3.1", "dataset": "1year", "portfolio": {"net_r": 10.0}}), encoding="utf-8")

    result = analyze(log, historical)
    assert result["forward"]["parsed_outcomes"] == 3
    assert result["forward"]["theoretical_net_r"] == -0.49
    assert result["forward"]["empirical_net_r"] == -1.30
    assert result["diagnostic_flags"]["small_sample"] is True
    assert result["historical_reference"]["dataset"] == "1year"


def test_no_network_or_strategy_mutation_surface():
    source = Path(__file__).resolve().parents[1] / "backtests" / "strategy_candidate_v9_3_1_shadow_forensic.py"
    text = source.read_text(encoding="utf-8")
    assert "ccxt" not in text
    assert "requests" not in text
    assert "urllib" not in text
    assert "place_order" not in text
    assert "update_threshold" not in text
