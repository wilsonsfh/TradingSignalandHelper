import pandas as pd
import pytest

from data.price_feed import MoomooPriceFeed, YFinanceFeed
from config import Config
from web.app import _build_feed


def test_downloader_receives_expected_arguments():
    captured = {}

    def download(symbol, **kwargs):
        captured["symbol"] = symbol
        captured.update(kwargs)
        return pd.DataFrame({"Close": [101.0]})

    feed = YFinanceFeed(download)

    assert feed.candles("AAPL", period="1mo", interval="1h")["Close"].iloc[-1] == 101.0
    assert captured == {
        "symbol": "AAPL",
        "period": "1mo",
        "interval": "1h",
        "progress": False,
        "auto_adjust": False,
    }


def test_multiindex_columns_are_flattened():
    columns = pd.MultiIndex.from_tuples([("Close", "AAPL")])
    feed = YFinanceFeed(
        lambda *args, **kwargs: pd.DataFrame([[101.0]], columns=columns)
    )

    assert feed.last_price("AAPL") == 101.0


@pytest.mark.parametrize(
    "frame",
    [
        None,
        pd.DataFrame(),
        pd.DataFrame({"Open": [1.0]}),
        pd.DataFrame({"Close": [float("nan")]}),
        pd.DataFrame({"Close": [float("inf")]}),
    ],
)
def test_invalid_download_is_rejected(frame):
    feed = YFinanceFeed(lambda *args, **kwargs: frame)

    with pytest.raises(ValueError):
        feed.last_price("AAPL")


def test_moomoo_feed_uses_candle_delegate_and_realtime_broker_price():
    class CandleFeed:
        def candles(self, symbol, period="6mo", interval="1d"):
            return pd.DataFrame({"Close": [99.0]})

    class Broker:
        def last_price(self, symbol):
            assert symbol == "AAPL"
            return 101.25

    feed = MoomooPriceFeed(CandleFeed(), Broker())

    assert feed.candles("AAPL")["Close"].iloc[-1] == 99.0
    assert feed.last_price("AAPL") == 101.25


def test_app_builds_realtime_moomoo_feed_for_moomoo_mode():
    config = Config()
    config.broker = "moomoo"
    config.data_source = "yfinance"
    broker = object()

    assert isinstance(_build_feed(config, broker), MoomooPriceFeed)
