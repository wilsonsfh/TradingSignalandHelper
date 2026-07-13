# cloudflare-tunnel — front the LOCAL bridge (Layer 2)

Layer 2 is the part that actually **trades** (Flask bridge + OpenD → moomoo). It cannot
be a Worker (OpenD is a persistent local gateway). This exposes the local bridge at a
stable HTTPS hostname on your **personal** Cloudflare account, protected by Access — so
TradingView (or the `trading-signal-notifier` Worker) can reach `/webhook`, and only you can
open the dashboard.

## Why a tunnel (vs opening a port)

- No inbound port-forwarding / public IP on your Mac; `cloudflared` dials out.
- Stable hostname + Cloudflare TLS, WAF, and **Access** in front of a laptop app.
- Same account model as danes-musings — **personal `wilsonsfh`, never corporate.**

## Setup (one-time, browser auth to the PERSONAL account)

```bash
brew install cloudflared
cloudflared tunnel login                 # browser: pick a zone in your personal account
cloudflared tunnel create signal-bridge  # prints TUNNEL_ID + ~/.cloudflared/<id>.json
cloudflared tunnel route dns signal-bridge signal-bridge.<your-domain>
cp config.example.yml config.yml         # fill TUNNEL_ID, credentials-file, hostname
```

Protect it with Access: Zero Trust → Access → Applications → add a self-hosted app for
`signal-bridge.<your-domain>` with a policy allowing only your email. Then add a
**bypass** (or service-token) policy scoped to the `/webhook` path so TradingView can
POST without an interactive login — the shared secret + IP allow-list remain its auth.

## Run

```bash
# terminal 1 — the bridge (BROKER=moomoo, TRD_ENV=SIMULATE, DATA_SOURCE=yfinance in .env)
python cli.py web
# terminal 2 — the tunnel
./cloudflare-tunnel/run-tunnel.sh
```

Point TradingView (or the notifier Worker) at `https://signal-bridge.<your-domain>/webhook`.
Keep both running during US market hours; OpenD must stay logged in.

## Alternatives to a laptop tunnel

- **Zo Computer (zo.computer):** a 24/7 personal cloud PC (native Telegram). Run the bridge
  + OpenD there so it survives your Mac sleeping; still front it with this tunnel or Zo's
  own hosting. Best "always-on without a VM."
- **VM (EC2/Lightsail, à la Curteis):** see `docs/deploy/README.md`. Most control, most ops.

The bridge already sends **Telegram** alerts itself (set `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` in `.env`), independent of the Worker — so even a pure local+tunnel
setup notifies you on opens, closes, and auto-exits.
