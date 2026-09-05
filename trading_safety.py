"""Safety primitives for Binance Futures order management.

These helpers are intentionally side-effect free so they can be unit-tested without
placing real orders. Integrations should fail closed when authoritative Binance
state is unavailable.
"""

from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable, Optional


class TradingStateUnavailable(RuntimeError):
    """Raised when an authoritative trading-state query fails."""


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay: float
    reason: str


# Retry only errors where another attempt can plausibly change the outcome.
_RETRYABLE_CODES = {
    -1001,  # DISCONNECTED
    -1003,  # TOO_MANY_REQUESTS / IP ban warning
    -1006,  # UNEXPECTED_RESP
    -1007,  # TIMEOUT
    -1015,  # TOO_MANY_ORDERS
    -1021,  # INVALID_TIMESTAMP
    -2010,  # NEW_ORDER_REJECTED (caller must still inspect message)
}

_RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


def classify_binance_error(error: Any, attempt: int, max_attempts: int = 3) -> RetryDecision:
    """Classify an exception/response for bounded retry with exponential backoff.

    Unknown failures are not retried. Known order-state errors such as -2013 and
    duplicate/protective-order conflicts are deliberately not blindly retried.
    """
    code = None
    status = None
    message = str(error)
    if isinstance(error, dict):
        code = error.get("code")
        status = error.get("status") or error.get("http_status")
        message = str(error.get("msg", message))
    else:
        code = getattr(error, "code", None)
        status = getattr(error, "http_status", None) or getattr(error, "status_code", None)

    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None

    retryable = status in _RETRYABLE_HTTP or code in _RETRYABLE_CODES
    # A timeout can be returned as text by requests/ccxt wrappers.
    if "timeout" in message.lower() and "-2013" not in message:
        retryable = True

    if attempt >= max_attempts or not retryable:
        return RetryDecision(False, 0.0, f"non-retryable or retry budget exhausted: {message}")

    delay = min(8.0, 0.5 * (2 ** max(0, attempt - 1)))
    return RetryDecision(True, delay, f"transient Binance/API failure: {message}")


def retry_call(fn: Callable[[], Any], *, max_attempts: int = 3, sleep_fn=time.sleep) -> Any:
    """Run a callable with bounded exponential backoff for retryable failures."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # classification below decides whether to retry
            last_error = exc
            decision = classify_binance_error(exc, attempt, max_attempts)
            if not decision.retry:
                raise
            sleep_fn(decision.delay)
    raise last_error  # pragma: no cover


def require_authoritative_positions(positions: Optional[Iterable[Any]]) -> list:
    """Convert authoritative position results to a list; never turn failure into []."""
    if positions is None:
        raise TradingStateUnavailable("Binance position state unavailable")
    return list(positions)


def protective_stop_key(order: dict) -> tuple:
    """Return the identity key used to enforce one SL per symbol/position side."""
    symbol = str(order.get("symbol", "")).upper()
    position_side = str(order.get("positionSide", "BOTH")).upper()
    return symbol, position_side


def choose_authoritative_stop(orders: Iterable[dict], symbol: str, position_side: str) -> Optional[dict]:
    """Choose one deterministic protective STOP_MARKET order for a position side."""
    candidates = []
    for order in orders:
        if str(order.get("symbol", "")).upper() != symbol.upper():
            continue
        if str(order.get("positionSide", "BOTH")).upper() != position_side.upper():
            continue
        order_type = str(order.get("type") or order.get("orderType") or "").upper()
        if order_type != "STOP_MARKET":
            continue
        close_position = order.get("closePosition")
        if close_position in (True, "true", "TRUE", 1, "1"):
            candidates.append(order)
    if not candidates:
        return None
    # Prefer the newest authoritative order when timestamps are available.
    return max(candidates, key=lambda x: int(x.get("updateTime") or x.get("bookTime") or 0))


def exactly_one_protective_stop(orders: Iterable[dict], symbol: str, position_side: str) -> bool:
    """Return True only when exactly one intended close-position SL exists."""
    matches = [
        o for o in orders
        if protective_stop_key(o) == (symbol.upper(), position_side.upper())
        and str(o.get("type") or o.get("orderType") or "").upper() == "STOP_MARKET"
        and o.get("closePosition") in (True, "true", "TRUE", 1, "1")
    ]
    return len(matches) == 1
