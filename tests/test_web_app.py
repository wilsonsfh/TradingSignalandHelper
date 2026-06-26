import pandas as pd

from config import Config
from broker.mock_broker import MockBroker
from web.app import create_app


class FakeFeed:
    def __init__(self, data):
        self._data = data

    def candles(self, symbol, period="6mo", interval="1d"):
        if symbol not in self._data:
            raise KeyError(symbol)
        return pd.DataFrame({"Close": [float(p) for p in self._data[symbol]]})

    def last_price(self, symbol):
        return float(self._data[symbol][-1])


def _cfg(watchlist):
    c = Config()
    c.watchlist = watchlist
    c.ema_fast = 2
    c.ema_slow = 4
    c.quantity = 1
    c.broker = "mock"
    c.trd_env = "SIMULATE"
    c.data_source = "demo"
    return c


def _app():
    feed = FakeFeed({
        "UP": [10, 10, 10, 10, 10, 10, 12],    # BUY
        "DN": [10, 10, 10, 10, 10, 10, 8],     # SELL
        "FLAT": [10, 11, 12, 13, 14, 15, 16],  # HOLD
    })
    broker = MockBroker()
    app = create_app(config=_cfg(["UP", "DN", "FLAT"]), feed=feed, broker=broker)
    app.testing = True
    return app, broker


def test_api_signals_returns_actions_and_mode():
    app, _ = _app()
    r = app.test_client().get("/api/signals")
    assert r.status_code == 200
    data = r.get_json()
    by = {s["symbol"]: s for s in data["signals"]}
    assert by["UP"]["action"] == "BUY"
    assert by["DN"]["action"] == "SELL"
    assert by["FLAT"]["action"] == "HOLD"
    assert data["real_money"] is False
    assert data["mode"] == "MOCK / SIMULATE"


def test_api_trade_opens_position():
    app, broker = _app()
    r = app.test_client().post("/api/trade", json={"symbol": "UP"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "OPENED"
    assert len(broker.open_positions()) == 1
    assert broker.open_positions()[0].symbol == "UP"


def test_api_trade_hold_is_noop():
    app, broker = _app()
    r = app.test_client().post("/api/trade", json={"symbol": "FLAT"})
    assert r.get_json()["status"] == "NOOP"
    assert broker.open_positions() == []


def test_api_state_lists_open_positions_with_pnl():
    app, broker = _app()
    client = app.test_client()
    client.post("/api/trade", json={"symbol": "UP"})
    r = client.get("/api/state")
    assert r.status_code == 200
    data = r.get_json()
    pos = {p["symbol"]: p for p in data["positions"]}
    assert "UP" in pos
    assert "pnl" in pos["UP"]
    assert "current_price" in pos["UP"]


def test_index_page_renders():
    app, _ = _app()
    r = app.test_client().get("/")
    assert r.status_code == 200
    assert b"TradingSignalandHelper" in r.data
