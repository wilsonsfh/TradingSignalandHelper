# Event-Driven TradingView -> moomoo Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the app from an internally-computed EMA paper-trader into an event-driven bridge where an external TradingView alert (the "event") is the source of truth for every trade, mirroring Curteis Yang's "the Pine script is the brain, the bridge stays dumb" design.

**Architecture:** TradingView Pine strategy fires a webhook alert on a chart event. The Flask `/webhook` endpoint authenticates, de-duplicates, and validates the alert, then executes it verbatim on the selected broker (MockBroker for tests/paper, MoomooBroker via OpenD for SIMULATE). Because moomoo has no native OCO, each entry becomes a manually-tied trio (market entry + limit take-profit + stop-loss order) reconciled by the existing broker state machine. The dashboard is reframed to show the stream of incoming events and the live legs of each position.

**Tech Stack:** Python 3.9+, Flask, SQLite (`sqlite3`), `moomoo-api==10.8.6808` (via OpenD, never called in tests), vanilla JS/CSS "Calm Risk Console" UI, pytest. No new heavy runtime dependencies.

## Source Of Truth

This plan models Curteis Yang, "Building a TradingView to moomoo Auto-Trading Bridge" (Medium, 2026-06-21). Load-bearing ideas adopted here:

- The bridge is dumb; TradingView Pine is the brain. Entry/TP/SL/side/quantity all arrive **in the alert**.
- One endpoint: `POST /webhook` with `{action, symbol, side, quantity, tp, sl, key}`.
- moomoo runs behind **OpenD** on `127.0.0.1:11111`; code never talks to moomoo directly.
- No native OCO -> one trade is 3 orders (market entry, limit TP, stop SL) tied together in local state so a fill on one cancels the other.
- Defence-in-depth: shared secret + TradingView IP allow-list + rate limit; HTTPS + Cloudflare at the edge.
- Deployment: OpenD + bridge run only during US market hours on a host with a persistent `Device.dat` and a stable HTTPS endpoint.

## Global Constraints

- Python `>=3.9`; keep the existing dependency set. Only stdlib + already-pinned packages; `moomoo-api` stays pinned at `10.8.6808`.
- SIMULATE / mock first. `TRD_ENV=REAL` stays behind the existing hard gate; the webhook remains **blocked in REAL mode** until the separate, human-approved REAL-enablement plan (Phase 6) lands.
- Every broker behaviour must be verifiable offline: extend `MockBroker` and the fake-SDK contract test in lockstep. Tests never start OpenD, log into an account, or place a live order.
- Preserve existing safety invariants: single open position per symbol, per-symbol claim, replay resistance (`event_id`), timestamp freshness, unknown-order-ID quarantine (`ENTRY_UNKNOWN` / `OPEN_PROTECTION_UNKNOWN` / `EXIT_UNKNOWN`), and no duplicate exits while a broker confirmation is pending.
- The alert is authoritative for `quantity`, `tp`, `sl`, and `side`/`action`, but always within server-side bounds (Task 1). The server never silently overrides an alert's numbers; it either honors them or rejects the alert.
- Local dev server binds `127.0.0.1`. Any public exposure is via HTTPS + Cloudflare (Phase 5), never the Flask dev server on `0.0.0.0`.
- UI work (Phase 3) MUST enter through the `frontend-design` skill and produce a side-by-side visual comparison before any markup/CSS changes; keep the existing "Calm Risk Console" system (this project does NOT use Kumo).
- Verification gate for every task: `pytest -q` green, `python -m compileall -q broker data signals state strategy trader web`, `node --check web/static/app.js` when JS changes, `pip check`, `git diff --check`.

## Design Decisions, Assumptions & Alternatives

**Chosen approach — "Honor-the-alert bridge" (evolve the existing `/webhook`).**
Keep the current app and its tested state machine, but make the webhook the primary path and honor the alert's numbers. Add a real stop-loss order to complete the manual OCO. Reframe the dashboard as an event monitor. Keep the internal EMA engine only as an optional manual/dashboard convenience.

Alternatives considered:

- **Pure dumb bridge (rejected as the first step):** delete `SignalEngine`/EMA and `/api/signals`+`/api/trade`, leaving only the executor. Closest to the article's literal "one endpoint" shape, but discards working, tested features and offline usefulness. Captured as an optional future simplification once the event path is proven.
- **Two-service split (rejected):** a separate minimal bridge microservice next to the existing app, sharing `broker/`+`state/`. Matches the article's "single Flask app" literally but adds a second process, shared-state coupling, and deployment overhead for no functional gain here.

Assumptions (all safe/reversible; revisit if wrong):

