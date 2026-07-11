# Credential-Free Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete every locally verifiable part of the paper-trading app so only an external Moomoo `SIMULATE` smoke test remains.

**Architecture:** Add a stdlib SQLite store and a `TradingRuntime` that serializes mutations, persists state, and exposes deterministic monitor ticks. Keep the current broker interface, add an injectable Moomoo SDK seam, and make Flask state reads side-effect-free.

**Tech Stack:** Python 3.9+, Flask 3, pandas 2, stdlib `sqlite3`/`threading`, pytest 8.

## Global Constraints

- Default to `BROKER=mock`, `TRD_ENV=SIMULATE`, and loopback web binding.
- No test may require credentials, OpenD, Yahoo, TradingView, or public network access.
- REAL-money webhook execution remains prohibited.
- Store timestamps as UTC ISO-8601 strings and use SQLite WAL plus a busy timeout.
- Do not commit or push; the owner did not request version-control writes.

## File Map

- Create `state/store.py`: SQLite schema, position/signal/order/activity/webhook persistence.
- Create `trader/runtime.py`: serialized execution, monitor ticks, lifecycle, persistence.
- Create `tests/test_store.py`: schema, restart, uniqueness, and replay tests.
- Create `tests/test_runtime.py`: monitoring, restart, idempotency, and lifecycle tests.
- Create `tests/test_price_feed.py`: offline yfinance response contracts.
- Modify `models.py`: stable position and external order identifiers.
- Modify `config.py`: strict validation and runtime settings.
- Modify `broker/mock_broker.py`: restore persisted positions and prevent duplicate opens.
- Modify `broker/moomoo_broker.py`: injected SDK, checked calls, cancellation, shutdown.
- Modify `web/app.py`: delegate mutations to runtime and harden webhooks.
- Modify `cli.py`: compose/start/stop runtime.
- Modify `.env.example` and `README.md`: accurate setup, safety, and verification.

---

### Task 1: Strict Configuration

**Files:**
- Create: `tests/test_config.py`
- Modify: `config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `Config.validate() -> None`, `state_db_path: str`, `soft_stop_poll_seconds: float`, `webhook_enabled: bool`, `webhook_max_age_seconds: int`.

- [ ] **Step 1: Write failing tests**

```python
def test_invalid_broker_fails_closed():
    cfg = Config()
    cfg.broker = "typo"
    with pytest.raises(ValueError, match="BROKER"):
        cfg.validate()

def test_invalid_trading_environment_fails_closed():
    cfg = Config()
    cfg.trd_env = "REL"
    with pytest.raises(ValueError, match="TRD_ENV"):
        cfg.validate()

def test_webhook_disabled_by_default():
    assert Config().webhook_enabled is False
```

- [ ] **Step 2: Run the red test**

Run: `.venv/bin/pytest tests/test_config.py -q`

Expected: FAIL because the new settings and `validate()` do not exist.

- [ ] **Step 3: Implement exact validation**

```python
def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

def validate(self) -> None:
    if self.broker not in {"mock", "moomoo"}:
        raise ValueError("BROKER must be 'mock' or 'moomoo'")
    if self.trd_env not in {"SIMULATE", "REAL"}:
        raise ValueError("TRD_ENV must be 'SIMULATE' or 'REAL'")
    if self.quantity <= 0 or self.soft_stop_poll_seconds <= 0:
        raise ValueError("QUANTITY and SOFT_STOP_POLL_SECONDS must be positive")
```

Add environment-backed fields with defaults `state/trading.sqlite`, `4.0`, `false`, and `300`.

- [ ] **Step 4: Run the focused and baseline tests**

Run: `.venv/bin/pytest tests/test_config.py tests/test_web_app.py -q`

Expected: PASS.

### Task 2: SQLite Store

**Files:**
- Create: `state/store.py`
- Create: `tests/test_store.py`
- Modify: `models.py`

**Interfaces:**
- Produces: `StateStore(path)`, `save_signal(signal)`, `save_position(position)`, `load_positions(open_only=False)`, `begin_order(request_id, signal, quantity, source)`, `finish_order(request_id, status, message, position=None)`, `add_activity(kind, symbol, message)`, `recent_activity(limit=20)`, and `claim_webhook_event(event_id, occurred_at) -> bool`.
- Produces: `Position.position_id`, `entry_order_id`, `take_profit_order_id`, and `exit_order_id`, all defaulted so current constructors remain valid.

- [ ] **Step 1: Write store round-trip and restart tests**

```python
def test_position_survives_store_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    position = Position("AAPL", 1, 100.0, 103.0, 98.0)
    StateStore(path).save_position(position)
    loaded = StateStore(path).load_positions(open_only=True)
    assert loaded == [position]

