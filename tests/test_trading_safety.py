import pytest

from trading_safety import (
    InvalidOrderRequest,
    TradingStateUnavailable,
    classify_binance_error,
    exactly_one_protective_stop,
    find_order_by_client_id,
    make_client_order_id,
    require_authoritative_positions,
    retry_call,
    validate_order_request,
)


def test_none_positions_fail_closed():
    with pytest.raises(TradingStateUnavailable):
        require_authoritative_positions(None)


def test_4130_is_not_blindly_retried():
    assert not classify_binance_error({"code": -4130, "msg": "open stop already exists"}, 1).retry


def test_1106_is_not_blindly_retried():
    assert not classify_binance_error({"code": -1106, "msg": "Parameter reduceOnly sent when not required"}, 1).retry


def test_2013_is_not_blindly_retried():
    assert not classify_binance_error({"code": -2013, "msg": "Order does not exist"}, 1).retry


def test_timeout_retries_with_backoff():
    sleeps, calls = [], [0]
    def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise TimeoutError("request timeout")
        return "ok"
    assert retry_call(flaky, max_attempts=3, sleep_fn=sleeps.append) == "ok"
    assert calls[0] == 3
    assert sleeps == [0.5, 1.0]


def test_exactly_one_intended_sl_per_side():
    orders = [{"symbol": "BTCUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "closePosition": True, "updateTime": 10}]
    assert exactly_one_protective_stop(orders, "BTCUSDT", "LONG")
    orders.append({"symbol": "BTCUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "closePosition": True, "updateTime": 20})
    assert not exactly_one_protective_stop(orders, "BTCUSDT", "LONG")


def test_partial_tp_does_not_change_sl_cardinality():
    orders = [
        {"symbol": "ETHUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "closePosition": True, "updateTime": 10},
        {"symbol": "ETHUSDT", "positionSide": "LONG", "type": "TAKE_PROFIT_MARKET", "closePosition": True, "updateTime": 11},
    ]
    assert exactly_one_protective_stop(orders, "ETHUSDT", "LONG")


def test_order_validation_rejects_bad_quantity_and_side():
    with pytest.raises(InvalidOrderRequest):
        validate_order_request("BTCUSDT", "BUY", 0)
    with pytest.raises(InvalidOrderRequest):
        validate_order_request("BTCUSDT", "HOLD", 1)


def test_order_validation_enforces_bounds():
    assert validate_order_request("BTCUSDT", "BUY", 2, price=100, min_qty=1, max_qty=3)[2] == 2
    with pytest.raises(InvalidOrderRequest):
        validate_order_request("BTCUSDT", "BUY", 0.5, min_qty=1)
    with pytest.raises(InvalidOrderRequest):
        validate_order_request("BTCUSDT", "BUY", 4, max_qty=3)


def test_client_order_id_is_bounded_and_recoverable():
    cid = make_client_order_id("BTCUSDT", "BUY", "entry", nonce=123456)
    assert len(cid) <= 36
    assert cid.startswith("ATLAS_BTCUSDT_BUY_ENTRY_")
    orders = [{"orderId": 99, "clientOrderId": cid, "status": "NEW"}]
    assert find_order_by_client_id(orders, cid)["orderId"] == 99


def test_find_order_by_client_id_returns_none_when_not_found():
    assert find_order_by_client_id([], "ATLAS_missing") is None
