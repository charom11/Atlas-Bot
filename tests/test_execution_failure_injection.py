import pytest
import requests
from execution_reconciliation import AmbiguousOrderSubmission, submit_market_order_idempotent
import main


def test_network_drop_after_fill_reconciles_0_duplicates():
    """
    Scenario: Order reaches exchange and fills, but network drops before response returns.
    Execution layer queries by clientOrderId, reconciles the fill, and never submits a duplicate.
    """
    submissions = []
    reconciliations = []

    def submit(params):
        submissions.append(params)
        # Network drop after exchange fill
        return {"error": "ReadTimeout: HTTPSConnectionPool(host='fapi.binance.com', port=443): Read timed out."}

    def reconcile(client_id):
        reconciliations.append(client_id)
        # Exchange shows the order was already filled
        return [{"orderId": 99901, "clientOrderId": client_id, "status": "FILLED"}]

    result = submit_market_order_idempotent(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.01,
        submit=submit,
        reconcile=reconcile,
        nonce=101,
    )

    assert result["orderId"] == 99901
    assert result["status"] == "FILLED"
    assert len(submissions) == 1, "Must not retry when order was already filled on exchange"
    assert len(reconciliations) == 1


def test_network_drop_before_fill_retries_once_same_client_id():
    """
    Scenario: Order request dropped before reaching exchange.
    Reconcile finds order does not exist on exchange.
    Layer retries exactly once using the IDENTICAL clientOrderId.
    """
    submissions = []
    reconciliations = []

    def submit(params):
        submissions.append(params)
        if len(submissions) == 1:
            return {"error": "ConnectionResetError: [WinError 10054] An existing connection was forcibly closed"}
        return {"orderId": 99902, "clientOrderId": params["newClientOrderId"], "status": "FILLED"}

    def reconcile(client_id):
        reconciliations.append(client_id)
        # Exchange has no record of this order
        return []

    result = submit_market_order_idempotent(
        symbol="ETHUSDT",
        side="SELL",
        quantity=0.5,
        submit=submit,
        reconcile=reconcile,
        nonce=202,
    )

    assert result["orderId"] == 99902
    assert len(submissions) == 2
    assert len(reconciliations) == 1
    # Both submissions must share identical clientOrderId to guarantee exchange-side idempotency
    assert submissions[0]["newClientOrderId"] == submissions[1]["newClientOrderId"]


def test_double_ambiguous_timeout_fails_closed():
    """
    Scenario: Initial submit times out, reconcile is inconclusive, retry times out.
    Layer refuses further speculative attempts and raises AmbiguousOrderSubmission.
    """
    submissions = []

    def submit(params):
        submissions.append(params)
        return {"error": "ETIMEDOUT: Connection timed out"}

    def reconcile(_client_id):
        # Inconclusive/None
        return None

    with pytest.raises(AmbiguousOrderSubmission):
        submit_market_order_idempotent(
            symbol="SOLUSDT",
            side="BUY",
            quantity=1.0,
            submit=submit,
            reconcile=reconcile,
            nonce=303,
        )

    # Exactly 2 submissions attempted, then hard fail-closed
    assert len(submissions) == 2


def test_position_api_outage_directional_cap_fails_closed(monkeypatch):
    """
    Scenario: Binance position endpoint 5xx outage returns None.
    Both open position count and directional cap fail closed, refusing new entries.
    """
    monkeypatch.setattr(main, "get_binance_futures_positions", lambda: None)

    # Position count must return None (fail closed, not 0)
    assert main.get_binance_futures_open_positions_count() is None

    # Directional cap check must reject entry when position state is unavailable
    cap_ok, active_cnt, msg = main.check_directional_portfolio_cap("BTCUSDT", "BUY", positions=None)
    assert cap_ok is False
    assert "unavailable" in msg.lower() or "fail closed" in msg.lower()


