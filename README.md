# TradingSignalandHelper

**A local, paper-first US-stock signal desk that helps you learn, review, and execute trades without jumping straight to real money.**

TradingSignalandHelper combines two small tools in one Python application:

1. A **signals bot** that turns price candles into `BUY`, `SELL`, or `HOLD` decisions using an EMA crossover strategy.
2. A **human-in-the-loop trade helper** whose dashboard shows the proposed order, take-profit, stop-loss, broker state, and activity before confirmation.

The application defaults to synthetic prices and fake fills. It needs no account,
credentials, or network connection for its complete mock workflow.

> [!WARNING]
> This is educational software, not financial advice or a profitable-strategy claim.
> Keep `BROKER=mock` or `TRD_ENV=SIMULATE`. Live-money behavior is not validated.

## Motivation

Many trading projects start at the most dangerous end: connect a broker, accept an
alert, and place an order. That hides the hard parts behind a successful demo:

- What happens after the process restarts?
- Is the take-profit still active?
- Did the exit fill, or was it only submitted?
- Can a retry place the same trade twice?
- What happens after a partial fill?
- Can a webhook replay an old order?
- Does the UI clearly distinguish monitored, pending, and unknown broker states?

This project starts with those questions instead. It is designed to make the trading
loop inspectable before it becomes financially consequential.

## Why Use It?

Use TradingSignalandHelper if you want to:

- **Learn trading automation safely.** The default mode works with fake money,
  synthetic prices, and no credentials.
- **Understand the full order lifecycle.** Entry, pending fills, partial quantities,
  TP cancellation, exit confirmation, and manual-reconciliation states are explicit.
- **Keep control in the intended UI flow.** The dashboard presents a review ticket
  before execution. The local mock API is not an authentication boundary and can be
  called directly by software with localhost access.
- **Study an inspectable strategy.** The EMA crossover is intentionally simple and
  replaceable; every signal includes its reason and risk levels.
- **Practice production-oriented engineering.** SQLite persistence, restart recovery,
  cross-process duplicate protection, replay-resistant webhooks, responsive UI, and
  failure-state tests are built in.
- **Move from mock to broker plumbing gradually.** The same interfaces support mock
  fills and Moomoo/OpenD paper trading without rewriting the app.

### Who It Is For

- Developers learning broker integrations and order-state machines.
- Traders who want a transparent paper-trading helper rather than a black box.
- Students experimenting with strategy code, persistence, monitoring, and webhooks.
- Anyone who wants to inspect every decision before considering live execution.

### Who Should Not Use It

- Anyone looking for guaranteed returns or a proven alpha strategy.
- Anyone wanting unattended live-money trading.
- Anyone unwilling to validate the application in paper mode first.
- Anyone expecting portfolio optimization, tax reporting, or institutional execution.

## What You Get

| Capability | What it does |
|---|---|
| EMA signals | Generates `BUY`, `SELL`, and `HOLD` with a readable reason. |
| Risk levels | Derives entry reference, take-profit, and stop-loss values. |
| Calm Risk Console | Shows mode, attention count, signals, protection state, P&L, and activity. |
| First-run guide | Teaches one real mock workflow: choose BUY, confirm, watch protection. |
| Dashboard confirmation | Uses an order ticket in the intended browser workflow; mock API callers can bypass the UI. |
| Durable state | Persists signals, orders, positions, activity, and webhook event IDs in SQLite. |
| Background monitor | Checks soft TP/SL independently of dashboard polling. |
| Broker-safe states | Tracks pending, partial, unprotected, and unknown-order conditions. |
| Duplicate protection | Serializes local mutations and claims symbols before submission. |
| Optional webhook | Rejects weak secrets, stale/replayed events, unknown symbols, and REAL mode. |
| Moomoo adapter | Contract-tested against the real `moomoo-api` `10.8.6808` package shape. |

## Quick Start: First Paper Trade

### 1. Install

```bash
git clone https://github.com/wilsonsfh/TradingSignalandHelper.git
cd TradingSignalandHelper

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Verify the local build

```bash
pytest -q
python cli.py demo
```

The demo opens one fake position and feeds prices until the take-profit closes it.

### 3. Launch the dashboard

```bash
python cli.py web
```

Open <http://127.0.0.1:5000>.

### 4. Use the in-product guide

In paper mode, the dashboard shows a dismissible three-step guide:

1. **Choose a BUY signal.** Click **Review** on an actionable row.
2. **Confirm the ticket.** Check quantity, market order, TP, and SL.
3. **Watch protection.** The position pane shows broker/monitor state before P&L or actions.

Dismissal persists across reloads. Select **How to use** to show the guide again.

### 5. Keep the process running

Soft-stop monitoring belongs to the Python process, not the browser tab. Keep
`python cli.py web` running while positions are active. Stop it with `Ctrl+C`.

The order ticket is a usability/safety check, not server authentication in mock mode.
Keep the app bound to `127.0.0.1`; any local client able to reach the API can call
mock trade routes directly. REAL mode separately requires literal `confirm: true`.

## Everyday Usage

### Offline end-to-end demo

```bash
python cli.py demo
```

### Print signals using delayed market data

```bash
python cli.py signals
```

### Run the local dashboard

```bash
python cli.py web
```

### Use yfinance in the dashboard

Set this in `.env`:

```dotenv
DATA_SOURCE=yfinance
```

Then restart `python cli.py web`.

## Modes

| `BROKER` | `TRD_ENV` | Data/order behavior | Recommended? |
|---|---|---|---|
| `mock` | `SIMULATE` | Synthetic or yfinance data; fake local fills. | **Yes — default.** |
| `moomoo` | `SIMULATE` | yfinance candles, realtime OpenD quotes, Moomoo paper orders. | Only after the smoke-test steps below. |
| `moomoo` | `REAL` | Real broker orders and real money. | **No — not validated.** |

Configuration fails closed. Unknown broker, environment, or incompatible data-source
values stop startup instead of silently falling through to live behavior.

## How It Works

```text
PriceFeed -> EMA Strategy -> Signal -> Dashboard review -> Executor -> Broker
                                  |                         |
                                  |                         +-> entry / TP / exit
                                  |
                                  +-> dashboard review and confirmation

