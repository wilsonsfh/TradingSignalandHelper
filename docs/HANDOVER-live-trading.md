# Handover — going live: paper trading (Step 1) then real money (Step 2)

Purpose: let a fresh session (or you) run **Step 1 (paper-first live loop)** and build/enable
**Step 2 (real money)** without prior chat context. Nothing here contains secrets or
account IDs — those live in your local `.env`, `wrangler.jsonc`, and Cloudflare dashboard.

## 0. Where things stand (2026-07-12)

- **The app already trades on paper.** Live signal in (`POST /webhook`, honoring the alert's
  `side/qty/tp/sl`) → executor → **moomoo via OpenD**: market entry + limit take-profit +
  stop-loss, tied as a **manual OCO**, with a hardened state machine (partial fills, restart
  recovery, unknown-ID quarantine). This is built + tested.
- **Real money is deliberately blocked** in the webhook (`web/app.py:315`, `if cfg.is_real_money: return 403`).
  That block is the switch Step 2 replaces with an explicit, guarded opt-in.
- **Layer 1 notifier Worker** (`cloudflare-notifier/`) is being deployed by you to your
  **personal** Cloudflare account (`trading-signal-notifier`, KV `EVENTS`) → TradingView →
  Telegram. It does NOT trade.
- **Layer 2 executor** = the Python bridge + OpenD on a persistent host, fronted by
  `cloudflare-tunnel/`. This is what trades.

## 1. Repo state

- Path: `/Users/wsoon/Projects/TradingSignalandHelper`
- Branch: `feature/event-driven-tradingview-bridge` (pushed to `origin` = `wilsonsfh/TradingSignalandHelper`; `main` untouched, no PR yet).
- Verify anytime (no bare `python` on this Mac — use the venv):
  ```bash
  .venv/bin/python -m pytest          # expect: 194 passed
  .venv/bin/python -m compileall -q broker data signals state strategy trader web notify config.py
  node --check web/static/app.js
  ```
- Latest commit: `5bbac76`. Key ones: alert parser `1a0027d`, honor-alert webhook `fee1cf9`,
  moomoo OCO `4d558fd`, event log `01ee175`, security `7b5a3ea`, notifier Worker `3c38149`,
  Telegram-in-bridge `d7fa084`, tunnel scaffold `5bbac76`.

## 2. Accounts, secrets, cost (READ FIRST — the common traps)

- **Personal Cloudflare account ONLY.** On a work Mac, `wrangler` is usually logged into the
  corporate `wsoon@cloudflare.com` account — do **not** deploy there. Use a **personal API
  token** (`export CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=…`) or `wrangler login` as your
  personal account. Your personal account is the one with the `wilsonsfh.workers.dev` subdomain.
- **Secrets (never commit):** `WEBHOOK_SECRET` (must match in the Worker, the bridge `.env`, and
  the TradingView alert `key`), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Generate the webhook
  secret with `openssl rand -hex 24`. One Telegram bot/chat is shared by both layers.
- **moomoo login lives in OpenD, never in `.env`.** The app only needs `OPEND_HOST`/`OPEND_PORT`.
- **Free tier:** Workers, Workers KV, Access, and Tunnel are all free at this scale. The only
  thing that costs money is a **custom domain** for a stable tunnel hostname — avoid it with a
  free **quick tunnel** (`cloudflared tunnel --url http://127.0.0.1:5000` → an ephemeral
  `trycloudflare.com` URL that changes each restart) or by fronting via the free `workers.dev`.
- On the Free plan you can't be surprise-billed; hitting a limit errors, it doesn't charge.

## 3. STEP 1 — run the live loop on PAPER (SIMULATE). Zero financial risk.

Prereq: a **moomoo account with paper trading enabled**.

