# TradingSignalandHelper Credential-Free Completion Design

**Date:** 2026-07-11
**Status:** Approved under the owner's autonomous-continuity instruction
**Scope:** Complete all work that does not require a Moomoo/OpenD login

## Goal

Turn the working mock-trading MVP into a restart-safe, production-shaped local
paper-trading application. The app must remain useful with no credentials and must
fail closed around live trading. The only deferred gate is a short Moomoo
`SIMULATE` smoke test against the owner's account.

## Completion Contract

Credential-free completion means:

1. Signals, positions, orders, and activity survive process restarts in SQLite.
2. Soft take-profit and stop-loss checks run independently of browser polling.
3. A position-changing operation is serialized and one open position per symbol is
   enforced.
4. Invalid broker or trading-environment configuration fails closed.
5. Every Moomoo SDK operation is checked and contract-tested through an injected
   fake SDK; no safety-critical TODO remains.
6. The yfinance adapter is contract-tested without network access.
7. Web routes validate input and return defined JSON errors for dependency failures.
8. Webhooks are disabled by default and reject weak secrets, replayed events,
   expired events, unknown symbols, and REAL-money mode.
9. A restart integration test proves that a persisted mock position can be closed by
   the monitor without any `/api/state` request.
10. The full suite, compile check, CLI demo, and diff checks pass offline.

## Approaches Considered

### A. Runtime + SQLite store + injectable SDK boundary (selected)

Add a small application runtime that coordinates the existing broker, executor,
feed, and a SQLite store. A background monitor calls a public, deterministic
`poll_once()` method. Moomoo calls pass through an injectable SDK seam.

This is the smallest approach that closes restart, monitoring, and broker-contract
gaps while preserving the existing interfaces.

### B. Persistent broker decorator

Wrap each broker with persistence. This keeps callers unchanged but hides lifecycle,
reconciliation, and monitoring behavior inside a wrapper. It makes failure states
and test setup harder to reason about.

### C. Event-sourced service with external workers

Use an append-only event stream and separate worker processes. This offers stronger
audit and isolation, but adds disproportionate infrastructure for a local,
single-user paper-trading assistant.

## Architecture

```text
Flask / CLI
    |
TradingRuntime <---- SoftStopMonitor thread
    |       \
Executor     SQLiteStore
    |
Broker
    |-- MockBroker
    `-- MoomooBroker -> injected SDK/OpenD boundary
```

### `state/store.py`

Use stdlib `sqlite3`, WAL mode, a busy timeout, explicit transactions, UTC ISO-8601
timestamps, and one connection per operation. Store:

- latest signal snapshots;
- position snapshots and close state;
- order attempts and external order IDs;
- append-only activity and operational errors;
- webhook event IDs for replay rejection.

A partial unique index permits only one open position per symbol.

### `trader/runtime.py`

Own application-level coordination:

- serialize trade, close, and monitor mutations with one re-entrant lock;
- persist every resulting position and activity event;
- expose side-effect-free state reads;
- expose deterministic `poll_once()` for tests;
- run/stop a monitor thread via `threading.Event`;
- isolate feed errors per symbol so one failure does not stop monitoring.

The monitor starts only from the CLI composition root, never implicitly when Flask
imports or tests construct an app.

### Brokers

`MockBroker` accepts restored positions and remains deterministic.

`MoomooBroker` accepts an injected SDK module or contexts. It must:

- reject invalid environments;
- check entry, fill lookup, TP placement, TP cancellation, and exit results;
- capture concrete order IDs rather than response containers;
- never use `0.0` as a successful unknown fill;
- never mark a position closed after a failed exit;
- cancel a resting TP before stop/manual exit and refuse to sell if cancellation is
  ambiguous;
- close its trade and quote contexts on shutdown.

Actual account reconciliation remains a narrow OpenD smoke-test gate because remote
response behavior cannot be proven without the account.

### Configuration and Web Safety

- Validate `BROKER` as `mock|moomoo` and `TRD_ENV` as `SIMULATE|REAL`.
- Add `STATE_DB_PATH`, `SOFT_STOP_POLL_SECONDS`, and `WEBHOOK_ENABLED`.
- Keep the local server bound to loopback by default.
- Disable webhooks unless explicitly enabled with a non-default secret.
- Require a unique event ID and recent timestamp; use constant-time secret checks.
- Restrict webhook symbols to the configured watchlist and use server-side prices.
- Keep webhook execution prohibited in REAL mode.

## Data Flow

1. CLI constructs the store, feed, broker, runtime, and Flask app.
2. Runtime restores mock positions from SQLite.
3. A trade request records the signal, executes once under the runtime lock, then
   persists the resulting position and event.
4. The monitor periodically loads open positions, reads one price per symbol, calls
   the broker, and persists closures/errors.
5. `/api/state` only reads current prices and persisted state; it never triggers an
   exit.
6. Shutdown signals and joins the monitor, closes broker contexts, and exits.

## Failure Behavior

- Invalid configuration: abort startup with a clear error.
- Feed failure: record an error, leave the position unchanged, continue other symbols.
- Store failure before broker submission: abort the action.
- Broker rejection: return a defined error; do not mutate local position state.
- Ambiguous TP cancellation: keep the position open and do not submit a sell.
- Exit rejection: keep the position open and record the failure.
- OpenD unavailable: dashboard can start degraded; trading returns a defined error.
- Monitor exception: catch per poll/symbol so the thread remains alive.

## Testing

Follow TDD for each slice:

- store schema, round trips, restart, uniqueness, and rollback;
- runtime persistence, independent monitor behavior, feed isolation, and shutdown;
- strict config validation;
- yfinance flat/MultiIndex/empty/missing/NaN response contracts;
- fake-Moomoo entry, fill, TP, cancel, exit, and every failure path;
- Flask validation, dependency failures, read-only state, and webhook hardening;
- offline restart integration from HTTP trade to monitor-driven closure.

## Explicitly Deferred

- Installing/logging into OpenD.
- One `SIMULATE` account/order lifecycle smoke test.
- TradingView paid-plan alert setup and public cloud exposure.
- Any REAL-money enablement.

These are external validation or optional deployment tasks, not unfinished internal
application behavior.
