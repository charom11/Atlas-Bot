"""Idempotent Binance order-submission guard.

This module contains the side-effect-free decision layer used by the execution
adapter. It validates an entry, assigns a deterministic client order id, and
requires reconciliation by that id before an ambiguous submission can be
retried. The exchange-specific HTTP adapter is injected by the caller.
"""

from typing import Any, Callable, Optional

from trading_safety import (
    InvalidOrderRequest,
    find_order_by_client_id,
    make_client_order_id,
    order_response_is_success,
    response_is_ambiguous,
    validate_order_request,
)


class AmbiguousOrderSubmission(RuntimeError):
    """Raised when Binance cannot prove whether an order was accepted."""


def submit_market_order_idempotent(
    *,
    symbol: str,
    side: str,
    quantity: float,
    submit: Callable[[dict], Any],
    reconcile: Callable[[str], Any],
    min_qty: float = 0.0,
    max_qty: Optional[float] = None,
    nonce: Optional[int] = None,
    intent: str = "ENTRY",
) -> Any:
    """Submit one market order without blind duplication.

    ``submit`` receives the complete order params, including ``newClientOrderId``.
    ``reconcile`` must query authoritative Binance order state using that client
    id and return either an order/list of orders or ``None`` when no matching
    order exists.

    A successful response is returned immediately. An ambiguous response is
    reconciled first; if an existing order is found it is returned. If Binance
    proves no order exists, the submission is retried once with the same client
    id. A second ambiguous response fails closed instead of submitting again.
    """
    symbol, side, quantity, _ = validate_order_request(
        symbol, side, quantity, min_qty=min_qty, max_qty=max_qty
    )
    client_order_id = make_client_order_id(symbol, side, intent, nonce=nonce)
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
        "newClientOrderId": client_order_id,
    }

    response = submit(dict(params))
    if not response_is_ambiguous(response):
        return response

    existing = reconcile(client_order_id)
    if order_response_is_success(existing):
        return existing
    if existing and not isinstance(existing, dict):
        match = find_order_by_client_id(existing, client_order_id)
        if match is not None:
            return match

    retry_response = submit(dict(params))
    if response_is_ambiguous(retry_response):
        # One reconciliation after the bounded retry is safe; never issue a
        # third blind submission with the same intent.
        existing = reconcile(client_order_id)
        if order_response_is_success(existing):
            return existing
        if existing and not isinstance(existing, dict):
            match = find_order_by_client_id(existing, client_order_id)
            if match is not None:
                return match
        raise AmbiguousOrderSubmission(
            f"Unable to prove Binance accepted or rejected {client_order_id}"
        )
    return retry_response
