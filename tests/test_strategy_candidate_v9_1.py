from strategy_candidate_v9_1 import V91Config, PRUNED_SETUPS, allowed_setups, asset_allowed, audit_summary, confirmation_ok, target_stop_atr, LONG


def test_pruned_setups_are_never_allowed():
    for regime in ("STRONG_TREND", "MILD_TREND", "HIGH_VOL", "BREAKDOWN", "RANGE", "CHOP"):
        assert PRUNED_SETUPS.isdisjoint(allowed_setups(regime))


def test_range_and_chop_are_hard_gated():
    assert allowed_setups("RANGE") == set()
    assert allowed_setups("CHOP") == set()


def test_fib_requires_structural_confirmation():
    assert not confirmation_ok("FIB_OTE", {"FIB_OTE": LONG, "MSS_SHIFT": 0, "TREND_CONTINUATION": 0})
    assert confirmation_ok("FIB_OTE", {"FIB_OTE": LONG, "MSS_SHIFT": LONG})


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
