import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from strategy_candidate_v9_3_1 import (
    V931Config,
    ShadowOpportunity,
    ACTIVE_SETUPS_V931,
    GATED_REGIMES_V931,
    LONG,
    SHORT,
    FLAT,
)
from v9_3_1_shadow_engine import (
    V931ShadowEngine,
    ShadowPosition,
    ShadowOutcome,
)


@pytest.fixture
def temp_data_dir(tmp_path):
    d = tmp_path / "shadow_test_data"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_shadow_engine_initialization(temp_data_dir):
    engine = V931ShadowEngine(data_dir=temp_data_dir)
    assert engine.config.shadow_mode is True
    assert engine.config.max_operating_leverage <= 5.0
    assert engine.friction_r == 0.026
    assert engine.max_hold_bars == 32
    assert len(engine.open_positions) == 0


def test_shadow_engine_opportunity_rejection(temp_data_dir):
    engine = V931ShadowEngine(data_dir=temp_data_dir)
    # Synthetic DataFrame with 220 bars
    n = 220
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "open": np.full(n, 100.0),
        "high": np.full(n, 100.2),
        "low": np.full(n, 99.8),
        "close": np.full(n, 100.0),
        "volume": np.full(n, 1000.0),
        "symbol": "SOLUSDT",
    }, index=idx)

    opp, outcomes = engine.evaluate_bar("SOLUSDT", df)
    # Even if no signal triggers or it is CHOP/RANGE, opportunity should be recorded to disk
    assert engine.opps_file.exists()
    with open(engine.opps_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["symbol"] == "SOLUSDT"
        assert rec["admitted"] is False


def test_shadow_engine_target_and_stop_resolution(temp_data_dir):
    engine = V931ShadowEngine(data_dir=temp_data_dir, friction_r=0.026)

    # Manually seed an open shadow position
    pos = ShadowPosition(
        position_id="test_pos_1",
        symbol="SOLUSDT",
        side=LONG,
        setup="TREND_CONTINUATION",
        regime="STRONG_TREND",
        entry_bar_time="2026-01-01 10:00:00",
        entry_price=100.0,
        stop_price=98.0,      # risk = 2.0
        target_price=105.0,   # reward = 5.0 (2.5x)
        atr=1.6,
        score=6,
        confirmations=2,
        bars_held=0,
        max_favorable_price=100.0,
        max_adverse_price=100.0,
    )
    engine.open_positions["SOLUSDT"] = pos

    # Bar 1: Price rallies to 105.50 (Target Hit)
    row_target = pd.Series({
        "open": 101.0,
        "high": 105.50,
        "low": 100.50,
        "close": 104.0,
    }, name="2026-01-01 10:15:00")

    outcome = engine._update_position("SOLUSDT", row_target, "2026-01-01 10:15:00")
    assert outcome is not None
    assert outcome.outcome_type == "TARGET"
    assert outcome.exit_price == 105.0
    assert outcome.gross_r == pytest.approx(2.50, rel=1e-3)
    assert outcome.net_r == pytest.approx(2.50 - 0.026, rel=1e-3)
    assert "SOLUSDT" not in engine.open_positions

    # Verify outcome file written
    assert engine.outcomes_file.exists()
    summary = engine.update_summary()
    assert summary["total_outcomes"] == 1
    assert summary["wins"] == 1
    assert summary["win_rate"] == 1.0


def test_shadow_engine_stop_resolution(temp_data_dir):
    engine = V931ShadowEngine(data_dir=temp_data_dir, friction_r=0.026)

    pos = ShadowPosition(
        position_id="test_pos_2",
        symbol="BTCUSDT",
        side=LONG,
        setup="MSS_SHIFT",
        regime="HIGH_VOL",
        entry_bar_time="2026-01-01 10:00:00",
        entry_price=50000.0,
        stop_price=49000.0,
        target_price=52000.0,
        atr=800.0,
        score=5,
        confirmations=1,
        bars_held=0,
        max_favorable_price=50000.0,
        max_adverse_price=50000.0,
    )
    engine.open_positions["BTCUSDT"] = pos

    # Bar: Price dumps to 48500 (Stop Hit)
    row_stop = pd.Series({
        "open": 49800.0,
        "high": 49900.0,
        "low": 48500.0,
        "close": 48600.0,
    }, name="2026-01-01 10:15:00")

    outcome = engine._update_position("BTCUSDT", row_stop, "2026-01-01 10:15:00")
    assert outcome is not None
    assert outcome.outcome_type == "STOP"
    assert outcome.exit_price == 49000.0
    assert outcome.gross_r == pytest.approx(-1.00, rel=1e-3)
    assert outcome.net_r == pytest.approx(-1.026, rel=1e-3)
    assert "BTCUSDT" not in engine.open_positions


def test_shadow_engine_timeout_resolution(temp_data_dir):
    engine = V931ShadowEngine(data_dir=temp_data_dir, max_hold_bars=32, friction_r=0.026)

    pos = ShadowPosition(
        position_id="test_pos_3",
        symbol="ETHUSDT",
        side=SHORT,
        setup="BB_ATR_EXPANSION",
        regime="HIGH_VOL",
        entry_bar_time="2026-01-01 10:00:00",
        entry_price=3000.0,
        stop_price=3100.0,
        target_price=2800.0,
        atr=50.0,
        score=5,
        confirmations=1,
        bars_held=31,  # Will reach 32 on next bar
        max_favorable_price=2950.0,
        max_adverse_price=3050.0,
    )
    engine.open_positions["ETHUSDT"] = pos

    row_timeout = pd.Series({
        "open": 2960.0,
        "high": 2980.0,
        "low": 2940.0,
        "close": 2950.0,
    }, name="2026-01-01 18:00:00")

    outcome = engine._update_position("ETHUSDT", row_timeout, "2026-01-01 18:00:00")
    assert outcome is not None
    assert outcome.outcome_type == "TIMEOUT"
    assert outcome.exit_price == 2950.0
    # Short from 3000 to 2950 with 100 risk = +0.50 gross R
    assert outcome.gross_r == pytest.approx(0.50, rel=1e-3)
    assert outcome.net_r == pytest.approx(0.50 - 0.026, rel=1e-3)


def test_shadow_engine_persistence_recovery(temp_data_dir):
    engine1 = V931ShadowEngine(data_dir=temp_data_dir)
    pos = ShadowPosition(
        position_id="persist_test",
        symbol="SUIUSDT",
        side=LONG,
        setup="TREND_CONTINUATION",
        regime="STRONG_TREND",
        entry_bar_time="2026-01-01 12:00:00",
        entry_price=3.50,
        stop_price=3.30,
        target_price=3.90,
        atr=0.15,
        score=7,
        confirmations=3,
        bars_held=5,
        max_favorable_price=3.70,
        max_adverse_price=3.45,
    )
    engine1.open_positions["SUIUSDT"] = pos
    engine1.last_evaluated_bar["SUIUSDT"] = "2026-01-01 13:15:00"
    engine1.save_state()

    # Re-instantiate a new engine from the same directory
    engine2 = V931ShadowEngine(data_dir=temp_data_dir)
    assert "SUIUSDT" in engine2.open_positions
    recovered_pos = engine2.open_positions["SUIUSDT"]
    assert recovered_pos.position_id == "persist_test"
    assert recovered_pos.entry_price == 3.50
    assert recovered_pos.bars_held == 5
    assert engine2.last_evaluated_bar["SUIUSDT"] == "2026-01-01 13:15:00"


def test_shadow_engine_zero_order_execution():
    """Verify that neither the engine nor daemon imports order execution routines."""
    import inspect
    import v9_3_1_shadow_engine
    import v9_3_1_shadow_daemon

    engine_src = inspect.getsource(v9_3_1_shadow_engine)
    daemon_src = inspect.getsource(v9_3_1_shadow_daemon)

    for forbidden in [
        "place_binance_futures_market_order",
        "submit_market_order_idempotent",
        "/fapi/v1/order",
        "POST",
    ]:
        assert forbidden not in engine_src, f"Forbidden execution logic '{forbidden}' found in v9_3_1_shadow_engine.py"
        assert forbidden not in daemon_src, f"Forbidden execution logic '{forbidden}' found in v9_3_1_shadow_daemon.py"
