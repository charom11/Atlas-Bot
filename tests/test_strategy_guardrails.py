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
