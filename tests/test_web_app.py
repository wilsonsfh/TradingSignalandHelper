from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from config import Config
from broker.mock_broker import MockBroker
from models import Position
from state.store import StateStore
from web.app import create_app


WEBHOOK_TEST_SECRET = "test-secret-value-32-characters!!"


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


def _app(webhook_enabled=False, webhook_secret=WEBHOOK_TEST_SECRET, ip_allowlist=None,
         signature_required=False, rate_per_min=5):
    feed = FakeFeed({
        "UP": [10, 10, 10, 10, 10, 10, 12],    # BUY
        "DN": [10, 10, 10, 10, 10, 10, 8],     # SELL
        "FLAT": [10, 11, 12, 13, 14, 15, 16],  # HOLD
    })
    broker = MockBroker()
    config = _cfg(["UP", "DN", "FLAT"])
    config.webhook_enabled = webhook_enabled
    config.webhook_secret = webhook_secret
    config.webhook_ip_allowlist = ip_allowlist or []
    config.webhook_signature_required = signature_required
    config.webhook_rate_per_min = rate_per_min
    app = create_app(config=config, feed=feed, broker=broker)
    app.testing = True
    return app, broker


def _alert(event_id="event-1", **changes):
    body = {
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "buy",
        "symbol": "UP",
        "key": WEBHOOK_TEST_SECRET,
    }
    body.update(changes)
    return body


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


@pytest.mark.parametrize("endpoint", ["/api/trade", "/api/close"])
def test_dashboard_actions_reject_symbol_outside_watchlist(endpoint):
    app, broker = _app()

    response = app.test_client().post(endpoint, json={"symbol": "NOPE"})

    assert response.status_code == 403
    assert response.is_json
    assert broker.open_positions() == []


@pytest.mark.parametrize("endpoint", ["/api/trade", "/api/close"])
def test_dashboard_actions_reject_non_object_json(endpoint):
    app, _ = _app()

    response = app.test_client().post(endpoint, json=[1])

    assert response.status_code == 400
    assert response.is_json