def test_multiple_protective_stops_collapsed_in_place_binance_futures_tp_sl(monkeypatch):
    """
    Scenario: Multiple stop orders exist on Binance for the position side.
    place_binance_futures_tp_sl verifies the exactly-one invariant and collapses orphan stops.
    """
    cancelled_algos = []

    open_algos = [
        {
            "algoId": 8001,
            "symbol": "BTCUSDT",
            "positionSide": "LONG",
            "type": "STOP_MARKET",
            "closePosition": True,
            "triggerPrice": "50000.0",
            "updateTime": 1000,
        },
        {
            "algoId": 8002,
            "symbol": "BTCUSDT",
            "positionSide": "LONG",
            "type": "STOP_MARKET",
            "closePosition": True,
            "triggerPrice": "50500.0",
            "updateTime": 2000,  # Newer authoritative stop
        },
    ]

    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        if method == "GET" and endpoint == "/fapi/v1/openAlgoOrders":
            return list(open_algos)
        if method == "POST" and endpoint == "/fapi/v1/order":
            return {"orderId": 7001, "symbol": "BTCUSDT", "status": "NEW"}
        return {}

    def fake_cancel_order_by_id(symbol, order_id=None, algo_id=None):
        if algo_id is not None:
            cancelled_algos.append(algo_id)
        return True

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)
    monkeypatch.setattr(main, "cancel_existing_protective_stops", lambda sym, position_side: True)
    monkeypatch.setattr(main, "place_protective_stop", lambda **kw: (True, 8002, 8002, "50500.0"))
    monkeypatch.setattr(main, "cancel_binance_order_by_id", fake_cancel_order_by_id)
    monkeypatch.setattr(main, "_save_position_targets", lambda: None)
    monkeypatch.setattr(main, "get_symbol_info", lambda s: (2, 3, 5.0))

    res = main.place_binance_futures_tp_sl(
        symbol="BTCUSDT",
        side="BUY",
        last_price=51000.0,
        atr=500.0,
        total_qty=0.01,
    )

    assert "sl_res" in res
    # The orphan stop (algoId 8001) must have been cancelled
    assert 8001 in cancelled_algos
    assert 8002 not in cancelled_algos
    assert main.ACTIVE_POSITION_TARGETS["BTCUSDT"]["sl_order_id"] == 8002


def test_multiple_protective_stops_collapsed_in_replace_protective_stop(monkeypatch):
    """
    Scenario: During trailing stop update, Binance shows multiple resting stops.
    _replace_protective_stop collapses duplicates, retaining only the authoritative stop.
    """
    cancelled_algos = []

    open_algos = [
        {
            "algoId": 9001,
            "symbol": "ETHUSDT",
            "positionSide": "LONG",
            "type": "STOP_MARKET",
            "closePosition": True,
            "triggerPrice": "2600.0",
            "updateTime": 1000,
        },
        {
            "algoId": 9002,
            "symbol": "ETHUSDT",
            "positionSide": "LONG",
            "type": "STOP_MARKET",
            "closePosition": True,
            "triggerPrice": "2650.0",
            "updateTime": 3000,
        },
    ]

    def fake_signed_request(method, endpoint, params=None, max_retries=3):
        if method == "GET" and endpoint == "/fapi/v1/openAlgoOrders":
            return list(open_algos)
        return {}

    def fake_cancel_order_by_id(symbol, order_id=None, algo_id=None):
        if algo_id is not None:
            cancelled_algos.append(algo_id)
        return True

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed_request)
    monkeypatch.setattr(main, "cancel_existing_protective_stops", lambda sym, position_side: True)
    monkeypatch.setattr(main, "place_protective_stop", lambda **kw: (True, 9002, 9002, "2650.0"))
    monkeypatch.setattr(main, "cancel_binance_order_by_id", fake_cancel_order_by_id)

    new_id, placed_str = main._replace_protective_stop(
        sym="ETHUSDT",
        close_side="SELL",
        side="LONG",
        qty=0.5,
        new_stop_price=2650.0,
        price_prec=2,
        old_order_id=9001,
        context_label="BE_LOCK",
        mark_price=2700.0,
    )

    assert new_id == 9002
    assert 9001 in cancelled_algos


