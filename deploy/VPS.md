# Hosting the fleet on a VPS — always on, reachable from anywhere

The faithful deployment: a small Linux server runs the whole platform
exactly as it runs locally — loop, panel, sandboxes, memory, inbox —
24/7, for about the price of a coffee a month. Work never stops unless
the owner presses the interrupt button in a cockpit; closing the laptop
changes nothing, because nothing runs on the laptop.

Everything below assembles **shipped, tested parts** (`agent.service`,
`bootstrap.py`, `backup.py`, the panel's token guard). Honest label: the
parts are tested; this exact assembly's first live run is its first real
test — run the verification step at the end before trusting it.

**The short path:** steps 1–3 below are automated by one line on a fresh
Ubuntu server — it clones the repository and runs `setup-vps.sh`, which
creates the user, installs the units *without enabling them*, and runs the
full test suite on the server before anything may start:

```bash
curl -fsSL https://raw.githubusercontent.com/reda-baqechame/self-learning-24.7-agent/main/get-fleet.sh | sudo bash
```

Then resume at step 4 (keys, `loop.py check`, enable). The long form below
remains the reference for what the short path did and why.

## 0. What you need

- A VPS: 2 vCPU / 2–4 GB RAM / 40 GB disk (≈ $4–6/month at Hetzner,
  DigitalOcean, etc.), Ubuntu 24.04 or similar.
- Your model key(s) — one OpenRouter key is enough.
- Optionally: an S3-compatible bucket (Cloudflare R2 / Backblaze B2) for
  off-site snapshots.

## 1. Provision (run once, as root)

```bash
apt update && apt install -y python3 python3-venv git docker.io
adduser --disabled-password --gecos "" agent
usermod -aG docker agent
```

## 2. Install the platform (as the `agent` user)

```bash
su - agent
git clone https://github.com/reda-baqechame/self-learning-24.7-agent.git agent
cd agent && python3 bootstrap.py --offline --no-panel
python3 bootstrap.py --key OPENROUTER_API_KEY=paste-your-key-here
python3 loop.py check     # every role must say OK before going further
```

Migrating an existing fleet instead of starting fresh? Copy your
`experts/`, `packs/`, `org/`, `commons/` directories (or
`backup.py pull` a snapshot) into place before `loop.py check` — an
expert IS a directory, so the move is a copy.

In `settings.toml`, set `sandbox = "docker"` — on a dedicated VPS there
is no reason to run model-authored commands on the host.

## 3. Run forever (systemd — as root)

The loop, from the shipped hardened unit:

```bash
cp /home/agent/agent/agent.service /etc/systemd/system/agent.service
systemctl daemon-reload && systemctl enable --now agent
```

The panel, a second unit (`/etc/systemd/system/panel.service`):

```ini
[Unit]
Description=Expert Fleet control panel
After=network-online.target

[Service]
Type=simple
User=agent
WorkingDirectory=/home/agent/agent
EnvironmentFile=/home/agent/agent/agent.env
ExecStart=/usr/bin/python3 /home/agent/agent/ui.py --home /home/agent/agent --host 127.0.0.1 --port 7777
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/agent/agent

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now panel
```

Both services restart on crash and on reboot. The fleet now lives
whether or not any human is connected.

## 4. Reach it from anywhere — phone included

**Never expose port 7777 to the internet.** Two good doors:

- **Tailscale** (simplest): `curl -fsSL https://tailscale.com/install.sh | sh && tailscale up`
  on the VPS, install the Tailscale app on your devices, open
  `http://<vps-tailscale-name>:7777`. Private network, zero config.
- **Cloudflare Tunnel + Zero Trust** (no client app needed): run
  `cloudflared` pointing at `localhost:7777`, put an Access policy in
  front. See `deploy/README.md` §access for the same rule stated for
  containers.

Either way, set `UI_TOKEN` in `agent.env` — the panel requires it the
moment it is reachable beyond localhost. The mobile layout is built in;
the cockpit's **⏸ interrupt** button is the only thing that stops a
pursuit, and it stops it honestly: the contract moves to `blocked` with
the reason on the ledger, resumable at any time.

## 5. Survive anything (off-site snapshots)

```bash
# as the agent user — crontab -e
17 3 * * * cd /home/agent/agent && /usr/bin/python3 backup.py create --out /home/agent/backups && /usr/bin/python3 backup.py push >> logs/backup.log 2>&1
```

`backup.py push` targets the S3-compatible bucket named in `agent.env`
(R2/B2 keys — see `backup.py --help`). Server dies → new VPS → steps
1–3 → `backup.py pull` → the fleet wakes with every memory, runbook,
contract and ledger intact.

## 6. Updates

```bash
su - agent && cd agent
git pull && python3 tests/run_all.py     # green before restart, always
sudo systemctl restart agent panel
```

## 7. Verify the deployment (the launch gate, on the server)

```bash
python3 doctor.py            # everything imports, fleet healthy
python3 preflight.py         # production gate: expect READY
python3 loop.py check        # live request per role: all OK
```

Then open the panel from your phone, start a small goal with a grader,
watch the cockpit, press ⏸ once to see the interrupt land on the
ledger, resume it, and let it finish VERIFIED. That round trip is the
deployment proof.