@pytest.mark.parametrize("endpoint", ["/api/trade", "/api/close"])
def test_dashboard_actions_reject_json_null(endpoint):
    app, _ = _app()
    response = app.test_client().post(
        endpoint,
        data="null",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.is_json


@pytest.mark.parametrize("endpoint", ["/api/trade", "/api/close"])
def test_dashboard_actions_reject_non_string_symbol(endpoint):
    app, _ = _app()
    response = app.test_client().post(endpoint, json={"symbol": 123})
    assert response.status_code == 400
    assert response.is_json


def test_api_signals_returns_json_when_store_is_unavailable():
    class FailingStore(StateStore):
        def save_signal(self, signal):
            raise RuntimeError("database unavailable")

    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    store = FailingStore(":memory:")
    app = create_app(
        config=_cfg(["UP"]),
        feed=feed,
        broker=MockBroker(),
        store=store,
    )
    app.testing = True

    response = app.test_client().get("/api/signals")

    assert response.status_code == 503
    assert response.is_json
    assert "database unavailable" in response.get_json()["message"]


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


def test_api_state_does_not_trigger_risk_updates():
    class CountingBroker(MockBroker):
        def __init__(self):
            super().__init__()
            self.update_count = 0

        def update_price(self, symbol, price):
            self.update_count += 1
            return super().update_price(symbol, price)

    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    broker = CountingBroker()
    app = create_app(config=_cfg(["UP"]), feed=feed, broker=broker)
    client = app.test_client()
    client.post("/api/trade", json={"symbol": "UP"})
    before = broker.update_count

    client.get("/api/state")

    assert broker.update_count == before


def test_api_state_shows_active_unprotected_position():
    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    broker = MockBroker([
        Position("UP", 1, 12.0, 12.36, 11.76, status="OPEN_UNPROTECTED")
    ])
    app = create_app(config=_cfg(["UP"]), feed=feed, broker=broker)

    state = app.test_client().get("/api/state").get_json()

    assert state["positions"][0]["status"] == "OPEN_UNPROTECTED"


def test_index_page_renders():
    app, _ = _app()
    r = app.test_client().get("/")
    assert r.status_code == 200
    assert b"TradingSignalandHelper" in r.data


def test_index_exposes_risk_console_landmarks():
    app, _ = _app()
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'id="statAttention"' in html
    assert 'id="lastUpdated"' in html
    assert '<dialog' in html and 'id="orderDialog"' in html
    assert 'rel="icon"' in html
    assert 'id="signalCount"' in html
    assert "Protection state" in html


def test_frontend_asset_covers_position_safety_states():
    script = Path("web/static/app.js").read_text()
    for state in (
        "OPEN_UNPROTECTED",
        "ENTRY_PENDING",
        "ENTRY_CANCEL_PENDING",
        "EXIT_PENDING",
        "TP_CANCEL_PENDING",
        "ENTRY_UNKNOWN",
        "OPEN_PROTECTION_UNKNOWN",
        "EXIT_UNKNOWN",
    ):
        assert state in script
    assert "showModal" in script
    assert "lastFocusedElement" in script
    assert "lastFocusedLabel" in script
    assert "restoreDialogFocus" in script
    assert "focusedControlLabel" in script
    assert "latestPositionsBySymbol" in script
    assert "signalRequestVersion" in script
    assert "stateRequestVersion" in script
    assert "Network error" in script
    assert "Cannot review sell" in script
    assert "Refresh incomplete" in script
    assert "Exact broker state" in script
    assert 'addEventListener("cancel"' in script


def test_index_exposes_event_stream_panel():
    app, _ = _app()
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'id="eventList"' in html
    assert "Incoming alerts" in html
    assert 'id="statEvents"' in html


def test_frontend_asset_covers_event_stream_and_legs():
    script = Path("web/static/app.js").read_text()
    assert "/api/events" in script
    assert "renderEvents" in script
    assert "position-legs" in script
    assert "loadEvents" in script


def test_live_index_uses_live_workspace_copy():
    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    cfg = _cfg(["UP"])
    cfg.broker = "moomoo"
    cfg.trd_env = "REAL"
    cfg.data_source = "yfinance"
    app = create_app(config=cfg, feed=feed, broker=MockBroker())
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Live trading workspace" in html
    assert "Paper trading workspace" not in html


def test_paper_index_exposes_optional_first_trade_guide():
    app, _ = _app()
    html = app.test_client().get("/").get_data(as_text=True)
    for marker in ('id="quickStart"', 'id="guideToggle"', 'id="guideDismiss"'):
        assert marker in html
    assert "Choose a BUY signal" in html
    assert "Confirm the ticket" in html
    assert "Watch protection" in html


def test_live_index_omits_first_trade_guide():
    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    cfg = _cfg(["UP"])
    cfg.broker = "moomoo"
    cfg.trd_env = "REAL"
    cfg.data_source = "yfinance"
    app = create_app(config=cfg, feed=feed, broker=MockBroker())
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'id="quickStart"' not in html
    assert 'id="guideToggle"' not in html


def test_first_trade_guide_persists_dismissal_and_replays():
    script = Path("web/static/app.js").read_text()
    styles = Path("web/static/styles.css").read_text()
    assert "signal-desk-guide-dismissed" in script
    assert "localStorage.getItem" in script
    assert "localStorage.setItem" in script
    assert "showQuickStart" in script
    assert 'toggle.addEventListener("click"' in script
    assert '$("#quickStartTitle")?.focus()' in script
    assert "#guideToggle, #guideDismiss" in styles
    assert "min-height: 44px" in styles


def test_real_money_confirmation_requires_literal_true():
    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    cfg = _cfg(["UP"])
    cfg.broker = "moomoo"
    cfg.trd_env = "REAL"
    cfg.data_source = "yfinance"
    app = create_app(config=cfg, feed=feed, broker=MockBroker())

    response = app.test_client().post(
        "/api/trade",
        json={"symbol": "UP", "confirm": "false"},
    )

    assert response.status_code == 412
    assert response.get_json()["status"] == "CONFIRM_REQUIRED"


def test_state_dependency_failure_returns_json_503():
    class FailingStore(StateStore):
        def recent_activity(self, limit=20):
            raise sqlite3.OperationalError("database unavailable")

    app = create_app(
        config=_cfg(["UP"]),
        feed=FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]}),
        broker=MockBroker(),
        store=FailingStore(":memory:"),
    )
    app.testing = True

    response = app.test_client().get("/api/state")

    assert response.status_code == 503
    assert response.is_json


def test_trade_store_failure_returns_json_503():
    class FailingStore(StateStore):
        def begin_order(self, *args, **kwargs):
            raise sqlite3.OperationalError("database unavailable")

    app = create_app(
        config=_cfg(["UP"]),
        feed=FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]}),
        broker=MockBroker(),
        store=FailingStore(":memory:"),
    )
    app.testing = True

    response = app.test_client().post("/api/trade", json={"symbol": "UP"})

    assert response.status_code == 503
    assert response.is_json


