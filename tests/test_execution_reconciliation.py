import pytest

from execution_reconciliation import AmbiguousOrderSubmission, submit_market_order_idempotent


def test_successful_submission_uses_client_order_id():
    calls = []

    def submit(params):
        calls.append(params)
        return {"orderId": 123, "clientOrderId": params["newClientOrderId"]}

    def reconcile(_client_id):
        raise AssertionError("reconcile must not run after a proven success")

    result = submit_market_order_idempotent(
        symbol="BTCUSDT", side="BUY", quantity=0.001,
        submit=submit, reconcile=reconcile, nonce=12345,
    )

    assert result["orderId"] == 123
    assert calls[0]["newClientOrderId"].startswith("ATLAS_BTCUSDT_BUY_ENTRY_")


def test_submission_supports_custom_intent_like_close():
    calls = []

    def submit(params):
        calls.append(params)
        return {"orderId": 321, "clientOrderId": params["newClientOrderId"]}

    result = submit_market_order_idempotent(
        symbol="ETHUSDT", side="SELL", quantity=0.01,
        submit=submit, reconcile=lambda _id: None, nonce=999,
        intent="CLOSE"
    )

    assert result["orderId"] == 321
    assert calls[0]["newClientOrderId"].startswith("ATLAS_ETHUSDT_SELL_CLOSE_")


def test_ambiguous_submission_reconciles_before_retry():
    submissions = []
    reconciliations = []

    def submit(params):
        submissions.append(params)
        return None

    def reconcile(client_id):
        reconciliations.append(client_id)
        return [{"orderId": 456, "clientOrderId": client_id}]

    result = submit_market_order_idempotent(
        symbol="ETHUSDT", side="SELL", quantity=0.01,
        submit=submit, reconcile=reconcile, nonce=7,
    )

    assert result["orderId"] == 456
    assert len(submissions) == 1
    assert len(reconciliations) == 1


def test_missing_reconciliation_allows_only_one_retry():
    submissions = []

    def submit(params):
        submissions.append(params)
        return None

    def reconcile(_client_id):
        return None

    with pytest.raises(AmbiguousOrderSubmission):
        submit_market_order_idempotent(
            symbol="BTCUSDT", side="BUY", quantity=0.001,
            submit=submit, reconcile=reconcile, nonce=9,
        )

    assert len(submissions) == 2
    assert submissions[0]["newClientOrderId"] == submissions[1]["newClientOrderId"]


def test_invalid_order_never_reaches_submit():
    called = False

    def submit(_params):
        nonlocal called
        called = True
        return {"orderId": 1}

    with pytest.raises(ValueError):
        submit_market_order_idempotent(
            symbol="BTCUSDT", side="BUY", quantity=0,
            submit=submit, reconcile=lambda _id: None,
        )

    assert called is False


def test_reconcile_ignores_error_dict_and_retries():
    submissions = []

    def submit(params):
        submissions.append(params)
        if len(submissions) == 1:
            return {"error": "request timeout"}
        return {"orderId": 999, "clientOrderId": params["newClientOrderId"]}

    # Return error dict (e.g. -2013 order does not exist) on reconcile query
    def reconcile(_client_id):
        return {"code": -2013, "msg": "Order does not exist."}

    result = submit_market_order_idempotent(
        symbol="SOLUSDT", side="BUY", quantity=0.1,
        submit=submit, reconcile=reconcile, nonce=42,
    )

    assert result["orderId"] == 999
    assert len(submissions) == 2


def test_place_binance_futures_market_order_wires_client_order_id(monkeypatch):
    import main

    signed_requests = []

    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        signed_requests.append((method, endpoint, dict(params or {})))
        if method == "POST" and endpoint == "/fapi/v1/order":
            return {
                "orderId": 777123,
                "symbol": params.get("symbol"),
                "status": "FILLED",
                "clientOrderId": params.get("newClientOrderId")
            }
        return {}

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)
    monkeypatch.setattr(main, "get_binance_futures_usdt_balance", lambda which="available": 1000.0)
    monkeypatch.setattr(main.CIRCUIT_BREAKER, "check_and_update", lambda eq: True)
    monkeypatch.setattr(main.MILESTONE_MANAGER, "update", lambda av: None)
    monkeypatch.setattr(main, "get_symbol_info", lambda sym: (2, 3, 5.0))
    monkeypatch.setattr(main, "place_binance_futures_tp_sl", lambda **kw: {"status": "ok"})
    monkeypatch.setattr(main, "_save_entry_timestamps", lambda: None)

    res = main.place_binance_futures_market_order(
        symbol="BTCUSDT",
        side="BUY",
        trade_usdt=50.0,
        leverage=75,
        last_price=60000.0
    )

    assert res.get("orderId") == 777123
    order_post = [r for r in signed_requests if r[0] == "POST" and r[1] == "/fapi/v1/order"][0]
    sent_params = order_post[2]
    assert sent_params["symbol"] == "BTCUSDT"
    assert sent_params["side"] == "BUY"
    assert sent_params["positionSide"] == "LONG"
    assert sent_params["type"] == "MARKET"
    assert "newClientOrderId" in sent_params
    assert sent_params["newClientOrderId"].startswith("ATLAS_BTCUSDT_BUY_ENTRY_")


