# TradingSignalandHelper

A small, **paper-first** trading assistant inspired by Curteis Yang's
[TradingView → moomoo bridge](https://medium.com/@curteisyang). It is two bots in one
Python project:

1. **Signals bot** — reads US-stock prices, runs an **EMA crossover** strategy, and
   outputs `BUY / SELL / HOLD` with a suggested entry, take-profit and stop-loss.
2. **Trade helper** — a tiny local web page with **one "Trade" button**. You review
   the proposed trade and click once to place it (human-in-the-loop).

It is built **hybrid**: everything runs locally with fake money first, and the
heavier pieces from the article (TradingView alerts, Cloudflare, AWS) can be added
later **without a rewrite**.

> ⚠️ **Money warning.** This software can place real trades. It defaults to a safe
> `mock` mode (fake fills). Real money requires `BROKER=moomoo` **and** `TRD_ENV=REAL`
> **and** an on-screen confirmation. Keep it on paper while you learn.

## How it works

```
price data → EMA strategy → Signal(BUY/SELL/HOLD, entry, TP, SL)
   → shown on the local web dashboard
   → YOU click "Trade"
   → executor → broker places: market ENTRY + limit TAKE-PROFIT + soft STOP-LOSS
   → everything logged
```

**Soft stop-loss:** moomoo's paper mode only supports market & limit orders (no native
stop). So the bot *watches the price and sells if the stop level is hit*. (A real stop
order can be used once you trade live.)

## Modes

| `BROKER` | `TRD_ENV` | Meaning |
|----------|-----------|---------|
| `mock`   | —         | Fake data + fake fills. No broker needed. **Default.** |
| `moomoo` | `SIMULATE`| Real moomoo **paper** trading via OpenD (fake money, real plumbing). Phase 5. |
| `moomoo` | `REAL`    | **Live money.** Double-gated. Not recommended while learning. |

## Quick start (mock mode — no network, no credentials)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults are fine for mock mode

pytest                        # run the test suite (29 tests)
python cli.py demo            # offline end-to-end demo in the terminal
python cli.py web             # launch the dashboard at http://127.0.0.1:5000
```

Open the dashboard, review the signals, and click **Buy / Sell** — a confirm
"order ticket" appears; confirm and the position shows up with live P&L. Everything
is fake money in `mock` mode.

`python cli.py signals` prints live signals using real (delayed) yfinance data —
set `DATA_SOURCE=yfinance` in `.env` to use real data in the dashboard too.

## Connect moomoo (Phase 5) — when you're ready, no credentials in code

The bot never stores your moomoo password — **OpenD** logs in, and the bot talks to
OpenD locally. To switch from `mock` to real **paper** trading:

```bash
pip install moomoo-api          # the SDK
# 1) Download & run OpenD (moomoo OpenAPI gateway), log in with your moomoo account.
# 2) Confirm it's listening on 127.0.0.1:11111 (placeholders below).
```

Then in `.env`:
```
BROKER=moomoo
TRD_ENV=SIMULATE        # paper / fake money (keep this while learning)
OPEND_HOST=127.0.0.1    # placeholder — change if OpenD runs elsewhere
OPEND_PORT=11111        # placeholder
```
`python cli.py web` will call `broker.connect()` on launch and tell you if OpenD
isn't reachable. `MoomooBroker` is a **scaffold**: the SDK calls follow moomoo's
docs but should be verified against your account on first connect. Paper mode allows
only market + limit orders, so the stop-loss runs as a soft watch (same as mock).

> Going to `TRD_ENV=REAL` places **live orders with real money**. The dashboard then
> requires an explicit confirm, and the webhook auto-trader is disabled for safety.

## TradingView webhook (Phase 6) — optional, future

`POST /webhook` lets a TradingView alert drive the same executor later:
```json
{ "action": "buy", "symbol": "AAPL", "price": 195.0, "tp": 200.0, "sl": 191.0, "key": "<WEBHOOK_SECRET>" }
```
- Authenticated by the shared `WEBHOOK_SECRET` (placeholder `change-me` in `.env`).
- Disabled automatically in REAL-money mode (no unattended live trading).
- Works in `mock`/paper today. Exposing it to the internet (Cloudflare WAF + HTTPS,
  AWS) is a later step, mirroring Curteis's setup.

## Project structure

```
models.py            Shared data types (Signal, BracketOrder, Position)
config.py            Settings loaded from .env
data/price_feed.py   Price data (yfinance now; moomoo quotes in Phase 5)
strategy/            Strategy interface + EMA crossover
signals/             Run the strategy across the watchlist
broker/              Broker interface + MockBroker (+ MoomooBroker in Phase 5)
trader/              Executor — the "Trade" action
web/                 Local dashboard + one button (+ /webhook stub for TradingView)
state/               SQLite log of signals/orders/positions
tests/               pytest suite
docs/superpowers/specs/   Approved design document
```

## Build phases

1. ✅ Scaffold + config + spec doc
2. ✅ EMA crossover strategy (TDD)
3. ✅ Mock broker + executor with soft stop-loss (TDD)
4. ✅ Web dashboard + one Trade button (dark, calm, confirm-ticket)
5. ✅ moomoo OpenD integration (paper) — *scaffolded; connect your account to verify live*
6. ✅ `/webhook` for future TradingView (works in mock; cloud exposure later)

See [`docs/superpowers/specs`](docs/superpowers/specs) for the full design.