# ───────── webhook (optional TradingView) ─────────

def test_webhook_is_disabled_by_default():
    app, _ = _app()
    assert app.test_client().post("/webhook", json=_alert()).status_code == 404


def test_webhook_rejects_non_object_json():
    app, _ = _app(webhook_enabled=True)
    response = app.test_client().post("/webhook", json=[1])
    assert response.status_code == 400
    assert response.is_json


def test_webhook_rejects_json_null():
    app, _ = _app(webhook_enabled=True)
    response = app.test_client().post(
        "/webhook",
        data="null",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.is_json


def test_webhook_rejects_non_string_symbol():
    app, _ = _app(webhook_enabled=True)
    response = app.test_client().post("/webhook", json=_alert(symbol=123))
    assert response.status_code == 400
    assert response.is_json


def test_webhook_rejects_default_secret_when_enabled():
    app, _ = _app(webhook_enabled=True, webhook_secret="change-me")
    response = app.test_client().post(
        "/webhook",
        json=_alert(key="change-me"),
    )
    assert response.status_code == 503


def test_webhook_rejects_trivially_weak_secret():
    app, _ = _app(webhook_enabled=True, webhook_secret="x")
    response = app.test_client().post("/webhook", json=_alert(key="x"))
    assert response.status_code == 503


def test_webhook_rejects_bad_key():
    app, broker = _app(webhook_enabled=True)
    response = app.test_client().post("/webhook", json=_alert(key="wrong"))
    assert response.status_code == 401
    assert broker.open_positions() == []


def test_webhook_buy_falls_back_to_risk_defaults_when_absent():
    app, broker = _app(webhook_enabled=True)
    response = app.test_client().post(
        "/webhook",
        json=_alert(price=100.0),  # no tp/sl in the alert -> server computes from pct
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "OPENED"
    position = broker.open_positions()[0]
    assert position.avg_price == 12.0
    assert position.take_profit == 12.36
    assert position.stop_loss == 11.76


def test_webhook_honors_alert_tp_sl_quantity():
    app, broker = _app(webhook_enabled=True)
    response = app.test_client().post(
        "/webhook",
        json=_alert(tp=13.0, sl=11.0, quantity=4),
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "OPENED"
    position = broker.open_positions()[0]
    assert position.take_profit == 13.0
    assert position.stop_loss == 11.0
    assert position.quantity == 4


def test_webhook_rejects_quantity_over_cap():
    app, broker = _app(webhook_enabled=True)
    response = app.test_client().post("/webhook", json=_alert(quantity=10_000))
    assert response.status_code == 400
    assert broker.open_positions() == []


def test_api_events_lists_recorded_alerts():
    app, _ = _app(webhook_enabled=True)
    client = app.test_client()
    client.post("/webhook", json=_alert(event_id="ev-1"))
    r = client.get("/api/events")
    assert r.status_code == 200
    events = r.get_json()["events"]
    assert any(e["symbol"] == "UP" and e["status"] == "OPENED" for e in events)


def test_api_events_records_rejected_alert():
    app, _ = _app(webhook_enabled=True)
    client = app.test_client()
    client.post("/webhook", json=_alert(symbol="NOPE"))  # out of watchlist
    statuses = {e["status"] for e in client.get("/api/events").get_json()["events"]}
    assert "FORBIDDEN" in statuses


def test_webhook_rejects_unlisted_ip():
    app, broker = _app(webhook_enabled=True, ip_allowlist=["203.0.113.9"])
    r = app.test_client().post(
        "/webhook", json=_alert(), environ_overrides={"REMOTE_ADDR": "10.0.0.1"}
    )
    assert r.status_code == 403
    assert r.get_json()["status"] == "IP_FORBIDDEN"
    assert broker.open_positions() == []


def test_webhook_allows_listed_ip():
    app, _ = _app(webhook_enabled=True, ip_allowlist=["10.0.0.1"])
    r = app.test_client().post(
        "/webhook", json=_alert(), environ_overrides={"REMOTE_ADDR": "10.0.0.1"}
    )
    assert r.status_code == 200


def test_webhook_requires_valid_hmac_when_enabled():
    import hashlib as _hl
    import hmac as _hm
    import json as _json

    app, _ = _app(webhook_enabled=True, signature_required=True)
    body = _alert()
    raw = _json.dumps(body).encode()
    sig = _hm.new(WEBHOOK_TEST_SECRET.encode(), raw, _hl.sha256).hexdigest()
    good = app.test_client().post(
        "/webhook", data=raw, content_type="application/json",
        headers={"X-Signature": sig},
    )
    assert good.status_code == 200
    bad = app.test_client().post(
        "/webhook", data=raw, content_type="application/json",
        headers={"X-Signature": "deadbeef"},
    )
    assert bad.status_code == 401
    assert bad.get_json()["status"] == "BAD_SIGNATURE"


def test_webhook_rate_limited_after_threshold():
    app, _ = _app(webhook_enabled=True, rate_per_min=2)
    client = app.test_client()
    assert client.post("/webhook", json=_alert(event_id="a", symbol="UP")).status_code == 200
    assert client.post("/webhook", json=_alert(event_id="b", symbol="DN")).status_code == 200
    blocked = client.post("/webhook", json=_alert(event_id="c", symbol="FLAT"))
    assert blocked.status_code == 429
    assert blocked.get_json()["status"] == "RATE_LIMITED"


def test_webhook_close_executes():
    app, broker = _app(webhook_enabled=True)
    client = app.test_client()
    assert client.post("/webhook", json=_alert(event_id="buy")).status_code == 200
    response = client.post(
        "/webhook",
        json=_alert(event_id="close", action="close"),
    )
    assert response.get_json()["status"] == "CLOSED"
    assert broker.open_positions() == []


def test_webhook_rejects_replayed_event():
    app, _ = _app(webhook_enabled=True)
    client = app.test_client()
    assert client.post("/webhook", json=_alert(event_id="same")).status_code == 200
    assert client.post("/webhook", json=_alert(event_id="same")).status_code == 409


def test_webhook_transient_failure_can_retry_without_reexecution():
    class FailingBroker(MockBroker):
        def place_bracket(self, order):
            raise RuntimeError("broker unavailable")

    config = _cfg(["UP"])
    config.webhook_enabled = True
    config.webhook_secret = "a" * 32
    app = create_app(
        config=config,
        feed=FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]}),
        broker=FailingBroker(),
    )
    alert = _alert(event_id="retry", key="a" * 32)

    first = app.test_client().post("/webhook", json=alert)
    second = app.test_client().post("/webhook", json=alert)

    assert first.status_code == 503
    assert second.status_code == 503


