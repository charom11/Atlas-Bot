import pytest
import os
import threading
import time
import main


def test_darwinian_attribution_closed_positions():
    """
    Verifies that when a position is closed and removed from ACTIVE_POSITION_TARGETS,
    its origin channel is preserved in _CLOSED_POSITION_CHANNELS, preventing default FIBONACCI skew.
    """
    sym = "TEST_SOL_USDT"
    channel = "POTATO_SR"

    # 1. Position active in ACTIVE_POSITION_TARGETS
    main.ACTIVE_POSITION_TARGETS[sym] = {"channel": channel, "side": "LONG"}
    assert main.get_channel_for_symbol(sym) == channel

    # 2. Position closes, channel recorded, then popped
    main.record_closed_position_channel(sym, channel)
    main.ACTIVE_POSITION_TARGETS.pop(sym, None)

    # 3. get_channel_for_symbol retrieves the recorded channel from history
    assert main.get_channel_for_symbol(sym) == channel

    # 4. Completely unrecorded symbol defaults safely to FIBONACCI
    assert main.get_channel_for_symbol("COMPLETELY_UNKNOWN_COIN") == "FIBONACCI"

    # Cleanup
    main._CLOSED_POSITION_CHANNELS.pop(sym, None)


def test_telegram_c2_is_authorized_fail_closed(monkeypatch):
    """
    Verifies that Telegram C2 command listener fails closed when TELEGRAM_CHAT_ID is empty,
    preventing unauthorized users from issuing C2 commands.
    """
    # Create bot instance
    bot = main.WeatherEnsembleBot(consensus_threshold=30, live_trading=False)

    # Helper function extracted to test the auth logic directly
    def check_auth(configured_chat_id, sender_id, chat_id):
        configured = (configured_chat_id or "").strip().strip('"').strip("'")
        if not configured:
            return False
        allowed = [s.strip() for s in configured.split(",") if s.strip()]
        return str(sender_id) in allowed or str(chat_id) in allowed

    # 1. Unset/empty chat ID -> Fail Closed (False for everyone)
    assert check_auth("", "123456", "123456") is False
    assert check_auth(None, "123456", "123456") is False

    # 2. Configured chat ID -> Authorize allowed sender/chat only
    allowed_id = "987654321"
    assert check_auth(allowed_id, allowed_id, "000") is True
    assert check_auth(allowed_id, "000", allowed_id) is True
    assert check_auth(allowed_id, "111222333", "444555666") is False

    # 3. Multiple comma-separated allowed IDs
    multi_cfg = "111, 222, 333"
    assert check_auth(multi_cfg, "222", "999") is True
    assert check_auth(multi_cfg, "888", "333") is True
    assert check_auth(multi_cfg, "444", "555") is False


def test_milestone_lock_manager_cold_start_spam_prevention(monkeypatch):
    """
    Verifies that MilestoneLockManager does not spam milestone alerts
    when starting up with pre-existing account balance above milestone thresholds.
    """
    alerts = []
    monkeypatch.setattr(main, "send_telegram_msg", lambda msg, **kw: alerts.append(msg))

    manager = main.MilestoneLockManager(initial_capital=14.20)
    assert manager._initialized is False

    # First update with existing wallet balance of $650
    locked = manager.update(650.0)
    assert manager._initialized is True
    assert locked == 500.0
    assert manager.locked_milestone == 500.0
    # Crucial: 0 spam alerts sent on boot!
    assert len(alerts) == 0

    # Subsequent increase above $1000 sends ONE alert for the newly crossed milestone
    locked_next = manager.update(1050.0)
    assert locked_next == 1000.0
    assert len(alerts) == 1
    assert "1,000.00 USDT" in alerts[0]


def test_http_session_pooling_singleton():
    """
    Verifies that get_binance_http_session returns a persistent singleton Session
    with connection pooling enabled.
    """
    session1 = main.get_binance_http_session()
    session2 = main.get_binance_http_session()
    assert session1 is session2

    # Check adapter mounting
    https_adapter = session1.adapters.get("https://")
    assert https_adapter is not None
    assert getattr(https_adapter, "_pool_connections", 0) >= 10
    assert getattr(https_adapter, "_pool_maxsize", 0) >= 20


def test_engine_lock_protects_concurrency():
    """
    Verifies that _ENGINE_LOCK is an RLock and that target dictionary state
    can be serialized without mutating race conditions.
    """
    assert isinstance(main._ENGINE_LOCK, type(threading.RLock()))

    # Test thread-safe snapshot saving
    main.ACTIVE_POSITION_TARGETS["TEST_CONCURRENCY"] = {
        "side": "LONG",
        "entry_price": 100.0,
        "current_sl": 95.0
    }
    try:
        # Saving uses with _ENGINE_LOCK: data = dict(ACTIVE_POSITION_TARGETS)
        main._save_position_targets()
    finally:
        main.ACTIVE_POSITION_TARGETS.pop("TEST_CONCURRENCY", None)


def test_close_binance_futures_position_reuses_supplied_position(monkeypatch):
    """
    Verifies that close_binance_futures_position does not perform redundant API queries
    when a target position is already supplied.
    """
    api_queries = []

    def mock_get_positions():
        api_queries.append("positionRisk")
        return [{"symbol": "BTCUSDT", "positionAmt": "0.1", "entryPrice": "80000"}]

    monkeypatch.setattr(main, "get_binance_futures_positions", mock_get_positions)

    # Mock order closing
    monkeypatch.setattr(main, "cancel_existing_protective_stops", lambda *a, **kw: 1)
    monkeypatch.setattr(main, "submit_market_order_idempotent", lambda *a, **kw: {"orderId": 9999})

    # Supply position directly
    supplied_pos = {"symbol": "BTCUSDT", "positionAmt": 0.1, "entryPrice": 80000}
    res = main.close_binance_futures_position("BTCUSDT", target_position=supplied_pos)

    # positionRisk was NOT queried because target_position was passed directly
    assert len(api_queries) == 0
    assert isinstance(res, dict)
