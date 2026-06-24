"""Run a strategy across a watchlist to produce signals."""
from __future__ import annotations

from typing import List

from models import Action, Signal
from strategy.base import Strategy
from data.price_feed import PriceFeed


class SignalEngine:
    def __init__(
        self,
        strategy: Strategy,
        feed: PriceFeed,
        period: str = "6mo",
        interval: str = "1d",
    ) -> None:
        self.strategy = strategy
        self.feed = feed
        self.period = period
        self.interval = interval

    def run(self, watchlist: List[str]) -> List[Signal]:
        signals: List[Signal] = []
        for symbol in watchlist:
            try:
                candles = self.feed.candles(symbol, self.period, self.interval)
                signals.append(self.strategy.generate(symbol, candles))
            except Exception as exc:  # data hiccup for one symbol shouldn't kill the run
                signals.append(
                    Signal(symbol, Action.HOLD, 0.0, reason=f"data error: {exc}")
                )
        return signals
