from strategy_guardrails import (
    atr_neutral_signal,
    directional_cap_allowed,
    require_fresh_data,
    seasonality_signal,
    validate_external_filter,
)


def test_atr_band_neutrality():
    assert atr_neutral_signal(0.10, 1.0, 0.15) == "NEUTRAL"
    assert atr_neutral_signal(0.20, 1.0, 0.15) == "BULLISH"
    assert atr_neutral_signal(-0.20, 1.0, 0.15) == "BEARISH"


def test_bad_atr_fails_closed():
    assert atr_neutral_signal(1.0, 0.0) == "NEUTRAL"
    assert atr_neutral_signal(1.0, -1.0) == "NEUTRAL"


def test_external_data_failure_fails_closed():
    assert require_fresh_data(False)[0] is False
    assert validate_external_filter(None) is False
    assert validate_external_filter({"funding": None}, required_keys=("funding",)) is False
    assert validate_external_filter({"funding": 0.0}, required_keys=("funding",)) is True


def test_directional_cap_requires_authoritative_state():
    assert directional_cap_allowed(False, 0.0, 1.0, 10.0) is False
    assert directional_cap_allowed(True, 4.0, 5.0, 10.0) is True
    assert directional_cap_allowed(True, 6.0, 5.0, 10.0) is False


def test_unvalidated_seasonality_is_neutral():
    assert seasonality_signal(False, "BULLISH") == "NEUTRAL"
    assert seasonality_signal(True, "BULLISH") == "BULLISH"
    assert seasonality_signal(True, "garbage") == "NEUTRAL"


def test_check_consensus_eligibility():
    from strategy_guardrails import check_consensus_eligibility

    # 14 bull, 2 bear (active=16, ratio=87.5% >= 75%, max=14 >= 13) -> eligible
    ok, active, max_c, ratio = check_consensus_eligibility(14, 2)
    assert ok is True
    assert active == 16
    assert max_c == 14
    assert ratio == 0.875

    # 12 bull, 4 bear (max=12 < 13) -> ineligible (needs >= 13 directional votes)
    ok, _, max_c, _ = check_consensus_eligibility(12, 4)
    assert ok is False

    # 13 bull, 5 bear (active=18, ratio=72.2% < 75%) -> ineligible (insufficient agreement ratio)
    ok, _, _, ratio = check_consensus_eligibility(13, 5)
    assert ok is False
    assert ratio < 0.75

    # 10 bull, 0 bear (active=10 < 12, max=10 < 13) -> ineligible
    ok, _, _, _ = check_consensus_eligibility(10, 0)
    assert ok is False

    # 15 bear, 2 bull (active=17, max=15 >= 13, ratio=88.2% >= 75%) -> eligible (bearish)
    ok, active, max_c, ratio = check_consensus_eligibility(2, 15)
    assert ok is True
    assert max_c == 15
    assert ratio > 0.75

