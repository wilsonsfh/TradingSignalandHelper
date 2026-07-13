# TradingSignalandHelper

**A signal-driven US-stock trading desk: your TradingView signal fires the trade — collapsing the old 3-click "review → confirm → watch" routine into zero-click, API-executed orders, paper-first and fully inspectable.**

TradingSignalandHelper is a **TradingView → moomoo bridge** built on Curteis Yang's
principle: **the Pine script is the brain; the bridge just executes.** Your chart
*signal* is the trigger — a TradingView alert fires a webhook and the app places the
entry, take-profit, and stop **automatically**, so you stop hand-placing every trade. A
human-in-the-loop dashboard stays on for oversight and one-tap real-money confirmation,
and every step of the order lifecycle is inspectable.

It bundles, in one Python application:

1. An **event-driven bridge**: a `POST /webhook` endpoint that accepts a TradingView
   alert (`action`, `symbol`, `side`, `quantity`, `tp`, `sl`) and executes it, honoring
   the alert's own size and risk levels.
2. A **broker-safe executor**: entry + limit take-profit + an optional resting stop-loss,
   tied together as a manual OCO because moomoo has no native OCO.
3. A **human-in-the-loop dashboard** (the Calm Risk Console) that streams incoming alerts,
   and shows each position's protection legs, P&L, and broker state.
4. An optional built-in **EMA signal engine** for manual review when you have no external
   alert source.

The application defaults to synthetic prices and fake fills. It needs no account,
credentials, or network connection for its complete mock workflow.

> [!WARNING]
> This is educational software, not financial advice or a profitable-strategy claim.
> Real-money execution is **gated off by default** and **not yet validated for live
> capital** — keep `BROKER=mock` or `TRD_ENV=SIMULATE` while learning.

## Signals first — from 3 clicks to zero

The signal is the product; everything else exists to execute it safely.

- **Before — the manual helper (still here for oversight):** a signal appears, you click
  **Review**, click **Confirm** on the order ticket, then watch protection. ~3 clicks per
  trade, and you have to be at the screen.
- **Now — the signal-driven bridge (the API integration):** your TradingView Pine alert
  fires on the chart event → `POST /webhook` → the app executes entry + take-profit + stop
  (a manual OCO) **automatically**. **Zero clicks per trade — the signal *is* the trigger.**
  The dashboard becomes a live oversight surface (incoming alerts, protection legs, P&L,
  audit trail), not the execution path.

| | Manual helper | Signal-driven bridge |
|---|---|---|
| Trigger | You, watching charts | Your TradingView signal |
| Clicks per trade | ~3 (Review → Confirm → watch) | 0 |
| Where you are | At the dashboard | Anywhere |
| Safety | Confirm ticket | Shared secret + replay/stale guards; REAL adds `confirm: true` + circuit breakers |

Broker confirmation always wins over optimistic UI, protection legs are tracked, and real
money stays gated off by default.

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
| Event-driven webhook | Executes TradingView alerts, honoring alert `quantity`/`tp`/`sl`; rejects weak secrets, stale/replayed events, unknown symbols, and over-cap sizes; REAL mode is gated off by default. |
| Manual OCO | Optional resting broker stop order paired with the limit take-profit; a fill on one leg cancels the other. |
| Incoming-alerts stream | The dashboard shows every inbound event (accepted or rejected) and each position's Entry/TP/Stop legs. |
| Defence-in-depth | Optional HMAC signature, source-IP allow-list, and per-IP rate limit on `/webhook`. |
| Moomoo adapter | Contract-tested against the real `moomoo-api` `10.8.6808` shape; brokerage entity is configurable (`MOOMOO_SECURITY_FIRM`: FUTU HK / moomoo US / SG / AU / …). |
| REAL-money gate | Double opt-in (`ALLOW_REAL_WEBHOOK` + per-alert `confirm`), per-order notional cap, daily-loss kill-switch, and a market-hours fence — all off by default, with an unmistakable "LIVE MONEY ARMED" dashboard. |
| Notifications | Optional Telegram pushes on open, close, auto-exit (TP/SL/stop), and rejection. |

> **Setting up the moomoo paper broker, or running on another machine?** This Quick Start is
> the credential-free mock path. For the moomoo + OpenD paper setup and the **"run it on another
> machine"** portability guide (git clone + venv; no Docker), see **[`docs/SETUP.md`](docs/SETUP.md)**.

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
TradingView alert (event) ─┐
                           ├─> /webhook ─> Signal ─> Executor ─> Broker
Built-in EMA strategy  ────┘   (honors alert tp/sl/qty)     │
   (manual dashboard path)                                  └─> entry / limit-TP / stop-SL (manual OCO)

