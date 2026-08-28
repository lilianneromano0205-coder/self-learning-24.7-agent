#!/usr/bin/env bash
# ===========================================================================
# THE DESKTOP INSTALLER (Linux / macOS) — the repository to a `fleet`
# command, one line, your own API keys:
#
#   curl -fsSL https://raw.githubusercontent.com/reda-baqechame/self-learning-24.7-agent/main/install.sh | bash
#
# What you get: the fleet cloned to ~/ExpertFleet (override with FLEET_DIR),
# an agent.env ready for your keys, and ~/.local/bin/fleet — a launcher that
# PROVES the wiring before it starts anything: bootstrap first, then the
# provider check, and only then the panel plus the loop. A launcher that
# starts a half-wired fleet teaches you the panel is lying; this one names
# what is missing and stops.
#
# What this deliberately does not do: no root, no package installs (the
# platform is Python stdlib only), no keys asked for or printed, nothing
# started — the first launch is yours:  fleet
#
# NOTE: launched locally the agents execute commands as YOUR user on THIS
# machine. Good for driving it yourself; for unattended 24/7 use the cloud
# path (get-fleet.sh / docker compose) or settings.toml sandbox = "docker".
# ===========================================================================

set -euo pipefail

REPO="https://github.com/reda-baqechame/self-learning-24.7-agent.git"
DEST="${FLEET_DIR:-$HOME/ExpertFleet}"
BIN="$HOME/.local/bin"

# -- prerequisites: name what is missing, then stop -------------------------
command -v git >/dev/null 2>&1 || { echo "git is required (apt install git / brew install git)" >&2; exit 1; }
PYBIN="$(command -v python3 || true)"
[ -n "$PYBIN" ] || { echo "python3 (3.11+) is required" >&2; exit 1; }
"$PYBIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || { echo "python3 3.11+ required, found $("$PYBIN" -V)" >&2; exit 1; }

# -- fetch: clone once, fast-forward thereafter (rerun = update) ------------
if [ -d "$DEST/.git" ]; then
    echo "== updating $DEST =="
    git -C "$DEST" pull --ff-only
else
    echo "== cloning to $DEST =="
    git clone --depth 1 "$REPO" "$DEST"
fi

# -- keys file: created once, never touched again if it exists --------------
if [ ! -f "$DEST/agent.env" ]; then
    cp "$DEST/agent.env.example" "$DEST/agent.env"
    chmod 600 "$DEST/agent.env"
    echo "wrote $DEST/agent.env — put your API keys there (SET SPEND CAPS AT THE PROVIDER FIRST)"
fi

# -- the `fleet` command: prove, then run -----------------------------------
mkdir -p "$BIN"
cat > "$BIN/fleet" <<WRAP
#!/usr/bin/env bash
# Expert Fleet launcher — written by install.sh; rerunning install.sh renews it.
#   fleet          prove the wiring, start the panel and the loop
#   fleet doctor   the full health verdict, nothing started
#   fleet check    provider round-trips only
set -eu
cd "$DEST"
case "\${1:-up}" in
  doctor) exec python3 doctor.py ;;
  check)  exec python3 loop.py check ;;
  up)
    python3 bootstrap.py --no-panel || { echo; echo "do the numbered steps above, then rerun: fleet"; exit 1; }
    python3 loop.py check || { echo; echo "fix the failing providers (keys go in agent.env), then rerun: fleet"; exit 1; }
    echo "all providers OK — panel on http://127.0.0.1:7777 ; Ctrl+C stops the loop, state survives"
    python3 ui.py &
    PANEL=\$!
    trap 'kill "\$PANEL" 2>/dev/null || true' EXIT
    exec python3 loop.py run
    ;;
  *) echo "usage: fleet [doctor|check]" >&2; exit 2 ;;
esac
WRAP
chmod 0755 "$BIN/fleet"

# -- a menu entry, where menus exist ----------------------------------------
if [ -d "$HOME/.local/share/applications" ]; then
    cat > "$HOME/.local/share/applications/expert-fleet.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Expert Fleet
Comment=The panel and the loop, wiring proven first
Exec=$BIN/fleet
Terminal=true
Categories=Development;
DESK
fi

echo
echo "Installed. Next:"
echo "  1. put a key in $DEST/agent.env   (any provider; one key is enough)"
echo "     or:  cd $DEST && python3 bootstrap.py --key sk-..."
echo "  2. run:  fleet        (add ~/.local/bin to PATH if your shell lacks it)"
