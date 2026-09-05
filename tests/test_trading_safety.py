import pytest

from trading_safety import (
    TradingStateUnavailable,
    classify_binance_error,
    exactly_one_protective_stop,
    require_authoritative_positions,
    retry_call,
)


def test_none_positions_fail_closed():
    with pytest.raises(TradingStateUnavailable):
        require_authoritative_positions(None)


def test_4130_is_not_blindly_retried():
    decision = classify_binance_error({"code": -4130, "msg": "open stop already exists"}, 1)
    assert decision.retry is False


def test_1106_is_not_blindly_retried():
    decision = classify_binance_error({"code": -1106, "msg": "Parameter reduceOnly sent when not required"}, 1)
    assert decision.retry is False


def test_2013_is_not_blindly_retried():
    decision = classify_binance_error({"code": -2013, "msg": "Order does not exist"}, 1)
    assert decision.retry is False


def test_timeout_retries_with_backoff():
    sleeps = []
    calls = [0]

    def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise TimeoutError("request timeout")
        return "ok"

    assert retry_call(flaky, max_attempts=3, sleep_fn=sleeps.append) == "ok"
    assert calls[0] == 3
    assert sleeps == [0.5, 1.0]


def test_exactly_one_intended_sl_per_side():
    orders = [
        {"symbol": "BTCUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "closePosition": True, "updateTime": 10},
    ]
    assert exactly_one_protective_stop(orders, "BTCUSDT", "LONG")
    orders.append({"symbol": "BTCUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "closePosition": True, "updateTime": 20})
    assert not exactly_one_protective_stop(orders, "BTCUSDT", "LONG")


def test_partial_tp_does_not_change_sl_cardinality():
    orders = [
        {"symbol": "ETHUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "closePosition": True, "updateTime": 10},
        {"symbol": "ETHUSDT", "positionSide": "LONG", "type": "TAKE_PROFIT_MARKET", "closePosition": True, "updateTime": 11},
    ]
    assert exactly_one_protective_stop(orders, "ETHUSDT", "LONG")
