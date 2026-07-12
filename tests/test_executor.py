from models import Action, Position, Signal
from broker.mock_broker import MockBroker
from trader.executor import Executor


def _sig(symbol, action, price, tp=None, sl=None):
    return Signal(symbol, action, price, take_profit=tp, stop_loss=sl)


def test_buy_signal_opens_position():
    b = MockBroker()
    ex = Executor(b, quantity=2)
    res = ex.execute(_sig("AAPL", Action.BUY, 100.0, tp=103.0, sl=98.0))
    assert res["status"] == "OPENED"
    opens = b.open_positions()
    assert len(opens) == 1
    assert opens[0].symbol == "AAPL"
    assert opens[0].quantity == 2
    assert opens[0].avg_price == 100.0


def test_buy_uses_signal_quantity_over_default():
    b = MockBroker()
    ex = Executor(b, quantity=1)
    res = ex.execute(
        Signal("AAPL", Action.BUY, 100.0, take_profit=103.0, stop_loss=98.0, quantity=5)
    )
    assert res["status"] == "OPENED"
    assert b.open_positions()[0].quantity == 5


def test_sell_signal_closes_open_long():
    b = MockBroker()
    ex = Executor(b, quantity=1)
    ex.execute(_sig("AAPL", Action.BUY, 100.0, tp=103.0, sl=98.0))
    res = ex.execute(_sig("AAPL", Action.SELL, 101.0))
    assert res["status"] == "CLOSED"
    assert b.open_positions() == []


def test_sell_signal_with_no_position_is_noop():
    b = MockBroker()
    ex = Executor(b, quantity=1)
    res = ex.execute(_sig("AAPL", Action.SELL, 101.0))
    assert res["status"] == "NOOP"
    assert b.open_positions() == []


def test_hold_signal_is_noop():
    b = MockBroker()
    ex = Executor(b, quantity=1)
    res = ex.execute(_sig("AAPL", Action.HOLD, 100.0))
    assert res["status"] == "NOOP"
    assert b.positions() == []


def test_buy_reports_pending_until_broker_confirms_entry_fill():
    class PendingEntryBroker(MockBroker):
        def place_bracket(self, order):
            position = Position(
                order.symbol,
                order.quantity,
                0.0,
                order.take_profit,
                order.stop_loss,
                status="ENTRY_PENDING",
            )
            self._positions.append(position)
            return position

    broker = PendingEntryBroker()
    result = Executor(broker).execute(
        _sig("AAPL", Action.BUY, 100.0, tp=103.0, sl=98.0)
    )

    assert result["status"] == "ENTRY_PENDING"


def test_sell_reports_pending_until_broker_confirms_exit_fill():
    class PendingExitBroker(MockBroker):
        def close(self, symbol, price, reason="MANUAL"):
            position = self.open_positions()[0]
            position.status = "EXIT_PENDING"
            return position

    broker = PendingExitBroker([Position("AAPL", 1, 100.0)])
    result = Executor(broker).execute(_sig("AAPL", Action.SELL, 101.0))

    assert result["status"] == "EXIT_PENDING"
