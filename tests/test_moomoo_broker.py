"""Offline contract tests for MoomooBroker; no SDK, network, or credentials."""
from types import SimpleNamespace

import pandas as pd
import pytest

from broker.moomoo_broker import MoomooBroker
from models import Action, BracketOrder, Position


class FakeTradeContext:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.fail_close = False
        self.fail_entry = False
        self.fail_tp = False
        self.fail_exit = False
        self.fail_cancel = False
        self.entry_pending = False
        self.entry_status = "SUBMITTING"
        self.entry_fill = 0.0
        self.entry_dealt_qty = 0.0
        self.tp_status = "SUBMITTED"
        self.tp_dealt_qty = 0.0
        self.exit_status = "SUBMITTED"
        self.exit_fill = 0.0
        self.exit_dealt_qty = 0.0
        self.entry_fill_on_cancel = None
        self.tp_fill_on_cancel = None
        self.missing_entry_order_id = False
        self.missing_tp_order_id = False
        self.missing_exit_order_id = False

    def place_order(self, **kwargs):
        self.calls.append(("place_order", kwargs))
        if kwargs["trd_side"] == "BUY":
            if self.fail_entry:
                return -1, "entry rejected"
            status = "SUBMITTING" if self.entry_pending else "FILLED_ALL"
            price = 0.0 if self.entry_pending else 100.0
            return 0, pd.DataFrame({
                "order_id": [None if self.missing_entry_order_id else "entry-1"],
                "order_status": [status],
                "dealt_avg_price": [price],
                "dealt_qty": [0.0 if self.entry_pending else kwargs["qty"]],
            })
        if kwargs["order_type"] == "NORMAL":
            if self.fail_tp:
                return -1, "tp rejected"
            return 0, pd.DataFrame({
                "order_id": [None if self.missing_tp_order_id else "tp-1"],
                "order_status": ["SUBMITTED"],
                "dealt_avg_price": [0.0],
                "dealt_qty": [0.0],
            })
        if self.fail_exit:
            return -1, "exit rejected"
        return 0, pd.DataFrame({
            "order_id": [None if self.missing_exit_order_id else "exit-1"],
            "order_status": [self.exit_status],
            "dealt_avg_price": [self.exit_fill],
            "dealt_qty": [self.exit_dealt_qty],
        })

    def order_list_query(self, **kwargs):
        self.calls.append(("order_list_query", kwargs))
        if kwargs["order_id"] == "entry-1":
            status, price, dealt_qty = self.entry_status, self.entry_fill, self.entry_dealt_qty
        elif kwargs["order_id"] == "exit-1":
            status, price, dealt_qty = self.exit_status, self.exit_fill, self.exit_dealt_qty
        else:
            status = self.tp_status
            price = 103.0 if self.tp_dealt_qty else 0.0
            dealt_qty = self.tp_dealt_qty
        return 0, pd.DataFrame({
            "order_id": [kwargs["order_id"]],
            "order_status": [status],
            "dealt_avg_price": [price],
            "dealt_qty": [dealt_qty],
        })

    def modify_order(self, modify_order_op, order_id, qty, price, **kwargs):
        self.calls.append(("modify_order", {
            "modify_order_op": modify_order_op,
            "order_id": order_id,
            "qty": qty,
            "price": price,
            **kwargs,
        }))
        if self.fail_cancel:
            return -1, "cancel rejected"
        if order_id == "entry-1":
            if self.entry_fill_on_cancel is not None:
                self.entry_dealt_qty = self.entry_fill_on_cancel
            self.entry_status = "CANCELLED_PART" if self.entry_dealt_qty else "CANCELLED_ALL"
        if order_id == "tp-1":
            if self.tp_fill_on_cancel is not None:
                self.tp_dealt_qty = self.tp_fill_on_cancel
            self.tp_status = "CANCELLED_PART" if self.tp_dealt_qty else "CANCELLED_ALL"
        return 0, pd.DataFrame({"order_id": [order_id]})

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("trade close failed")