def test_fail_closed_order_book_imbalance(monkeypatch):
    """
    Scenario: Order book depth request fails, returns non-200, or returns zero volume.
    Gate must fail closed (False), never fail open (True).
    """
    class FakeResponse:
        def __init__(self, status_code, data=None):
            self.status_code = status_code
            self._data = data or {}

        def json(self):
            return self._data

    # 1. Connection error
    def fake_get_err(*a, **kw):
        raise requests.exceptions.ConnectionError("API disconnected")

    monkeypatch.setattr(requests, "get", fake_get_err)
    confirmed, ratio, bid, ask = main.check_order_book_imbalance("BTCUSDT", "BUY")
    assert confirmed is False
    assert ratio == 0.0

    # 2. HTTP 500 error
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(500))
    confirmed, ratio, bid, ask = main.check_order_book_imbalance("BTCUSDT", "BUY")
    assert confirmed is False
    assert ratio == 0.0

    # 3. Empty bids / asks
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(200, {"bids": [], "asks": []}))
    confirmed, ratio, bid, ask = main.check_order_book_imbalance("BTCUSDT", "BUY")
    assert confirmed is False
    assert ratio == 0.0


def test_fail_closed_funding_rate(monkeypatch):
    """
    Scenario: Funding rate cache is empty, missing the symbol, or raises exception.
    Gate must fail closed (False), never fail open (True).
    """
    # Prevent live network call from repopulating cache in unit test
    monkeypatch.setattr(main.GLOBAL_CACHE, "update", lambda *a, **kw: None)

    # 1. Empty cache
    main.GLOBAL_CACHE.all_funding = {}
    confirmed, rate = main.check_funding_rate("BTCUSDT", "BUY")
    assert confirmed is False

    # 2. Cache is None
    main.GLOBAL_CACHE.all_funding = None
    confirmed, rate = main.check_funding_rate("BTCUSDT", "BUY")
    assert confirmed is False

    # 3. Symbol not in cache
    main.GLOBAL_CACHE.all_funding = {"ETHUSDT": 0.0001}
    confirmed, rate = main.check_funding_rate("BTCUSDT", "BUY")
    assert confirmed is False

    # 4. Exception in cache update
    def bad_update(*a, **kw):
        raise RuntimeError("Cache failure")

    monkeypatch.setattr(main.GLOBAL_CACHE, "update", bad_update)
    confirmed, rate = main.check_funding_rate("BTCUSDT", "BUY")
    assert confirmed is False
    assert rate == 0.0


def test_fail_closed_4h_smc_bias(monkeypatch):
    """
    Scenario: 4H SMC klines request fails (HTTP non-200, empty list, or exception).
    Gate must fail closed (False), never return True with neutral bias.
    """
    class FakeResponse:
        def __init__(self, status_code, data=None):
            self.status_code = status_code
            self._data = data or []

        def json(self):
            return self._data

    # 1. HTTP 500
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(500))
    aligned, bias = main.check_4h_smc_bias("BTCUSDT", "BUY")
    assert aligned is False
    assert "UNAVAILABLE" in bias

    # 2. Insufficient klines (< 20)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(200, [[0, 0, 0, 0, 100.0]] * 10))
    aligned, bias = main.check_4h_smc_bias("BTCUSDT", "BUY")
    assert aligned is False
    assert "UNAVAILABLE" in bias

    # 3. Exception
    def fake_get_err(*a, **kw):
        raise requests.exceptions.Timeout("Kline timeout")

    monkeypatch.setattr(requests, "get", fake_get_err)
    aligned, bias = main.check_4h_smc_bias("BTCUSDT", "BUY")
    assert aligned is False
    assert "UNAVAILABLE" in bias
