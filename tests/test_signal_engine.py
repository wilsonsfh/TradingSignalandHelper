import pandas as pd

from models import Action
from strategy.ema_crossover import EMACrossover
from signals.engine import SignalEngine


class FakeFeed:
    """Duck-typed price feed for tests (no network)."""

    def __init__(self, data):
        self._data = data  # symbol -> list[prices] | Exception

    def candles(self, symbol, period="6mo", interval="1d"):
        v = self._data[symbol]
        if isinstance(v, Exception):
            raise v
        return pd.DataFrame({"Close": [float(p) for p in v]})

    def last_price(self, symbol):
        return float(self._data[symbol][-1])


def test_engine_produces_a_signal_per_symbol():
    feed = FakeFeed({
        "UP": [10, 10, 10, 10, 10, 10, 12],   # crosses up -> BUY
        "DN": [10, 10, 10, 10, 10, 10, 8],    # crosses down -> SELL
    })
    engine = SignalEngine(EMACrossover(fast=2, slow=4), feed)

    signals = engine.run(["UP", "DN"])

    by = {s.symbol: s for s in signals}
    assert by["UP"].action is Action.BUY
    assert by["DN"].action is Action.SELL


def test_engine_handles_feed_errors_as_hold():
    feed = FakeFeed({"BAD": ValueError("no data")})
    engine = SignalEngine(EMACrossover(fast=2, slow=4), feed)

    signals = engine.run(["BAD"])

    assert len(signals) == 1
    assert signals[0].action is Action.HOLD
    assert "data error" in signals[0].reason.lower()
