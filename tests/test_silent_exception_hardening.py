import pytest
import requests
import main


def test_check_order_flow_absorption_fails_closed_on_error(monkeypatch):
    """
    Scenario: Order flow aggTrades API fails, returns non-200, has insufficient trades,
    or raises network exception.
    Gate must strictly fail closed (False), never fail open (True).
    """
    class FakeResponse:
        def __init__(self, status_code, data=None):
            self.status_code = status_code
            self._data = data or []

        def json(self):
            return self._data

    # 1. HTTP 500 error
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(500))
    ok, desc, delta, abs_type = main.check_order_flow_absorption("BTCUSDT", "BUY")
    assert ok is False
    assert "UNAVAILABLE" in desc or "Fail Closed" in desc

    # 2. Insufficient trades (< 30)
    few_trades = [{"q": "1.0", "p": "80000.0", "m": True}] * 10
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(200, few_trades))
    ok, desc, delta, abs_type = main.check_order_flow_absorption("BTCUSDT", "BUY")
    assert ok is False
    assert "UNAVAILABLE" in desc or "Fail Closed" in desc

    # 3. Connection error
    def bad_get(*a, **kw):
        raise requests.exceptions.ConnectionError("AggTrades endpoint unreachable")

    monkeypatch.setattr(requests, "get", bad_get)
    ok, desc, delta, abs_type = main.check_order_flow_absorption("BTCUSDT", "BUY")
    assert ok is False
    assert "Fail Closed" in desc

    # 4. Realistic Binance trades with string prices and quantities (no TypeError)
    realistic_trades = [
        {"q": "0.15", "p": f"{4420.0 + (i % 5) * 0.1:.2f}", "m": (i % 2 == 0)}
        for i in range(40)
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(200, realistic_trades))
    ok, desc, delta, abs_type = main.check_order_flow_absorption("PAXGUSDT", "BUY")
    assert "ORDER FLOW ERROR" not in desc
    assert isinstance(delta, float)


def test_sync_binance_realized_pnl_logs_warning_on_failure(monkeypatch, capsys):
    """
    Scenario: Income history query fails during circuit breaker update.
    Error is captured and logged with [CIRCUIT BREAKER WARN] rather than silently swallowed.
    """
    def bad_request(*a, **kw):
        raise RuntimeError("Income API timeout")

    monkeypatch.setattr(main, "binance_futures_signed_request", bad_request)
    main.CIRCUIT_BREAKER.sync_binance_realized_pnl()

    captured = capsys.readouterr()
    assert "[CIRCUIT BREAKER WARN]" in captured.out
    assert "Income API timeout" in captured.out


def test_emergency_tp_cleanup_failure_logged(monkeypatch, capsys):
    """
    Scenario: SL placement fails; bot cancels TP orders and executes emergency close.
    If cancel_binance_order_by_id raises an exception, it is logged with [EMERGENCY CLEANUP ERROR]
    and the emergency close still proceeds.
    """
    # Mock place_protective_stop to fail
    monkeypatch.setattr(main, "cancel_existing_protective_stops", lambda *a, **kw: True)
    monkeypatch.setattr(main, "place_protective_stop", lambda **kw: (False, None, None, None))

    # Mock cancel_binance_order_by_id to fail
    def bad_cancel(symbol, order_id=None, algo_id=None):
        raise RuntimeError("Cancel failed - exchange error")

    monkeypatch.setattr(main, "cancel_binance_order_by_id", bad_cancel)

    # Mock emergency close to succeed
    close_called = []
    def fake_close(sym):
        close_called.append(sym)
        return {"orderId": 999999}

    monkeypatch.setattr(main, "close_binance_futures_position", fake_close)
    monkeypatch.setattr(main, "send_telegram_msg", lambda *a, **kw: None)
    monkeypatch.setattr(main, "get_symbol_info", lambda sym: (2, 3, 5.0))

    # This test exercises the TP/SL failure path only; CCXT time synchronization
    # is unrelated and must not make a real network request from CI.
    class FakeExchange:
        pass

    monkeypatch.setattr(main, "get_ccxt_exchange", lambda: FakeExchange())

    # Mock TP placement
    def fake_signed(method, endpoint, params=None, max_retries=3):
        if method == "POST" and endpoint == "/fapi/v1/order":
            return {"orderId": 12345}
        if method == "GET" and endpoint == "/fapi/v1/openAlgoOrders":
            return []
        return {}

    monkeypatch.setattr(main, "binance_futures_signed_request", fake_signed)

    res = main.place_binance_futures_tp_sl(
        symbol="BTCUSDT",
        side="BUY",
        last_price=60000.0,
        atr=500.0,
        total_qty=0.01,
    )

    captured = capsys.readouterr()
    assert "[SL PLACEMENT FAILED]" in captured.out
    assert "[EMERGENCY CLEANUP ERROR]" in captured.out
    assert len(close_called) == 1
    assert res.get("error") == "SL placement failed"
