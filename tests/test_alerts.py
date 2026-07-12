from datetime import datetime, timedelta, timezone

import pytest

from models import Action
from signals.alerts import AlertError, parse_alert

NOW = datetime(2026, 7, 12, 13, 30, tzinfo=timezone.utc)


def _body(**over):
    body = {
        "event_id": "evt-1",
        "timestamp": "2026-07-12T13:30:00Z",
        "action": "open",
        "side": "buy",
        "symbol": "aapl",
        "quantity": 2,
        "tp": 195.20,
        "sl": 191.80,
    }
    body.update(over)
    return body


def test_parses_open_buy_and_uppercases_symbol():
    a = parse_alert(_body(), watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)
    assert a.action == "open" and a.side is Action.BUY
    assert a.symbol == "AAPL" and a.quantity == 2
    assert a.take_profit == 195.20 and a.stop_loss == 191.80
    assert a.event_id == "evt-1"


def test_close_action_maps_to_sell():
    a = parse_alert(_body(action="close", side="sell"), watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)
    assert a.action == "close" and a.side is Action.SELL


def test_symbol_outside_watchlist_rejected():
    with pytest.raises(AlertError):
        parse_alert(_body(symbol="TSLA"), watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)


def test_quantity_over_cap_rejected():
    with pytest.raises(AlertError):
        parse_alert(_body(quantity=999), watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)


def test_non_positive_or_nonfinite_prices_rejected():
    for bad in (0, -1, "x", float("inf")):
        with pytest.raises(AlertError):
            parse_alert(_body(tp=bad), watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)


def test_stale_timestamp_rejected():
    old = (NOW - timedelta(seconds=601)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(AlertError):
        parse_alert(_body(timestamp=old), watchlist=["AAPL"], max_quantity=10, max_age_seconds=600, now=NOW)


def test_missing_event_id_rejected():
    body = _body()
    del body["event_id"]
    with pytest.raises(AlertError):
        parse_alert(body, watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)


def test_stop_loss_not_below_take_profit_rejected():
    with pytest.raises(AlertError):
        parse_alert(_body(tp=100.0, sl=110.0), watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)


def test_quantity_optional():
    body = _body()
    del body["quantity"]
    a = parse_alert(body, watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)
    assert a.quantity is None
