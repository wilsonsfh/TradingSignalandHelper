"""Price data feeds.

`YFinanceFeed` provides free (delayed) candles for signals and monitor prices.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Optional

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

    def __init__(self, downloader: Optional[Callable] = None) -> None:
        self._downloader = downloader

    def _download(self, symbol: str, **kwargs):
        if self._downloader is None:
            import yfinance as yf

            self._downloader = yf.download
        return self._downloader(symbol, **kwargs)

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> "pd.DataFrame":
        import pandas as pd

        df = self._download(
            symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            raise ValueError(f"No price data returned for {symbol!r}")
        # yfinance sometimes returns MultiIndex columns; flatten to simple names.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        if "Close" not in df.columns:
            raise ValueError(f"Price data for {symbol!r} has no Close column")
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        last = float(close.iloc[-1])
        if not math.isfinite(last):
            raise ValueError(f"Price data for {symbol!r} has no finite last close")
        return df

    def last_price(self, symbol: str) -> float:
        df = self.candles(symbol, period="5d", interval="1d")
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        return float(close.iloc[-1])


class MoomooPriceFeed(PriceFeed):
    """Use yfinance candles for strategy and OpenD quotes for risk monitoring."""

    def __init__(self, candle_feed: PriceFeed, broker) -> None:
        self.candle_feed = candle_feed
        self.broker = broker

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> "pd.DataFrame":
        return self.candle_feed.candles(symbol, period=period, interval=interval)

    def last_price(self, symbol: str) -> float:
        price = float(self.broker.last_price(symbol))
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"Moomoo returned an invalid price for {symbol!r}")
        return price