class FakeQuoteContext:
    def __init__(self):
        self.closed = False
        self.fail_close = False
        self.fail_snapshot = False
        self.requested_codes = None

    def get_market_snapshot(self, codes):
        self.requested_codes = codes
        if self.fail_snapshot:
            return -1, "quote rejected"
        return 0, pd.DataFrame({"code": codes, "last_price": [101.25]})

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("quote close failed")


class FakeSDK:
    RET_OK = 0
    TrdMarket = SimpleNamespace(US="US")
    TrdEnv = SimpleNamespace(SIMULATE="SIMULATE", REAL="REAL")
    TrdSide = SimpleNamespace(BUY="BUY", SELL="SELL")
    OrderType = SimpleNamespace(MARKET="MARKET", NORMAL="NORMAL")
    ModifyOrderOp = SimpleNamespace(CANCEL="CANCEL")

    def __init__(self):
        self.trade = FakeTradeContext()
        self.quote = FakeQuoteContext()
        self.trade_args = None
        self.quote_args = None
        self.fail_quote_context = False

    def OpenSecTradeContext(self, **kwargs):
        self.trade_args = kwargs
        return self.trade

    def OpenQuoteContext(self, **kwargs):
        if self.fail_quote_context:
            raise RuntimeError("quote context failed")
        self.quote_args = kwargs
        return self.quote


def bracket(quantity=1):
    return BracketOrder("AAPL", Action.BUY, quantity, take_profit=103.0, stop_loss=98.0)


def connected_broker(sdk=None):
    sdk = sdk or FakeSDK()
    return MoomooBroker(sdk=sdk).connect(), sdk


def test_import_and_construct_without_sdk():
    broker = MoomooBroker(trd_env="SIMULATE")
    assert broker.open_positions() == []


def test_invalid_environment_is_rejected():
    with pytest.raises(ValueError, match="TRD_ENV"):
        MoomooBroker(trd_env="REL")


def test_invalid_market_is_rejected():
    with pytest.raises(ValueError, match="market"):
        MoomooBroker(market="USS")


def test_trading_methods_require_connection():
    broker = MoomooBroker()
    with pytest.raises(RuntimeError, match="not connected"):
        broker.place_bracket(bracket())
    with pytest.raises(RuntimeError):
        broker.update_price("AAPL", 100.0)
    with pytest.raises(RuntimeError):
        broker.close("AAPL", 100.0)


def test_connect_uses_exact_context_arguments():
    broker, sdk = connected_broker()
    assert sdk.trade_args == {"filter_trdmarket": "US", "host": "127.0.0.1", "port": 11111}
    assert sdk.quote_args == {"host": "127.0.0.1", "port": 11111}
    assert broker._env() == "SIMULATE"


def test_place_bracket_captures_entry_and_tp_ids():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    assert position.avg_price == 100.0
    assert position.entry_order_id == "entry-1"
    assert position.take_profit_order_id == "tp-1"
    assert sdk.trade.calls[0][1]["order_type"] == "MARKET"
    assert sdk.trade.calls[1][1]["order_type"] == "NORMAL"


def test_entry_rejection_creates_no_position():
    broker, sdk = connected_broker()
    sdk.trade.fail_entry = True
    with pytest.raises(RuntimeError, match="entry order failed"):
        broker.place_bracket(bracket())
    assert broker.positions() == []


def test_unknown_fill_is_kept_as_pending_for_reconciliation():
    broker, sdk = connected_broker()
    sdk.trade.entry_pending = True
    position = broker.place_bracket(bracket())
    assert position.status == "ENTRY_PENDING"
    assert position.avg_price == 0.0
    assert position.take_profit_order_id is None


def test_pending_entry_reconciles_and_places_take_profit():
    broker, sdk = connected_broker()
    sdk.trade.entry_pending = True
    position = broker.place_bracket(bracket())
    sdk.trade.entry_status = "FILLED_ALL"
    sdk.trade.entry_fill = 100.0
    sdk.trade.entry_dealt_qty = 1.0

    broker.update_price("AAPL", 100.0)

    assert position.status == "OPEN"
    assert position.avg_price == 100.0
    assert position.take_profit_order_id == "tp-1"