def test_webhook_store_failure_returns_json_503():
    class FailingStore(StateStore):
        def claim_webhook_event(self, event_id, occurred_at):
            raise sqlite3.OperationalError("database unavailable")

    config = _cfg(["UP"])
    config.webhook_enabled = True
    config.webhook_secret = "a" * 32
    app = create_app(
        config=config,
        feed=FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]}),
        broker=MockBroker(),
        store=FailingStore(":memory:"),
    )
    app.testing = True

    response = app.test_client().post(
        "/webhook",
        json=_alert(key="a" * 32),
    )

    assert response.status_code == 503
    assert response.is_json


def test_webhook_rejects_expired_event():
    app, _ = _app(webhook_enabled=True)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
    assert app.test_client().post(
        "/webhook",
        json=_alert(timestamp=expired),
    ).status_code == 400


def test_webhook_rejects_symbol_outside_watchlist():
    app, _ = _app(webhook_enabled=True)
    assert app.test_client().post(
        "/webhook",
        json=_alert(symbol="NOPE"),
    ).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"event_id": ""},
        {"timestamp": "not-a-time"},
        {"action": "wait"},
    ],
)
def test_webhook_rejects_malformed_event(changes):
    app, _ = _app(webhook_enabled=True)
    assert app.test_client().post(
        "/webhook",
        json=_alert(**changes),
    ).status_code == 400


def test_webhook_blocked_in_real_money_mode():
    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    cfg = _cfg(["UP"])
    cfg.broker = "moomoo"
    cfg.trd_env = "REAL"
    cfg.data_source = "yfinance"
    cfg.webhook_enabled = True
    cfg.webhook_secret = WEBHOOK_TEST_SECRET
    app = create_app(config=cfg, feed=feed, broker=MockBroker())
    response = app.test_client().post("/webhook", json=_alert())
    assert response.status_code == 403


# ───────── REAL-money webhook gate (Step 2: default OFF) ─────────