def test_close_binance_futures_position_wires_client_order_id_with_close_intent(monkeypatch):
    import main

    signed_requests = []

    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        signed_requests.append((method, endpoint, dict(params or {})))
        if method == "POST" and endpoint == "/fapi/v1/order":
            return {
                "orderId": 888456,
                "symbol": params.get("symbol"),
                "status": "FILLED",
                "clientOrderId": params.get("newClientOrderId")
            }
        elif method == "DELETE":
            return {"code": 200, "msg": "success"}
        elif method == "GET" and endpoint in ("/fapi/v1/openOrders", "/fapi/v1/openAlgoOrders"):
            return []
        return {}

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)
    monkeypatch.setattr(main, "get_binance_futures_positions", lambda: [
        {"symbol": "ETHUSDT", "positionAmt": 1.5, "markPrice": 2500.0}
    ])

    res = main.close_binance_futures_position("ETHUSDT")

    assert res.get("orderId") == 888456
    order_post = [r for r in signed_requests if r[0] == "POST" and r[1] == "/fapi/v1/order"][0]
    sent_params = order_post[2]
    assert sent_params["symbol"] == "ETHUSDT"
    assert sent_params["side"] == "SELL"
    assert sent_params["positionSide"] == "LONG"
    assert sent_params["quantity"] == "1.5"
    assert sent_params["newClientOrderId"].startswith("ATLAS_ETHUSDT_SELL_CLOSE_")


def test_get_binance_futures_open_positions_count_fail_closed(monkeypatch):
    import main

    monkeypatch.setattr(main, "get_binance_futures_positions", lambda: None)
    assert main.get_binance_futures_open_positions_count() is None

    monkeypatch.setattr(main, "get_binance_futures_positions", lambda: [])
    assert main.get_binance_futures_open_positions_count() == 0

    monkeypatch.setattr(main, "get_binance_futures_positions", lambda: [{"symbol": "BTCUSDT"}])
    assert main.get_binance_futures_open_positions_count() == 1


def test_cancel_binance_symbol_all_orders_verifies_clean(monkeypatch):
    import main

    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        if method == "DELETE":
            return {"code": 200}
        if method == "GET" and endpoint == "/fapi/v1/openOrders":
            return []
        if method == "GET" and endpoint == "/fapi/v1/openAlgoOrders":
            return []
        return []

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)
    clean, rem = main.cancel_binance_symbol_all_orders("BTCUSDT")
    assert clean is True
    assert rem == 0


def test_place_protective_stop_reconciles_timeout(monkeypatch):
    import main

    # Simulate CCXT timeout, then Algo API timeout, but openAlgoOrders reveals stop was placed
    def fake_exchange():
        class FakeEx:
            def create_order(self, *a, **kw):
                raise TimeoutError("CCXT timeout")
        return FakeEx()

    calls = []
    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        calls.append((method, endpoint))
        if method == "POST" and endpoint == "/fapi/v1/algoOrder":
            return {"error": "request timeout"}
        if method == "GET" and endpoint == "/fapi/v1/openAlgoOrders":
            return [{
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "type": "STOP_MARKET",
                "closePosition": True,
                "algoId": 999111,
                "updateTime": 500
            }]
        return []

    monkeypatch.setattr(main, "get_ccxt_exchange", fake_exchange)
    monkeypatch.setattr(main, "to_ccxt_symbol", lambda s: "BTC/USDT:USDT")
    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)

    success, oid, algo_id, stop_str = main.place_protective_stop(
        symbol="BTCUSDT", close_side="SELL", position_side="LONG", qty=0.1, stop_price=55000.0, price_prec=2, max_retries=1
    )

    assert success is True
    assert algo_id == 999111


def test_cancel_existing_stops_for_side_accepts_code_200(monkeypatch):
    import main

    deleted_endpoints = []

    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        if method == "GET" and endpoint == "/fapi/v1/openAlgoOrders":
            return [{
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "type": "STOP_MARKET",
                "closePosition": True,
                "algoId": 888001
            }]
        if method == "DELETE" and endpoint == "/fapi/v1/algoOrder":
            deleted_endpoints.append((endpoint, params))
            # Binance returns HTTP 200 inside JSON payload on successful algo deletion
            return {"algoId": 888001, "clientAlgoId": "test_algo", "code": "200", "msg": "success"}
        if method == "GET" and endpoint == "/fapi/v1/openOrders":
            return []
        return []

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)
    count = main.cancel_existing_protective_stops("BTCUSDT", "LONG")
    assert count == 1
    assert len(deleted_endpoints) == 1
    assert deleted_endpoints[0][1]["algoId"] == 888001


def test_cancel_binance_order_by_id_algo_code_200(monkeypatch):
    import main

    called = []

    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        called.append((method, endpoint, params))
        if method == "DELETE" and endpoint == "/fapi/v1/algoOrder":
            return {"algoId": 2000001415267591, "clientAlgoId": "x-test", "code": "200", "msg": "success"}
        if method == "DELETE" and endpoint == "/fapi/v1/order":
            # Should NOT be reached if algo deletion succeeds with code 200
            raise AssertionError("Regular order cancellation should not be attempted when algo deletion returns code 200")
        return {}

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)
    res = main.cancel_binance_order_by_id("BTCUSDT", algo_id=2000001415267591)
    assert res is not None
    assert res.get("code") == "200"
    assert res.get("msg") == "success"
    assert len(called) == 1
    assert called[0][1] == "/fapi/v1/algoOrder"

