import time
import pytest
import requests

from market_state_ws import MarketStateManager
import main


def test_fresh_ws_state_returns_funding_and_mark_price_without_rest(monkeypatch):
    """
    Scenario: WebSocket state is connected and fresh (< 15s).
    Accessing funding rate and mark price returns instantly without making REST requests.
    """
    manager = MarketStateManager(auto_seed_rest=False)
    manager.ws_connected = True
    manager.last_msg_time = time.time()
    manager.funding_rates = {"BTCUSDT": 0.0001, "ETHUSDT": -0.0002}
    manager.mark_prices = {"BTCUSDT": 80000.0, "ETHUSDT": 2700.0}

    # If any REST call is attempted, raise an assertion error
    def fail_on_rest(*a, **kw):
        raise AssertionError("REST must not be called when WebSocket cache is fresh")

    monkeypatch.setattr(requests, "get", fail_on_rest)

    assert manager.is_healthy() is True

    # 1. Normal funding rate
    ok, rate = manager.get_funding_rate("BTCUSDT", target_side="BUY")
    assert ok is True
    assert rate == 0.0001

    # 2. Mark price
    mp = manager.get_mark_price("BTCUSDT")
    assert mp == 80000.0

    # 3. All funding dict
    all_f = manager.get_all_funding()
    assert all_f == {"BTCUSDT": 0.0001, "ETHUSDT": -0.0002}


def test_stale_ws_state_triggers_rest_fallback(monkeypatch):
    """
    Scenario: WebSocket connection is stale (> 15s) or symbol is missing.
    Manager automatically falls back to authoritative REST endpoint.
    """
    manager = MarketStateManager(auto_seed_rest=False)
    manager.ws_connected = True
    manager.last_msg_time = time.time() - 30.0  # 30s ago (stale)
    manager.funding_rates = {"BTCUSDT": 0.0001}

    assert manager.is_healthy() is False

    rest_called = []

    class FakeResponse:
        def __init__(self, data):
            self.status_code = 200
            self._data = data

        def json(self):
            return self._data

    def fake_get(url, timeout=None):
        rest_called.append(url)
        return FakeResponse({"symbol": "BTCUSDT", "lastFundingRate": "0.00025", "markPrice": "80500.0"})

    monkeypatch.setattr(requests, "get", fake_get)

    ok, rate = manager.get_funding_rate("BTCUSDT", target_side="BUY")
    assert ok is True
    assert rate == 0.00025
    assert len(rest_called) == 1
    assert "premiumIndex" in rest_called[0]


def test_failed_ws_and_failed_rest_strictly_fails_closed(monkeypatch):
    """
    Scenario: WebSocket is disconnected AND REST endpoint is down.
    Manager strictly fails closed (False, 0.0), rejecting trade entry.
    """
    manager = MarketStateManager(auto_seed_rest=False)
    manager.ws_connected = False
    manager.last_msg_time = 0.0
    manager.funding_rates = {}

    def bad_get(*a, **kw):
        raise requests.exceptions.ConnectionError("Exchange down")

    monkeypatch.setattr(requests, "get", bad_get)

    ok, rate = manager.get_funding_rate("SOLUSDT", target_side="BUY")
    assert ok is False
    assert rate == 0.0

    mp = manager.get_mark_price("SOLUSDT")
    assert mp is None


def test_stream_ingestion_markprice_and_kline():
    """
    Scenario: WebSocket receives !markPrice@arr and btcusdt@kline_15m stream events.
    In-memory state correctly updates parsed rates and completed kline history.
    """
    manager = MarketStateManager(auto_seed_rest=False)

    # 1. Ingest mark price event
    mark_msg = """{
        "stream": "!markPrice@arr",
        "data": [
            {"s": "BTCUSDT", "p": "81000.5", "r": "0.00012", "T": 1700000000},
            {"s": "AVAXUSDT", "p": "25.4", "r": "-0.0003", "T": 1700000000}
        ]
    }"""
    manager._on_message(None, mark_msg)

    assert manager.mark_prices["BTCUSDT"] == 81000.5
    assert manager.funding_rates["BTCUSDT"] == 0.00012
    assert manager.mark_prices["AVAXUSDT"] == 25.4
    assert manager.funding_rates["AVAXUSDT"] == -0.0003

    # 2. Ingest forming kline (x=False) -> should not append to completed candles
    forming_kline_msg = """{
        "stream": "btcusdt@kline_15m",
        "data": {
            "k": {
                "t": 100000, "o": "81000", "h": "81200", "l": "80900", "c": "81100",
                "v": "50", "T": 100899, "q": "4000000", "n": 200, "V": "25", "Q": "2000000",
                "B": "0", "x": false
            }
        }
    }"""
    manager._on_message(None, forming_kline_msg)
    assert len(manager.btc_15m_raw) == 0

    # 3. Ingest closed kline (x=True) -> should append to completed candles
    closed_kline_msg = """{
        "stream": "btcusdt@kline_15m",
        "data": {
            "k": {
                "t": 100000, "o": "81000", "h": "81200", "l": "80900", "c": "81150",
                "v": "100", "T": 100899, "q": "8000000", "n": 400, "V": "50", "Q": "4000000",
                "B": "0", "x": true
            }
        }
    }"""
    manager._on_message(None, closed_kline_msg)
    assert len(manager.btc_15m_raw) == 1
    assert manager.btc_15m_raw[0][0] == 100000
    assert manager.btc_15m_raw[0][4] == "81150"


def test_global_cache_hybrid_integration(monkeypatch):
    """
    Scenario: GlobalDataCache uses WebSocket state when healthy, avoiding REST.
    """
    cache = main.GlobalDataCache(enable_ws=False)
    fake_manager = MarketStateManager(auto_seed_rest=False)
    fake_manager.ws_connected = True
    fake_manager.last_msg_time = time.time()
    fake_manager.funding_rates = {"BTCUSDT": 0.0001, "ETHUSDT": 0.00005}
    # Provide 35 mock completed klines
    fake_manager.btc_15m_raw = [[i * 1000, 100, 105, 95, 102, 10, (i + 1) * 1000] for i in range(35)]
    fake_manager.btc_15m_updated_at = time.time()

    cache.market_state = fake_manager

    def fail_on_rest(*a, **kw):
        raise AssertionError("REST must not be invoked when WebSocket state is fresh in GLOBAL_CACHE")

    monkeypatch.setattr(requests, "get", fail_on_rest)

    cache.update(force=True)

    assert cache.all_funding.get("BTCUSDT") == 0.0001
    assert cache.btc_15m_raw is not None
    assert len(cache.btc_15m_raw) == 35


def test_core_main_proxy_parity():
    """
    Scenario: Verify core/main.py acts as a seamless compatibility launcher forwarding to root main.py.
    """
    import core.main

    # Ensure critical classes and functions are identical
    assert hasattr(core.main, "WeatherEnsembleBot")
    assert hasattr(core.main, "place_binance_futures_market_order")
    assert hasattr(core.main, "GLOBAL_CACHE")
    assert hasattr(core.main, "submit_market_order_idempotent")
    assert hasattr(core.main, "MarketStateManager")
    assert core.main.WeatherEnsembleBot is main.WeatherEnsembleBot
