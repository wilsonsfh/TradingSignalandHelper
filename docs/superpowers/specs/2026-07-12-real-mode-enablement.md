# REAL-mode enablement — conditions (spec only, NOT implemented)

**Status:** out of scope for the event-driven bridge plan. This document records
what a future, explicitly-approved plan MUST satisfy before REAL auto-execution
is ever enabled. No code implements REAL webhook trading today.

## Current guardrails (keep until deliberately removed)

- `TRD_ENV=REAL` is only reached with `BROKER=moomoo` and an explicit env change.
- `/webhook` is hard-blocked in REAL mode (`web/app.py`): it returns 403 before
  any order path. This block must stay until every condition below is met.
- Dashboard REAL orders already require a literal `confirm: true`.

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
