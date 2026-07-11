import pandas as pd

from broker.mock_broker import MockBroker
from config import Config
from models import Position
from state.store import StateStore
from web.app import create_app


class MutableFeed:
    def __init__(self, prices):
        self.prices = prices

    def candles(self, symbol, period="6mo", interval="1d"):
        return pd.DataFrame({"Close": [float(value) for value in self.prices[symbol]]})

    def last_price(self, symbol):
        return float(self.prices[symbol][-1])


def _config(path):
    config = Config()
    config.watchlist = ["UP"]
    config.ema_fast = 2
    config.ema_slow = 4
    config.state_db_path = str(path)
    config.broker = "mock"
    config.trd_env = "SIMULATE"
    return config


def test_trade_persists_then_monitor_closes_after_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    first_store = StateStore(path)
    first_app = create_app(
        config=_config(path),
        feed=MutableFeed({"UP": [10, 10, 10, 10, 10, 10, 12]}),
        broker=MockBroker(),
        store=first_store,
    )
    response = first_app.test_client().post("/api/trade", json={"symbol": "UP"})
    assert response.get_json()["status"] == "OPENED"

    second_store = StateStore(path)
    restored = MockBroker(second_store.load_positions(open_only=True))
    second_app = create_app(
        config=_config(path),
        feed=MutableFeed({"UP": [10, 10, 10, 10, 10, 10, 11]}),
        broker=restored,
        store=second_store,
    )
    second_app.extensions["trading_runtime"].poll_once()

    state = second_app.test_client().get("/api/state").get_json()
    assert state["positions"] == []
    assert state["activity"][0]["type"] == "auto"


def test_normal_app_construction_restores_mock_positions(tmp_path):
    path = tmp_path / "state.sqlite"
    StateStore(path).save_position(Position("UP", 1, 100.0, 103.0, 98.0))

    app = create_app(config=_config(path))

    runtime = app.extensions["trading_runtime"]
    assert [position.symbol for position in runtime.broker.open_positions()] == ["UP"]
