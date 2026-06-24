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

## Quick start (mock mode)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults are fine for mock mode

pytest                        # run the test suite
```

(The signals CLI and the one-button web dashboard arrive in later phases — see below.)

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
2. EMA crossover strategy (TDD)
3. Mock broker + executor with soft stop-loss (TDD)
4. Web dashboard + one Trade button  *(designed with real trading-app references)*
5. moomoo OpenD integration (paper)
6. `/webhook` stub for future TradingView + polish

See [`docs/superpowers/specs`](docs/superpowers/specs) for the full design.
