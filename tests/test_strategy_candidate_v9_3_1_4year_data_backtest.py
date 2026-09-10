from pathlib import Path
import json

from backtests.strategy_candidate_v9_3_1_4year_data_backtest import compare


def test_compare_reports_observer_vs_reference(tmp_path: Path):
    observer = {"portfolio": {
        "trades": 100,
        "win_rate": 0.4,
        "profit_factor": 1.02,
        "net_r": 5.0,
        "expectancy_r": 0.05,
        "max_drawdown_r": 10.0,
    }}
    ref = tmp_path / "reference.json"
    ref.write_text(json.dumps({"portfolio": {
        "trades": 120,
        "win_rate": 0.42,
        "profit_factor": 1.05,
        "net_r": 8.0,
        "expectancy_r": 0.066,
        "max_drawdown_r": 12.0,
    }}), encoding="utf-8")

    out = compare(observer, ref)
    assert out["reference_exists"] is True
    assert out["comparison"]["trades"]["difference_observer_minus_reference"] == -20
    assert out["comparison"]["net_r"]["difference_observer_minus_reference"] == -3.0


def test_compare_handles_missing_reference(tmp_path: Path):
    observer = {"portfolio": {"trades": 1, "net_r": 1.0}}
    out = compare(observer, tmp_path / "missing.json")
    assert out["reference_exists"] is False
    assert out["comparison"]["trades"]["observer_replay"] == 1
