import pandas as pd
import pytest

from models import Action
from strategy.ema_crossover import EMACrossover


def _df(prices):
    """Build a candle DataFrame from a list of close prices."""
    return pd.DataFrame({"Close": [float(p) for p in prices]})


def test_buy_when_fast_crosses_above_slow():
    strat = EMACrossover(fast=2, slow=4, take_profit_pct=3.0, stop_loss_pct=2.0)
    # flat, then a jump up -> fast EMA crosses above slow EMA on the last bar
    candles = _df([10, 10, 10, 10, 10, 10, 12])

    sig = strat.generate("AAPL", candles)

    assert sig.action is Action.BUY
    assert sig.symbol == "AAPL"
    assert sig.price == 12.0
    assert sig.take_profit == pytest.approx(12.0 * 1.03)
    assert sig.stop_loss == pytest.approx(12.0 * 0.98)


def test_sell_when_fast_crosses_below_slow():
    strat = EMACrossover(fast=2, slow=4)
    # flat, then a drop -> fast EMA crosses below slow EMA on the last bar
    candles = _df([10, 10, 10, 10, 10, 10, 8])

    sig = strat.generate("MSFT", candles)

    assert sig.action is Action.SELL
    assert sig.price == 8.0


def test_hold_when_no_crossover():
    strat = EMACrossover(fast=2, slow=4)
    # steadily rising -> fast stays above slow, no crossover on the last bar
    candles = _df([10, 11, 12, 13, 14, 15, 16])

    sig = strat.generate("NVDA", candles)

    assert sig.action is Action.HOLD


def test_hold_when_insufficient_data():
    strat = EMACrossover(fast=2, slow=4)
    candles = _df([10, 10])  # fewer than slow + 1 rows

    sig = strat.generate("SPY", candles)

    assert sig.action is Action.HOLD
    assert "insufficient" in sig.reason.lower()


def test_sell_and_hold_carry_no_tp_sl():
    strat = EMACrossover(fast=2, slow=4)
    sell = strat.generate("MSFT", _df([10, 10, 10, 10, 10, 10, 8]))
    hold = strat.generate("NVDA", _df([10, 11, 12, 13, 14, 15, 16]))
    assert sell.take_profit is None and sell.stop_loss is None
    assert hold.take_profit is None and hold.stop_loss is None