1. Download + run **OpenD** (from moomoo's OpenAPI site); log in with your moomoo ID/password.
   Keep it running.
2. Install the optional SDK: `.venv/bin/pip install -r requirements-moomoo.txt`.
3. `.env` (copy from `.env.example`), set:
   ```dotenv
   BROKER=moomoo
   TRD_ENV=SIMULATE
   DATA_SOURCE=yfinance
   OPEND_HOST=127.0.0.1
   OPEND_PORT=11111
   USE_BROKER_STOP_ORDER=true       # true = real resting stop (Curteis' 3-order OCO); false = soft monitored stop
   WEBHOOK_ENABLED=true
   WEBHOOK_SECRET=<same 32+ char secret as the Worker / TradingView key>
   TELEGRAM_BOT_TOKEN=<your bot token>
   TELEGRAM_CHAT_ID=<your chat id>
   ```
4. Run the bridge + expose it:
   ```bash
   .venv/bin/python cli.py web            # terminal 1  (dashboard http://127.0.0.1:5000)
   cloudflared tunnel --url http://127.0.0.1:5000   # terminal 2 (free quick tunnel → prints an https URL)
   ```
   (Or a named tunnel with `cloudflare-tunnel/` if you own a domain — see that folder's README.)
5. In TradingView, create an alert whose **Webhook URL** is `<tunnel-url>/webhook` and whose
   message is JSON (see `cloudflare-notifier/README.md` for the exact body), with
   `"key":"<WEBHOOK_SECRET>"`.
6. **SIMULATE smoke checklist** (do one small position): realtime quote works → entry submits →
   entry fills → take-profit placed → stop placed (if `USE_BROKER_STOP_ORDER=true`) → hit a
   level and confirm the sibling order cancels → restart the bridge and confirm the position is
   recovered → clean `Ctrl+C` shutdown → Telegram messages arrived for each. All fake money.

Gotchas: keep OpenD + bridge + tunnel all running during US market hours; the quick-tunnel URL
changes each restart (update the TradingView URL if you restart it). Trades only run while this
host is on — for always-on, host Layer 2 on a VM or Zo Computer.

## 4. STEP 2 — enable REAL money (code to BUILD next session, then you flip it on)

Do this only after Step 1's paper smoke passes. Design spec:
`docs/superpowers/specs/2026-07-12-real-mode-enablement.md`.

**What a future session must build (ships OFF by default; owner flips it):**

1. `config.py`: add `allow_real_webhook` (env `ALLOW_REAL_WEBHOOK`, default **False**),
   `max_notional` (env `MAX_NOTIONAL`, per-order cap), `max_daily_loss` (env `MAX_DAILY_LOSS`,
   kill-switch). Validate positivity.
2. `web/app.py` webhook (the block at **`web/app.py:315`**): replace the hard
   `if cfg.is_real_money: return 403` with:
   - if `is_real_money and not cfg.allow_real_webhook` → still `403` (blocked);
   - if allowed → require `body.get("confirm") is True` (like the dashboard REAL gate at `:141`);
   - enforce `price * quantity <= max_notional`.
3. `state/store.py`: track realized P&L per UTC day; expose a helper the runtime checks.
4. `trader/runtime.py`: before opening in REAL, enforce the daily-loss kill-switch, market-hours,
   and stale-quote guards; refuse and Telegram-alert when tripped.
5. Startup reconciliation: on boot in REAL, compare local SQLite state against the broker's real
   open orders/positions; refuse to trade on divergence until resolved.
6. Tests: REAL gate (blocked unless `ALLOW_REAL_WEBHOOK` + `confirm:true`), notional cap, daily-loss
   kill-switch — all via the fake SDK, no live account.

**What you (owner) do to actually go live, after the code exists:**
- Fund a **real** moomoo account; in OpenD log into it.
- `.env`: `TRD_ENV=REAL`, `ALLOW_REAL_WEBHOOK=true`, set small `MAX_NOTIONAL` and `MAX_DAILY_LOSS`,
  keep `confirm:true` in the TradingView alert body.
- Re-run the smoke with **one tiny position**, watch Telegram + the dashboard closely, then scale
  slowly. Real money is irreversible — start with the smallest size and lowest caps.

## 5. Invariants — do not regress

- SIMULATE/mock-first; REAL off by default and behind `ALLOW_REAL_WEBHOOK` + `confirm:true` + caps.
- The alert is authoritative for `tp/sl/quantity` within bounds (`MAX_ALERT_QUANTITY`, default 100).
- Manual OCO: a fill on one leg cancels the sibling; `USE_BROKER_STOP_ORDER` toggles resting stop
  vs soft monitored stop; unknown broker order IDs quarantine the position (no blind re-sell).
- Telegram is best-effort, non-blocking, config-gated (no-op if unset).
- Never deploy this personal project to the corporate Cloudflare account.
- Terminology: write "traceability", not "provenance".

## 6. Reference map

- Code: `web/app.py` (webhook + APIs), `signals/alerts.py` (parser), `trader/{executor,runtime}.py`,
  `broker/moomoo_broker.py` (OCO state machine), `state/store.py`, `notify/telegram.py`.
- Deploy: `cloudflare-notifier/` (Layer 1 Worker), `cloudflare-tunnel/` (Layer 2 front),
  `docs/deploy/README.md` (hosts overview), `docs/superpowers/specs/2026-07-12-real-mode-enablement.md`.
- Learning: personal wiki `wiki/projects/trading-signal-and-helper.md`,
  `wiki/sources/2026-07-12-trading-signal-cloudflare-telegram-architecture.md`, and the
  `trading-signal-architecture.canvas` map.
