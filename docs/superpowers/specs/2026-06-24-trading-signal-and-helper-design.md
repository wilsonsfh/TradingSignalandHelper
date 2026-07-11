# TradingSignalandHelper — Design

**Date:** 2026-06-24
**Status:** Implemented; extended by [the credential-free completion design](2026-07-11-credential-free-completion-design.md)
**Owner:** wilsonsfh

## Goal

Build two bots in one Python project, inspired by Curteis Yang's TradingView → moomoo
bridge:

1. **Signals bot** — generate `BUY / SELL / HOLD` signals from a trading strategy.
2. **Trade helper** — a single-button tool that executes the proposed trade.

Approach: **Hybrid, paper-first.** Self-contained and local now (zero cost, zero risk);
structured so TradingView + Cloudflare + AWS can be added later without a rewrite.

## Key research findings (primary sources)

- **moomoo OpenAPI has built-in paper trading** via `TrdEnv = SIMULATE`. The same code
  places orders in paper or live mode → build & test safely with fake money.
- **moomoo SG can paper-trade US stocks/ETFs/options.** → US stocks are the target market.
- **TradingView webhooks require a paid plan + 2FA.** → deferred to the optional cloud phase.
- **moomoo paper mode supports only market + limit orders (no native stop).** → the
  stop-loss is implemented as a *soft stop*: the bot watches price and sells when hit.
- **No native OCO** → one trade = market entry + limit take-profit + soft stop-loss,
  paired in software so closing one cancels the other.

## Architecture

```
price data → EMA strategy → Signal → dashboard → [Trade button] → executor → broker
                                                                         │
                                                  market entry + limit TP + soft SL
```

### Components

| Module | Responsibility | Depends on |
|--------|----------------|------------|
| `models.py` | Shared data types: `Signal`, `BracketOrder`, `Position` | — |
| `config.py` | Settings from `.env` | env |
| `data/price_feed.py` | `PriceFeed` interface + `YFinanceFeed` (daily candles) | yfinance |
| `strategy/base.py` | `Strategy` interface (pure: candles → Signal) | models |
| `strategy/ema_crossover.py` | EMA crossover strategy | pandas, models |
| `signals/engine.py` | Run a strategy across the watchlist | strategy, data |
| `broker/base.py` | `Broker` interface | models |
| `broker/mock_broker.py` | Simulated fills + soft TP/SL watch | models |
| `broker/moomoo_broker.py` | Moomoo via OpenD (paper first; injected SDK contract) | moomoo-api |
| `trader/executor.py` | Turn a Signal into broker calls (the "Trade" action) | broker, models |
| `trader/runtime.py` | Serialize mutations, persist outcomes, run soft-stop monitoring | broker, data, state |
| `web/app.py` | Flask dashboard, trade APIs, and opt-in hardened `/webhook` | flask |
| `state/store.py` | SQLite log of signals/orders/positions | stdlib sqlite3 |
| `cli.py` | `signals` (print latest) and `trade` (execute latest) commands | all |

### Modes (config switch)

- `BROKER=mock` (default): fake fills; no broker needed; used by all tests.
- `BROKER=moomoo` + `TRD_ENV=SIMULATE`: real moomoo paper trading via OpenD.
- `TRD_ENV=REAL`: live money — gated behind explicit config **and** on-screen confirm.

### Data flow

1. `price_feed` fetches recent daily candles per watchlist symbol.
2. `strategy.ema_crossover` computes fast/slow EMAs → `Signal` with entry (last close),
   take-profit (+`TAKE_PROFIT_PCT`%), stop-loss (−`STOP_LOSS_PCT`%).
3. `signals.engine` stores the latest signals.
4. Dashboard / `cli signals` displays them.
5. User clicks **Trade** → `trader.runtime` → `trader.executor` → broker; the runtime's
   independent monitor watches prices and closes on TP/SL.
6. All events logged to `state`.

## Strategy (starting)

**EMA crossover**, long-only:
- Fast EMA (default 9) and slow EMA (default 21) of daily Close.
- `BUY` when fast crosses **above** slow; `SELL` when fast crosses **below** slow; else `HOLD`.
- Configurable via `.env`. Interface allows adding/swapping strategies later.

## Defaults

| Setting | Default |
|---------|---------|
| Market | US stocks |
| Watchlist | AAPL, MSFT, NVDA, SPY |
| Timeframe | Daily candles |
| EMA periods | fast 9 / slow 21 |
| Position size | 1 share / trade |
| Take-profit / Stop-loss | +3% / −2% |
| Direction | Long-only |

## Safety

- Defaults to `mock`.
- Real money requires `BROKER=moomoo` + `TRD_ENV=REAL` + on-screen confirmation.
- `.env` is git-ignored; no secrets committed. `Device.dat` (OpenD) git-ignored.

## Testing

TDD throughout. Strategy, stores, runtime, brokers, data adapters, Flask routes, and
restart behavior are tested deterministically without network access.

## Build phases

1. Completed: scaffold + strict config + specs.
2. Completed: EMA crossover strategy.
3. Completed: mock broker + executor + durable SQLite state.
4. Completed: dashboard + serialized runtime + independent soft-stop monitor.
5. Credential-free complete: Moomoo SDK contract, cancellation, failure handling, and setup guide. External `SIMULATE` smoke test remains.
6. Completed locally: opt-in, replay-resistant webhook. Public TradingView/cloud setup remains optional.

## Future (not now)

- TradingView paid-plan alert configuration for the existing `/webhook` endpoint.
- Cloudflare WAF + HTTPS; AWS scheduled EC2 / Lightsail deploy for 24/5 operation.
