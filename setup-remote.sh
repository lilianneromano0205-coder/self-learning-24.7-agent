#!/usr/bin/env bash
# Reach your Expert Fleet from anywhere — phone, laptop, any network — with a
# private HTTPS URL and no open ports. Run on the VPS as root AFTER
# setup-vps.sh:   sudo bash setup-remote.sh
#
# Uses Tailscale: a private network between your devices. The panel stays
# bound to localhost; Tailscale serves it over HTTPS only to your own devices.
# Nothing is exposed to the public internet — the safest remote-access shape
# for an agent that can run commands and spend money.

set -euo pipefail

echo "== installing tailscale =="
curl -fsSL https://tailscale.com/install.sh | sh

echo "== enabling the control panel service =="
systemctl enable --now agent-ui

cat <<'EOF'

Next, three steps you must do yourself (they need your accounts):

1. Connect this server to your private network:
     sudo tailscale up
   Follow the printed link and log in (Google/GitHub/email — free tier is fine).

2. Publish the panel privately over HTTPS:
     sudo tailscale serve --bg 7777
   It prints a URL like https://your-vps.tailXXXX.ts.net — that is your
   platform address, reachable from any device on your tailnet.

3. Install Tailscale on your phone and laptop (App Store / Play Store /
   tailscale.com/download), log in with the SAME account, and open that URL.
   Your fleet is now with you anywhere.

Optional extras:
  * `tailscale funnel 7777` would expose it to the PUBLIC internet — only do
    this if you set UI_TOKEN in /home/agent/agent.env first, and prefer not to.
  * Prefer your own domain instead of Tailscale? Put Caddy in front:
      caddy reverse-proxy --from agents.yourdomain.com --to 127.0.0.1:7777
    (automatic HTTPS) and set UI_TOKEN in agent.env so the API requires it.
EOF