SQLite StateStore <-> TradingRuntime <-> background soft-stop monitor
```

### Main Objects

- **Signal:** symbol, action, price, TP, SL, reason, timestamp.
- **Position:** quantity, basis, protection levels, broker IDs, and lifecycle state.
- **Activity:** order, monitor, closure, webhook, and error evidence.

### Position State Families

The UI groups detailed broker states into understandable families:

| Family | Examples | UI behavior |
|---|---|---|
| Monitored | `OPEN` | TP/SL watch active; close action available. |
| In progress | `ENTRY_PENDING`, `EXIT_PENDING`, cancellation pending | Wait for broker confirmation; duplicate action suppressed. |
| Manual attention | Unknown order IDs or unprotected state | Automation pauses or offers a controlled exit. |

## Safety Model

The project deliberately prefers a visible stop over an optimistic guess.

- **Mock-first default:** no account or credentials are needed.
- **Literal live confirmation:** REAL dashboard orders require JSON boolean `true`,
  not merely a truthy string.
- **No REAL webhooks:** unattended webhook execution is always blocked in REAL mode.
- **Confirmed closure:** an accepted exit is not considered closed until the broker
  reports the fill.
- **Partial-fill reconciliation:** entry, TP, and exit quantities are recalculated
  before follow-up actions.
- **Unknown-ID quarantine:** if a broker accepts an order without a trackable ID,
  automation stops instead of risking a duplicate sell.
- **Pre-submit symbol claim:** separate local processes cannot intentionally open the
  same symbol concurrently.
- **Read-only state endpoint:** loading `/api/state` cannot trigger a trade.
- **Failing monitor isolation:** one symbol/feed error does not terminate the monitor.
- **Safe shutdown:** broker contexts stay connected if the monitor cannot stop cleanly.

## Persistence and Recovery

The default database is `state/trading.sqlite` and is ignored by Git.

Persisted records include:

- latest signals;
- order attempts and idempotent request IDs;
- open, pending, degraded, and closed positions;
- external entry/TP/exit order IDs and quantities;
- recent activity and operational failures;
- claimed webhook event IDs;
- symbol claims used to prevent duplicate submissions.

Back up state while the application is stopped:

```bash
cp state/trading.sqlite state/trading.backup.sqlite
```

Reset mock history while the application is stopped:

```bash
rm state/trading.sqlite
```

SQLite WAL/SHM sidecars are also ignored and must not be committed.

## Configuration

Copy `.env.example` to `.env` and change only what you understand.

| Variable | Default | Purpose |
|---|---:|---|
| `BROKER` | `mock` | `mock` or `moomoo`. |
| `TRD_ENV` | `SIMULATE` | `SIMULATE` or `REAL`; used by Moomoo. |
| `DATA_SOURCE` | `demo` | `demo` or `yfinance`; Moomoo requires yfinance candles. |
| `WATCHLIST` | `AAPL,MSFT,NVDA,SPY` | Comma-separated US symbols. |
| `EMA_FAST` | `9` | Fast EMA period. |
| `EMA_SLOW` | `21` | Slow EMA period. |
| `CANDLE_PERIOD` | `6mo` | Historical window passed to the feed. |
| `CANDLE_INTERVAL` | `1d` | Candle interval. |
| `QUANTITY` | `1` | Tracked shares per dashboard BUY. |
| `TAKE_PROFIT_PCT` | `3.0` | TP percentage above entry. |
| `STOP_LOSS_PCT` | `2.0` | SL percentage below entry. |
| `STATE_DB_PATH` | `state/trading.sqlite` | SQLite file. |
| `SOFT_STOP_POLL_SECONDS` | `4.0` | Background risk-monitor interval. |
| `OPEND_HOST` | `127.0.0.1` | Local Moomoo OpenD host. |
| `OPEND_PORT` | `11111` | Local Moomoo OpenD port. |
| `WEBHOOK_ENABLED` | `false` | Enables optional mock/paper webhook. |
| `WEBHOOK_SECRET` | `change-me` | Must be replaced with at least 32 characters. |
| `WEBHOOK_MAX_AGE_SECONDS` | `300` | Replay/age window. |
| `WEB_HOST` | `127.0.0.1` | Dashboard bind host. |
| `WEB_PORT` | `5000` | Dashboard port. |

## Moomoo/OpenD Paper-Trading Gate

The optional SDK is pinned to the real package version used for contract validation:

```bash
pip install -r requirements-moomoo.txt
```

The project never stores your Moomoo password. OpenD owns account login and the app
connects to OpenD locally.

Set:

```dotenv
BROKER=moomoo
TRD_ENV=SIMULATE
DATA_SOURCE=yfinance
OPEND_HOST=127.0.0.1
OPEND_PORT=11111
```

Then:

1. Download and run OpenD.
2. Log into Moomoo inside OpenD.
3. Start `python cli.py web`.
4. Use one small paper position.
5. Verify realtime quote, entry, fill, TP, TP cancellation, soft-stop exit,
   restart recovery, and clean shutdown.
6. Return to `BROKER=mock` if any real response differs from the contract tests.

Credential-free inspection already validated the Python method signatures and actual
terminal order statuses in `moomoo-api` `10.8.6808`. No account-facing behavior is
claimed until this smoke test is completed.

## Optional TradingView Webhook

The webhook is disabled by default and is never allowed to trade in REAL mode.

```dotenv
WEBHOOK_ENABLED=true
WEBHOOK_SECRET=replace-with-at-least-32-random-characters
WEBHOOK_MAX_AGE_SECONDS=300
```

Example request:

```json
{
  "event_id": "unique-alert-id",
  "timestamp": "2026-07-12T12:00:00Z",
  "action": "buy",
  "symbol": "AAPL",
  "key": "replace-with-at-least-32-random-characters"
}
```

The endpoint rejects:

- disabled or weak/default secrets;
- stale, future-skewed, or replayed events;
- malformed/non-object JSON;
- unknown actions and symbols outside the watchlist;
- every request in REAL mode.

Caller-supplied prices and risk levels are ignored. The server reads its configured
feed and derives TP/SL itself.

Do not expose the Flask development server directly to the Internet. Public webhook
deployment still needs HTTPS, authentication/rate limiting, and a production server.

## Project Structure

```text
models.py                    Signal, bracket-order, and position types
config.py                    Strict environment configuration
data/                        Synthetic and yfinance feeds
strategy/                    Strategy interface and EMA crossover
signals/                     Watchlist signal engine
broker/                      Mock and Moomoo/OpenD adapters
trader/executor.py            Signal-to-broker actions
trader/runtime.py             Serialization, persistence, monitor lifecycle
state/store.py                SQLite schema and repository
web/app.py                    Flask dashboard and APIs
web/templates/index.html     Calm Risk Console markup
web/static/                  State-aware client rendering and responsive design
tests/                       Unit, contract, API, and restart integration tests
docs/superpowers/            Specs, plans, and A/B/C design comparisons
```

## Verification

The current credential-free gate contains **152 tests**.

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q broker data signals state strategy trader web
node --check web/static/app.js
.venv/bin/pip check
git diff --check
```

