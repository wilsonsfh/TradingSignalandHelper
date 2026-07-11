import pytest

from models import Action, Position, Signal
from broker.base import BrokerOrderRejected
from broker.mock_broker import MockBroker
from state.store import StateStore
from trader.executor import Executor
from trader.runtime import TradingRuntime


class ScriptedFeed:
    def __init__(self, prices):
        self.prices = prices

    def last_price(self, symbol):
        value = self.prices[symbol]
        if isinstance(value, Exception):
            raise value
        return float(value)


def _runtime(store, prices, positions=None, poll_seconds=4.0):
    broker = MockBroker(positions)
    runtime = TradingRuntime(
        broker,
        ScriptedFeed(prices),
        Executor(broker),
        store,
        poll_seconds=poll_seconds,
    )
    return runtime, broker


def test_poll_once_closes_stop_without_http(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    runtime, _ = _runtime(store, {"AAPL": 97.0})
    runtime.execute(Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0))

    closed = runtime.poll_once()

    assert closed[0].close_reason == "STOP_LOSS"
    assert store.load_positions(open_only=True) == []
    assert store.recent_activity()[0]["type"] == "auto"


def test_restored_position_is_monitored_after_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    first_store = StateStore(path)
    first, _ = _runtime(first_store, {"AAPL": 100.0})
    first.execute(Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0))

    second_store = StateStore(path)
    second, _ = _runtime(
        second_store,
        {"AAPL": 97.0},
        second_store.load_positions(open_only=True),
    )
    second.poll_once()

    assert second_store.load_positions(open_only=True) == []


def test_duplicate_open_for_symbol_is_noop(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    runtime, broker = _runtime(store, {"AAPL": 100.0})
    signal = Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0)

    first = runtime.execute(signal)
    second = runtime.execute(signal)

    assert first["status"] == "OPENED"
    assert second["status"] == "NOOP"
    assert len(broker.open_positions()) == 1


def test_replayed_request_id_does_not_execute_twice(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    runtime, broker = _runtime(store, {"AAPL": 100.0})
    signal = Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0)

    first = runtime.execute(signal, request_id="same-request")
    replay = runtime.execute(signal, request_id="same-request")

    assert replay["status"] == first["status"]
    assert replay["message"] == first["message"]
    assert len(broker.open_positions()) == 1


def test_feed_failure_for_one_symbol_does_not_stop_others(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    runtime, broker = _runtime(
        store,
        {"AAPL": RuntimeError("feed down"), "MSFT": 97.0},
    )
    runtime.execute(Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0))
    runtime.execute(Signal("MSFT", Action.BUY, 100.0, 103.0, 98.0))

    closed = runtime.poll_once()

    assert [position.symbol for position in closed] == ["MSFT"]
    assert [position.symbol for position in broker.open_positions()] == ["AAPL"]
    assert any(item["type"] == "error" and item["symbol"] == "AAPL" for item in store.recent_activity())


def test_poll_persists_non_closing_broker_reconciliation(tmp_path):
    class ReconcilingBroker(MockBroker):
        def update_price(self, symbol, price):
            position = self.open_positions()[0]
            position.status = "OPEN"
            position.avg_price = price
            return []

    store = StateStore(tmp_path / "state.sqlite")
    broker = ReconcilingBroker([Position("AAPL", 1, 0.0, status="ENTRY_PENDING")])
    store.save_position(broker.positions()[0])
    runtime = TradingRuntime(
        broker,
        ScriptedFeed({"AAPL": 100.0}),
        Executor(broker),
        store,
    )

    runtime.poll_once()

    restored = store.load_positions(open_only=True)[0]
    assert restored.status == "OPEN"
    assert restored.avg_price == 100.0


def test_poll_persists_degraded_position_after_broker_error(tmp_path):
    class FailingBroker(MockBroker):
        def update_price(self, symbol, price):
            position = self.open_positions()[0]
            position.status = "OPEN_UNPROTECTED"
            position.take_profit_order_id = None
            raise RuntimeError("exit order failed")

    store = StateStore(tmp_path / "state.sqlite")
    position = Position("AAPL", 1, 100.0, 103.0, 98.0, take_profit_order_id="tp-1")
    broker = FailingBroker([position])
    store.save_position(position)
    runtime = TradingRuntime(
        broker,
        ScriptedFeed({"AAPL": 97.0}),
        Executor(broker),
        store,
    )

    runtime.poll_once()

    restored = store.load_positions(open_only=True)[0]
    assert restored.status == "OPEN_UNPROTECTED"
    assert restored.take_profit_order_id is None


