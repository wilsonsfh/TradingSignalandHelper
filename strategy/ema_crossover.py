"""EMA crossover strategy (long-only).

BUY  when the fast EMA crosses ABOVE the slow EMA on the latest bar.
SELL when the fast EMA crosses BELOW the slow EMA on the latest bar.
HOLD otherwise (or when there isn't enough data yet).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from models import Action, Signal
from strategy.base import Strategy

if TYPE_CHECKING:
    import pandas as pd


class EMACrossover(Strategy):
    name = "ema_crossover"

    def __init__(
        self,
        fast: int = 9,
        slow: int = 21,
        take_profit_pct: float = 3.0,
        stop_loss_pct: float = 2.0,
    ) -> None:
        if fast >= slow:
            raise ValueError("fast period must be smaller than slow period")
        self.fast = fast
        self.slow = slow
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct

    def _close(self, candles: "pd.DataFrame"):
        for col in ("Close", "close"):
            if col in candles.columns:
                return candles[col].astype(float)
        raise KeyError("candles must contain a 'Close' column")

    def generate(self, symbol: str, candles: "pd.DataFrame") -> Signal:
        close = self._close(candles)
        last_close = float(close.iloc[-1])

        if len(close) < self.slow + 1:
            return Signal(symbol, Action.HOLD, last_close, reason="insufficient data")

        fast_ema = close.ewm(span=self.fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow, adjust=False).mean()
        prev_diff = float(fast_ema.iloc[-2] - slow_ema.iloc[-2])
        curr_diff = float(fast_ema.iloc[-1] - slow_ema.iloc[-1])

        if prev_diff <= 0 < curr_diff:
            tp = round(last_close * (1 + self.take_profit_pct / 100.0), 4)
            sl = round(last_close * (1 - self.stop_loss_pct / 100.0), 4)
            return Signal(
                symbol, Action.BUY, last_close,
                take_profit=tp, stop_loss=sl,
                reason=f"EMA{self.fast} crossed above EMA{self.slow}",
            )

        if prev_diff >= 0 > curr_diff:
            return Signal(
                symbol, Action.SELL, last_close,
                reason=f"EMA{self.fast} crossed below EMA{self.slow}",
            )

        return Signal(symbol, Action.HOLD, last_close, reason="no crossover")
