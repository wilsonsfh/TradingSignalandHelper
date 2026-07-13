# Self-host for your own cross-device use (Cloudflare Tunnel + Access)

This app is **paper-first and localhost-bound by design** — its dashboard/mock API is
**not authenticated** (any client that can reach the port can call trade routes). So do
**not** expose it directly to the public internet.

To reach *your own* instance from any device securely, put it behind a **Cloudflare
Tunnel** with a **Cloudflare Access** policy that allows **only you**. The app keeps
running on `127.0.0.1`; Cloudflare authenticates every request at the edge before it ever
reaches the app. No app code changes.

## Prerequisites

- A domain on your Cloudflare account (Tunnel public hostnames need a zone; `*.workers.dev` won't do).
- `cloudflared` installed: `brew install cloudflared`.
- The app running locally: `python cli.py web` (defaults to `127.0.0.1:5000`).

## 1. Create a named tunnel

```bash
cloudflared tunnel login                     # pick your domain
cloudflared tunnel create trading-helper     # note the Tunnel ID / creds file
```

## 2. Route a hostname to the local app

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL-ID>
credentials-file: /Users/<you>/.cloudflared/<TUNNEL-ID>.json
ingress:
  - hostname: trading.<YOUR-DOMAIN>
    service: http://127.0.0.1:5000
  - service: http_status:404
```

```bash
cloudflared tunnel route dns trading-helper trading.<YOUR-DOMAIN>
cloudflared tunnel run trading-helper        # keep this running (or install as a service)
```

Run it as a background service so it survives reboots:

```bash
sudo cloudflared service install
```

## 3. Lock it to only you (Zero Trust Access)

In the Zero Trust dashboard → **Access → Applications → Add → Self-hosted**:

- **Application domain:** `trading.<YOUR-DOMAIN>`
- **Policy:** `Allow` · Include → **Emails** → `<YOUR-EMAIL>` (add your device posture / WARP rule if you want).

Your account's existing **default-deny** already blocks everyone else, so this one Allow
policy = "only me, from any device, after Cloudflare login."

## 4. Use it

Open `https://trading.<YOUR-DOMAIN>` on any device → Cloudflare Access login → the dashboard.

## Caveats

- **Keep it in paper mode** (`BROKER=mock` or `TRD_ENV=SIMULATE`). The Access layer authenticates
  *you*; it does not make the app itself multi-user or safe for real-money automation.
- **Trading (not just viewing) needs OpenD** running on the same always-on host as the app.
- This is single-user (you). True multi-user public use would require real per-user auth + per-user
  broker credentials — a larger change this app isn't built for yet.
