"""Price data feeds.

`YFinanceFeed` provides free (delayed) daily candles for computing signals.
A moomoo-backed feed for the live soft-stop watch is added in Phase 5.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


class PriceFeed(ABC):
    @abstractmethod
    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> "pd.DataFrame":
        """Return OHLC candles with at least a 'Close' column."""
        raise NotImplementedError

    @abstractmethod
    def last_price(self, symbol: str) -> float:
        """Return the most recent price for a symbol."""
        raise NotImplementedError


class YFinanceFeed(PriceFeed):
    """Free, delayed price data via yfinance. Good enough for daily signals."""

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> "pd.DataFrame":
        import pandas as pd
        import yfinance as yf

        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
        if df is None or df.empty:
            raise ValueError(f"No price data returned for {symbol!r}")
        # yfinance sometimes returns MultiIndex columns; flatten to simple names.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        return df

    def last_price(self, symbol: str) -> float:
        df = self.candles(symbol, period="5d", interval="1d")
        return float(df["Close"].iloc[-1])
