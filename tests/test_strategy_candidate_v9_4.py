import numpy as np
import pandas as pd
import pytest

from strategy_candidate_v9 import LONG, SHORT, FLAT
from strategy_candidate_v9_4 import (
    V94Config,
    ACTIVE_SETUPS_V94,
    DISABLED_SETUPS_V94,
    ALLOWED_REGIMES_V94,
    GATED_REGIMES_V94,
    normalized_atr,
    volatility_band_ok,
    effective_min_score,
    effective_risk_pct,
    admit_opportunity_v94,
    backtest_frame_v94,
    integration_audit_summary,
)


def test_v94_config_defaults():
    cfg = V94Config()
    assert cfg.enable_volatility_band is True
    assert cfg.atr_pct_floor == 0.0015
    assert cfg.atr_pct_ceiling == 0.0600
    assert cfg.mild_trend_min_score == 6
    assert cfg.enable_breakeven_trail is True
    assert cfg.breakeven_trigger_r == 1.00
    assert cfg.max_operating_leverage == 5.0
    assert cfg.shadow_mode is True


def test_normalized_atr():
    assert normalized_atr(100.0, 2.0) == pytest.approx(0.02)
    assert normalized_atr(0.0, 2.0) == 0.0
    assert normalized_atr(-50.0, 2.0) == 0.0


def test_volatility_band_ok():
    cfg = V94Config(atr_pct_floor=0.002, atr_pct_ceiling=0.05)
    assert volatility_band_ok(100.0, 1.0, cfg) is True     # 1% -> ok
    assert volatility_band_ok(100.0, 0.1, cfg) is False    # 0.1% -> too low (dead tape)
    assert volatility_band_ok(100.0, 8.0, cfg) is False    # 8.0% -> too high (news spike)


def test_effective_min_score():
    cfg = V94Config(min_score=5, mild_trend_min_score=6)
    assert effective_min_score("STRONG_TREND", cfg) == 5
    assert effective_min_score("HIGH_VOL", cfg) == 5
    assert effective_min_score("MILD_TREND", cfg) == 6


def test_effective_risk_pct():
    cfg = V94Config(max_risk_per_trade_pct=0.0035, enable_regime_risk_scaling=True)
    assert effective_risk_pct("STRONG_TREND", cfg) == pytest.approx(0.0035)
    assert effective_risk_pct("MILD_TREND", cfg) == pytest.approx(0.0035 * 0.75)
    assert effective_risk_pct("HIGH_VOL", cfg) == pytest.approx(0.0035 * 0.60)


def test_admit_opportunity_v94_rejects_volatility_band_extreme():
    idx = pd.date_range("2026-01-01", periods=1, freq="15min", tz="UTC")
    row = pd.Series({
        "open": 100.0,
        "high": 100.05,
        "low": 99.95,
        "close": 100.0,
        "atr": 0.05,  # 0.05% -> below 0.15% floor
        "vol_ratio": 1.5,
        "atr_ratio": 1.1,
        "trend": LONG,
        "ema20": 103.0,
        "ema50": 102.0,
        "ema100": 101.0,
        "ema200": 100.0,
        "symbol": "SOLUSDT",
        "regime": "STRONG_TREND",
    }, name=idx[0])

    votes = {"TREND_CONTINUATION": LONG}
    opp = admit_opportunity_v94(row, votes)
    assert opp is not None
    assert opp.admitted is False
    assert "outside volatility band" in opp.rejection_reason


def test_admit_opportunity_v94_rejects_weak_mild_trend_score():
    idx = pd.date_range("2026-01-01", periods=1, freq="15min", tz="UTC")
    # Score of 5 in MILD_TREND should not be admitted because mild_trend_min_score is 6
    row = pd.Series({
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "atr": 1.5,
        "vol_ratio": 1.0,
        "atr_ratio": 1.0,
        "trend": LONG,
        "ema20": 103.0,
        "ema50": 102.0,
        "ema100": 101.0,
        "ema200": 100.0,
        "symbol": "SOLUSDT",
        "regime": "MILD_TREND",
    }, name=idx[0])

    votes = {"TREND_CONTINUATION": LONG}
    opp = admit_opportunity_v94(row, votes)
    # Because score=5 < mild_trend_min_score=6, it is rejected (returns None or admitted=False)
    assert opp is None or opp.admitted is False




def test_v94_safety_and_audit_summary():
    summary = integration_audit_summary()
    assert summary["candidate"] == "V9.4"
    assert summary["live_orders_permitted"] is False
    assert summary["main_py_authoritative"] is True
    assert summary["leverage_75x_rejected"] is True
    assert summary["max_operating_leverage"] == 5.0
    assert summary["volatility_band_enabled"] is True
    assert summary["breakeven_trail_enabled"] is True
