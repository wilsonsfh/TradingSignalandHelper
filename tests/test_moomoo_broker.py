"""Tests for the MoomooBroker scaffold — only the parts that don't need the SDK.

Live order behaviour must be verified against a real OpenD connection (see README).
"""
import pytest

from models import Action, BracketOrder
from broker.moomoo_broker import MoomooBroker


def test_import_and_construct_without_sdk():
    b = MoomooBroker(host="127.0.0.1", port=11111, trd_env="SIMULATE", market="US")
    assert b.trd_env == "SIMULATE"
    assert b.open_positions() == []  # safe before connecting


def test_trading_methods_require_connection():
    b = MoomooBroker()
    order = BracketOrder("AAPL", Action.BUY, 1, take_profit=103.0, stop_loss=98.0)
    with pytest.raises(RuntimeError) as exc:
        b.place_bracket(order)
    assert "not connected" in str(exc.value).lower()
    with pytest.raises(RuntimeError):
        b.update_price("AAPL", 100.0)
    with pytest.raises(RuntimeError):
        b.close("AAPL", 100.0)


def test_code_format():
    b = MoomooBroker(market="US")
    assert b._code("AAPL") == "US.AAPL"
