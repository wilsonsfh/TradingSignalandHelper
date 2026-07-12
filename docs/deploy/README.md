# Deploying the TradingView → moomoo bridge

This runbook mirrors the infrastructure in Curteis Yang's "Building a TradingView
to moomoo Auto-Trading Bridge." It is **optional** and separate from the
SIMULATE/mock-testable application. Nothing here runs OpenD or an account during
development; follow it only when you deploy a real (paper) bridge.

> Safety: keep `TRD_ENV=SIMULATE`. The webhook is always blocked in REAL mode
> until the gated plan in `docs/superpowers/specs/2026-07-12-real-mode-enablement.md`
> is completed and explicitly approved.

## Two layers, and where to host each

| Layer | What it does | Where it runs | Scaffold |
|---|---|---|---|
| 1 — Notifier | Receive TradingView webhook → validate → log → **Telegram** + dashboard | Cloudflare Worker (serverless, always-on), personal account | `cloudflare-notifier/` |
| 2 — Executor | Actually place moomoo orders via **OpenD** (entry + TP + stop OCO) | A **persistent host** — cannot be a Worker | see options below |

Layer 1 gets you event-driven **signals + Telegram** today. Add Layer 2 when you want
the alert to also trade. Both sit under your **personal `wilsonsfh`** Cloudflare account
(never corporate — the danes-musings separation).

**Host options for Layer 2 (pick one):**

- **Local Mac + Cloudflare Tunnel** — fastest, zero cost, reuses the bridge you already
  have; runs while your Mac is on. See `cloudflare-tunnel/`.
- **Zo Computer (zo.computer)** — 24/7 personal cloud PC with native Telegram; always-on
  without a VM; paid, third-party.
- **VM (EC2/Lightsail)** — the Curteis-style always-on box; most control/ops. This runbook.

The bridge sends Telegram alerts itself (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`), so
Layer 2 notifies you even without Layer 1.

## Topology

```text
TradingView alert (Pine)
      │  POST /webhook  {action,symbol,side,quantity,tp,sl,key}
      ▼
Cloudflare (proxied DNS · WAF IP allow-list · rate limit · TLS)
      ▼
Origin host  ── Caddy (HTTPS, :443) ──► Flask bridge (127.0.0.1:5000)
                                              │
                                              ▼
                                        OpenD (127.0.0.1:11111) ──► moomoo
```

The bridge never talks to moomoo directly; it talks to OpenD over localhost, and
OpenD holds the authenticated session.

## Host choice

The bridge is a **stateful, part-time** service (US market hours only), which
changes the usual calculus:

| Option | Cost/mo (approx) | Notes |
|--------|------------------|-------|
| Lightsail 1 GB | ~$7 flat | Simplest: VPS + disk + static IP + transfer in one bundle. Cannot self-schedule, so you pay 24/7. |
| Scheduled EC2 `t3.micro` | ~$1.6 compute + ~$0.6 disk + Elastic IP | Cheapest: stopped instances bill no compute. Start/stop on a market-hours schedule. More moving parts. |
| Always-on EC2 | ~$7.6 + disk + IP | No reason to run while the market is closed 2/3 of the day. |
| Railway / stateless PaaS | — | Poor fit: always-on model, awkward persistent disk for `Device.dat`. |

Recommendation: **Lightsail** for simplicity, **scheduled EC2** to shave cost and
learn more AWS. The 512 MB tier is too small for OpenD + Flask + OS.

## Persistence

OpenD writes a `Device.dat` that stores device identity; without a persistent
disk you get a re-verification prompt every night. Keep it on a durable volume
(e.g. an 8 GB gp3 EBS volume that survives instance stop/start) and confirm
OpenD's data directory points at it.

## Market-hours scheduling (scheduled EC2)

- EventBridge Scheduler (or cron on a small always-on box) starts the instance
  ~15 min before the US open and stops it after the close, Mon–Fri.
- On boot, `systemd` starts OpenD → bridge → Caddy (order matters; the bridge
  needs OpenD, Caddy needs the bridge).
- Attach an Elastic IP so DNS keeps pointing at the box across restarts.

Example unit ordering (sketch — adapt paths):

```ini
# opend.service      → runs the OpenD CLI headless, logs in from env/secret
# bridge.service     → After=opend.service ; ExecStart=python cli.py web
# caddy.service      → After=bridge.service ; reverse-proxies :443 → 127.0.0.1:5000
```

## HTTPS (Caddy)

Caddy gets automatic TLS. Even behind Cloudflare you must keep origin **port 80**
reachable so the ACME/Let's-Encrypt HTTP challenge can complete; if you forget,
Cloudflare returns a 525 and HTTPS never comes up.

```caddyfile
your-bridge.example.com {
    reverse_proxy 127.0.0.1:5000
}
```

## Cloudflare (defence-in-depth)

- Proxied DNS + free TLS out of the box.
- **WAF custom rule** on the `/webhook` path: allow TradingView's four published
  webhook IPs, block everything else. Verify the current list in TradingView's
  docs before deploying:
  `52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7`.
- **Rate-limit rule** on `/webhook`: ~5 requests/min.
- SSL/TLS mode **Full** or **Full (strict)** so it matches Caddy's certificate.

App-layer equivalents exist as a backstop (`WEBHOOK_IP_ALLOWLIST`,
`WEBHOOK_RATE_PER_MIN`, `WEBHOOK_SIGNATURE_REQUIRED`) for when the app is not
behind Cloudflare. Note `X-Forwarded-For` is only trustworthy behind a proxy you
control; direct exposure should rely on `remote_addr`.

## Secrets

- `WEBHOOK_SECRET`: ≥32 random characters, delivered via the host's secret
  mechanism or a `chmod 600` `.env`. Never commit it.
- If `WEBHOOK_SIGNATURE_REQUIRED=true`, the sender must send
  `X-Signature: hex(HMAC_SHA256(raw_body, secret))`. TradingView cannot compute
  an HMAC over the body, so signature mode is for non-TradingView senders; for
  TradingView, the shared key + IP allow-list are the two layers.

## Deploy `.env` (example — no real secrets)

```dotenv
BROKER=moomoo
TRD_ENV=SIMULATE
DATA_SOURCE=yfinance
WATCHLIST=AAPL,MSFT,NVDA,SPY
OPEND_HOST=127.0.0.1
OPEND_PORT=11111
USE_BROKER_STOP_ORDER=true
WEBHOOK_ENABLED=true
WEBHOOK_SECRET=replace-with-32+-random-characters
WEBHOOK_RATE_PER_MIN=5
WEB_HOST=127.0.0.1
WEB_PORT=5000
```

## Go-live checklist

1. OpenD is running and logged in (GUI locally to test, CLI headless on the box).
2. `Device.dat` lives on the persistent disk; no nightly re-verification.
3. A test SIMULATE alert flows end-to-end: TradingView → Cloudflare → Caddy →
   bridge → OpenD → moomoo paper, and appears in `/api/events`.
4. WAF allow-list + rate-limit rules are active on `/webhook`.
5. Schedule starts/stops the instance around US market hours.
6. Clean shutdown: stopping the service cancels nothing silently — check open
   positions and resting orders first.
```
