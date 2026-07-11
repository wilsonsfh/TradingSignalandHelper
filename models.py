"""Shared data structures used across the project.

These are plain data containers (no behaviour) so they can be imported
anywhere without creating circular dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


class Action(str, Enum):
    """What a signal tells us to do."""
    BUY = "BUY"    # open a long position
    SELL = "SELL"  # close an existing long position
    HOLD = "HOLD"  # do nothing


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Signal:
    """A trading signal produced by a strategy."""
    symbol: str
    action: Action
    price: float                        # reference / entry price (latest close)
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class BracketOrder:
    """An instruction to open a position with attached take-profit / stop-loss."""
    symbol: str
    side: Action                        # BUY to open long; SELL to close long
    quantity: int
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    entry_type: str = "MARKET"


@dataclass
class Position:
    """A position tracked by a broker."""
    symbol: str
    quantity: int
    avg_price: float
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    status: str = "OPEN"                 # OPEN | CLOSED
    close_price: Optional[float] = None
    close_reason: str = ""               # TAKE_PROFIT | STOP_LOSS | MANUAL
    opened_at: datetime = field(default_factory=_utcnow)
    closed_at: Optional[datetime] = None
    position_id: str = field(default_factory=lambda: uuid4().hex)
    entry_order_id: Optional[str] = None
    take_profit_order_id: Optional[str] = None
    take_profit_order_quantity: Optional[float] = None
    exit_order_id: Optional[str] = None
    exit_order_quantity: Optional[float] = None
