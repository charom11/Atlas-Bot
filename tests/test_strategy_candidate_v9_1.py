from strategy_candidate_v9_1 import V91Config, PRUNED_SETUPS, allowed_setups, asset_allowed, audit_summary, confirmation_ok, target_stop_atr, LONG


def test_pruned_setups_are_never_allowed():
    for regime in ("STRONG_TREND", "MILD_TREND", "HIGH_VOL", "BREAKDOWN", "RANGE", "CHOP"):
        assert PRUNED_SETUPS.isdisjoint(allowed_setups(regime))


def test_range_and_chop_are_hard_gated():
    assert allowed_setups("RANGE") == set()
    assert allowed_setups("CHOP") == set()


def test_fib_requires_structural_confirmation():
    assert not confirmation_ok("FIB_OTE", {"FIB_OTE": LONG, "MSS_SHIFT": 0, "TREND_CONTINUATION": 0, "PULLBACK_CONTINUATION": 0})
    assert confirmation_ok("FIB_OTE", {"FIB_OTE": LONG, "MSS_SHIFT": LONG})


def test_non_fib_setup_only_requires_its_own_vote():
    assert not confirmation_ok("MSS_SHIFT", {"MSS_SHIFT": 0})
    assert confirmation_ok("MSS_SHIFT", {"MSS_SHIFT": LONG})


def test_asset_tiering_defaults_to_tier1_and_tier2():
    cfg = V91Config()
    assert asset_allowed("SUIUSDT", cfg)
    assert asset_allowed("SOLUSDT", cfg)
    assert asset_allowed("BTCUSDT", cfg)
    assert not asset_allowed("AVAXUSDT", cfg)


def test_asset_tier3_can_be_enabled_for_research():
    assert asset_allowed("AVAXUSDT", V91Config(allow_tier_3=True))


def test_high_vol_can_be_disabled_without_changing_other_regimes():
    cfg = V91Config(allow_high_vol=False)
    assert allowed_setups("HIGH_VOL", cfg) == set()
    assert allowed_setups("STRONG_TREND", cfg)


def test_mild_trend_can_be_disabled():
    assert allowed_setups("MILD_TREND", V91Config(allow_mild_trend=False)) == set()


def test_fibonacci_can_be_disabled():
    assert "FIB_OTE" not in allowed_setups("STRONG_TREND", V91Config(allow_fibonacci=False))


def test_target_calibration_only_changes_trend_continuation():
    cfg = V91Config()
    assert target_stop_atr("TREND_CONTINUATION", cfg) == (1.25, 2.50)
    assert target_stop_atr("MSS_SHIFT", cfg) == (1.25, 2.00)


def test_audit_summary_is_explicitly_research_only():
    summary = audit_summary()
    assert summary["production_wired"] is False
    assert summary["range_allowed"] is False
    assert summary["chop_allowed"] is False
    assert summary["fib_requires_confirmation"] is True


def test_v91_backtest_frame_disallowed_asset_returns_empty():
    from strategy_candidate_v9_1 import backtest_frame
    import pandas as pd
    import numpy as np

    idx = pd.date_range("2025-01-01", periods=300, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "open": np.full(300, 100.0),
        "high": np.full(300, 101.0),
        "low": np.full(300, 99.0),
        "close": np.full(300, 100.0),
        "volume": np.full(300, 1000.0),
        "symbol": "AVAXUSDT",
    }, index=idx)
    # Default V91Config disallows Tier 3 (AVAXUSDT)
    trades = backtest_frame(df, config=V91Config())
    assert trades == []


def test_v91_backtest_frame_allowed_asset_executes():
    from strategy_candidate_v9_1 import backtest_frame
    import pandas as pd
    import numpy as np

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
    trades = backtest_frame(df, config=V91Config())
    assert isinstance(trades, list)
    for t in trades:
        assert t.symbol == "SOLUSDT"
        assert t.setup not in PRUNED_SETUPS