def test_only_one_open_position_per_symbol(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_position(Position("AAPL", 1, 100.0))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_position(Position("AAPL", 1, 101.0))

def test_webhook_event_is_claimed_once(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    assert store.claim_webhook_event("evt-1", "2026-07-11T00:00:00+00:00")
    assert not store.claim_webhook_event("evt-1", "2026-07-11T00:00:00+00:00")
```

- [ ] **Step 2: Run the red test**

Run: `.venv/bin/pytest tests/test_store.py -q`

Expected: FAIL because `state.store` does not exist.

- [ ] **Step 3: Implement schema and mappings**

Create schema version 1 with `signals`, `positions`, `orders`, `activity`, and
`webhook_events`; enable `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, and foreign
keys for every connection. Use JSON-free typed columns and `INSERT ... ON CONFLICT`
for mutable snapshots. Create:

```sql
CREATE UNIQUE INDEX one_open_position_per_symbol
ON positions(symbol) WHERE status != 'CLOSED';
```

Use `dataclasses.asdict` only after converting enums and datetimes to strings;
reconstruct `Position` with timezone-aware `datetime.fromisoformat`.

- [ ] **Step 4: Run store tests twice**

Run: `.venv/bin/pytest tests/test_store.py -q && .venv/bin/pytest tests/test_store.py -q`

Expected: both runs PASS, proving idempotent schema creation.

### Task 3: Runtime and Independent Monitor

**Files:**
- Create: `trader/runtime.py`
- Create: `tests/test_runtime.py`
- Modify: `broker/mock_broker.py`

**Interfaces:**
- Consumes: `StateStore` from Task 2 and existing `Executor`, `Broker`, `PriceFeed`.
- Produces: `TradingRuntime.execute(signal, source="dashboard", request_id=None)`, `close(symbol, price)`, `poll_once()`, `state()`, `start()`, and `stop()`.
- Produces: `MockBroker(initial_positions=None)`.

- [ ] **Step 1: Write monitor and restart tests**

```python
def test_poll_once_closes_stop_without_http(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    broker = MockBroker()
    feed = ScriptedFeed({"AAPL": 97.0})
    runtime = TradingRuntime(broker, feed, Executor(broker), store)
    runtime.execute(Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0))
    assert runtime.poll_once()[0].close_reason == "STOP_LOSS"
    assert store.load_positions(open_only=True) == []

def test_restored_position_is_monitored_after_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    first_store = StateStore(path)
    first = MockBroker()
    TradingRuntime(first, ScriptedFeed({"AAPL": 100.0}), Executor(first), first_store).execute(
        Signal("AAPL", Action.BUY, 100.0, 103.0, 98.0)
    )
    second_store = StateStore(path)
    second = MockBroker(second_store.load_positions(open_only=True))
    runtime = TradingRuntime(second, ScriptedFeed({"AAPL": 97.0}), Executor(second), second_store)
    runtime.poll_once()
    assert second_store.load_positions(open_only=True) == []
```

- [ ] **Step 2: Run the red test**

Run: `.venv/bin/pytest tests/test_runtime.py -q`

Expected: FAIL because `TradingRuntime` and restoration do not exist.

- [ ] **Step 3: Implement serialized runtime**

Use `threading.RLock` for `execute`, `close`, and `poll_once`. Before BUY, reject
another non-closed position for the symbol. Persist a pending order before calling
the executor, then persist the result and activity. `poll_once()` catches feed or
broker errors per symbol and records an `error` activity without terminating the
loop.

`start()` launches one daemon thread that repeatedly calls `poll_once()` and waits on
`threading.Event`; `stop()` sets the event, joins it, and calls `broker.disconnect()`
when available. Repeated start/stop calls are idempotent.

- [ ] **Step 4: Verify focused behavior**

Run: `.venv/bin/pytest tests/test_runtime.py tests/test_mock_broker.py tests/test_executor.py -q`

Expected: PASS.

### Task 4: Flask and CLI Composition

**Files:**
- Modify: `web/app.py`
- Modify: `cli.py`
- Modify: `tests/test_web_app.py`
- Create: `tests/test_restart_integration.py`

**Interfaces:**
- Consumes: `TradingRuntime` and `StateStore` from Tasks 2-3.
- Produces: `create_app(..., runtime=None, store=None)` and
  `app.extensions["trading_runtime"]`.

- [ ] **Step 1: Write route-side-effect and restart integration tests**

```python
def test_state_route_does_not_trigger_broker_update(runtime_app, broker):
    before = broker.update_count
    runtime_app.test_client().get("/api/state")
    assert broker.update_count == before

def test_trade_persists_then_monitor_closes_after_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    app = build_test_app(path, price=100.0)
    assert app.test_client().post("/api/trade", json={"symbol": "UP"}).get_json()["status"] == "OPENED"
    restarted = build_test_app(path, price=97.0, restore=True)
    restarted.extensions["trading_runtime"].poll_once()
    state = restarted.test_client().get("/api/state").get_json()
    assert state["positions"] == []
    assert state["activity"][0]["type"] == "auto"
```

- [ ] **Step 2: Run the red tests**

Run: `.venv/bin/pytest tests/test_web_app.py tests/test_restart_integration.py -q`

Expected: FAIL because Flask still mutates broker state and does not restore SQLite.

- [ ] **Step 3: Delegate routes to the runtime**

Construct an in-memory store only for explicitly injected test broker/feed pairs;
normal `create_app()` uses `cfg.state_db_path`. Route `/api/trade` through
`runtime.execute`, `/api/close` through `runtime.close`, and `/api/state` through a
side-effect-free runtime/store read. Convert known `ValueError`/`RuntimeError` failures
to JSON `400`/`503` responses.

In `cmd_web`, validate config, restore persisted mock positions before broker
construction, start the runtime before `app.run`, and stop it in `finally`.

- [ ] **Step 4: Run web and restart tests**

Run: `.venv/bin/pytest tests/test_web_app.py tests/test_restart_integration.py -q`

Expected: PASS.

### Task 5: Price Feed Contract

**Files:**
- Modify: `data/price_feed.py`
- Create: `tests/test_price_feed.py`

**Interfaces:**
- Produces: `YFinanceFeed(downloader=None)`, where the downloader matches
  `yfinance.download(symbol, period, interval, progress, auto_adjust)`.

- [ ] **Step 1: Write response-shape tests**

```python
def test_multiindex_columns_are_flattened():
    columns = pd.MultiIndex.from_tuples([("Close", "AAPL")])
    feed = YFinanceFeed(lambda *args, **kwargs: pd.DataFrame([[101.0]], columns=columns))
    assert feed.last_price("AAPL") == 101.0

@pytest.mark.parametrize("frame", [None, pd.DataFrame(), pd.DataFrame({"Open": [1.0]}), pd.DataFrame({"Close": [float("nan")]})])
def test_invalid_download_is_rejected(frame):
    with pytest.raises(ValueError):
        YFinanceFeed(lambda *args, **kwargs: frame).last_price("AAPL")
```

- [ ] **Step 2: Run the red tests**

Run: `.venv/bin/pytest tests/test_price_feed.py -q`

Expected: FAIL because downloader injection and complete validation do not exist.

- [ ] **Step 3: Implement downloader injection and validation**

Resolve the real downloader lazily only when none is injected. Validate non-empty
data, a `Close` column after flattening, and a finite numeric last close with
`math.isfinite`.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_price_feed.py tests/test_signal_engine.py -q`

Expected: PASS.

### Task 6: Moomoo Offline Contract and Safety

**Files:**
- Modify: `broker/moomoo_broker.py`
- Rewrite: `tests/test_moomoo_broker.py`

**Interfaces:**
- Produces: `MoomooBroker(..., sdk=None)`, `connect()`, and `disconnect()`.
- `sdk` exposes `RET_OK`, trading enums, `OpenSecTradeContext`, and
  `OpenQuoteContext`; test fakes record every call.

- [ ] **Step 1: Build a fake SDK and write failure-first tests**

```python
def test_stop_cancels_tp_before_market_sell(fake_sdk):
    broker = connected_broker(fake_sdk)
    position = broker.place_bracket(bracket())
    broker.update_price("AAPL", 97.0)
    assert fake_sdk.trade.calls[-2][0] == "modify_order"
    assert fake_sdk.trade.calls[-1][0] == "place_order"
    assert position.status == "CLOSED"

def test_failed_exit_keeps_position_open(fake_sdk):
    broker = connected_broker(fake_sdk)
    position = broker.place_bracket(bracket())
    fake_sdk.trade.fail_next_market_sell = True
    with pytest.raises(RuntimeError, match="exit order failed"):
        broker.close("AAPL", 99.0)
    assert position.status == "OPEN"

def test_failed_cancel_does_not_sell(fake_sdk):
    broker = connected_broker(fake_sdk)
    broker.place_bracket(bracket())
    fake_sdk.trade.fail_cancel = True
    with pytest.raises(RuntimeError, match="cancel"):
        broker.update_price("AAPL", 97.0)
    assert not fake_sdk.trade.market_sell_calls
```

Also cover constructor arguments, exact `SIMULATE` mapping, entry rejection,
positive fill requirement, TP rejection, concrete order-ID extraction, confirmed TP
fill, context closure, and invalid environment rejection.

- [ ] **Step 2: Run the red contract suite**

Run: `.venv/bin/pytest tests/test_moomoo_broker.py -q`

Expected: FAIL on unchecked exit, absent SDK injection, and missing remote cancel.

- [ ] **Step 3: Implement the minimal checked state machine**

Store only string order IDs on `Position`. Extract `order_id`, `cost_price` or
`dealt_avg_price`, and `order_status` from dict-like or DataFrame responses. Check
every return code. On stop/manual close: cancel TP, then submit market sell, then mark
closed. If cancellation fails, query TP status; when already filled, mark
`TAKE_PROFIT`, otherwise raise without selling. At the TP threshold, query order
status and mark closed only when the remote order reports `FILLED_ALL`.

`disconnect()` calls `close()` on both contexts and clears local references.

- [ ] **Step 4: Run broker and runtime suites**

Run: `.venv/bin/pytest tests/test_moomoo_broker.py tests/test_runtime.py -q`

Expected: PASS without importing the real SDK.

### Task 7: Webhook Hardening

**Files:**
- Modify: `web/app.py`
- Modify: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `StateStore.claim_webhook_event` and config webhook settings.
- Request schema: `event_id`, `timestamp`, `action`, `symbol`, and `key`; caller
  prices are ignored in favor of `feed.last_price`.

- [ ] **Step 1: Write hardening tests**

```python
def test_webhook_is_disabled_by_default():
    response = _app()[0].test_client().post("/webhook", json=valid_alert())
    assert response.status_code == 404

def test_webhook_rejects_default_secret(enabled_app):
    assert enabled_app.test_client().post("/webhook", json=valid_alert(key="change-me")).status_code == 503

def test_webhook_rejects_replay(enabled_app):
    client = enabled_app.test_client()
    assert client.post("/webhook", json=valid_alert(event_id="one")).status_code == 200
    assert client.post("/webhook", json=valid_alert(event_id="one")).status_code == 409
```

Also test expired timestamps, symbols outside the watchlist, malformed action, missing
event ID, server-side price use, and REAL-mode prohibition.

- [ ] **Step 2: Run the red tests**

Run: `.venv/bin/pytest tests/test_web_app.py -q`

Expected: FAIL because webhook enablement, expiry, replay, and allowlisting are absent.

- [ ] **Step 3: Implement strict webhook admission**

Return `404` when disabled. Return `503` for the default/blank secret, compare secrets
with `hmac.compare_digest`, parse timezone-aware ISO timestamps, enforce the configured
maximum age, allow only watchlist symbols, and claim the event ID before execution.
Return `409` for replay and preserve the existing REAL-mode `403`.

- [ ] **Step 4: Run all web tests**

Run: `.venv/bin/pytest tests/test_web_app.py -q`

Expected: PASS.

### Task 8: Documentation and Credential-Free Release Gate

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docs/superpowers/specs/2026-06-24-trading-signal-and-helper-design.md`

**Interfaces:**
- Produces: accurate phase/readiness descriptions and exact operator commands.

- [ ] **Step 1: Update documentation**

Document persistent state, monitor lifecycle, webhook opt-in schema, strict config,
database reset/backup, degraded OpenD behavior, and the remaining `SIMULATE` smoke
test. Remove stale “scaffold complete” and fixed test-count wording.

- [ ] **Step 2: Run complete offline verification**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q broker data signals state strategy trader web
.venv/bin/python cli.py demo
git diff --check
```

Expected: all tests pass, compile exits zero, demo reports an opened then
take-profit-closed fake position, and diff check emits no output.

- [ ] **Step 3: Review change locality and safety**

Confirm no `.env`, database, credential, `Device.dat`, or generated cache file is
tracked. Confirm remaining `TODO` references are nonsafety future deployment notes,
not unchecked broker behavior.
