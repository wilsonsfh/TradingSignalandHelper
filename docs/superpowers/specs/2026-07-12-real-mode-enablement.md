# REAL-mode enablement — conditions

**Status (2026-07-12):** the **gate layer is now implemented and off by default**
(`trader/safety.py` + `web/app.py`; see `docs/HANDOVER-live-trading.md`). Items 1,
3, and 4 below are built and unit-tested. Items 2 (live-broker startup
reconciliation), 5 (recorded-corpus dry-run replay), and 6 (human checkpoint)
remain REQUIRED before any real capital is risked.

## Current guardrails (keep until deliberately removed)

- `TRD_ENV=REAL` is only reached with `BROKER=moomoo` and an explicit env change.
- `/webhook` stays hard-blocked in REAL mode unless `ALLOW_REAL_WEBHOOK=true`
  (`web/app.py`): otherwise it returns 403 `DISABLED` before any order path.
- Dashboard REAL orders already require a literal `confirm: true`.

## Implemented (Step 2, default OFF)

- **Double opt-in** — `ALLOW_REAL_WEBHOOK=true` (env, owner-set) AND per-alert
  `confirm: true`; either missing → 403/412. (`test_safety.py`, `test_web_app.py`)
- **Circuit breakers** — `MAX_NOTIONAL` per-order cap and `MAX_DAILY_LOSS`
  realized-loss kill-switch (`state/store.py: realized_pnl_since`); 0 disables each.
- **Market-hours fence** — REAL `open` orders rejected outside US RTH
  (`ENFORCE_MARKET_HOURS`, holidays not modelled); closing always allowed.

## Required before enabling REAL webhook auto-execution

1. **Double opt-in.** A dedicated env flag (e.g. `ALLOW_REAL_WEBHOOK=true`) AND a
   per-alert `confirm: true`; either missing → reject. The flag is owner-set on
   the host, never defaulted.
2. **Startup reconciliation.** On boot, reconcile local SQLite state against the
   broker's real order/position truth (open orders, resting TP/stop, fills) and
   refuse to trade on divergence until resolved.
3. **Circuit breakers.** Enforce max notional per order, max open exposure, and a
   daily realized-loss kill-switch that disables the webhook when tripped.
4. **Market-hours + freshness guards.** Reject alerts outside RTH and reject
   trades when the last quote is stale beyond a threshold.
5. **Dry-run replay.** Replay a corpus of recorded SIMULATE events against the
   REAL code path with a mocked broker and confirm identical decisions.
6. **Human checkpoint.** A mandatory review sign-off; enabling REAL is a
   destructive/irreversible-risk action per the operating rules and needs the
   owner's credentials and explicit go-ahead.

## Explicitly out of scope here

- Shorting / non-long strategies.
- Multiple concurrent positions per symbol.
- Any change that would weaken the SIMULATE-first default.
