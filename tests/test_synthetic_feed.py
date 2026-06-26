import pandas as pd

from models import Action
from strategy.ema_crossover import EMACrossover
from data.synthetic_feed import SyntheticFeed


def test_candles_have_close_and_enough_rows():
    feed = SyntheticFeed(length=120)
    df = feed.candles("AAPL")
    assert isinstance(df, pd.DataFrame)
    assert "Close" in df.columns
    assert len(df) == 120


def test_candles_are_deterministic_per_symbol():
    feed = SyntheticFeed(length=60)
    a = feed.candles("AAPL")["Close"].tolist()
    b = feed.candles("AAPL")["Close"].tolist()
    assert a == b  # stable within a session


def test_different_symbols_differ():
    feed = SyntheticFeed(length=60)
    a = feed.candles("AAPL")["Close"].tolist()
    b = feed.candles("MSFT")["Close"].tolist()
    assert a != b


def test_last_price_is_positive_float():
    feed = SyntheticFeed()
    feed.candles("AAPL")  # populate the cache
    px = feed.last_price("AAPL")
    assert isinstance(px, float)
    assert px > 0


def test_designated_action_matches_strategy_output():
    """The demo feed's engineered tail must make the strategy emit that action."""
    feed = SyntheticFeed()
    strat = EMACrossover()  # default 9/21
    expected = {"BUY": Action.BUY, "SELL": Action.SELL, "HOLD": Action.HOLD}
    for sym in ["AAPL", "MSFT", "NVDA", "SPY", "TSLA", "AMZN", "GOOG", "META"]:
        sig = strat.generate(sym, feed.candles(sym))
        assert sig.action is expected[feed._action(sym)]


def test_watchlist_has_actionable_signals():
    feed = SyntheticFeed()
    strat = EMACrossover()
    actions = {strat.generate(s, feed.candles(s)).action
               for s in ["AAPL", "MSFT", "NVDA", "SPY"]}
    assert actions & {Action.BUY, Action.SELL}  # at least one tradeable