Additional observed gates:

- real `moomoo-api` `10.8.6808` method/status contract check;
- Impeccable UI detector: `[]`;
- browser checks at 1440px, 820px, and 390px without overflow;
- 44px mobile controls;
- native dialog Escape/focus restoration across polling re-renders;
- stale-response protection and unknown-quantity SELL blocking;
- first-run guide dismissal/reload/replay acceptance;
- clean browser console.

## Limitations

- EMA crossover is a teaching strategy, not evidence of profitability.
- No backtesting, walk-forward analysis, fees, slippage, or tax modeling yet.
- Moomoo paper-account behavior still needs the owner-run OpenD smoke test.
- Soft stops require the Python process to remain running.
- The Flask development server is local-only and not a production deployment.
- Only long US-stock positions and one active position per symbol are modeled.
- REAL-money mode is intentionally not validated or recommended.

## Roadmap

The highest-value next steps are:

1. Complete and record the OpenD `SIMULATE` smoke test.
2. Add backtesting with fees, slippage, and walk-forward splits.
3. Add max exposure, daily-loss, market-hours, and stale-quote guards.
4. Reconcile local positions/orders against broker truth at startup.
5. Add health notifications and background-service packaging.
6. Deploy the optional webhook behind production HTTPS and rate limiting.
7. Consider REAL mode only after extended paper observation and a separate safety review.

## Documentation

- Completion design: `docs/superpowers/specs/2026-07-11-credential-free-completion-design.md`
- Dashboard design: `docs/superpowers/specs/2026-07-11-dashboard-revamp-design.md`
- Dashboard comparison: `docs/superpowers/mockups/2026-07-11-dashboard-options.html`
- Onboarding comparison: `docs/superpowers/mockups/2026-07-12-onboarding-options.html`

## Disclaimer

Trading involves risk. This repository is for education and software experimentation.
It does not provide investment advice, guarantee execution, or claim that its strategy
will make money. You are responsible for validating every broker interaction and for
any decision to connect an account.