SQLite StateStore <-> TradingRuntime <-> background soft-stop monitor
Event log ─> /api/events ─> "Incoming alerts" panel
```

### Main Objects

- **Signal:** symbol, action, price, quantity, TP, SL, reason, timestamp.
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
| `WEBHOOK_ENABLED` | `false` | Enables the TradingView webhook (paper only). |
| `WEBHOOK_SECRET` | `change-me` | Must be replaced with at least 32 characters. |
| `WEBHOOK_MAX_AGE_SECONDS` | `300` | Replay/age window. |
| `WEBHOOK_SIGNATURE_REQUIRED` | `false` | Require an HMAC `X-Signature` header. |
| `WEBHOOK_IP_ALLOWLIST` | (empty) | Comma-separated source IPs allowed on `/webhook`; empty = rely on the edge/WAF. |
| `WEBHOOK_RATE_PER_MIN` | `5` | Per-IP `/webhook` rate limit. |
| `MAX_ALERT_QUANTITY` | `100` | Server cap on alert-supplied quantity. |
| `USE_BROKER_STOP_ORDER` | `false` | Resting broker stop order (manual OCO) vs a soft monitored stop. |
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

## Event-Driven Signals (TradingView Webhook)

This is the primary signal path and the core of the TradingView → moomoo bridge. The
webhook is disabled by default and is never allowed to trade in REAL mode.

```dotenv
WEBHOOK_ENABLED=true
WEBHOOK_SECRET=replace-with-at-least-32-random-characters
WEBHOOK_MAX_AGE_SECONDS=300
# Optional hardening:
WEBHOOK_SIGNATURE_REQUIRED=false
WEBHOOK_IP_ALLOWLIST=
WEBHOOK_RATE_PER_MIN=5
```

The alert is the brain. Point a TradingView alert at `POST /webhook` with a body like:

```json
{
  "event_id": "unique-alert-id",
  "timestamp": "2026-07-12T12:00:00Z",
  "action": "open",
  "side": "buy",
  "symbol": "AAPL",
  "quantity": 4,
  "tp": 210.00,
  "sl": 190.00,
  "key": "replace-with-at-least-32-random-characters"
}
```

- `action`/`side` choose open-long vs close: `open`/`buy` opens, `close`/`sell` closes.
- `quantity`, `tp`, and `sl` are **honored** (within the server `MAX_ALERT_QUANTITY` cap
  and a `sl < tp` sanity check). If `tp`/`sl` are omitted, the server falls back to
  `TAKE_PROFIT_PCT` / `STOP_LOSS_PCT`. The reference price always comes from the server feed.

The endpoint rejects: disabled or weak/default secrets; stale, future-skewed, or replayed
events; malformed/non-object JSON; unknown actions; symbols outside the watchlist;
quantities over the cap; and every request in REAL mode. With hardening enabled it also
enforces an HMAC `X-Signature`, a source-IP allow-list, and a per-IP rate limit.

Every inbound alert — accepted or rejected — is recorded to the event log and shown in the
dashboard's **Incoming alerts** panel and via `GET /api/events`.

Do not expose the Flask development server directly to the Internet. For production, see
`docs/deploy/README.md` (OpenD + Caddy HTTPS + Cloudflare WAF/rate-limit + market-hours
scheduling).

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

The current credential-free gate contains **188 tests**.

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
- alert-honoring webhook (quantity/tp/sl), event log, and `/api/events` surfacing;
- webhook defence-in-depth: HMAC signature, IP allow-list, and per-IP rate limit;
- manual-OCO broker stop order with sibling-leg cancellation;
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
6. Deploy the webhook to production using `docs/deploy/README.md` (HTTPS + Cloudflare).
7. Consider REAL mode only after extended paper observation and a separate safety review.

## Documentation

- **Setup & credentials (paper-first) + run on another machine:** [`docs/SETUP.md`](docs/SETUP.md)
- **Resume / handover note:** [`docs/NEXT.md`](docs/NEXT.md)
- **Live-trading — Step 1 (paper) & Step 2 (real money):** [`docs/HANDOVER-live-trading.md`](docs/HANDOVER-live-trading.md)
- Event-driven bridge plan: `docs/superpowers/plans/2026-07-12-event-driven-tradingview-bridge.md`
- Deployment runbook: `docs/deploy/README.md`
- REAL-mode enablement conditions: `docs/superpowers/specs/2026-07-12-real-mode-enablement.md`
- Completion design: `docs/superpowers/specs/2026-07-11-credential-free-completion-design.md`
- Dashboard design: `docs/superpowers/specs/2026-07-11-dashboard-revamp-design.md`
- Event-stream comparison: `docs/superpowers/mockups/2026-07-12-event-stream-options.html`
- Dashboard comparison: `docs/superpowers/mockups/2026-07-11-dashboard-options.html`
- Onboarding comparison: `docs/superpowers/mockups/2026-07-12-onboarding-options.html`

## Disclaimer

Trading involves risk. This repository is for education and software experimentation.
It does not provide investment advice, guarantee execution, or claim that its strategy
will make money. You are responsible for validating every broker interaction and for
any decision to connect an account.
