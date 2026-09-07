from strategy_candidate_v9_1 import V91Config, PRUNED_SETUPS, allowed_setups, asset_allowed, audit_summary, confirmation_ok, target_stop_atr, LONG


def test_v91_policy_smoke():
    assert PRUNED_SETUPS.isdisjoint(allowed_setups("STRONG_TREND"))
    assert allowed_setups("RANGE") == set()
    assert not confirmation_ok("FIB_OTE", {"FIB_OTE": LONG})
    assert confirmation_ok("FIB_OTE", {"FIB_OTE": LONG, "MSS_SHIFT": LONG})
    assert asset_allowed("SUIUSDT")
    assert not asset_allowed("AVAXUSDT")
    assert target_stop_atr("TREND_CONTINUATION") == (1.25, 2.50)
    assert audit_summary()["production_wired"] is False
