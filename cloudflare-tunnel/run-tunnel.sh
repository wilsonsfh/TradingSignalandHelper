#!/usr/bin/env bash
# Run the Cloudflare Tunnel that fronts the local bridge (python cli.py web on :5000).
#
# One-time setup (browser auth to your PERSONAL wilsonsfh account — NOT corporate):
#   brew install cloudflared
#   cloudflared tunnel login                 # browser: choose a zone in the personal account
#   cloudflared tunnel create signal-bridge  # prints a TUNNEL_ID + writes ~/.cloudflared/<id>.json
#   cloudflared tunnel route dns signal-bridge signal-bridge.<your-domain>
#   cp config.example.yml config.yml         # fill TUNNEL_ID, credentials-file, hostname
#
# Then run the bridge and this tunnel side by side:
#   (terminal 1)  python cli.py web
#   (terminal 2)  ./cloudflare-tunnel/run-tunnel.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$DIR/config.yml" ]; then
  echo "Missing $DIR/config.yml — copy config.example.yml and fill it in first." >&2
  exit 1
fi
exec cloudflared tunnel --config "$DIR/config.yml" run
