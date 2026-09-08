import numpy as np
import pandas as pd
import pytest

from strategy_candidate_v9_3_1 import (
    V931Config,
    ACTIVE_SETUPS_V931,
    DISABLED_SETUPS_V931,
    ALLOWED_REGIMES_V931,
    GATED_REGIMES_V931,
    TIER_1,
    TIER_2,
    TIER_3,
    asset_allowed,
    allowed_setups,
    target_stop_atr,
    admit_opportunity,
    backtest_frame,
    integration_audit_summary,
    LONG,
    SHORT,
    FLAT,
)


def test_v931_safety_and_shadow_defaults():
    cfg = V931Config()
    assert cfg.shadow_mode is True
    assert cfg.max_operating_leverage <= 5.0
    assert cfg.max_operating_leverage < 75.0
    assert cfg.max_risk_per_trade_pct == 0.0035
    assert cfg.max_portfolio_risk_pct == 0.015


def test_v931_integration_audit_summary():
    summary = integration_audit_summary()
    assert summary["candidate"] == "V9.3.1"
    assert summary["live_orders_permitted"] is False
    assert summary["main_py_authoritative"] is True
    assert summary["breakdown_gated"] is True
    assert summary["pullback_gated"] is True
    assert summary["vwap_trend_gated"] is True
    assert summary["leverage_75x_rejected"] is True
    assert set(summary["active_setups"]) == ACTIVE_SETUPS_V931
    assert "VWAP_TREND" in summary["disabled_setups"]


def test_v931_gated_regimes_include_breakdown():
    for regime in ("RANGE", "CHOP", "BREAKDOWN"):
        assert allowed_setups(regime) == set()
    for regime in ("STRONG_TREND", "HIGH_VOL"):
        assert allowed_setups(regime) == set(ACTIVE_SETUPS_V931)


def test_v931_gated_setups_are_strictly_excluded():
    for regime in ("STRONG_TREND", "HIGH_VOL", "MILD_TREND"):
        allowed = allowed_setups(regime)
        for dis in DISABLED_SETUPS_V931:
            assert dis not in allowed
        assert "VWAP_TREND" not in allowed
        assert "PULLBACK_CONTINUATION" not in allowed


def test_v931_asset_tiering():
    cfg = V931Config(allow_tier_2=True, allow_tier_3=False)
    assert asset_allowed("SOLUSDT", cfg)
    assert asset_allowed("BTCUSDT", cfg)
    assert not asset_allowed("AVAXUSDT", cfg)
    assert asset_allowed("AVAXUSDT", V931Config(allow_tier_3=True))


def test_v931_asymmetric_target_on_trend():
    cfg = V931Config()
    assert target_stop_atr("TREND_CONTINUATION", cfg) == (1.25, 2.50)
    assert target_stop_atr("BB_ATR_EXPANSION", cfg) == (1.25, 2.00)
    assert target_stop_atr("MSS_SHIFT", cfg) == (1.25, 2.00)
    assert target_stop_atr("BREAKOUT_RETEST", cfg) == (1.25, 2.00)


def test_v931_admit_opportunity_rejects_gated_regime():
    idx = pd.date_range("2025-01-01", periods=1, freq="15min", tz="UTC")
    row = pd.Series({
        "close": 100.0,
        "atr": 1.5,
        "symbol": "SOLUSDT",
        "regime": "BREAKDOWN",
    }, name=idx[0])
    votes = {"TREND_CONTINUATION": LONG}
    opp = admit_opportunity(row, votes)
    assert opp is not None
    assert opp.admitted is False
    assert "BREAKDOWN" in opp.rejection_reason


def test_v931_backtest_frame_synthetic():
    n = 350
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    base = 100 * np.exp(np.arange(n) * 0.0005)
    df = pd.DataFrame({
        "open": base - 0.05,
        "high": base + 0.35,
        "low": base - 0.35,
        "close": base,
        "volume": np.full(n, 1000.0),
        "symbol": "SOLUSDT",
    }, index=idx)
    trades = backtest_frame(df)
    assert isinstance(trades, list)
    for t in trades:
        assert t.setup in ACTIVE_SETUPS_V931
        assert t.regime not in GATED_REGIMES_V931
