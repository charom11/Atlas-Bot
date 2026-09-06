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
