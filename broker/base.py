"""Broker interface: execute orders and track positions.

Implementations:
  - MockBroker: simulated fills + soft stop-loss/take-profit.
  - MoomooBroker: Moomoo via OpenD, paper first.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from models import BracketOrder, Position


class BrokerOrderRejected(RuntimeError):
    """Broker definitively rejected an order before any exposure was created."""


class Broker(ABC):
    @abstractmethod
    def place_bracket(self, order: BracketOrder) -> Position:
        """Open a position (market entry) with attached TP/SL. Returns the Position."""
        raise NotImplementedError

    @abstractmethod
    def positions(self) -> List[Position]:
        """Return all positions (open and closed)."""
        raise NotImplementedError

    @abstractmethod
    def open_positions(self) -> List[Position]:
        """Return only currently-open positions."""
        raise NotImplementedError

    @abstractmethod
    def update_price(self, symbol: str, price: float) -> List[Position]:
        """Feed a fresh price; close any open position whose TP or SL is hit.

        This implements the *soft* stop-loss / take-profit watch needed because
        moomoo paper trading does not support native stop orders.

        Returns the list of positions closed by this price update.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self, symbol: str, price: float, reason: str = "MANUAL") -> Position:
        """Manually close an open position at the given price."""
        raise NotImplementedError
