# ▶ Resume here (handover) — 2026-07-12

Short "pick up where we left off" note. Full detail: `docs/SETUP.md`,
`docs/HANDOVER-live-trading.md`, `PROGRESS_REPORT.md`.

## State right now
- **Everything is merged into `main`.** A plain `git clone` lands on the current event-driven
  version — no branch checkout needed. Working tree is clean. Both feature branches
  (`feature/event-driven-tradingview-bridge` and the older `feature/credential-free-completion`)
  are fully incorporated in `main` and are now redundant (safe to delete when you like).
- **232 tests green.** `moomoo-api==10.08.6808` installed in `.venv`. The Cloudflare notifier
  Worker is named `signal-notifier` (matches the deployed Worker).
- `.env` is already set for **moomoo SG paper**: `BROKER=moomoo`, `TRD_ENV=SIMULATE`,
  `DATA_SOURCE=yfinance`, `MOOMOO_SECURITY_FIRM=FUTUSG`, OpenD `127.0.0.1:11111`,
  `WEBHOOK_ENABLED=false`. Config validates. (`.env` is git-ignored — recreate it on a new machine.)
- Built & shipped: event-driven webhook bridge, manual-OCO moomoo adapter, REAL-money gate
  (off by default), obvious REAL "LIVE MONEY ARMED" UI + Apple motion, configurable brokerage
  entity, `scripts/check_opend.py` probe, full setup + portability guide.
- **The only blocker is Phase A below (moomoo account + OpenD) — owner-side. There are no code blockers.**

## ◀ IMMEDIATE NEXT ACTION (owner — Phase A, needs your login)
1. **moomoo SG app:** finish US account opening + open **Paper Trading** (fake buying power). No funding needed.
2. **OpenD:** download macOS build from <https://www.moomoo.com/OpenAPI>, launch, log in with
   moomoo ID + password (only OpenD sees it), leave running on `127.0.0.1:11111`.
3. Run and paste the output back to the agent:
   ```bash
   cd /Users/wsoon/Projects/TradingSignalandHelper
   .venv/bin/python scripts/check_opend.py
   ```
   Expect `OK · connected` + an account table incl. a `SIMULATE` account.

## Then the agent resumes (in order)
1. Interpret probe output; fix entity/paper/market-data issues if any.
2. Guide first **paper trade from the dashboard** (`.venv/bin/python cli.py web` → Review → Confirm),
   confirm it appears in moomoo Paper Trading. ← Phase A checkpoint.
3. **Phase B:** generate `WEBHOOK_SECRET` (`openssl rand -hex 24`), start `cloudflared tunnel
   --url http://127.0.0.1:5000`, fire a test alert with **curl** (no TradingView account needed).
4. Optional: Telegram bot (BotFather token + chat id) and the Cloudflare notifier Worker
   (personal CF account only, never corporate).

## Queued code work (PAUSED by owner until after paper run)
Before REAL money: build **(a) startup reconciliation** (local state vs live broker) and
**(b) dry-run replay** (recorded SIMULATE corpus → REAL path), then owner sign-off. Spec:
`docs/superpowers/specs/2026-07-12-real-mode-enablement.md`. REAL gate itself is already built
and OFF (`ALLOW_REAL_WEBHOOK`).

## Constraints to remember
- TradingView webhooks need a **paid plan + 2FA**, ports 80/443 only, no IPv6, 3s timeout.
- Cloudflare = **personal** account only. Secrets never committed. OpenD must stay running to trade.
- No bare `python` — use `.venv/bin/python`.