def _real_app(*, allow_real=True, max_notional=0.0, max_daily_loss=0.0,
              enforce_market_hours=False, store=None):
    feed = FakeFeed({
        "UP": [10, 10, 10, 10, 10, 10, 12],
        "DN": [10, 10, 10, 10, 10, 10, 8],
    })
    broker = MockBroker()
    cfg = _cfg(["UP", "DN"])
    cfg.broker = "moomoo"
    cfg.trd_env = "REAL"
    cfg.data_source = "yfinance"
    cfg.webhook_enabled = True
    cfg.webhook_secret = WEBHOOK_TEST_SECRET
    cfg.allow_real_webhook = allow_real
    cfg.max_notional = max_notional
    cfg.max_daily_loss = max_daily_loss
    cfg.enforce_market_hours = enforce_market_hours
    app = create_app(config=cfg, feed=feed, broker=broker, store=store)
    app.testing = True
    return app, broker


def test_webhook_real_hard_blocked_without_optin():
    app, broker = _real_app(allow_real=False)
    r = app.test_client().post("/webhook", json=_alert(confirm=True))
    assert r.status_code == 403
    assert r.get_json()["status"] == "DISABLED"
    assert broker.open_positions() == []


def test_webhook_real_requires_confirm_even_with_optin():
    app, broker = _real_app(allow_real=True)
    r = app.test_client().post("/webhook", json=_alert())  # no confirm
    assert r.status_code == 412
    assert r.get_json()["status"] == "CONFIRM_REQUIRED"
    assert broker.open_positions() == []


def test_webhook_real_confirm_must_be_literal_true():
    app, _ = _real_app(allow_real=True)
    r = app.test_client().post("/webhook", json=_alert(confirm="true"))
    assert r.status_code == 412
    assert r.get_json()["status"] == "CONFIRM_REQUIRED"


def test_webhook_real_opens_with_optin_and_confirm():
    app, broker = _real_app(allow_real=True, enforce_market_hours=False)
    r = app.test_client().post("/webhook", json=_alert(confirm=True))
    assert r.status_code == 200
    assert r.get_json()["status"] == "OPENED"
    assert broker.open_positions()[0].symbol == "UP"


def test_webhook_real_notional_cap_blocks_oversized_order():
    app, broker = _real_app(allow_real=True, max_notional=5.0)  # UP=12 > 5
    r = app.test_client().post("/webhook", json=_alert(confirm=True))
    assert r.status_code == 403
    assert r.get_json()["status"] == "NOTIONAL_EXCEEDED"
    assert broker.open_positions() == []


def test_webhook_real_daily_loss_kill_switch_blocks():
    store = StateStore(":memory:")
    store.save_position(Position(
        "DN", 1, 100.0, status="CLOSED", close_price=80.0,
        close_reason="STOP_LOSS", closed_at=datetime.now(timezone.utc),
    ))  # -20 realized today
    app, broker = _real_app(allow_real=True, max_daily_loss=10.0, store=store)
    r = app.test_client().post("/webhook", json=_alert(confirm=True))
    assert r.status_code == 403
    assert r.get_json()["status"] == "KILL_SWITCH"
    assert broker.open_positions() == []


def test_webhook_real_close_allowed_with_confirm():
    app, broker = _real_app(allow_real=True, enforce_market_hours=False)
    client = app.test_client()
    assert client.post("/webhook", json=_alert(event_id="o", confirm=True)).status_code == 200
    r = client.post("/webhook", json=_alert(event_id="c", action="close", confirm=True))
    assert r.get_json()["status"] == "CLOSED"
    assert broker.open_positions() == []


# ───────── REAL-money armed banner (obvious trigger) ─────────

def test_real_index_shows_armed_banner():
    feed = FakeFeed({"UP": [10, 10, 10, 10, 10, 10, 12]})
    cfg = _cfg(["UP"])
    cfg.broker = "moomoo"
    cfg.trd_env = "REAL"
    cfg.data_source = "yfinance"
    cfg.max_notional = 2000.0
    cfg.max_daily_loss = 500.0
    app = create_app(config=cfg, feed=feed, broker=MockBroker())
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'class="armed-banner"' in html
    assert "LIVE MONEY ARMED" in html
    assert "$2,000" in html and "$500" in html   # live caps shown in the banner


def test_paper_index_hides_armed_banner():
    app, _ = _app()
    html = app.test_client().get("/").get_data(as_text=True)
    assert "armed-banner" not in html
    assert "LIVE MONEY ARMED" not in html
