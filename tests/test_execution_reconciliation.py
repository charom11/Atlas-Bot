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
