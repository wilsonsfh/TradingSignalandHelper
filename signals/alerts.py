"""Parse and validate an untrusted TradingView alert into an instruction.

The alert is authoritative for side/quantity/tp/sl, but only within
server-side bounds. Anything out of bounds is rejected, never silently
clamped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from models import Action


class AlertError(ValueError):
    """Raised when an alert body is malformed or out of bounds."""


_OPEN = {"open", "buy", "long"}
_CLOSE = {"close", "sell", "short", "exit"}


@dataclass
class ParsedAlert:
    action: str
    side: Action
    symbol: str
    quantity: Optional[int]
    take_profit: Optional[float]
    stop_loss: Optional[float]
    event_id: str
    occurred_at: datetime


def _price(value: object, name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AlertError(f"{name} must be a number")
    try:
        price = float(value)
    except (TypeError, ValueError):
        raise AlertError(f"{name} must be a number")
    if not math.isfinite(price) or price <= 0:
        raise AlertError(f"{name} must be a positive, finite price")
    return round(price, 4)


def parse_alert(
    body: dict,
    *,
    watchlist: List[str],
    max_quantity: int,
    max_age_seconds: int,
    now: Optional[datetime] = None,
) -> ParsedAlert:
    if not isinstance(body, dict):
        raise AlertError("alert body must be a JSON object")
    now = now or datetime.now(timezone.utc)

    event_id = str(body.get("event_id", "")).strip()
    timestamp = str(body.get("timestamp", "")).strip()
    if not event_id or not timestamp:
        raise AlertError("event_id and timestamp are required")
    try:
        occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise AlertError("timestamp must be ISO-8601")
    if occurred_at.tzinfo is None:
        raise AlertError("timestamp must be timezone-aware")
    age = abs((now - occurred_at.astimezone(timezone.utc)).total_seconds())
    if age > max_age_seconds:
        raise AlertError("alert is too old or too far in the future")

    action_raw = str(body.get("action", "")).lower().strip()
    side_raw = str(body.get("side", "")).lower().strip()
    tokens = {action_raw, side_raw}
    if action_raw != "open" and tokens & _CLOSE:
        action, side = "close", Action.SELL
    elif tokens & _OPEN:
        action, side = "open", Action.BUY
    else:
        raise AlertError("could not determine open/buy or close/sell")

    symbol_value = body.get("symbol")
    if symbol_value is not None and not isinstance(symbol_value, str):
        raise AlertError("symbol must be a string")
    symbol = (symbol_value or "").upper().strip()
    if not symbol:
        raise AlertError("symbol is required")
    if symbol not in watchlist:
        raise AlertError("symbol is outside the watchlist")

    quantity: Optional[int] = None
    if body.get("quantity") is not None:
        raw_quantity = body["quantity"]
        if isinstance(raw_quantity, bool):
            raise AlertError("quantity must be an integer")
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            raise AlertError("quantity must be an integer")
        if quantity <= 0:
            raise AlertError("quantity must be positive")
        if quantity > max_quantity:
            raise AlertError(f"quantity exceeds MAX_ALERT_QUANTITY ({max_quantity})")

    take_profit = _price(body.get("tp"), "tp")
    stop_loss = _price(body.get("sl"), "sl")
    if action == "open" and take_profit is not None and stop_loss is not None:
        if not (stop_loss < take_profit):
            raise AlertError("stop_loss must be below take_profit for a long entry")

    return ParsedAlert(
        action=action,
        side=side,
        symbol=symbol,
        quantity=quantity,
        take_profit=take_profit,
        stop_loss=stop_loss,
        event_id=event_id,
        occurred_at=occurred_at,
    )
