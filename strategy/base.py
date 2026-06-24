"""Strategy interface: turn recent price candles into a Signal."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from models import Signal

if TYPE_CHECKING:  # avoid importing pandas at runtime just for type hints
    import pandas as pd


class Strategy(ABC):
    """A strategy turns recent OHLC candles into a single Signal.

    Implementations must be pure: given the same candles, return the same
    Signal. All I/O (fetching prices) happens elsewhere.
    """

    name: str = "base"

    @abstractmethod
    def generate(self, symbol: str, candles: "pd.DataFrame") -> Signal:
        """Given OHLC candles (must include a 'Close' column), return a Signal."""
        raise NotImplementedError
