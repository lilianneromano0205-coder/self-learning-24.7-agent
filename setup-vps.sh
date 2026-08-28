#!/usr/bin/env bash
# One-shot VPS bootstrap (Ubuntu 24.04). Run as root FROM THIS DIRECTORY:
#   sudo bash setup-vps.sh
# Creates the unprivileged user, installs dependencies, copies the agent,
# installs the systemd units, and runs the offline test suite as the agent
# user. It does NOT enable the services — you enable them after `loop.py
# check` passes with your keys in place.

set -euo pipefail

# DROPPING PRIVILEGES WITHOUT DEPENDING ON `sudo`.
#
# This script runs as root and used `sudo -u agent ...` to step down. A
# deployment rehearsal on a fresh Ubuntu 26.04 machine aborted at that exact
# line with "sudo: command not found": minimal images do not ship sudo, and
# `set -e` then killed the run BEFORE the files were copied, the units were
# installed, or the acceptance suite was executed — leaving a half-built
# machine that looked provisioned and had nothing in /home/agent/agent.
#
# Hetzner's stock image does include sudo, so this would probably have
# worked. "Probably" is not the standard for the one script that stands
# between an owner and a working fleet. `runuser` ships with util-linux on
# every Linux that exists and is the correct root-side tool for this; su is
# the fallback, and sudo is never required.
as_agent() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u agent -- "$@"
    else
        su agent -c "$(printf '%q ' "$@")"
    fi
}

echo "== packages =="
apt-get update -qq
# `python-is-python3` IS NOT OPTIONAL, and its absence was invisible to
# every layer of verification this project owns.
#
# Ubuntu ships `python3` and NO `python`. Gates, done-checks and runbook
# steps shell out to `python ...`, which on a bare server returns exit 127
# with "/bin/sh: 1: python: not found" — so the acceptance suite THIS SCRIPT
# RUNS AS ITS FINAL GATE fails five tests and the install aborts on a
# freshly bought machine.
#
# It survived 119 tests, 56 mutations and six-platform CI because every one
# of those environments happens to provide `python`: a developer's Windows
# box has it, and GitHub's setup-python action creates it. Only a bare
# Ubuntu server does not — which is the one environment that was never
# tested until a throwaway container was pointed at it. Measured: without
# this package 5 tests fail on 24.04 and 26.04 alike; with it, 116 pass and
# 0 fail on Ubuntu 26.04 / Python 3.14.4.
apt-get install -y -qq python3 python3-pip python-is-python3 \
                      ffmpeg yt-dlp pandoc zip

echo "== user =="
id -u agent >/dev/null 2>&1 || adduser --disabled-password --gecos "" agent
as_agent pip install --break-system-packages --quiet pymupdf

echo "== files =="
mkdir -p /home/agent/agent
cp -r ./* /home/agent/agent/
chown -R agent:agent /home/agent/agent

if [ ! -f /home/agent/agent.env ]; then
  cat > /home/agent/agent.env <<'EOF'
# Fill these in, then: python3 /home/agent/agent/loop.py check --root /home/agent/agent
# SET SPEND CAPS AT EVERY PROVIDER BEFORE FIRST USE.
DEEPSEEK_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
EOF
  chown agent:agent /home/agent/agent.env
  chmod 600 /home/agent/agent.env
  echo "wrote /home/agent/agent.env — fill in your keys"
fi

echo "== systemd units (installed, not enabled) =="
cp /home/agent/agent/agent.service /etc/systemd/system/
cp /home/agent/agent/agent-inbox.service /etc/systemd/system/
cp /home/agent/agent/agent-inbox.timer /etc/systemd/system/
cp /home/agent/agent/agent-ui.service /etc/systemd/system/
systemctl daemon-reload

echo "== offline acceptance tests (as agent) =="
cd /home/agent/agent && as_agent python3 tests/run_all.py

cat <<'EOF'

Bootstrap complete. Remaining manual steps:
  1. Put your API keys in /home/agent/agent.env  (spend caps first!)
  2. cd /home/agent/agent && set -a && . /home/agent/agent.env && set +a \
       && python3 loop.py check          # every role must say OK
  3. systemctl enable --now agent agent-inbox.timer
  4. Drop material into /home/agent/agent/inbox/ and walk away.
     Check blocked.md and gaps.md daily for the first week.
EOF