def test_manual_close_persists_degraded_position_after_broker_error(tmp_path):
    class FailingBroker(MockBroker):
        def close(self, symbol, price, reason="MANUAL"):
            position = self.open_positions()[0]
            position.status = "OPEN_UNPROTECTED"
            position.take_profit_order_id = None
            raise RuntimeError("exit order failed")

    store = StateStore(tmp_path / "state.sqlite")
    position = Position("AAPL", 1, 100.0, 103.0, 98.0, take_profit_order_id="tp-1")
    broker = FailingBroker([position])
    store.save_position(position)
    runtime = TradingRuntime(
        broker,
        ScriptedFeed({"AAPL": 99.0}),
        Executor(broker),
        store,
    )

    with pytest.raises(RuntimeError, match="exit order failed"):
        runtime.close("AAPL", 99.0)

    restored = store.load_positions(open_only=True)[0]
    assert restored.status == "OPEN_UNPROTECTED"
    assert restored.take_profit_order_id is None


def test_execute_persists_position_created_before_broker_error(tmp_path):
    class FailingBroker(MockBroker):
        def place_bracket(self, order):
            self._positions.append(
                Position(
                    order.symbol,
                    order.quantity,
                    100.0,
                    order.take_profit,
                    order.stop_loss,
                    status="OPEN_UNPROTECTED",
                )
            )
            raise RuntimeError("take-profit response malformed")

    store = StateStore(tmp_path / "state.sqlite")
    broker = FailingBroker()
    runtime = TradingRuntime(
        broker,
        ScriptedFeed({"AAPL": 100.0}),
        Executor(broker),
        store,
    )

    with pytest.raises(RuntimeError, match="take-profit response malformed"):
        runtime.execute(Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0))

    restored = store.load_positions(open_only=True)[0]
    assert restored.status == "OPEN_UNPROTECTED"


def test_symbol_claim_prevents_cross_runtime_duplicate_submission(tmp_path):
    path = tmp_path / "state.sqlite"
    first_store = StateStore(path)
    second_store = StateStore(path)
    first, first_broker = _runtime(first_store, {"AAPL": 100.0})
    second, second_broker = _runtime(second_store, {"AAPL": 100.0})
    signal = Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0)

    assert first.execute(signal, request_id="first")["status"] == "OPENED"
    assert second.execute(signal, request_id="second")["status"] == "NOOP"
    assert len(first_broker.open_positions()) == 1
    assert second_broker.open_positions() == []


def test_poll_handles_open_positions_failure_without_escaping(tmp_path):
    class FailingBroker(MockBroker):
        def open_positions(self):
            raise RuntimeError("broker unavailable")

    store = StateStore(tmp_path / "state.sqlite")
    broker = FailingBroker()
    runtime = TradingRuntime(broker, ScriptedFeed({}), Executor(broker), store)

    assert runtime.poll_once() == []
    assert store.recent_activity()[0]["type"] == "error"


def test_monitor_continues_after_unexpected_poll_failure(tmp_path):
    class FlakyRuntime(TradingRuntime):
        calls = 0

        def poll_once(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("unexpected")
            self._stop_event.set()
            return []

    store = StateStore(tmp_path / "state.sqlite")
    broker = MockBroker()
    runtime = FlakyRuntime(
        broker,
        ScriptedFeed({}),
        Executor(broker),
        store,
        poll_seconds=0.001,
    )

    runtime._monitor()

    assert runtime.calls == 2


def test_stop_does_not_disconnect_while_monitor_is_alive(tmp_path):
    class DisconnectingBroker(MockBroker):
        disconnected = False

        def disconnect(self):
            self.disconnected = True

    class StuckThread:
        def join(self, timeout=None):
            return None

        def is_alive(self):
            return True

    broker = DisconnectingBroker()
    runtime = TradingRuntime(
        broker,
        ScriptedFeed({}),
        Executor(broker),
        StateStore(tmp_path / "state.sqlite"),
    )
    runtime._thread = StuckThread()

    with pytest.raises(RuntimeError, match="did not stop"):
        runtime.stop()

    assert broker.disconnected is False


def test_rejected_buy_releases_symbol_claim_for_retry(tmp_path):
    class RejectingBroker(MockBroker):
        def place_bracket(self, order):
            raise BrokerOrderRejected("entry rejected")

    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    broker = RejectingBroker()
    runtime = TradingRuntime(
        broker,
        ScriptedFeed({"AAPL": 100.0}),
        Executor(broker),
        store,
    )

    with pytest.raises(BrokerOrderRejected, match="entry rejected"):
        runtime.execute(Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0))

    assert StateStore(path).claim_symbol("AAPL", "retry") is True


def test_start_and_stop_are_idempotent(tmp_path):
    runtime, _ = _runtime(
        StateStore(tmp_path / "state.sqlite"),
        {},
        poll_seconds=0.01,
    )

    runtime.start()
    thread = runtime._thread
    runtime.start()
    assert runtime._thread is thread

    runtime.stop()
    runtime.stop()
    assert thread is not None
    assert not thread.is_alive()
