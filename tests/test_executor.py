from models import Action, Signal
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
