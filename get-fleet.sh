#!/usr/bin/env bash
# ===========================================================================
# THE CLOUD ONE-LINER — a fresh Ubuntu server to a running fleet, one command.
#
#   curl -fsSL https://raw.githubusercontent.com/reda-baqechame/self-learning-24.7-agent/main/get-fleet.sh | sudo bash
#
# What it does, in order, and why each step refuses to be skipped:
#   1. installs git, clones the repository to a staging directory
#   2. hands off to setup-vps.sh — the same audited bootstrap that creates
#      the unprivileged `agent` user, installs the systemd units WITHOUT
#      enabling them, and runs the full offline test suite as that user.
#      A server that has not passed the suite has not installed the fleet;
#      it has copied some files.
#
# What it deliberately does NOT do:
#   * it does not start anything — your keys go in /home/agent/agent.env
#     first (set spend caps at every provider BEFORE the first call), then
#     `loop.py check` must pass, then YOU enable the services
#   * it does not open a port to the internet. The panel binds localhost;
#     reach it over Tailscale or a Cloudflare Tunnel with UI_TOKEN set.
#     deploy/VPS.md walks every step, including the backup cron and the
#     round-trip that ends with the pause button pressed once, on purpose,
#     so you know the interrupt works before you depend on it.
#
# Prefer containers? Skip this script entirely:
#   git clone <repo> && cd <dir> && cp agent.env.example agent.env
#   # put keys in agent.env, then:
#   docker compose up -d        # sandboxed, resource-braked, healthchecked
# ===========================================================================

set -euo pipefail

REPO="https://github.com/reda-baqechame/self-learning-24.7-agent.git"
STAGE="/opt/expert-fleet-src"

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root:  curl -fsSL .../get-fleet.sh | sudo bash" >&2
    exit 1
fi

echo "== git =="
command -v git >/dev/null 2>&1 || { apt-get update -qq; apt-get install -y -qq git; }

echo "== fetch =="
if [ -d "$STAGE/.git" ]; then
    git -C "$STAGE" pull --ff-only
else
    git clone --depth 1 "$REPO" "$STAGE"
fi

echo "== bootstrap (setup-vps.sh: user, deps, units, full test suite) =="
cd "$STAGE"
bash setup-vps.sh
