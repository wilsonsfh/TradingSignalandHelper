# Setup & credentials guide (paper first)

Hand-holding setup for the accounts, tools, and credentials you provide. Do it in two
phases — **Phase A proves moomoo paper execution with the fewest moving parts** (no
TradingView, no Cloudflare), then **Phase B adds the TradingView webhook path**. Real
money is a later, deliberate step (see the end + `docs/HANDOVER-live-trading.md`).

Nothing here is committed as a secret. The app never stores your moomoo password —
**OpenD** holds the login; the app only talks to OpenD locally.

## What you need (at a glance)

| # | Thing | Why | Cost | Needed for |
|---|-------|-----|------|-----------|
| 1 | **moomoo account** (moomoo ID) + an opened **US trading account** with paper trading | The broker | Free to open | Phase A |
| 2 | **OpenD** (moomoo's gateway app) | Bridges the app ↔ moomoo; holds your login | Free | Phase A |
| 3 | Python venv + `moomoo-api` SDK | The adapter | Free | Phase A |
| 4 | **WEBHOOK_SECRET** (you generate) | Auth for `/webhook` | Free | Phase B |
| 5 | **cloudflared** | Public HTTPS URL for TradingView → your local app | Free | Phase B |
| 6 | **TradingView** account, **paid plan + 2FA** | Sends the webhook alert | Paid (Essential+) | Phase B |
| 7 | *(optional)* Telegram bot | Push notifications | Free | Phase B |
| 8 | *(optional)* personal **Cloudflare** account | The notifier Worker layer | Free tier | Phase B |

> Region note: US-stock paper trading is supported on most moomoo entities (US/SG/AU/etc.)
> but details vary — confirm your entity offers **US paper trading** in the moomoo app.

---

## Phase 0 — your machine (2 min)

```bash
cd /Users/wsoon/Projects/TradingSignalandHelper
.venv/bin/python -m pytest -q          # sanity: should say "232 passed"
.venv/bin/pip install -r requirements-moomoo.txt   # moomoo-api==10.8.6808 (already installed this session)
```
✅ Done when `pytest` is green and `.venv/bin/pip show moomoo-api` prints version 10.08.6808.

---

## Phase A — moomoo + OpenD → your first paper trade (no TradingView needed)

### A1 · moomoo account
1. Install the **moomoo** app (or futubull, depending on your region) and register — this is your **moomoo ID**.
2. Complete **account opening** for the **US market** (identity check; free). You do NOT need to fund it for paper trading.
3. In the app, open **Paper Trading** and confirm you have a US paper account (you'll see fake buying power). This is what `TRD_ENV=SIMULATE` uses.
4. *(If quotes come back empty later)* enable **US market data** (Level 1 is typically free) in the app — the bridge pulls realtime quotes through OpenD.

### A2 · OpenD (the gateway)
1. Download **OpenD** for macOS from moomoo's OpenAPI page: <https://www.moomoo.com/OpenAPI> (docs: <https://openapi.moomoo.com/moomoo-api-doc/en/quick/opend-base.html>).
2. Unzip and launch OpenD (GUI or command-line build — either is fine).
3. **Log in** with your **moomoo ID + password** inside OpenD. (The password lives only in OpenD.)
4. Confirm it's listening on the default **`127.0.0.1` port `11111`**. Leave OpenD running the whole time you use the app.

### A3 · configure the bridge
Copy `.env.example` → `.env` and set:
```dotenv
BROKER=moomoo
TRD_ENV=SIMULATE            # paper account
DATA_SOURCE=yfinance        # required with moomoo
OPEND_HOST=127.0.0.1
OPEND_PORT=11111
MOOMOO_SECURITY_FIRM=FUTUSG # ← moomoo SG. (US=FUTUINC, HK=FUTUSECURITIES, AU=FUTUAU, …)
# leave WEBHOOK_ENABLED unset/false for Phase A
```
> **Why `MOOMOO_SECURITY_FIRM` matters:** the SDK defaults to FUTU HK. On a **moomoo SG**
> account you MUST set `FUTUSG` or OpenD lists zero accounts and nothing trades.

### A4 · verify the connection, then trade
Run the read-only probe (uses your `.env`; lists accounts, places no orders):
```bash
.venv/bin/python scripts/check_opend.py
```
- Before OpenD is up you'll see: `FAIL · nothing listening at 127.0.0.1:11111` — expected.
- With OpenD running + logged in: `OK · connected` + an account table, and
  `OK · a SIMULATE (paper) account is available`. 🎉
- `get_acc_list error` / no SIMULATE account → your `MOOMOO_SECURITY_FIRM` may not match
  your entity, or Paper Trading isn't enabled in the moomoo app. Paste the output to me.

Then place a **paper trade from the dashboard** (no webhook needed):
```bash
.venv/bin/python cli.py web         # open http://127.0.0.1:5000
```
Find a **BUY** signal → **Review** → **Confirm buy**. A position should appear with TP/SL
legs, and the **paper order shows up in the moomoo app's Paper Trading**.

✅ **Phase A checkpoint:** a paper order you placed from the dashboard appears in moomoo.
This proves the whole execution + protection path end-to-end. Stop here and tell me if
anything failed — this is the highest-value milestone.

---

## Phase B — the TradingView webhook path (event-driven)

Now let the *chart* fire trades. Keep OpenD + the app running from Phase A.

### B1 · webhook secret
```bash
openssl rand -hex 24        # copy this value; it's your shared secret
```
Put the SAME value in three places: `.env` `WEBHOOK_SECRET=…`, the TradingView alert body
`"key"`, and (if you use it) the Cloudflare Worker secret. Then in `.env`:
```dotenv
WEBHOOK_ENABLED=true
WEBHOOK_SECRET=<the value>
```

### B2 · public HTTPS URL (cloudflared)
```bash
brew install cloudflared
cloudflared tunnel --url http://127.0.0.1:5000     # prints an https://…trycloudflare.com URL
```
Free and ephemeral — the URL **changes each restart** (update the alert if you restart it).
TradingView only accepts **ports 80/443**, so you must use this HTTPS URL, never `:5000`.

### B3 · test the webhook WITHOUT TradingView first (you have no TV account yet)
You don't need TradingView to prove the webhook path — send the alert yourself with `curl`
(swap in your tunnel URL + secret). This is the whole point of the event-driven design:
```bash
curl -X POST https://<your-tunnel>.trycloudflare.com/webhook \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"test-1","timestamp":"'"$(date -u +%FT%TZ)"'","action":"open","side":"buy","symbol":"AAPL","quantity":1,"tp":235.0,"sl":225.0,"key":"<WEBHOOK_SECRET>"}'
```
A paper position should open and appear in the dashboard's **Incoming alerts** panel. (Use a
symbol in your `WATCHLIST`.) Re-sending the same `event_id` returns `409 REPLAY` — by design.

### B3b · (later) the real TradingView alert  ⚠️ needs a **paid plan + 2FA**
When you decide to sign up: webhook alerts require a **paid** TradingView plan (Essential+)
**and** 2FA. Then create an alert → **Notifications → Webhook URL** = `<tunnel-url>/webhook`,
with the same JSON as the curl body above but using TradingView placeholders, e.g.
`"symbol":"{{ticker}}"`. Only these TradingView IPs send the POST (optionally allowlist via
`WEBHOOK_IP_ALLOWLIST`): `52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7`.

### B4 · Telegram notifications (optional)
1. Message **@BotFather** → `/newbot` → copy the **token**.
2. Message your new bot once, then open `https://api.telegram.org/bot<token>/getUpdates` and copy your numeric **chat id**.
3. `.env`: `TELEGRAM_BOT_TOKEN=…` and `TELEGRAM_CHAT_ID=…`. (No-op if unset.)

### B5 · Cloudflare notifier Worker (optional, personal account only)
Only if you want the always-on notifier layer (`cloudflare-notifier/`). Use your **personal**
Cloudflare account — **never** the corporate `wsoon@cloudflare.com` one. Auth with a personal
API token (`export CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=…`) so you don't clobber a
corporate `wrangler login`. See `cloudflare-notifier/README.md`.

✅ **Phase B checkpoint:** a TradingView alert (or a manual test POST) shows up in the
**Incoming alerts** panel and opens a paper position; Telegram pings if configured.

---

## Run it on another machine (portability)

**You do NOT need Docker.** OpenD is a host-native desktop gateway that holds your moomoo
login and listens on `127.0.0.1:11111`; containerizing the app only adds host↔container
networking and a security footgun for a single-user local tool. A plain clone + venv is
simpler and is the supported path.

On the new machine (where you can safely enter your moomoo credentials):
```bash
git clone https://github.com/wilsonsfh/TradingSignalandHelper.git
cd TradingSignalandHelper
git checkout feature/event-driven-tradingview-bridge   # ← all current work is here, not main
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-moomoo.txt                 # app deps + moomoo SDK (pulls requirements.txt)
cp .env.example .env                                   # set BROKER=moomoo, TRD_ENV=SIMULATE,
                                                       # DATA_SOURCE=yfinance, MOOMOO_SECURITY_FIRM=FUTUSG
pytest -q                                              # expect 232 passed
```
Then follow **Phase A** (run OpenD, then `python scripts/check_opend.py`). `.env` is
git-ignored, so your credentials/secrets never leave that machine; SQLite state is created
locally on first run, so nothing else needs porting.

> ⚠️ **Branch gotcha:** `main` is intentionally still the pre-bridge code, so a plain
> `git clone` lands on old code — you must `git checkout feature/event-driven-tradingview-bridge`
> (or merge it to `main` first). The repo is public, so the clone needs no auth.

---

## Later — switching to REAL money (do not rush)

Only after Phase A + B are solid on paper, and after the two remaining code follow-ups
(startup reconciliation + dry-run replay) + your sign-off:
- Fund a real moomoo account; log OpenD into it.
- `.env`: `TRD_ENV=REAL`, `ALLOW_REAL_WEBHOOK=true`, small `MAX_NOTIONAL` + `MAX_DAILY_LOSS`, `ENFORCE_MARKET_HOURS=true`.
- TradingView alert body must include `"confirm": true`.
- The dashboard turns into the **LIVE MONEY ARMED** red state so you always know it's live.
Full detail: `docs/HANDOVER-live-trading.md` §Step 2.

## Gotchas (the things that actually bite)
- **OpenD must stay running** during any trading — if it exits, orders/quotes stop.
- **TradingView**: paid plan + 2FA required; ports 80/443 only; no IPv6; 3s timeout.
- **moomoo `security_firm`** in the SDK must match your entity, or `get_acc_list` fails.
- **Market data**: no realtime US quotes → enable free LV1 US data in the moomoo app.
- **Secrets**: never commit `.env`, tokens, or the webhook secret.
- **Cloudflare**: personal account only for this project.

