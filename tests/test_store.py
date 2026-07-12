import sqlite3

import pytest

from models import Action, Position, Signal
from state.store import StateStore


def test_position_survives_store_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    position = Position(
        "AAPL",
        2,
        100.0,
        103.0,
        98.0,
        entry_order_id="entry-1",
        take_profit_order_id="tp-1",
        take_profit_order_quantity=2.0,
        exit_order_quantity=1.0,
    )

    StateStore(path).save_position(position)

    assert StateStore(path).load_positions(open_only=True) == [position]


def test_stop_order_fields_survive_store_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    position = Position(
        "AAPL",
        1,
        100.0,
        103.0,
        98.0,
        stop_loss_order_id="stop-1",
        stop_loss_order_quantity=1.0,
    )

    StateStore(path).save_position(position)

    loaded = StateStore(path).load_positions(open_only=True)
    assert loaded == [position]
    assert loaded[0].stop_loss_order_id == "stop-1"
    assert loaded[0].stop_loss_order_quantity == 1.0


def test_event_log_records_and_reads_back(tmp_path):
    store = StateStore(tmp_path / "s.sqlite")
    store.record_event("webhook", "AAPL", "open", 2, 110.0, 95.0, "OPENED", "opened", "e1")
    store.record_event("webhook", "MSFT", "close", None, None, None, "CLOSED", "closed", "e2")
    events = store.recent_events()
    assert events[0]["symbol"] == "MSFT"  # newest first
    assert events[1]["symbol"] == "AAPL"
    assert events[1]["quantity"] == 2
    assert events[1]["status"] == "OPENED"
    assert "time" in events[0]


def test_closed_position_is_not_loaded_as_open(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    position = Position("AAPL", 1, 100.0)
    store.save_position(position)
    position.status = "CLOSED"
    position.close_price = 101.0
    position.close_reason = "MANUAL"
    store.save_position(position)

    assert store.load_positions(open_only=True) == []
    assert store.load_positions() == [position]


def test_only_one_open_position_per_symbol(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_position(Position("AAPL", 1, 100.0))

    with pytest.raises(sqlite3.IntegrityError):
        store.save_position(Position("AAPL", 1, 101.0))


def test_signal_order_and_activity_round_trip(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    signal = Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0, "crossed")
    position = Position("AAPL", 1, 100.0, 103.0, 98.0)

    store.save_signal(signal)
    assert store.begin_order("req-1", signal, 1, "dashboard") is True
    assert store.begin_order("req-1", signal, 1, "dashboard") is False
    store.save_position(position)
    store.finish_order("req-1", "OPENED", "opened", position)
    store.add_activity("trade", "AAPL", "opened")

    assert store.latest_signals() == [signal]
    assert store.get_order("req-1") == {
        "request_id": "req-1",
        "source": "dashboard",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "status": "OPENED",
        "message": "opened",
        "position_id": position.position_id,
    }
    activity = store.recent_activity()
    assert activity[0]["type"] == "trade"
    assert activity[0]["symbol"] == "AAPL"
    assert activity[0]["message"] == "opened"
    assert "+00:00" in activity[0]["time"]


def test_webhook_event_is_claimed_once(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")

    assert store.claim_webhook_event("evt-1", "2026-07-11T00:00:00+00:00") is True
    assert store.claim_webhook_event("evt-1", "2026-07-11T00:00:00+00:00") is False


def test_webhook_event_claim_can_be_released_after_failed_execution(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    assert store.claim_webhook_event("evt-1", "2026-07-11T00:00:00+00:00") is True

    store.release_webhook_event("evt-1")

    assert store.claim_webhook_event("evt-1", "2026-07-11T00:00:00+00:00") is True


def test_symbol_claim_serializes_open_intents_across_store_instances(tmp_path):
    path = tmp_path / "state.sqlite"
    first = StateStore(path)
    second = StateStore(path)

    assert first.claim_symbol("AAPL", "request-1") is True
    assert second.claim_symbol("AAPL", "request-2") is False
    first.release_symbol("AAPL")
    assert second.claim_symbol("AAPL", "request-2") is True


def test_in_memory_store_persists_across_operations():
    store = StateStore(":memory:")
    position = Position("AAPL", 1, 100.0)

    store.save_position(position)

    assert store.load_positions() == [position]
