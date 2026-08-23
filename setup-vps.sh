#!/usr/bin/env bash
# One-shot VPS bootstrap (Ubuntu 24.04). Run as root FROM THIS DIRECTORY:
#   sudo bash setup-vps.sh
# Creates the unprivileged user, installs dependencies, copies the agent,
# installs the systemd units, and runs the offline test suite as the agent
# user. It does NOT enable the services — you enable them after `loop.py
# check` passes with your keys in place.

set -euo pipefail

echo "== packages =="
apt-get update -qq
apt-get install -y -qq python3 python3-pip ffmpeg yt-dlp pandoc zip

echo "== user =="
id -u agent >/dev/null 2>&1 || adduser --disabled-password --gecos "" agent
sudo -u agent pip install --break-system-packages --quiet pymupdf

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
cd /home/agent/agent && sudo -u agent python3 tests/run_all.py

cat <<'EOF'

Bootstrap complete. Remaining manual steps:
  1. Put your API keys in /home/agent/agent.env  (spend caps first!)
  2. cd /home/agent/agent && set -a && . /home/agent/agent.env && set +a \
       && python3 loop.py check          # every role must say OK
  3. systemctl enable --now agent agent-inbox.timer
  4. Drop material into /home/agent/agent/inbox/ and walk away.
     Check blocked.md and gaps.md daily for the first week.
EOF