def test_tp_rejection_uses_soft_protection_state():
    broker, sdk = connected_broker()
    sdk.trade.fail_tp = True
    position = broker.place_bracket(bracket())
    assert position.status == "OPEN_UNPROTECTED"
    assert position.take_profit_order_id is None


def test_stop_cancels_tp_before_market_sell():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    broker.update_price("AAPL", 97.0)
    names = [name for name, _ in sdk.trade.calls]
    assert names[-3:] == ["modify_order", "order_list_query", "place_order"]
    assert position.status == "EXIT_PENDING"
    assert position.exit_order_id == "exit-1"

    sdk.trade.exit_status = "FILLED_ALL"
    sdk.trade.exit_fill = 97.0
    sdk.trade.exit_dealt_qty = 1.0
    assert broker.update_price("AAPL", 97.0) == [position]
    assert position.status == "CLOSED"


def test_pending_exit_does_not_submit_duplicate_sell():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    broker.update_price("AAPL", 97.0)
    sells_before = len([
        call for name, call in sdk.trade.calls
        if name == "place_order" and call["trd_side"] == "SELL" and call["order_type"] == "MARKET"
    ])

    broker.update_price("AAPL", 97.0)

    sells_after = len([
        call for name, call in sdk.trade.calls
        if name == "place_order" and call["trd_side"] == "SELL" and call["order_type"] == "MARKET"
    ])
    assert position.status == "EXIT_PENDING"
    assert sells_after == sells_before


def test_partially_filled_cancelled_exit_tracks_remaining_open_quantity():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket(quantity=10))
    broker.update_price("AAPL", 97.0)
    sdk.trade.exit_status = "CANCELLED_ALL"
    sdk.trade.exit_fill = 97.0
    sdk.trade.exit_dealt_qty = 4.0

    broker.update_price("AAPL", 97.0)

    assert position.status == "OPEN_UNPROTECTED"
    assert position.quantity == 6.0
    assert position.exit_order_id is None


def test_failed_exit_keeps_position_open():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    sdk.trade.fail_exit = True
    with pytest.raises(RuntimeError, match="exit order failed"):
        broker.close("AAPL", 99.0)
    assert position.status == "OPEN_UNPROTECTED"


def test_failed_cancel_does_not_sell_when_tp_is_not_filled():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    sdk.trade.fail_cancel = True
    with pytest.raises(RuntimeError, match="cancel"):
        broker.update_price("AAPL", 97.0)
    assert position.status == "OPEN"
    assert not any(
        name == "place_order" and call["trd_side"] == "SELL" and call["order_type"] == "MARKET"
        for name, call in sdk.trade.calls
    )


def test_cancel_race_with_filled_tp_does_not_market_sell():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    sdk.trade.fail_cancel = True
    sdk.trade.tp_status = "FILLED_ALL"

    broker.update_price("AAPL", 97.0)

    assert position.status == "CLOSED"
    assert position.close_reason == "TAKE_PROFIT"
    assert not any(
        name == "place_order" and call["trd_side"] == "SELL" and call["order_type"] == "MARKET"
        for name, call in sdk.trade.calls
    )


def test_take_profit_closes_only_after_remote_fill():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    assert broker.update_price("AAPL", 103.0) == []
    assert position.status == "OPEN"
    sdk.trade.tp_status = "FILLED_ALL"
    sdk.trade.tp_dealt_qty = 1.0
    assert broker.update_price("AAPL", 103.0) == [position]
    assert position.close_reason == "TAKE_PROFIT"


