"""In-memory broker for development and tests.

Simulates market fills and implements the *soft* take-profit / stop-loss watch:
feed it prices via ``update_price`` and it closes positions when a level is hit.
No network, fully deterministic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from models import Action, BracketOrder, Position
from broker.base import Broker


class MockBroker(Broker):
    def __init__(self, initial_positions: Optional[Iterable[Position]] = None) -> None:
        self._last_price: Dict[str, float] = {}
        self._positions: List[Position] = list(initial_positions or [])

    def place_bracket(self, order: BracketOrder) -> Position:
        if order.side is not Action.BUY:
            raise ValueError("MockBroker.place_bracket only opens long positions (BUY)")
        if any(p.status != "CLOSED" and p.symbol == order.symbol for p in self._positions):
            raise ValueError(f"an open position already exists for {order.symbol!r}")
        price = self._last_price.get(order.symbol)
        if price is None:
            raise ValueError(
                f"no market price known for {order.symbol!r}; call update_price first"
            )
        pos = Position(
            symbol=order.symbol,
            quantity=order.quantity,
            avg_price=price,
            take_profit=order.take_profit,
            stop_loss=order.stop_loss,
            status="OPEN",
        )
        self._positions.append(pos)
        return pos

    def positions(self) -> List[Position]:
        return list(self._positions)

    def open_positions(self) -> List[Position]:
        return [p for p in self._positions if p.status != "CLOSED"]

    def update_price(self, symbol: str, price: float) -> List[Position]:
        self._last_price[symbol] = price
        closed: List[Position] = []
        for p in self._positions:
            if p.status == "CLOSED" or p.symbol != symbol:
                continue
            if p.take_profit is not None and price >= p.take_profit:
                self._close(p, price, "TAKE_PROFIT")
                closed.append(p)
            elif p.stop_loss is not None and price <= p.stop_loss:
                self._close(p, price, "STOP_LOSS")
                closed.append(p)
        return closed

    def close(self, symbol: str, price: float, reason: str = "MANUAL") -> Position:
        for p in self._positions:
            if p.status != "CLOSED" and p.symbol == symbol:
                self._close(p, price, reason)
                return p
        raise ValueError(f"no open position for {symbol!r}")

    @staticmethod
    def _close(p: Position, price: float, reason: str) -> None:
        p.status = "CLOSED"
        p.close_price = price
        p.close_reason = reason
        p.closed_at = datetime.now(timezone.utc)
