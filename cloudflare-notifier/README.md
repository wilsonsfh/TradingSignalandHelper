# trading-signal-notifier — TradingView → Telegram (Cloudflare Worker)

The always-on **edge front** for TradingSignalandHelper. TradingView fires a chart-event
alert → this Worker authenticates it, records it (KV), shows it on a small dashboard, and
pushes a **Telegram** message. Deployed under the **wilsonsfh** Cloudflare account via
Wrangler — the same way `danes-musings` is.

## What it is / is NOT

- ✅ Receives TradingView webhooks, validates them, logs them, and notifies you on Telegram.
- ✅ Honors the alert's `tp`/`sl`/`quantity` and the same schema as the Python bridge.
- ❌ Does **not** place moomoo orders. Live execution needs OpenD — a persistent local
  gateway — which a Worker (stateless V8 isolate) cannot run. That stays on a persistent host.

## Architecture (two layers, honest)

```text
                 ┌── Layer 1: notifier (THIS Worker, always-on, serverless) ──┐
TradingView ──►  │  /webhook → validate → KV event log → Telegram push        │ ──► your phone
   alert         │  / , /api/events  (dashboard, protect with Access)         │
                 └────────────────────────────────────────────────────────────┘
                 ┌── Layer 2: executor (persistent host — NOT a Worker) ───────┐
                 │  Python bridge + OpenD → moomoo paper/live orders (OCO)      │
                 │  runs on: your Mac (local) · a VM (EC2/Lightsail, à la       │
                 │  Curteis) · or a Zo Computer (zo.computer, 24/7 cloud PC)    │
                 └────────────────────────────────────────────────────────────┘
```

Start with Layer 1 (this Worker) to get **event-driven signals + Telegram** live today.
Add Layer 2 when you want the alert to also *trade* — then have TradingView (or this
Worker) also POST to the local bridge via a Cloudflare Tunnel.

## Auth model (same account as danes-musings)

- **`wrangler login`** in a browser authenticates the wilsonsfh Cloudflare account. The
  Worker lands at `https://trading-signal-notifier.<subdomain>.workers.dev`.
- **`/webhook`** is the machine path: authenticated by a ≥32-char shared `key` in the body
  (constant-time checked), plus an optional HMAC `X-Signature` and optional TradingView
  IP allow-list. Keep interactive Access **off** this path so TradingView can reach it.
- **`/` and `/api/events`** are the human path: turn on one-click **Cloudflare Access**
  (Workers & Pages → your Worker → Settings → Domains & Routes → *Enable Cloudflare Access*).
  Then only your browser SSO can read the dashboard — this is the "open browser to
  authenticate" step.

## ⚠️ Use your PERSONAL account, not the corporate one

This is a personal project. It must deploy to your **personal `wilsonsfh` Cloudflare
account** (the one with the `wilsonsfh.workers.dev` subdomain, like danes-musings) —
**never** the corporate `wsoon@cloudflare.com` account. On a work Mac, `wrangler` is
usually already logged into the corporate account, so **don't** rely on the ambient
login. Two clean ways to target the personal account without clobbering the corporate one:

**Option A — personal API token (recommended; leaves corporate login untouched):**
Personal dashboard → *Manage Account → API Tokens* → create a token with *Workers Scripts:Edit*
+ *Workers KV Storage:Edit* for the personal account, then:

```bash
export CLOUDFLARE_API_TOKEN=<personal-account-token>
export CLOUDFLARE_ACCOUNT_ID=<personal-account-id>
```

**Option B — switch the browser login** (simpler, but replaces the corporate OAuth session):
`npx wrangler logout && npx wrangler login`  ← browser: sign in as the personal account.

## Deploy (what YOU do — I pre-built + typechecked the code)

Prereqs: Node 18+, a Telegram bot (below), and the personal-account auth above.

```bash
cd cloudflare-notifier
npm install
# generate a strong shared secret (also paste this into the TradingView alert `key`):
openssl rand -hex 24
npx wrangler kv namespace create EVENTS   # paste the printed id into wrangler.jsonc kv_namespaces[0].id
npx wrangler secret put WEBHOOK_SECRET     # paste the openssl value
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_CHAT_ID
npm run deploy
```

Then in the personal dashboard, enable Cloudflare Access on the Worker's `workers.dev`
URL to protect `/` and `/api/events` (this is the "open browser to authenticate" step
for the human dashboard).

## Telegram bot (one-time)

1. In Telegram, message **@BotFather** → `/newbot` → get the **bot token**.
2. Message your new bot once (say "hi"), then open
   `https://api.telegram.org/bot<token>/getUpdates` and read `result[].message.chat.id`
   → that's your **chat_id**. (Set both as Wrangler secrets above.)

## TradingView alert (the signal source)

Create an alert whose **Webhook URL** is `https://trading-signal-notifier.<subdomain>.workers.dev/webhook`
and whose message is JSON (Pine can build this):

```json
{
  "event_id": "{{timenow}}-{{ticker}}",
  "timestamp": "{{timenow}}",
  "action": "open",
  "side": "buy",
  "symbol": "{{ticker}}",
  "quantity": 4,
  "tp": 210.00,
  "sl": 190.00,
  "key": "your-32+char-WEBHOOK_SECRET"
}
```

Requires a TradingView plan that allows webhook alerts.

## About "zo automations" (zo.computer)

Zo Computer is a 24/7 personal **cloud computer** with a native **Telegram** channel. Two ways it fits:

- **Simplest Telegram-only:** skip the bot wiring and let Zo relay alerts to Telegram.
- **Layer-2 host:** because Zo is a persistent cloud PC you control, it can host the Python
  bridge + OpenD (the part Workers can't run) — its own testimonial is a trader who runs
  strategy infra on it. This is the turnkey alternative to a VM/EC2 for live trading.

Recommendation: keep this Worker as the Cloudflare-native front (matches danes-musings), and
choose **Zo** *or* **local+Tunnel** *or* **a VM** for Layer 2 when you want live moomoo trades.

## Local dev

```bash
npm run dev            # wrangler dev; put secrets in .dev.vars (git-ignored)
```