def test_partial_take_profit_sells_only_remaining_quantity():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.tp_status = "FILLED_PART"
    sdk.trade.tp_dealt_qty = 4.0

    broker.update_price("AAPL", 97.0)

    market_sells = [
        call for name, call in sdk.trade.calls
        if name == "place_order" and call["trd_side"] == "SELL" and call["order_type"] == "MARKET"
    ]
    assert market_sells[-1]["qty"] == 6.0
    assert position.status == "EXIT_PENDING"


def test_partial_pending_entry_cancels_remainder_and_protects_filled_quantity():
    broker, sdk = connected_broker()
    sdk.trade.entry_pending = True
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.entry_status = "FILLED_PART"
    sdk.trade.entry_fill = 100.0
    sdk.trade.entry_dealt_qty = 4.0

    broker.update_price("AAPL", 100.0)

    assert position.status == "OPEN"
    assert position.quantity == 4.0
    assert position.avg_price == 100.0
    assert position.take_profit_order_id == "tp-1"
    cancel = next(call for name, call in sdk.trade.calls if name == "modify_order")
    assert cancel["order_id"] == "entry-1"


def test_cancelled_partial_entry_adopts_fill_without_recancelling():
    broker, sdk = connected_broker()
    sdk.trade.entry_pending = True
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.entry_status = "CANCELLED_ALL"
    sdk.trade.entry_fill = 100.0
    sdk.trade.entry_dealt_qty = 4.0

    broker.update_price("AAPL", 100.0)

    assert position.status == "OPEN"
    assert position.quantity == 4.0
    assert not any(name == "modify_order" for name, _ in sdk.trade.calls)


def test_cancelled_partial_take_profit_exits_only_remaining_quantity():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.tp_status = "CANCELLED_ALL"
    sdk.trade.tp_dealt_qty = 4.0

    broker.update_price("AAPL", 97.0)

    market_sell = next(
        call for name, call in reversed(sdk.trade.calls)
        if name == "place_order" and call["order_type"] == "MARKET" and call["trd_side"] == "SELL"
    )
    assert market_sell["qty"] == 6.0
    assert position.status == "EXIT_PENDING"
    assert not any(name == "modify_order" for name, _ in sdk.trade.calls)


def test_cancelled_part_is_treated_as_terminal():
    broker, sdk = connected_broker()
    sdk.trade.entry_pending = True
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.entry_status = "CANCELLED_PART"
    sdk.trade.entry_fill = 100.0
    sdk.trade.entry_dealt_qty = 4.0

    broker.update_price("AAPL", 100.0)

    assert position.status == "OPEN"
    assert position.quantity == 4.0
    assert not any(name == "modify_order" for name, _ in sdk.trade.calls)


@pytest.mark.parametrize("status", ["SUBMIT_FAILED", "FILL_CANCELLED"])
def test_sdk_failure_statuses_are_terminal(status):
    assert MoomooBroker._is_terminal(status) is True


def test_entry_cancel_requeries_quantity_after_fill_race():
    broker, sdk = connected_broker()
    sdk.trade.entry_pending = True
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.entry_status = "FILLED_PART"
    sdk.trade.entry_fill = 100.0
    sdk.trade.entry_dealt_qty = 4.0
    sdk.trade.entry_fill_on_cancel = 6.0

    broker.update_price("AAPL", 100.0)

    assert position.status == "OPEN"
    assert position.quantity == 6.0


def test_tp_cancel_requeries_quantity_after_fill_race():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.tp_status = "FILLED_PART"
    sdk.trade.tp_dealt_qty = 4.0
    sdk.trade.tp_fill_on_cancel = 7.0

    broker.update_price("AAPL", 97.0)

    market_sell = next(
        call for name, call in reversed(sdk.trade.calls)
        if name == "place_order" and call["order_type"] == "MARKET" and call["trd_side"] == "SELL"
    )
    assert market_sell["qty"] == 3.0


def test_missing_entry_order_id_tracks_unknown_exposure():
    broker, sdk = connected_broker()
    sdk.trade.missing_entry_order_id = True

    with pytest.raises(RuntimeError, match="manual reconciliation"):
        broker.place_bracket(bracket())

    assert broker.open_positions()[0].status == "ENTRY_UNKNOWN"