1. **Paper/SIMULATE is the target for this plan.** Auto-execution stays out of REAL mode. REAL is a separate, explicitly-gated plan requiring credentials + human confirmation.
2. **Long-only, one position per symbol** remains the supported model (matches current broker). `action=open, side=buy` opens; `action=close`/`side=sell` closes. Shorting is out of scope.
3. **`tp`/`sl` in the alert are absolute prices** (as in Curteis' example `tp: 195.20, sl: 191.80`), not percentages. When absent, the server may fall back to the configured percentages (documented per task).
4. TradingView's published webhook source IPs are treated as config with a default list, verified against TradingView's current documentation at deploy time (Task 10).

---

## File Structure

- Create: `signals/alerts.py` — alert schema, `parse_alert()`, `AlertError`, bounds validation. One responsibility: turn an untrusted JSON body into a validated, normalized instruction.
- Create: `tests/test_alerts.py` — unit tests for the parser/bounds.
- Modify: `models.py` — add explicit `quantity`/`tp`/`sl` carriage on `Signal`; add `stop_loss_order_id` + `stop_loss_order_quantity` to `Position`.
- Modify: `trader/executor.py`, `trader/runtime.py` — allow a per-signal quantity override (alert-driven) instead of a fixed `cfg.quantity`.
- Modify: `broker/base.py`, `broker/mock_broker.py`, `broker/moomoo_broker.py` — place + reconcile a real stop-loss order and pair it with the take-profit as a manual OCO; keep soft-stop fallback.
- Modify: `state/store.py` — persist a first-class event log (action/symbol/qty/tp/sl/result/status/time) and stop-order fields.
- Modify: `web/app.py` — rewrite `/webhook` to honor the alert; add `/api/events`; add HMAC, IP allow-list, and rate-limit guards.
- Modify: `web/templates/index.html`, `web/static/app.js`, `web/static/styles.css` — event stream panel + per-position OCO legs (via `frontend-design`).
- Modify: `config.py`, `.env.example` — new knobs (`WEBHOOK_SIGNATURE_REQUIRED`, `WEBHOOK_IP_ALLOWLIST`, `WEBHOOK_RATE_PER_MIN`, `MAX_ALERT_QUANTITY`, `USE_BROKER_STOP_ORDER`).
- Create: `docs/deploy/README.md` — OpenD + bridge + market-hours scheduling + persistent `Device.dat` + HTTPS/Caddy + Cloudflare WAF runbook.
- Modify: `README.md`, `PROGRESS_REPORT.md` — document the event-driven model.

---

## Phases & Tasks

- Phase 1 — Honor the alert (Pine is the brain): Tasks 1-3
- Phase 2 — Manual OCO with a real stop order: Tasks 4-6
- Phase 3 — Event-driven dashboard surface: Tasks 7-8
- Phase 4 — Security hardening (defence-in-depth): Tasks 9-11
- Phase 5 — Deployment blueprint (docs only): Task 12
- Phase 6 — REAL enablement (separate gated plan): Task 13 (spec-only)
- Phase 7 — Verification & docs: Task 14

## Phase 1 — Honor the alert (Pine is the brain)

Today `/webhook` ignores `tp`/`sl`/`quantity` from the alert and recomputes them. This phase makes the alert authoritative, within server bounds.

### Task 1: Alert schema + validating parser

**Files:**
- Create: `signals/alerts.py`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Produces:
  - `class AlertError(ValueError)` — raised with a human-readable message on any invalid alert.
  - `@dataclass ParsedAlert` with fields: `action: str` (`"open"|"close"`), `side: Action` (`Action.BUY|Action.SELL`), `symbol: str` (upper), `quantity: int|None`, `take_profit: float|None`, `stop_loss: float|None`, `event_id: str`, `occurred_at: datetime` (tz-aware).
  - `def parse_alert(body: dict, *, watchlist: list[str], max_quantity: int, max_age_seconds: int, now: datetime | None = None) -> ParsedAlert`.
- Consumes: `models.Action`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_alerts.py
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
    body = _body(); del body["event_id"]
    with pytest.raises(AlertError):
        parse_alert(body, watchlist=["AAPL"], max_quantity=10, max_age_seconds=300, now=NOW)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alerts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'signals.alerts'`.

- [ ] **Step 3: Implement `signals/alerts.py`**

```python
"""Parse and validate an untrusted TradingView alert into an instruction.

The alert is authoritative for side/quantity/tp/sl, but only within
server-side bounds. Anything out of bounds is rejected, never silently
clamped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from models import Action


class AlertError(ValueError):
    """Raised when an alert body is malformed or out of bounds."""


_OPEN = {"open", "buy", "long"}
_CLOSE = {"close", "sell", "short", "exit"}


@dataclass
class ParsedAlert:
    action: str
    side: Action
    symbol: str
    quantity: Optional[int]
    take_profit: Optional[float]
    stop_loss: Optional[float]
    event_id: str
    occurred_at: datetime


def _price(value: object, name: str) -> Optional[float]:
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        raise AlertError(f"{name} must be a number")
    if not math.isfinite(price) or price <= 0:
        raise AlertError(f"{name} must be a positive, finite price")
    return round(price, 4)


def parse_alert(
    body: dict,
    *,
    watchlist: List[str],
    max_quantity: int,
    max_age_seconds: int,
    now: Optional[datetime] = None,
) -> ParsedAlert:
    if not isinstance(body, dict):
        raise AlertError("alert body must be a JSON object")
    now = now or datetime.now(timezone.utc)

    event_id = str(body.get("event_id", "")).strip()
    timestamp = str(body.get("timestamp", "")).strip()
    if not event_id or not timestamp:
        raise AlertError("event_id and timestamp are required")
    try:
        occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise AlertError("timestamp must be ISO-8601")
    if occurred_at.tzinfo is None:
        raise AlertError("timestamp must be timezone-aware")
    age = abs((now - occurred_at.astimezone(timezone.utc)).total_seconds())
    if age > max_age_seconds:
        raise AlertError("alert is too old or too far in the future")

    action_raw = str(body.get("action", "")).lower().strip()
    side_raw = str(body.get("side", "")).lower().strip()
    tokens = {action_raw, side_raw}
    if tokens & _CLOSE and action_raw != "open":
        action, side = "close", Action.SELL
    elif tokens & _OPEN:
        action, side = "open", Action.BUY
    else:
        raise AlertError("could not determine open/buy or close/sell")

    symbol_value = body.get("symbol")
    if symbol_value is not None and not isinstance(symbol_value, str):
        raise AlertError("symbol must be a string")
    symbol = (symbol_value or "").upper().strip()
    if not symbol:
        raise AlertError("symbol is required")
    if symbol not in watchlist:
        raise AlertError("symbol is outside the watchlist")

    quantity: Optional[int] = None
    if body.get("quantity") is not None:
        try:
            quantity = int(body["quantity"])
        except (TypeError, ValueError):
            raise AlertError("quantity must be an integer")
        if quantity <= 0:
            raise AlertError("quantity must be positive")
        if quantity > max_quantity:
            raise AlertError(f"quantity exceeds MAX_ALERT_QUANTITY ({max_quantity})")

    take_profit = _price(body.get("tp"), "tp")
    stop_loss = _price(body.get("sl"), "sl")
    if action == "open" and take_profit is not None and stop_loss is not None:
        if not (stop_loss < take_profit):
            raise AlertError("stop_loss must be below take_profit for a long entry")

    return ParsedAlert(
        action=action,
        side=side,
        symbol=symbol,
        quantity=quantity,
        take_profit=take_profit,
        stop_loss=stop_loss,
        event_id=event_id,
        occurred_at=occurred_at,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alerts.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add signals/alerts.py tests/test_alerts.py
git commit -m "feat(alerts): validating parser that honors alert side/qty/tp/sl within bounds"
```

### Task 2: Per-signal quantity override through the executor

**Files:**
- Modify: `models.py` (add `quantity` to `Signal`)
- Modify: `trader/executor.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- Consumes: `models.Signal` (now carries optional `quantity`).
- Produces: `Executor.execute(signal)` uses `signal.quantity` when set, else the configured default; `runtime.execute(signal, ...)` unchanged signature.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_executor.py (add)
def test_executor_uses_signal_quantity_over_default():
    broker = MockBroker()
    ex = Executor(broker, default_quantity=1)
    sig = Signal("AAPL", Action.BUY, 100.0, take_profit=103.0, stop_loss=98.0, quantity=5)
    pos = ex.execute(sig)
    assert pos.quantity == 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_executor.py::test_executor_uses_signal_quantity_over_default -v`
Expected: FAIL — `Signal` has no `quantity` (TypeError) or quantity is 1.

- [ ] **Step 3: Add `quantity` to `Signal` and use it in the executor**

In `models.py`, add to `Signal` (after `reason`):

```python
    quantity: Optional[int] = None     # alert-supplied size; None => executor default
```

In `trader/executor.py`, where the `BracketOrder` quantity is set, replace the fixed default with:

```python
        quantity = signal.quantity if signal.quantity else self.default_quantity
```

(Confirm the constructor stores `self.default_quantity`; rename the param if it is currently `quantity`.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_executor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add models.py trader/executor.py tests/test_executor.py
git commit -m "feat(executor): honor alert-supplied quantity, falling back to configured default"
```

### Task 3: Rewire `/webhook` to honor the alert

**Files:**
- Modify: `web/app.py:264-354` (the `webhook()` view)
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `signals.alerts.parse_alert`, `AlertError`; `Config.max_alert_quantity` (Task 9 adds the knob; until then use `len(watchlist)*existing default` — see note).
- Produces: `/webhook` builds the `Signal` from the parsed alert (its `tp`/`sl`/`quantity`), preserving replay/freshness/auth/watchlist and the REAL-mode block.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_app.py (add)
def test_webhook_honors_alert_tp_sl_quantity(client_factory):
    client, store = client_factory(webhook=True, secret="x" * 32)
    body = {
        "event_id": "e1", "timestamp": _fresh_iso(),
        "action": "open", "side": "buy", "symbol": "AAPL",
        "quantity": 4, "tp": 210.0, "sl": 190.0, "key": "x" * 32,
    }
    r = client.post("/webhook", json=body)
    assert r.status_code == 200
    pos = r.get_json()["position"]
    assert pos["quantity"] == 4
    assert pos["take_profit"] == 210.0 and pos["stop_loss"] == 190.0
```

(Reuse or add the `client_factory`/`_fresh_iso` helpers already used by existing webhook tests in this file.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_web_app.py::test_webhook_honors_alert_tp_sl_quantity -v`
Expected: FAIL — quantity is `cfg.quantity` (1) and tp/sl are recomputed, not 210/190.

- [ ] **Step 3: Replace the body of `webhook()` after the auth/REAL checks**

Keep lines up to and including the REAL-mode block (`web/app.py:280-284`). Replace the manual field extraction + tp/sl computation (current lines ~286-336) with:

```python
        from signals.alerts import AlertError, parse_alert

        try:
            alert = parse_alert(
                body,
                watchlist=cfg.watchlist,
                max_quantity=cfg.max_alert_quantity,
                max_age_seconds=cfg.webhook_max_age_seconds,
            )
        except AlertError as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 400

        try:
            price = float(feed.last_price(alert.symbol))
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": f"no price available: {exc}"}), 503

        try:
            claimed = store.claim_webhook_event(alert.event_id, alert.occurred_at.isoformat())
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        if not claimed:
            return jsonify({"status": "REPLAY", "message": "event_id was already processed"}), 409

        take_profit = alert.take_profit
        stop_loss = alert.stop_loss
        if alert.action == "open":
            if take_profit is None:
                take_profit = round(price * (1 + cfg.take_profit_pct / 100), 2)
            if stop_loss is None:
                stop_loss = round(price * (1 - cfg.stop_loss_pct / 100), 2)
        else:
            take_profit = stop_loss = None

        signal = Signal(
            alert.symbol, alert.side, price,
            take_profit=take_profit, stop_loss=stop_loss,
            reason="tradingview webhook", quantity=alert.quantity,
        )
```

Leave the existing `runtime.execute(...)` call and its release-on-error handling intact below this block.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_web_app.py -q`
Expected: PASS (new test + all existing webhook tests still green).

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_web_app.py
git commit -m "feat(webhook): honor alert-supplied tp/sl/quantity; fall back to configured pct only when absent"
```

> **Note on `cfg.max_alert_quantity`:** Task 9 formally adds this config knob. If Phase 4 is deferred, add the single line to `config.py` now: `max_alert_quantity: int = field(default_factory=lambda: int(os.getenv("MAX_ALERT_QUANTITY", "100")))`.

## Phase 2 — Manual OCO with a real stop order

Curteis' trade is three orders (market entry, limit TP, stop SL) tied together so a fill on one cancels the other. Today the app places entry + limit-TP and monitors SL in software. This phase adds a real broker stop order and OCO pairing, keeping the soft-stop as a fallback. Everything is proven offline through `MockBroker` and the fake-SDK contract test — **OpenD is never started**.

### Task 4: Verify the SDK stop-order contract, add Position fields, place a stop order

**Files:**
- Modify: `models.py` (Position fields)
- Modify: `broker/moomoo_broker.py` (add `_place_stop_loss`)
- Modify: `tests/test_moomoo_broker.py` (fake-SDK contract)

**Interfaces:**
- Produces: `Position.stop_loss_order_id: Optional[str]`, `Position.stop_loss_order_quantity: Optional[float]`; `MoomooBroker._place_stop_loss(position)` places a stop order and records the id, or sets `OPEN_UNPROTECTED` (rejected) / `OPEN_PROTECTION_UNKNOWN` (accepted without id).

- [ ] **Step 1: Verify the installed SDK's stop-order API (read-only inspection, no OpenD)**

Run:

```bash
python - <<'PY'
import moomoo, inspect
print("OrderType:", [n for n in dir(moomoo.OrderType) if not n.startswith("_")])
print("place_order:", inspect.signature(moomoo.OpenSecTradeContext.place_order))
PY
```

Expected: an `OrderType` list that includes a stop variant (e.g. `STOP`, `STOP_LIMIT`) and a `place_order` signature exposing the trigger-price parameter (commonly `aux_price`). Record the exact enum name + trigger param; use them in Step 3. If no stop type exists for US in this SDK build, STOP the task and fall back to soft-stop only (Task 6) — note it in `PROGRESS_REPORT.md`.

- [ ] **Step 2: Write the failing contract test**

```python
# tests/test_moomoo_broker.py (add) — FakeCtx mirrors the recorded signature
def test_place_stop_loss_records_order_id(make_broker):
    broker, ctx = make_broker()  # existing fake-SDK helper
    pos = _open_filled_position(broker, ctx, symbol="AAPL", qty=3, tp=110.0, sl=95.0)
    assert pos.stop_loss_order_id is not None
    assert pos.stop_loss_order_quantity == 3
    last = ctx.orders[-1]
    assert last["order_type"] == broker._sdk.OrderType.STOP       # or recorded name
    assert last["aux_price"] == 95.0                              # or recorded trigger param
    assert last["trd_side"] == broker._sdk.TrdSide.SELL
```

- [ ] **Step 3: Implement `_place_stop_loss` and call it after TP**

Add to `models.Position` (after the take-profit fields):

```python
    stop_loss_order_id: Optional[str] = None
    stop_loss_order_quantity: Optional[float] = None
```

Add to `MoomooBroker` (use the enum/param names recorded in Step 1):

```python
    def _place_stop_loss(self, position: Position) -> None:
        if position.stop_loss is None:
            return
        ret, data = self._ctx.place_order(
            price=position.stop_loss,          # limit for STOP_LIMIT; ignored for pure STOP
            qty=position.quantity,
            code=self._code(position.symbol),
            trd_side=self._sdk.TrdSide.SELL,
            order_type=self._sdk.OrderType.STOP,
            aux_price=position.stop_loss,       # trigger price
            trd_env=self._env(),
        )
        if ret != self._sdk.RET_OK:
            position.status = "OPEN_UNPROTECTED"   # soft-stop monitor takes over (Task 6)
            return
        position.stop_loss_order_quantity = float(position.quantity)
        try:
            position.stop_loss_order_id = self._order_id(data, "stop-loss")
        except RuntimeError as exc:
            position.status = "OPEN_PROTECTION_UNKNOWN"
            raise RuntimeError(
                "moomoo accepted stop-loss protection without an order ID; "
                "manual reconciliation required"
            ) from exc
```

Guard the call behind config (Task 9's `USE_BROKER_STOP_ORDER`, default `True`). In `place_bracket` and `_reconcile_entry`, immediately after the existing `self._place_take_profit(position)` call, add:

```python
        if self._use_broker_stop_order and position.status == "OPEN":
            self._place_stop_loss(position)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_moomoo_broker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add models.py broker/moomoo_broker.py tests/test_moomoo_broker.py
git commit -m "feat(moomoo): place a real stop-loss order after entry+TP (verified SDK contract)"
```

### Task 5: OCO pairing — a fill on one leg cancels the other

**Files:**
- Modify: `broker/moomoo_broker.py` (`update_price`, `_exit_position`)
- Test: `tests/test_moomoo_broker.py`

**Interfaces:**
- Produces: in `update_price`, if the stop-loss order fills -> cancel the TP limit, mark `CLOSED`/`STOP_LOSS`; if the TP fills -> cancel the stop order, mark `CLOSED`/`TAKE_PROFIT`; manual close/`_exit_position` cancels both remaining legs before (or instead of) the market exit.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_moomoo_broker.py (add)
def test_stop_fill_cancels_take_profit(make_broker):
    broker, ctx = make_broker()
    pos = _open_filled_position(broker, ctx, "AAPL", qty=2, tp=110.0, sl=95.0)
    ctx.fill_order(pos.stop_loss_order_id, price=95.0, qty=2)   # fake SDK helper
    broker.update_price("AAPL", 95.0)
    assert pos.status == "CLOSED" and pos.close_reason == "STOP_LOSS"
    assert ctx.was_cancelled(pos.take_profit_order_id)


def test_tp_fill_cancels_stop(make_broker):
    broker, ctx = make_broker()
    pos = _open_filled_position(broker, ctx, "AAPL", qty=2, tp=110.0, sl=95.0)
    ctx.fill_order(pos.take_profit_order_id, price=110.0, qty=2)
    broker.update_price("AAPL", 110.0)
    assert pos.status == "CLOSED" and pos.close_reason == "TAKE_PROFIT"
    assert ctx.was_cancelled(pos.stop_loss_order_id)
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_moomoo_broker.py -k "cancels" -v`
Expected: FAIL — stop leg is not queried/reconciled yet.

- [ ] **Step 3: Reconcile the stop leg in `update_price` (mirror the TP block)**

In `update_price`, inside the per-position loop and before the price-threshold checks, add a stop-order reconciliation symmetric to the existing TP block (`moomoo_broker.py:220-241`):

```python
            if position.stop_loss_order_id:
                status, fill_price, dealt = self._query_order(position.stop_loss_order_id)
                original = float(position.stop_loss_order_quantity or position.quantity)
                position.stop_loss_order_quantity = original
                if self._is_filled(status) or dealt >= original:
                    if position.take_profit_order_id:
                        try:
                            self._cancel_order(position.take_profit_order_id, "take-profit")
                        except RuntimeError:
                            pass
                        position.take_profit_order_id = None
                    self._mark_closed(position, fill_price or position.stop_loss or price, "STOP_LOSS")
                    closed.append(position)
                    continue
                if self._is_terminal(status):
                    position.stop_loss_order_id = None
                    position.stop_loss_order_quantity = None
```

Then, in the existing TP-filled branch (where `_mark_closed(..., "TAKE_PROFIT")` is called), immediately before marking closed, cancel a live stop order:

```python
                    if position.stop_loss_order_id:
                        try:
                            self._cancel_order(position.stop_loss_order_id, "stop-loss")
                        except RuntimeError:
                            pass
                        position.stop_loss_order_id = None
```

- [ ] **Step 4: Cancel both legs on manual close in `_exit_position`**

At the start of `_exit_position`, after the quarantine/pending guards and before the TP-cancel block, cancel a live stop order so the manual market exit cannot double-sell:

```python
        if position.stop_loss_order_id:
            try:
                self._cancel_order(position.stop_loss_order_id, "stop-loss")
            except RuntimeError:
                pass
            position.stop_loss_order_id = None
            position.stop_loss_order_quantity = None
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_moomoo_broker.py -q`
Expected: PASS (new OCO tests + all existing state-machine tests still green).

- [ ] **Step 6: Commit**

```bash
git add broker/moomoo_broker.py tests/test_moomoo_broker.py
git commit -m "feat(moomoo): manual OCO — a fill on TP or stop cancels the sibling leg"
```

### Task 6: Soft-stop fallback + MockBroker parity + restart recovery

**Files:**
- Modify: `broker/mock_broker.py` (mirror stop-order fields/behaviour for offline tests)
- Modify: `state/store.py` (persist `stop_loss_order_id` / `stop_loss_order_quantity`)
- Test: `tests/test_mock_broker.py`, `tests/test_store.py`, `tests/test_restart_integration.py`

**Interfaces:**
- Consumes: `Position` stop-order fields.
- Produces: when `USE_BROKER_STOP_ORDER` is false or the stop order was rejected (`OPEN_UNPROTECTED`), the existing price-threshold soft stop in `update_price` still exits the position; stop-order ids survive a restart.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mock_broker.py (add)
def test_soft_stop_still_exits_when_broker_stop_disabled():
    broker = MockBroker()
    pos = broker.place_bracket(BracketOrder("AAPL", Action.BUY, 1, take_profit=110.0, stop_loss=95.0))
    broker.update_price("AAPL", 94.0)
    assert pos.status == "CLOSED" and pos.close_reason == "STOP_LOSS"

# tests/test_store.py (add)
def test_store_round_trips_stop_order_fields(tmp_path):
    store = StateStore(str(tmp_path / "s.sqlite"))
    p = Position("AAPL", 1, 100.0, stop_loss_order_id="SL1", stop_loss_order_quantity=1.0)
    store.save_position(p)
    loaded = store.load_positions(open_only=True)[0]
    assert loaded.stop_loss_order_id == "SL1" and loaded.stop_loss_order_quantity == 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_mock_broker.py tests/test_store.py -q`
Expected: FAIL — store does not persist the new columns; MockBroker lacks stop fields.

- [ ] **Step 3: Implement parity + persistence**

- In `state/store.py`, add `stop_loss_order_id` (TEXT) and `stop_loss_order_quantity` (REAL) to the positions table `CREATE TABLE`, the `INSERT`/`UPSERT` column list, and the row->`Position` hydration. Add an idempotent `ALTER TABLE ... ADD COLUMN` migration guarded by a `PRAGMA table_info` check so existing databases upgrade cleanly.
- In `broker/mock_broker.py`, keep the existing price-threshold stop as the authoritative soft stop (it already exits on `price <= stop_loss`). No live broker stop exists in mock; the fields exist only for state parity, so simply carry them through unchanged.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mock_broker.py tests/test_store.py tests/test_restart_integration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add broker/mock_broker.py state/store.py tests/test_mock_broker.py tests/test_store.py
git commit -m "feat(state): persist stop-order legs; keep soft-stop fallback with mock parity"
```

## Phase 3 — Event-driven dashboard surface

The dashboard should make the *event stream* first-class: what alert arrived, whether it was honored/rejected/replayed, and the live legs (entry / TP / stop) of each position. This reframes "signals" from something the app computes to something the app receives.

### Task 7: First-class event log + `/api/events`

**Files:**
- Modify: `state/store.py` (event log table + writer + reader)
- Modify: `web/app.py` (record each alert outcome; add `GET /api/events`)
- Test: `tests/test_store.py`, `tests/test_web_app.py`

**Interfaces:**
- Produces:
  - `StateStore.record_event(source: str, symbol: str, action: str, quantity, tp, sl, status: str, message: str, event_id: str | None) -> None`
  - `StateStore.recent_events(limit: int = 50) -> list[dict]`
  - `GET /api/events` -> `{"events": [...], "mode": ..., "real_money": ...}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py (add)
def test_event_log_records_and_reads_back(tmp_path):
    store = StateStore(str(tmp_path / "s.sqlite"))
    store.record_event("webhook", "AAPL", "open", 2, 110.0, 95.0, "OK", "opened", "e1")
    events = store.recent_events()
    assert events[0]["symbol"] == "AAPL" and events[0]["status"] == "OK"
    assert events[0]["quantity"] == 2

# tests/test_web_app.py (add)
def test_api_events_returns_recorded_alerts(client_factory):
    client, store = client_factory(webhook=True, secret="x" * 32)
    client.post("/webhook", json={
        "event_id": "e1", "timestamp": _fresh_iso(), "action": "open",
        "side": "buy", "symbol": "AAPL", "quantity": 1, "key": "x" * 32})
    r = client.get("/api/events")
    assert r.status_code == 200
    assert any(e["symbol"] == "AAPL" for e in r.get_json()["events"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_store.py -k event tests/test_web_app.py -k events -v`
Expected: FAIL — `record_event`/`recent_events`/`/api/events` do not exist.

- [ ] **Step 3: Implement the event log**

- In `state/store.py`: add a `CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, symbol TEXT, action TEXT, quantity INTEGER, tp REAL, sl REAL, status TEXT, message TEXT, event_id TEXT)`. Implement `record_event(...)` (INSERT with `datetime.now(timezone.utc).isoformat()`), and `recent_events(limit=50)` (SELECT ordered by `id DESC`, returned as dicts with a `time` field formatted `%H:%M:%S`).
- In `web/app.py` `/webhook`: after the parse and after `runtime.execute(...)` returns, call `store.record_event("webhook", alert.symbol, alert.action, alert.quantity, take_profit, stop_loss, result["status"], result["message"], alert.event_id)`. Also record a rejection event in the `AlertError`, `REPLAY`, and `EXPIRED` branches (status = the failure code) so the stream shows blocked alerts too.
- Add the endpoint:

```python
    @app.get("/api/events")
    def api_events():
        return jsonify({
            "events": store.recent_events(),
            "mode": cfg.mode_label,
            "real_money": cfg.is_real_money,
        })
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_store.py tests/test_web_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add state/store.py web/app.py tests/test_store.py tests/test_web_app.py
git commit -m "feat(events): first-class alert event log + /api/events endpoint"
```

### Task 8: Dashboard event stream + OCO legs (UI — routes through frontend-design)

**Files:**
- Modify: `web/templates/index.html`, `web/static/app.js`, `web/static/styles.css`

**Interfaces:**
- Consumes: `GET /api/events`, and the extended `/api/state` position fields (`stop_loss_order_id`, leg statuses).

> **PROCESS GATE (from AGENTS.md):** This task MUST enter through the `frontend-design` skill: output the two-line Design Read + `Use`/`Skip` pack ledger, then produce a **side-by-side visual comparison** (current dashboard vs event-first dashboard) using the brainstorming visual companion before writing any markup/CSS. Keep the existing "Calm Risk Console" system and Cloudflare-independent vanilla tokens. Do NOT introduce a new component library.

- [ ] **Step 1: Design gate**

Invoke `frontend-design`; produce the comparison mockup for an "Incoming alerts" panel (time, source, symbol, action, qty, tp/sl, status pill: `OK`/`REJECTED`/`REPLAY`/`EXPIRED`) and a per-position "legs" row (Entry / Take-profit / Stop, each showing state). Self-review against hierarchy, color, responsive behaviour, reduced-motion, and the paper-only framing. Continue with the strongest option.

- [ ] **Step 2: Add the events panel to the page**

Add a section to `index.html` and, in `app.js`, add a poller that `fetch`es `/api/events` on the existing refresh cadence and renders rows. Reuse the existing stale-poll versioning guard so a slow response can't overwrite newer data. Status pills reuse existing state classes.

- [ ] **Step 3: Render position legs**

Extend the position card renderer in `app.js` to show three leg chips (Entry filled/pending, TP order live/filled/none, Stop order live/filled/none/soft) derived from the position fields. Add minimal CSS to `styles.css` following existing tokens.

- [ ] **Step 4: Verify UI**

Run: `node --check web/static/app.js`
Then load `python cli.py web` (mock mode), POST a sample alert with `curl`, and confirm the event appears and the legs render. Capture a screenshot at desktop + mobile widths for the visual record.

- [ ] **Step 5: Commit**

```bash
git add web/templates/index.html web/static/app.js web/static/styles.css
git commit -m "feat(ui): event stream panel + per-position OCO legs (Calm Risk Console)"
```

## Phase 4 — Security hardening (defence-in-depth)

Curteis' two layers are "spoof a TradingView source IP **and** know the secret." We add an app-layer equivalent so the app is safe even before the Cloudflare edge (Phase 5) is in place: config knobs, an optional HMAC signature, a TradingView IP allow-list, and a per-path rate limit. All default to the safe/closed setting.

### Task 9: Config knobs for the bridge

**Files:**
- Modify: `config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces on `Config`: `max_alert_quantity: int` (default 100), `use_broker_stop_order: bool` (default True), `webhook_signature_required: bool` (default False), `webhook_ip_allowlist: list[str]` (default the TradingView IPs), `webhook_rate_per_min: int` (default 5).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py (add)
def test_bridge_defaults(monkeypatch):
    for k in ("MAX_ALERT_QUANTITY", "USE_BROKER_STOP_ORDER", "WEBHOOK_SIGNATURE_REQUIRED",
              "WEBHOOK_IP_ALLOWLIST", "WEBHOOK_RATE_PER_MIN"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config()
    assert cfg.max_alert_quantity == 100
    assert cfg.use_broker_stop_order is True
    assert cfg.webhook_signature_required is False
    assert cfg.webhook_rate_per_min == 5
    assert "52.89.214.238" in cfg.webhook_ip_allowlist
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py::test_bridge_defaults -v`
Expected: FAIL — attributes do not exist.

- [ ] **Step 3: Add the fields to `config.py`**

```python
    max_alert_quantity: int = field(default_factory=lambda: int(os.getenv("MAX_ALERT_QUANTITY", "100")))
    use_broker_stop_order: bool = field(default_factory=lambda: _env_bool("USE_BROKER_STOP_ORDER", True))
    webhook_signature_required: bool = field(default_factory=lambda: _env_bool("WEBHOOK_SIGNATURE_REQUIRED", False))
    webhook_ip_allowlist: List[str] = field(
        default_factory=lambda: _split_plain(
            os.getenv("WEBHOOK_IP_ALLOWLIST",
                      "52.89.214.238,34.212.75.30,54.218.53.128,52.32.178.7")
        )
    )
    webhook_rate_per_min: int = field(default_factory=lambda: int(os.getenv("WEBHOOK_RATE_PER_MIN", "5")))
```

Add a `_split_plain` helper (like `_split_csv` but without `.upper()`, since IPs are case-neutral and must not be mangled). Add matching lines to `.env.example` with brief comments. Extend `Config.validate()` to require `max_alert_quantity > 0` and `webhook_rate_per_min > 0`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py .env.example tests/test_config.py
git commit -m "feat(config): bridge safety knobs (alert cap, stop-order toggle, signature, ip allow-list, rate limit)"
```

### Task 10: TradingView IP allow-list + optional HMAC signature on `/webhook`

**Files:**
- Modify: `web/app.py` (guards at the top of `webhook()`)
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `cfg.webhook_ip_allowlist`, `cfg.webhook_signature_required`, `cfg.webhook_secret`.
- Produces: requests from a non-allow-listed IP get `403 IP_FORBIDDEN`; when `webhook_signature_required`, a missing/invalid `X-Signature` header gets `401 BAD_SIGNATURE`. The shared-key check remains.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_app.py (add)
def test_webhook_rejects_unlisted_ip(client_factory):
    client, _ = client_factory(webhook=True, secret="x" * 32, ip_allowlist=["203.0.113.9"])
    r = client.post("/webhook", json={"key": "x" * 32}, environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    assert r.status_code == 403 and r.get_json()["status"] == "IP_FORBIDDEN"


def test_webhook_requires_valid_hmac_when_enabled(client_factory):
    import hashlib, hmac as _h, json
    secret = "x" * 32
    client, _ = client_factory(webhook=True, secret=secret, signature_required=True,
                               ip_allowlist=["10.0.0.1"])
    body = {"event_id": "e1", "timestamp": _fresh_iso(), "action": "open",
            "side": "buy", "symbol": "AAPL", "key": secret}
    raw = json.dumps(body).encode()
    sig = _h.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    ok = client.post("/webhook", data=raw, content_type="application/json",
                     headers={"X-Signature": sig}, environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    assert ok.status_code == 200
    bad = client.post("/webhook", data=raw, content_type="application/json",
                      headers={"X-Signature": "deadbeef"}, environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    assert bad.status_code == 401 and bad.get_json()["status"] == "BAD_SIGNATURE"
```

(Extend `client_factory` to accept `ip_allowlist` and `signature_required`.)

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_web_app.py -k "ip or hmac" -v`
Expected: FAIL — guards not implemented.

- [ ] **Step 3: Add the guards at the very top of `webhook()`**

Immediately after the `webhook_enabled` / misconfigured-secret checks, before parsing:

```python
        remote = (request.headers.get("X-Forwarded-For", request.remote_addr or "")
                  .split(",")[0].strip())
        if cfg.webhook_ip_allowlist and remote not in cfg.webhook_ip_allowlist:
            return jsonify({"status": "IP_FORBIDDEN", "message": "source IP is not allow-listed"}), 403

        raw = request.get_data(cache=True)  # cache so get_json() still works below
        if cfg.webhook_signature_required:
            supplied = request.headers.get("X-Signature", "")
            expected = hmac.new(cfg.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                return jsonify({"status": "BAD_SIGNATURE", "message": "missing or invalid signature"}), 401
```

Add `import hashlib` at the top of `web/app.py`.

> **Trust note:** `X-Forwarded-For` is only trustworthy behind a proxy you control (Cloudflare -> your origin, Phase 5). Document that when the app is exposed directly (no proxy), operators should set `WEBHOOK_IP_ALLOWLIST` to the direct peers or rely on `request.remote_addr` by leaving XFF stripping to the deployment. The default posture is "behind Cloudflare."

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_web_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_web_app.py
git commit -m "feat(webhook): TradingView IP allow-list + optional HMAC signature (defence-in-depth)"
```

### Task 11: Per-path rate limit on `/webhook`

**Files:**
- Create: `web/ratelimit.py` (tiny in-process token bucket)
- Modify: `web/app.py`
- Test: `tests/test_ratelimit.py`, `tests/test_web_app.py`

**Interfaces:**
- Produces: `class RateLimiter(per_min: int, now: Callable[[], float] = time.monotonic)` with `def allow(key: str) -> bool`. `/webhook` returns `429 RATE_LIMITED` when exceeded.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ratelimit.py
from web.ratelimit import RateLimiter

def test_allows_up_to_limit_then_blocks():
    t = {"v": 0.0}
    rl = RateLimiter(per_min=2, now=lambda: t["v"])
    assert rl.allow("ip") and rl.allow("ip")
    assert not rl.allow("ip")
    t["v"] = 61.0
    assert rl.allow("ip")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ratelimit.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the limiter and wire it**

```python
# web/ratelimit.py
from __future__ import annotations
import time
from collections import deque
from threading import Lock
from typing import Callable, Deque, Dict


class RateLimiter:
    def __init__(self, per_min: int, now: Callable[[], float] = time.monotonic) -> None:
        self.per_min = max(1, per_min)
        self._now = now
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = self._now()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= 60.0:
                hits.popleft()
            if len(hits) >= self.per_min:
                return False
            hits.append(now)
            return True
```

In `web/app.py`, build one `RateLimiter(cfg.webhook_rate_per_min)` in `create_app` and, at the top of `webhook()` (after the IP check), add:

```python
        if not app.extensions["webhook_rate_limiter"].allow(remote or "anon"):
            return jsonify({"status": "RATE_LIMITED", "message": "too many requests"}), 429
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ratelimit.py tests/test_web_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/ratelimit.py web/app.py tests/test_ratelimit.py tests/test_web_app.py
git commit -m "feat(webhook): in-process per-IP rate limit (5/min default)"
```

## Phase 5 — Deployment blueprint (docs only)

This phase writes the runbook that mirrors the article's infrastructure. No application code changes; nothing here runs OpenD or touches an account during implementation.

### Task 12: `docs/deploy/README.md` runbook

**Files:**
- Create: `docs/deploy/README.md`
- Modify: `.env.example` (add a commented "Deployment" block)

**Interfaces:** none (documentation).

- [ ] **Step 1: Write the runbook**

Cover, as prose + copyable snippets (no secrets, placeholders for hosts/domains):

1. **Topology:** TradingView -> Cloudflare (proxied DNS, WAF, rate limit) -> origin host -> Caddy (HTTPS) -> Flask bridge (`127.0.0.1:5000`) -> OpenD (`127.0.0.1:11111`) -> moomoo. Include the sequence diagram in text.
2. **Host choice:** scheduled EC2 `t3.micro` (compute billed only during market hours) vs Lightsail `$7` (flat, simplest). State the tradeoff exactly as the article does; recommend Lightsail for simplicity, scheduled EC2 for cost.
3. **Persistence:** a persistent disk for OpenD's `Device.dat` so the session is not re-verified nightly. Note the exact path used by OpenD on the target OS.
4. **Scheduling:** EventBridge Scheduler (or cron) to start the instance ~15 min before the US open and stop it after the close, Mon-Fri; systemd units start OpenD -> bridge -> Caddy on boot.
5. **HTTPS:** Caddy auto-TLS; keep origin port 80 open for the ACME/Let's-Encrypt check even behind Cloudflare (avoids the 525 error the article calls out).
6. **Cloudflare:** WAF custom rule allow-listing TradingView's four published webhook IPs on `/webhook` (verify the current list in TradingView docs), a 5 req/min rate-limit rule on that path, and the correct SSL/TLS encryption mode (Full or Full (strict)) so it matches Caddy's cert.
7. **Secrets:** `WEBHOOK_SECRET` (>=32 random chars) via the host's secret mechanism/`.env` with `600` perms; never in git. If `WEBHOOK_SIGNATURE_REQUIRED=true`, configure the TradingView alert to send the `X-Signature` header (or document that TradingView cannot sign, so signature mode is for non-TradingView senders and the IP allow-list + secret are the TradingView layers).
8. **Runbook checks:** how to confirm OpenD is logged in, the bridge is healthy, a test SIMULATE alert flows end-to-end, and how to stop cleanly.

- [ ] **Step 2: Commit**

```bash
git add docs/deploy/README.md .env.example
git commit -m "docs(deploy): OpenD + bridge + market-hours schedule + HTTPS + Cloudflare runbook"
```

## Phase 6 — REAL enablement (separate, human-gated)

### Task 13: REAL-mode design note (spec-only; do NOT implement here)

**Files:**
- Create: `docs/superpowers/specs/2026-07-12-real-mode-enablement.md`

**Interfaces:** none (specification).

REAL auto-execution is intentionally out of scope for this plan. The webhook stays blocked in REAL mode (`web/app.py:280-284`). This task only records what a future, explicitly-approved plan must satisfy before REAL is ever enabled:

- [ ] **Step 1: Write the spec note** covering: an explicit per-alert `confirm:true` **and** an env opt-in (e.g. `ALLOW_REAL_WEBHOOK=true`) both required; startup reconciliation of local state against the broker's real order/position truth; a max-notional / max-daily-loss circuit breaker; market-hours + quote-freshness guards; a dry-run replay of recorded SIMULATE events; and a mandatory human review checkpoint. No code. Note that enabling REAL requires the owner's credentials and is a destructive/irreversible-risk action per the operating rules.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-07-12-real-mode-enablement.md
git commit -m "docs(spec): conditions required before any REAL-mode enablement (no code)"
```

## Phase 7 — Verification & docs

### Task 14: Full gate + README/PROGRESS updates

**Files:**
- Modify: `README.md`, `PROGRESS_REPORT.md`

- [ ] **Step 1: Run the full verification gate**

```bash
pytest -q
python -m compileall -q broker data signals state strategy trader web
node --check web/static/app.js
pip check
git diff --check
```

Expected: all green; test count increased from 152 by the new tests (alerts, executor, moomoo OCO, store, config, ratelimit, web).

- [ ] **Step 2: Update `README.md`** — reframe the intro and "How it works" around the event-driven model: TradingView Pine (brain) -> `/webhook` (dumb bridge, honors alert tp/sl/qty) -> broker manual OCO (entry + limit TP + stop SL). Document the alert schema, the new `.env` knobs, the security layers, and a `curl` example. Keep the paper-first/SIMULATE framing and the REAL-out-of-scope note.

- [ ] **Step 3: Update `PROGRESS_REPORT.md`** — add a dated "Completed" bullet describing the event-driven pivot, the files/areas touched, branch + commit SHAs, and that the full gate passed. Update any status table rows.

- [ ] **Step 4: Commit**

```bash
git add README.md PROGRESS_REPORT.md
git commit -m "docs: document the event-driven TradingView->moomoo bridge model"
```

- [ ] **Step 5 (after push):** log the shipped change in `PROGRESS_REPORT.md` per the working agreement and, if this becomes a durable learning, add a wiki source entry.

---

## Self-Review (author checklist, completed)

- **Spec coverage:** Curteis' six load-bearing ideas map to tasks — dumb-bridge/alert-authoritative (Tasks 1-3), one `/webhook` endpoint (Task 3), OpenD boundary (existing, unchanged), no-native-OCO 3-order trio (Tasks 4-6), defence-in-depth (Tasks 9-11), market-hours/persistent/HTTPS deployment (Task 12). Event surfacing (Tasks 7-8) satisfies the user's "give signal based on events" ask.
- **Placeholder scan:** no `TBD`/`TODO`/"add validation" left; pivotal logic (parser, quantity override, stop-order, OCO cancel, HMAC, IP allow-list, rate limiter) is shown as real code. UI markup is intentionally deferred to the `frontend-design` gate (Task 8) rather than pre-written, and that dependency is called out explicitly.
- **Type consistency:** `ParsedAlert` fields, `Signal.quantity`, `Position.stop_loss_order_id`/`stop_loss_order_quantity`, `RateLimiter.allow`, and the new config attributes are used with the same names throughout. `_split_plain` (IP-safe) is distinguished from the existing `_split_csv` (upper-casing).
- **Scope:** one cohesive subsystem (the event bridge). REAL enablement (Phase 6) and edge deployment (Phase 5) are isolated as docs/spec so the code phases (1-4, 7) produce working, SIMULATE/mock-testable software on their own.
- **Safety:** SIMULATE/mock-first preserved; webhook stays blocked in REAL; all broker behaviour is proven offline via `MockBroker` + fake SDK; the SDK stop-order contract is verified by inspection (Task 4 Step 1) before wiring, never by running OpenD.


