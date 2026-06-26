"""Offline synthetic price feed for demos and the dashboard MVP.

Goal: with no network and no credentials, still give the dashboard a *lively* mix
of BUY / SELL / HOLD signals plus open positions whose P&L moves.

Design:
- A stable per-symbol seed (hashlib, so it's reproducible across runs) picks a base
  price and a designated action.
- ``candles`` returns a flat history ending in a single up/down/none tick that makes
  the EMA-crossover strategy emit exactly that action on the last bar. (We never draw
  candles, so the flat history is invisible; only the resulting signal matters.)
- ``last_price`` wanders ~±4% around the last close over time, so positions feel alive
  and can hit their soft TP/SL.
"""
from __future__ import annotations

import hashlib
import math
import random
import time
from typing import Dict, Optional

from data.price_feed import PriceFeed

# Weighted so most watchlist symbols are actionable (lively dashboard).
_ACTION_BY_BUCKET = {0: "BUY", 1: "BUY", 2: "SELL", 3: "SELL", 4: "HOLD"}


class SyntheticFeed(PriceFeed):
    def __init__(self, length: int = 120) -> None:
        self.length = max(length, 30)
        self._last_close: Dict[str, float] = {}

    def _seed(self, symbol: str) -> int:
        digest = hashlib.md5(symbol.upper().encode()).hexdigest()
        return int(digest[:8], 16)

    def _base(self, symbol: str) -> float:
        return round(random.Random(self._seed(symbol)).uniform(40, 400), 2)

    def _action(self, symbol: str) -> str:
        return _ACTION_BY_BUCKET[self._seed(symbol) % 5]

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d"):
        import pandas as pd

        base = self._base(symbol)
        action = self._action(symbol)
        closes = [base] * (self.length - 1)
        if action == "BUY":
            closes.append(round(base * 1.03, 2))   # last-bar jump up -> fast crosses above
        elif action == "SELL":
            closes.append(round(base * 0.97, 2))    # last-bar drop -> fast crosses below
        else:
            closes.append(base)                      # no change -> HOLD
        self._last_close[symbol] = closes[-1]
        return pd.DataFrame({"Close": closes})

    def last_price(self, symbol: str) -> float:
        anchor: Optional[float] = self._last_close.get(symbol)
        if anchor is None:
            anchor = self._base(symbol)
        # Gentle ~±1.2% wander (kept below the default 2% stop so demo positions
        # don't instantly stop out; P&L still ticks green/red). Real soft TP/SL
        # firing is covered by the broker unit tests.
        t = time.time()
        wobble = 0.012 * math.sin(t / 18.0 + (self._seed(symbol) % 7))
        noise = random.Random(int(t)).gauss(0, 0.003)
        return round(max(1.0, anchor * (1 + wobble + noise)), 2)