def test_missing_tp_order_id_blocks_automated_exit():
    broker, sdk = connected_broker()
    sdk.trade.missing_tp_order_id = True

    with pytest.raises(RuntimeError, match="manual reconciliation"):
        broker.place_bracket(bracket())

    position = broker.open_positions()[0]
    assert position.status == "OPEN_PROTECTION_UNKNOWN"
    with pytest.raises(RuntimeError, match="manual reconciliation"):
        broker.update_price("AAPL", 97.0)


def test_missing_exit_order_id_quarantines_unknown_exit():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    sdk.trade.missing_exit_order_id = True

    with pytest.raises(RuntimeError, match="manual reconciliation"):
        broker.update_price("AAPL", 97.0)

    assert position.status == "EXIT_UNKNOWN"
    sells_before = len([
        call for name, call in sdk.trade.calls
        if name == "place_order" and call["trd_side"] == "SELL" and call["order_type"] == "MARKET"
    ])
    with pytest.raises(RuntimeError, match="manual reconciliation"):
        broker.update_price("AAPL", 97.0)
    sells_after = len([
        call for name, call in sdk.trade.calls
        if name == "place_order" and call["trd_side"] == "SELL" and call["order_type"] == "MARKET"
    ])
    assert sells_after == sells_before


def test_tp_fill_reconciles_even_after_price_drops_below_target():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket())
    sdk.trade.tp_status = "FILLED_ALL"
    sdk.trade.tp_dealt_qty = 1.0

    assert broker.update_price("AAPL", 99.0) == [position]
    assert position.status == "CLOSED"


def test_active_partial_tp_updates_remaining_quantity_below_target():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket(quantity=10))
    sdk.trade.tp_status = "FILLED_PART"
    sdk.trade.tp_dealt_qty = 4.0

    broker.update_price("AAPL", 99.0)

    assert position.status == "OPEN"
    assert position.quantity == 6.0


def test_active_partial_exit_updates_remaining_quantity():
    broker, sdk = connected_broker()
    position = broker.place_bracket(bracket(quantity=10))
    broker.update_price("AAPL", 97.0)
    sdk.trade.exit_status = "SUBMITTED"
    sdk.trade.exit_dealt_qty = 4.0

    broker.update_price("AAPL", 97.0)

    assert position.status == "EXIT_PENDING"
    assert position.quantity == 6.0


def test_constructor_restores_persisted_active_positions():
    position = Position("AAPL", 1, 100.0, 103.0, 98.0, take_profit_order_id="tp-1")
    broker = MoomooBroker(sdk=FakeSDK(), initial_positions=[position])
    assert broker.open_positions() == [position]


def test_last_price_uses_realtime_quote_context():
    broker, sdk = connected_broker()
    assert broker.last_price("AAPL") == 101.25
    assert sdk.quote.requested_codes == ["US.AAPL"]


def test_last_price_rejects_quote_failure():
    broker, sdk = connected_broker()
    sdk.quote.fail_snapshot = True
    with pytest.raises(RuntimeError, match="quote failed"):
        broker.last_price("AAPL")


def test_disconnect_closes_both_contexts():
    broker, sdk = connected_broker()
    broker.disconnect()
    assert sdk.trade.closed is True
    assert sdk.quote.closed is True


def test_quote_context_failure_closes_trade_context():
    sdk = FakeSDK()
    sdk.fail_quote_context = True
    broker = MoomooBroker(sdk=sdk)

    with pytest.raises(RuntimeError, match="quote context failed"):
        broker.connect()

    assert sdk.trade.closed is True


def test_disconnect_attempts_both_contexts_when_one_close_fails():
    broker, sdk = connected_broker()
    sdk.trade.fail_close = True

    with pytest.raises(RuntimeError, match="trade close failed"):
        broker.disconnect()

    assert sdk.trade.closed is True
    assert sdk.quote.closed is True
    assert broker._ctx is None
    assert broker._quote is None
