import pytest

from models import Action, BracketOrder
from broker.mock_broker import MockBroker


def _open_long(broker, symbol="AAPL", price=100.0, qty=1, tp=103.0, sl=98.0):
    broker.update_price(symbol, price)
    order = BracketOrder(symbol=symbol, side=Action.BUY, quantity=qty,
                         take_profit=tp, stop_loss=sl)
    return broker.place_bracket(order)


def test_place_bracket_opens_position_at_last_price():
    b = MockBroker()
    pos = _open_long(b, price=100.0, tp=103.0, sl=98.0)
    assert pos.status == "OPEN"
    assert pos.avg_price == 100.0
    assert pos.take_profit == 103.0
    assert pos.stop_loss == 98.0
    assert len(b.open_positions()) == 1


def test_take_profit_closes_position():
    b = MockBroker()
    _open_long(b, price=100.0, tp=103.0, sl=98.0)
    closed = b.update_price("AAPL", 103.0)
    assert len(closed) == 1
    assert closed[0].status == "CLOSED"
    assert closed[0].close_reason == "TAKE_PROFIT"
    assert closed[0].close_price == 103.0
    assert b.open_positions() == []


def test_stop_loss_closes_position():
    b = MockBroker()
    _open_long(b, price=100.0, tp=103.0, sl=98.0)
    closed = b.update_price("AAPL", 97.5)
    assert len(closed) == 1
    assert closed[0].close_reason == "STOP_LOSS"
    assert b.open_positions() == []


def test_price_between_tp_and_sl_keeps_position_open():
    b = MockBroker()
    _open_long(b, price=100.0, tp=103.0, sl=98.0)
    closed = b.update_price("AAPL", 101.0)
    assert closed == []
    assert len(b.open_positions()) == 1


def test_price_update_for_other_symbol_does_not_close():
    b = MockBroker()
    _open_long(b, symbol="AAPL", price=100.0, tp=103.0, sl=98.0)
    closed = b.update_price("MSFT", 50.0)
    assert closed == []
    assert len(b.open_positions()) == 1


def test_manual_close():
    b = MockBroker()
    _open_long(b, price=100.0, tp=103.0, sl=98.0)
    pos = b.close("AAPL", 99.0, reason="MANUAL")
    assert pos.status == "CLOSED"
    assert pos.close_reason == "MANUAL"
    assert pos.close_price == 99.0
    assert b.open_positions() == []


def test_place_bracket_without_known_price_raises():
    b = MockBroker()
    order = BracketOrder(symbol="AAPL", side=Action.BUY, quantity=1,
                         take_profit=103.0, stop_loss=98.0)
    with pytest.raises(ValueError):
        b.place_bracket(order)
