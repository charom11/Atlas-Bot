import pytest

from risk_guard import RiskLimitBreached, RiskStateUnavailable, RiskLimits, load_limits_from_env, validate_order_risk


def base(**overrides):
    values = dict(
        equity=1000,
        existing_notional=0,
        existing_margin=0,
        open_positions=0,
        order_notional=500,
        order_margin=50,
        requested_leverage=10,
        daily_pnl=0,
        limits=RiskLimits(),
    )
    values.update(overrides)
    return values


def test_safe_order_passes():
    validate_order_risk(**base())


def test_leverage_limit_fails_closed():
    with pytest.raises(RiskLimitBreached):
        validate_order_risk(**base(requested_leverage=11))


def test_position_count_limit():
    with pytest.raises(RiskLimitBreached):
        validate_order_risk(**base(open_positions=3))


def test_margin_utilization_limit():
    with pytest.raises(RiskLimitBreached):
        validate_order_risk(**base(order_margin=60))


def test_total_notional_limit():
    with pytest.raises(RiskLimitBreached):
        validate_order_risk(**base(existing_notional=600, order_notional=500))


def test_daily_loss_blocks_new_positions():
    with pytest.raises(RiskLimitBreached):
        validate_order_risk(**base(daily_pnl=-50))


def test_invalid_account_state_does_not_become_zero():
    with pytest.raises(RiskStateUnavailable):
        validate_order_risk(**base(equity=0))


def test_env_limits_are_conservative_and_overridable():
    limits = load_limits_from_env({
        "ATLAS_MAX_LEVERAGE": "7",
        "ATLAS_MAX_POSITIONS": "2",
        "ATLAS_MAX_MARGIN_UTILIZATION": "0.08",
        "ATLAS_MAX_TOTAL_NOTIONAL_PCT": "0.75",
        "ATLAS_MAX_DAILY_LOSS_PCT": "0.04",
    })
    assert limits == RiskLimits(7, 2, 0.08, 0.75, 0.04)


def test_invalid_env_is_rejected():
    with pytest.raises(ValueError):
        load_limits_from_env({"ATLAS_MAX_LEVERAGE": "not-a-number"})
