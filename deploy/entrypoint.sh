#!/bin/sh
# ===========================================================================
# CONTAINER ENTRYPOINT — restore, run, snapshot.   (CLOUDFLARE.md §6 item 3)
#
# The fact this file exists to answer, in Cloudflare's own words as quoted in
# CLOUDFLARE.md §3.2: "All disk is ephemeral. When a Container instance goes
# to sleep, the next time it is started, it will have a fresh disk as defined
# by its container image."  For a platform whose whole architecture is "an
# expert IS a directory" — identity, courses, skills, failures, missions,
# state.json — a fresh disk means the fleet forgets everything it studied.
# That is the one outcome this platform exists to prevent.
#
# The fix that looks obvious and is WRONG is mounting R2 with FUSE. §3.2
# spells it out: loop.py's task mutex is O_CREAT|O_EXCL and every ledger
# write is tmp+fsync+os.replace, and NEITHER is atomic on object storage.
# Putting state.json on R2-FUSE silently reintroduces U15 — two loops running
# one task — across a network filesystem where it is far harder to see. So
# the split this script implements is:
#
#     container local disk  =  working state  (POSIX, fast, what the tests cover)
#     R2                    =  durable memory, reached ONLY by backup.py push/pull
#
# R2 IS NEVER MOUNTED HERE. If you find yourself adding a mount, read §3.2
# again — that reasoning is why this file is shaped the way it is.
#
# Lifecycle:
#   boot      pull the newest archive, verify it, restore it, THEN start work
#   run       the workload (the panel, or a one-shot drain for a DO alarm)
#   snapshot  backup.py create + verify + push, on an interval AND on SIGTERM
#   stop      because Cloudflare signals before it stops the container
#
# Every environment variable is documented in deploy/README.md, including the
# data-loss window this design leaves open. Read that before you deploy: the
# window is real, it is bounded by FLEET_SNAPSHOT_INTERVAL_S, and pretending
# otherwise would be exactly the false green this repository refuses.
# ===========================================================================

set -eu

# --------------------------------------------------------------- exit codes
# Borrowed from sysexits.h so an operator (or a Worker reading the container's
# exit status) can tell "I have no state to restore" apart from "your archive
# is corrupt" without parsing logs.
EX_USAGE=64        # this script was configured impossibly
EX_DATAERR=65      # the newest archive is damaged — we refuse to run past it
EX_UNAVAILABLE=69  # the store is configured but unreachable
EX_CANTCREAT=73    # another entrypoint already owns this state directory
EX_CONFIG=78       # durable state was REQUIRED and is not configured

# ------------------------------------------------------------------ config
_self=$(cd "$(dirname "$0")" && pwd)
FLEET_CODE=${FLEET_CODE:-$(dirname "$_self")}
FLEET_HOME=${FLEET_HOME:-$FLEET_CODE}

FLEET_MODE=${FLEET_MODE:-serve}                 # serve | drain
FLEET_UI_HOST=${FLEET_UI_HOST:-0.0.0.0}
FLEET_UI_PORT=${FLEET_UI_PORT:-7777}

# The spool MUST live outside the fleet home. backup.py's _walk() skips
# __pycache__/.git/node_modules/tmp/demo-run and nothing else — an archive
# written inside the home is therefore archived by the NEXT snapshot, which
# on a 2 GB ephemeral disk compounds until the disk is full and the fleet
# stops being able to save itself at all.
FLEET_SPOOL=${FLEET_SPOOL:-/tmp/fleet-snapshots}
FLEET_STAGING=${FLEET_STAGING:-/tmp/fleet-restore}

FLEET_SNAPSHOT_INTERVAL_S=${FLEET_SNAPSHOT_INTERVAL_S:-900}
FLEET_SNAPSHOT_WAIT_S=${FLEET_SNAPSHOT_WAIT_S:-120}
FLEET_DRAIN_GRACE_S=${FLEET_DRAIN_GRACE_S:-120}
FLEET_KEEP_LOCAL=${FLEET_KEEP_LOCAL:-3}
FLEET_WITH_LOGS=${FLEET_WITH_LOGS:-0}

FLEET_STORE=${FLEET_STORE:-auto}                # auto | r2 | dir | none
FLEET_STORE_DIR=${FLEET_STORE_DIR:-}
FLEET_R2_ENDPOINT=${FLEET_R2_ENDPOINT:-}
FLEET_R2_BUCKET=${FLEET_R2_BUCKET:-}
FLEET_R2_PREFIX=${FLEET_R2_PREFIX:-}
FLEET_R2_REGION=${FLEET_R2_REGION:-auto}

FLEET_RESTORE_KEY=${FLEET_RESTORE_KEY:-}
FLEET_REQUIRE_STATE=${FLEET_REQUIRE_STATE:-0}
FLEET_ALLOW_DEGRADED_START=${FLEET_ALLOW_DEGRADED_START:-0}
FLEET_HEARTBEAT_S=${FLEET_HEARTBEAT_S:-30}
FLEET_LOCK_STALE_S=${FLEET_LOCK_STALE_S:-180}

# Container logs are the only forensics left once an instance is gone, and a
# python process whose stdout is a pipe buffers 8 KB of them by default — so a
# panel that dies takes its own last words with it. The image sets this too;
# it is set here as well so the script behaves the same run outside the image.
export PYTHONUNBUFFERED=1

# The label ends up in the archive FILENAME, which is the R2 object key. Two
# containers snapshotting in the same second would otherwise write the same
# key and one would silently overwrite the other's memory. Instance-stamped
# keys mean a push can never destroy an archive it did not create.
FLEET_INSTANCE=${FLEET_INSTANCE:-$( (hostname 2>/dev/null || echo container) | tr -cd 'A-Za-z0-9-' | cut -c1-24 )}
[ -n "$FLEET_INSTANCE" ] || FLEET_INSTANCE=container

# The boot lock lives INSIDE the state directory, because the thing it
# protects is the state directory — a bind-mounted home shared by two
# containers is a real operator mistake and this is where it is visible. It
# sits under tmp/ because backup.py's _walk() already skips a directory named
# `tmp`, so the lock never travels inside an archive: a lock restored into a
# fresh container would be a lock held by a process that does not exist.
LOCK_DIR="$FLEET_HOME/tmp/entrypoint-lock"
SNAP_LOCK="$FLEET_SPOOL/.snapshot-lock"
MAIN_PID=$$          # background loops check this to notice they are orphans

STORE=none
WORKLOAD_KIND=other   # `panel` only when WE started ui.py, since only then is
                      # POST /api/shutdown the right way to stop it
WORKLOAD_PID=""
TIMER_PID=""
HEARTBEAT_PID=""
USED_SETSID=0
SHUTTING_DOWN=0
HOLD_LOCK=0

# ------------------------------------------------------------------ logging
# One prefix, one clock. Container logs are the only forensics you get after
# an instance is gone, so anything this script decides, it says out loud.
_stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log()  { echo "[entrypoint $(_stamp)] $*"; }
warn() { echo "[entrypoint $(_stamp)] WARNING: $*" >&2; }
die()  { echo "[entrypoint $(_stamp)] FATAL: $1" >&2; exit "${2:-1}"; }

banner() {
    echo "==========================================================================" >&2
    for _l in "$@"; do echo "  $_l" >&2; done
    echo "==========================================================================" >&2
}

# ------------------------------------------------------------------ python
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "FATAL: no python interpreter on PATH" >&2; exit 64; fi
BACKUP="$FLEET_CODE/backup.py"

# ------------------------------------------------------------ sanity checks
[ -f "$BACKUP" ] || die "$BACKUP not found — FLEET_CODE=$FLEET_CODE is not the code directory" "$EX_USAGE"

case "$FLEET_MODE" in
    serve|drain) ;;
    *) die "FLEET_MODE must be serve or drain, not '$FLEET_MODE'" "$EX_USAGE" ;;
esac

case "$FLEET_SPOOL" in
    "$FLEET_HOME"|"$FLEET_HOME"/*)
        die "FLEET_SPOOL ($FLEET_SPOOL) is inside FLEET_HOME ($FLEET_HOME). Each snapshot would then archive every previous snapshot; on an ephemeral 2 GB disk that fills the disk and the fleet loses the ability to save itself." "$EX_USAGE" ;;
esac

mkdir -p "$FLEET_SPOOL" "$FLEET_HOME" "$FLEET_HOME/tmp"

# ===================================================================== lock
# Idempotence — item 4 of the brief. Two entrypoints against ONE state
# directory is the corruptible case: both would restore, both would promote,
# and the second would either clobber the first's freshly restored experts or
# start a loop against a half-populated tree.
#
# mkdir is the mutex because mkdir is atomic on a local POSIX filesystem —
# the same guarantee loop.py leans on with O_CREAT|O_EXCL, and the same
# guarantee CLOUDFLARE.md §3.2 says object storage does NOT provide. This
# lock is therefore only meaningful for a state directory on local disk.
#
# WHAT THIS LOCK CANNOT DO: two Cloudflare Container instances have two
# separate disks, so this lock never sees the other one. Cross-instance
# safety comes from (a) running a single instance — see deploy/README.md —
# and (b) instance-stamped archive keys, so concurrent instances fork rather
# than overwrite each other. Claiming more than that would be a claim with
# no mechanism behind it.
#
# Liveness is decided by a HEARTBEAT FILE, not by a pid. A pid is worthless
# across containers: two containers have two pid namespaces, so `kill -0 7`
# asks about OUR pid 7, not theirs, and would cheerfully report a dead lock
# owner alive or a live one dead. A file mtime on the shared state directory
# is the same fact for both of them.
_lock_write() {
    printf 'pid=%s\ninstance=%s\nat=%s\n' "$$" "$FLEET_INSTANCE" "$(_stamp)" > "$LOCK_DIR/owner"
    : > "$LOCK_DIR/heartbeat"
}

_age_s() {
    "$PY" -c 'import os, sys, time
try:
    print(int(time.time() - os.path.getmtime(sys.argv[1])))
except OSError:
    print(-1)' "$1"
}

acquire_boot_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        _lock_write
        HOLD_LOCK=1
        return 0
    fi
    _opid=$(sed -n 's/^pid=//p' "$LOCK_DIR/owner" 2>/dev/null || true)
    _oinst=$(sed -n 's/^instance=//p' "$LOCK_DIR/owner" 2>/dev/null || true)
    _oat=$(sed -n 's/^at=//p' "$LOCK_DIR/owner" 2>/dev/null || true)
    _hb=$(_age_s "$LOCK_DIR/heartbeat")

    if [ "$_hb" -ge 0 ] && [ "$_hb" -lt "$FLEET_LOCK_STALE_S" ]; then
        die "another entrypoint owns $FLEET_HOME and is ALIVE — its heartbeat is ${_hb}s old (instance='$_oinst' pid='$_opid' since $_oat). Two of them would restore over each other and then run two loops against one state directory. Point this container at its own state directory, or stop the other one." "$EX_CANTCREAT"
    fi
    if [ "$_oinst" = "$FLEET_INSTANCE" ] && [ -n "$_opid" ] && kill -0 "$_opid" 2>/dev/null; then
        die "another entrypoint in THIS container (pid $_opid) already owns $FLEET_HOME. If you are certain that process is gone, remove $LOCK_DIR and start again." "$EX_CANTCREAT"
    fi
    # A lock nobody has touched for FLEET_LOCK_STALE_S: the container that
    # held it is gone, which is the normal case for a bind-mounted home whose
    # container was killed. Taking it over is correct; doing it SILENTLY would
    # hide a crash loop, so it is logged with everything we know about the
    # previous owner.
    warn "taking over a stale boot lock: heartbeat ${_hb}s old (instance='$_oinst' pid='$_opid' since $_oat)"
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" 2>/dev/null || die "lost the race for $LOCK_DIR; refusing to run two entrypoints" "$EX_CANTCREAT"
    _lock_write
    HOLD_LOCK=1
}

# The heartbeat is what makes the lock above mean something. Without it the
# only timestamp available is the boot time, so a container that has been
# healthy for three days would look three days stale to anyone else.
#
# It stops the moment the entrypoint that owns the lock stops. An orphaned
# heartbeat is worse than no heartbeat: it would keep asserting that a dead
# fleet is alive, and every future container would refuse to start on a state
# directory nobody is actually using. Here `kill -0` IS the right test, unlike
# in acquire_boot_lock: this is our own child asking about its own parent, in
# one pid namespace.
heartbeat_loop() {
    _sleeper=""
    trap 'if [ -n "$_sleeper" ]; then kill "$_sleeper" 2>/dev/null || true; fi; exit 0' TERM INT
    while true; do
        sleep "$FLEET_HEARTBEAT_S" &
        _sleeper=$!
        wait "$_sleeper" || true
        _sleeper=""
        kill -0 "$MAIN_PID" 2>/dev/null || exit 0
        : > "$LOCK_DIR/heartbeat" 2>/dev/null || true
    done
}

stop_heartbeat() {
    if [ -z "$HEARTBEAT_PID" ]; then return 0; fi
    kill -TERM "$HEARTBEAT_PID" 2>/dev/null || true
    HEARTBEAT_PID=""
}

release_boot_lock() {
    [ "$HOLD_LOCK" = 1 ] || return 0
    HOLD_LOCK=0
    rm -rf "$LOCK_DIR" 2>/dev/null || true
}

# ==================================================================== store
# Three backends behind three verbs. `r2` is the deployment target; `dir` is a
# plain directory, which is what makes every path below testable without a
# Cloudflare account AND is the right choice for a docker-compose or VPS
# install whose backup directory is a real persistent mount. On Cloudflare,
# `dir` is worthless — see deploy/README.md.
detect_store() {
    _want=$FLEET_STORE
    if [ "$_want" = auto ]; then
        if [ -n "$FLEET_R2_ENDPOINT" ] && [ -n "$FLEET_R2_BUCKET" ]; then _want=r2
        elif [ -n "$FLEET_STORE_DIR" ]; then _want=dir
        else _want=none; fi
    fi
    case "$_want" in
        r2)
            if [ -z "$FLEET_R2_ENDPOINT" ] || [ -z "$FLEET_R2_BUCKET" ]; then
                die "FLEET_STORE=r2 needs FLEET_R2_ENDPOINT and FLEET_R2_BUCKET" "$EX_USAGE"
            fi
            # Ask the Credential Authority whether keys resolve rather than
            # re-implementing its four sources (env, agent.env beside the
            # expert AND beside the code, inline, key file) in shell: a
            # subsystem that models fewer sources reports a working
            # configuration broken. It prints yes/no and never a value.
            _have=$("$PY" -c 'import sys
sys.path.insert(0, sys.argv[1])
import backup
kid, sec = backup._s3_credentials(sys.argv[2])
print("yes" if kid and sec else "no")' "$FLEET_CODE" "$FLEET_HOME")
            if [ "$_have" = yes ]; then
                STORE=r2
            else
                STORE=none
                banner "R2 IS CONFIGURED BUT ITS CREDENTIALS ARE NOT." \
                       "" \
                       "  endpoint : $FLEET_R2_ENDPOINT" \
                       "  bucket   : $FLEET_R2_BUCKET" \
                       "" \
                       "Set R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY (or the AWS_*" \
                       "equivalents) as container secrets. Until then this fleet is" \
                       "STATELESS: nothing is restored and nothing is saved."
            fi
            ;;
        dir)
            [ -n "$FLEET_STORE_DIR" ] || die "FLEET_STORE=dir needs FLEET_STORE_DIR" "$EX_USAGE"
            mkdir -p "$FLEET_STORE_DIR"
            STORE=dir
            ;;
        none)
            STORE=none
            ;;
        *)
            die "FLEET_STORE must be auto, r2, dir or none — not '$_want'" "$EX_USAGE"
            ;;
    esac
}

# -> every archive key in the store, one per line. A non-zero return means the
# store could not be READ, which is not the same fact as "the store is empty",
# and the caller must never conflate the two.
store_list() {
    case "$STORE" in
        r2)
            "$PY" "$BACKUP" remote-list --endpoint "$FLEET_R2_ENDPOINT" \
                --bucket "$FLEET_R2_BUCKET" --prefix "$FLEET_R2_PREFIX" \
                --region "$FLEET_R2_REGION" --root "$FLEET_HOME" --json \
                > "$FLEET_SPOOL/.listing.json" || return 1
            "$PY" -c 'import json, sys
for row in json.load(open(sys.argv[1])):
    key = row.get("key", "")
    if key.endswith(".zip"):
        print(key)' "$FLEET_SPOOL/.listing.json"
            ;;
        dir)
            ls -1 "$FLEET_STORE_DIR" 2>/dev/null | grep '\.zip$' || true
            ;;
        *)
            return 1
            ;;
    esac
}

# -> the newest key read from stdin. Archive names are
# fleet-YYYY-MM-DD-HHMMSS[-label].zip and that stamp is fixed-width and
# zero-padded, so lexicographic order over the BASENAME is chronological
# order. Sorting whole keys would sort by prefix first, which is not what
# "newest" means once you use FLEET_R2_PREFIX.
newest_key() {
    "$PY" -c 'import os, sys
keys = [line.strip() for line in sys.stdin if line.strip()]
print(max(keys, key=os.path.basename) if keys else "")'
}

# Download one key into $2. Non-zero only when no file arrived.
store_get() {
    _key=$1
    _dest=$2
    mkdir -p "$_dest"
    case "$STORE" in
        r2)
            # backup.py pull re-verifies what it downloaded, and as of this
            # writing that verification is BROKEN: `pull()` does
            #     rep = verify(out)
            #     if rep.get("problems"):
            # where verify() returns an (ok, report) TUPLE — so every pull
            # ends in AttributeError, including a pull of a perfectly good
            # archive (reproduced locally, without a network). The bytes are
            # written before that line, so the download itself is fine.
            #
            # The gate below is therefore OUR OWN verify, not pull's exit
            # status. That is the right shape even after the bug is fixed: a
            # restore must never trust the downloader's claim that the bytes
            # are good, because a truncated download and a corrupt archive
            # look identical until somebody recomputes the checksums.
            set +e
            "$PY" "$BACKUP" pull "$_key" --dest "$_dest" \
                --endpoint "$FLEET_R2_ENDPOINT" --bucket "$FLEET_R2_BUCKET" \
                --region "$FLEET_R2_REGION" --root "$FLEET_HOME"
            _rc=$?
            set -e
            if [ "$_rc" -ne 0 ]; then
                warn "backup.py pull exited $_rc — verifying the downloaded file ourselves before trusting or discarding it"
            fi
            ;;
        dir)
            cp "$FLEET_STORE_DIR/$_key" "$_dest/$(basename "$_key")" || return 1
            ;;
        *)
            return 1
            ;;
    esac
    [ -f "$_dest/$(basename "$_key")" ]
}

# Upload one archive. A push is a COPY: the local archive is never moved or
# deleted here, so a failed upload cannot cost you the snapshot you just took.
store_put() {
    _arch=$1
    case "$STORE" in
        r2)
            "$PY" "$BACKUP" push "$_arch" --endpoint "$FLEET_R2_ENDPOINT" \
                --bucket "$FLEET_R2_BUCKET" --prefix "$FLEET_R2_PREFIX" \
                --region "$FLEET_R2_REGION" --root "$FLEET_HOME"
            ;;
        dir)
            # .part then mv: a reader must never see a half-written archive,
            # and mv within one directory is atomic.
            _base=$(basename "$_arch")
            cp "$_arch" "$FLEET_STORE_DIR/$_base.part" && \
                mv "$FLEET_STORE_DIR/$_base.part" "$FLEET_STORE_DIR/$_base"
            ;;
        *)
            return 1
            ;;
    esac
}

# ================================================================== restore
# The three cases the brief names, handled explicitly and differently, because
# collapsing them is how a platform loses a fleet quietly.
restore_at_boot() {
    if [ "$STORE" = none ]; then
        if [ "$FLEET_REQUIRE_STATE" = 1 ]; then
            die "FLEET_REQUIRE_STATE=1 and no durable store is configured — refusing to run a fleet whose memory would die with the container" "$EX_CONFIG"
        fi
        banner "RUNNING STATELESS — NOTHING WILL SURVIVE THIS CONTAINER." \
               "" \
               "No durable store is configured, so:" \
               "  * nothing was restored at boot;" \
               "  * NO SNAPSHOTS WILL BE TAKEN, not on the interval and not on SIGTERM;" \
               "  * on Cloudflare Containers the disk is ephemeral, so every expert" \
               "    this fleet trains, every course it studies and every skill it" \
               "    proves is DESTROYED the next time the instance sleeps." \
               "" \
               "Fix it by setting FLEET_R2_ENDPOINT, FLEET_R2_BUCKET," \
               "R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY — see deploy/README.md." \
               "Set FLEET_REQUIRE_STATE=1 to make this a refusal instead of a warning."
        return 0
    fi

    # A disk that already carries experts is a WARM start: a container that
    # restarted in place, or a bind-mounted home. Restoring an archive on top
    # of live work would overwrite everything that happened since that
    # snapshot — the exact silent state loss this file exists to prevent.
    if [ -d "$FLEET_HOME/experts" ] && [ -n "$(ls -A "$FLEET_HOME/experts" 2>/dev/null || true)" ]; then
        log "state directory already holds experts — warm start, skipping restore"
        return 0
    fi

    log "store=$STORE — looking for the newest archive to restore"
    if ! store_list > "$FLEET_SPOOL/.keys" 2> "$FLEET_SPOOL/.keys.err"; then
        sed 's/^/    /' "$FLEET_SPOOL/.keys.err" >&2 || true
        if [ "$FLEET_ALLOW_DEGRADED_START" = 1 ]; then
            warn "cannot list the store, and FLEET_ALLOW_DEGRADED_START=1 — starting with an EMPTY fleet. If archives exist that we could not see, this instance now forks away from them."
            return 0
        fi
        die "the store is configured but could not be listed (error above). Refusing to start: this instance cannot tell 'no archive yet' apart from 'cannot reach the archives', and starting fresh in the second case forks the fleet away from its own memory. Fix the endpoint or the credentials, or set FLEET_ALLOW_DEGRADED_START=1 if you really do mean to start empty." "$EX_UNAVAILABLE"
    fi

    if [ -n "$FLEET_RESTORE_KEY" ]; then
        _key=$FLEET_RESTORE_KEY
        log "FLEET_RESTORE_KEY is set — restoring the archive the operator chose: $_key"
    else
        _key=$(newest_key < "$FLEET_SPOOL/.keys")
    fi

    # CASE 1 — no archive yet. A fresh fleet, not a failure. Say so plainly and
    # carry on; refusing here would mean a brand-new deployment never starts.
    if [ -z "$_key" ]; then
        log "no archive in the store yet — this is a FRESH START, not an error"
        log "the first snapshot goes out in ${FLEET_SNAPSHOT_INTERVAL_S}s, or on SIGTERM, whichever comes first"
        return 0
    fi

    log "newest archive: $_key"
    rm -rf "$FLEET_STAGING"
    mkdir -p "$FLEET_STAGING/dl"
    if ! store_get "$_key" "$FLEET_STAGING/dl"; then
        die "could not download $_key from the store. Refusing to start: there IS state out there, and this instance would otherwise begin an empty, divergent life beside it." "$EX_UNAVAILABLE"
    fi
    _arch="$FLEET_STAGING/dl/$(basename "$_key")"

    # CASE 2 — a corrupt archive. Every checksum in the manifest is recomputed
    # BEFORE anything touches the state directory, and a failure refuses the
    # boot. Starting anyway would mean the fleet comes up empty, snapshots
    # that emptiness and pushes it — turning one damaged archive into a
    # permanently lost fleet. A refusal is recoverable; that is not.
    if ! "$PY" "$BACKUP" verify "$_arch"; then
        banner "THE ARCHIVE IS DAMAGED — REFUSING TO START." \
               "" \
               "  key : $_key" \
               "" \
               "Nothing has been written to $FLEET_HOME. The fleet's state is still" \
               "in the store, exactly as it was." \
               "" \
               "Do NOT restart into a fresh fleet to 'get it running': the first" \
               "snapshot would push that emptiness on top of a working history." \
               "Pick a known-good archive deliberately instead:" \
               "" \
               "  python backup.py remote-list --endpoint ... --bucket ...   # list them" \
               "  FLEET_RESTORE_KEY=<older-key>                              # then redeploy"
        exit "$EX_DATAERR"
    fi

    log "archive verified intact — restoring"
    "$PY" "$BACKUP" restore "$_arch" --dest "$FLEET_STAGING/tree"
    promote_state "$FLEET_STAGING/tree"
    rm -rf "$FLEET_STAGING"
    log "restore complete"
}

# The archive carries the whole fleet home, CODE INCLUDED. Copying all of it
# over the live tree would replace the image's modules with whatever version
# happened to be running when the snapshot was taken — a silent downgrade of
# the platform every time somebody restores an older backup. The image is the
# source of truth for CODE; the archive is the source of truth for STATE. So
# only runtime-state paths are promoted, and that list is exactly the
# runtime-state section of .gitignore ("The CODE is versioned; the MINDS are
# not").
STATE_PATHS="experts retired teamwork commons contexts inbox goals events approvals consults checkpoints logs briefing.md commons-digest.md state.json"

promote_state() {
    _tree=$1
    for _p in $STATE_PATHS; do
        [ -e "$_tree/$_p" ] || continue
        if [ -d "$_tree/$_p" ]; then
            mkdir -p "$FLEET_HOME/$_p"
            # -n, never clobber: anything already on the live disk wins. The
            # directory itself is never replaced, because under
            # docker-compose experts/ is a MOUNT POINT and rmdir on a mount
            # point fails with EBUSY.
            cp -a -n "$_tree/$_p/." "$FLEET_HOME/$_p/" 2>/dev/null || \
                cp -R "$_tree/$_p/." "$FLEET_HOME/$_p/"
            log "  restored $_p/"
        elif [ -e "$FLEET_HOME/$_p" ]; then
            warn "  $_p already exists on disk — kept the local copy"
        else
            cp -a "$_tree/$_p" "$FLEET_HOME/$_p" 2>/dev/null || cp "$_tree/$_p" "$FLEET_HOME/$_p"
            log "  restored $_p"
        fi
    done
}

# prompts/, settings.toml and mcp.json come from the IMAGE, never from an
# archive: backup.py redacts any inline api_key it finds in a settings.toml,
# so restoring one would hand the fleet a configuration whose key literally
# reads "<redacted by backup>". Container deployments put keys in the
# environment instead. bootstrap.seed_home is called rather than copied
# because it is the ONE definition of what a fleet home contains, and a second
# copy would drift the day somebody adds a file. It never overwrites, so this
# is safe to run on every boot — and it must run on every boot, including the
# fresh-start path, or the panel comes up in a directory that is not yet a
# fleet home.
seed_home_from_image() {
    "$PY" -c 'import sys
sys.path.insert(0, sys.argv[1])
import bootstrap
copied = bootstrap.seed_home(sys.argv[2])
print("[entrypoint] seeded from the image:", ", ".join(copied) if copied else "nothing (already a fleet home)")' \
        "$FLEET_CODE" "$FLEET_HOME"
}

# ================================================================= snapshot
# create -> verify -> push -> prune. The verify is not ceremony: pushing an
# archive nobody checked means the FIRST time its checksums are recomputed is
# during a restore, at the exact moment there is nothing else left.
snapshot() {
    _why=$1
    if [ "$STORE" = none ]; then
        return 0
    fi

    # One snapshot at a time. The interval timer and the SIGTERM handler can
    # collide, and two concurrent `create` runs would write two archives of a
    # tree that is moving underneath both of them.
    _waited=0
    while ! mkdir "$SNAP_LOCK" 2>/dev/null; do
        if [ "$_why" != final ]; then
            log "snapshot ($_why) skipped — one is already running"
            return 0
        fi
        if [ "$_waited" -ge "$FLEET_SNAPSHOT_WAIT_S" ]; then
            warn "waited ${_waited}s for the running snapshot; taking the final one anyway"
            break
        fi
        sleep 2
        _waited=$((_waited + 2))
    done

    _logs_flag=""
    if [ "$FLEET_WITH_LOGS" = 1 ]; then _logs_flag="--with-logs"; fi

    set +e
    # shellcheck disable=SC2086  # _logs_flag is deliberately word-split
    "$PY" "$BACKUP" create --home "$FLEET_HOME" --out "$FLEET_SPOOL" \
        --label "$FLEET_INSTANCE" $_logs_flag --json \
        > "$FLEET_SPOOL/.create.json" 2> "$FLEET_SPOOL/.create.err"
    _rc=$?
    set -e
    if [ "$_rc" -ne 0 ]; then
        warn "snapshot ($_why) FAILED at create: $(tr '\n' ' ' < "$FLEET_SPOOL/.create.err" 2>/dev/null)"
        rmdir "$SNAP_LOCK" 2>/dev/null || true
        return 1
    fi
    _arch=$("$PY" -c 'import json, sys
print(json.load(open(sys.argv[1]))["path"])' "$FLEET_SPOOL/.create.json")

    if ! "$PY" "$BACKUP" verify "$_arch" > /dev/null 2>&1; then
        warn "snapshot ($_why) produced a DAMAGED archive and was NOT pushed: $_arch"
        warn "the store still holds the previous archive — it was not overwritten"
        rmdir "$SNAP_LOCK" 2>/dev/null || true
        return 1
    fi

    set +e
    store_put "$_arch" > /dev/null 2> "$FLEET_SPOOL/.push.err"
    _rc=$?
    set -e
    if [ "$_rc" -ne 0 ]; then
        warn "snapshot ($_why) created and verified $_arch but the PUSH failed: $(tr '\n' ' ' < "$FLEET_SPOOL/.push.err" 2>/dev/null)"
        warn "that work now exists only on ephemeral disk and dies with this container"
        rmdir "$SNAP_LOCK" 2>/dev/null || true
        return 1
    fi

    log "snapshot ($_why) pushed: $(basename "$_arch")"
    prune_spool
    rmdir "$SNAP_LOCK" 2>/dev/null || true
    return 0
}

# The spool sits on the container's disk, which on the smallest instance type
# is 2 GB in total. Unbounded snapshots would eventually leave no room to take
# the next one — the failure mode where a backup system destroys the thing it
# was protecting. Only LOCAL copies are pruned; the store keeps every archive.
prune_spool() {
    _n=0
    for _f in $(ls -1t "$FLEET_SPOOL"/*.zip 2>/dev/null || true); do
        _n=$((_n + 1))
        if [ "$_n" -gt "$FLEET_KEEP_LOCAL" ]; then rm -f "$_f"; fi
    done
    return 0
}

# The sleep runs as a CHILD that the timer can kill. `sleep 900` started
# inline would survive the timer being terminated, and an orphaned sleep keeps
# every inherited file descriptor open — which, at shutdown, is how a
# container that has finished its work still looks alive.
snapshot_timer() {
    _sleeper=""
    trap 'if [ -n "$_sleeper" ]; then kill "$_sleeper" 2>/dev/null || true; fi; exit 0' TERM INT
    while true; do
        sleep "$FLEET_SNAPSHOT_INTERVAL_S" &
        _sleeper=$!
        wait "$_sleeper" || true
        _sleeper=""
        # An orphaned timer would go on archiving a fleet whose entrypoint is
        # gone — and would fight the next container for the snapshot lock.
        kill -0 "$MAIN_PID" 2>/dev/null || exit 0
        snapshot interval || true
    done
}

# ================================================================= workload
start_workload() {
    if [ "$#" -gt 0 ]; then
        log "workload (from arguments): $*"
        _run_bg "$@"
        return 0
    fi
    case "$FLEET_MODE" in
        serve)
            log "workload: the control panel on $FLEET_UI_HOST:$FLEET_UI_PORT (home $FLEET_HOME)"
            WORKLOAD_KIND=panel
            _run_bg "$PY" "$FLEET_CODE/ui.py" --home "$FLEET_HOME" \
                --host "$FLEET_UI_HOST" --port "$FLEET_UI_PORT"
            ;;
        drain)
            # CLOUDFLARE.md §6.4: a Durable Object alarm pokes the container,
            # the container drains its queue and sleeps again. `--drain` exits
            # when no queued or running task remains, so the instance stops
            # billing for idle time instead of holding the box open.
            log "workload: draining every expert's queue, then exiting"
            _run_bg /bin/sh -c '
                set -u
                found=0
                for d in "$1"/experts/*/; do
                    [ -d "$d" ] || continue
                    found=1
                    echo "[entrypoint] draining $d"
                    "$2" "$3/loop.py" run --drain --root "$d" || \
                        echo "[entrypoint] WARNING: drain of $d exited non-zero" >&2
                done
                [ "$found" = 1 ] || echo "[entrypoint] no experts to drain"
            ' _ "$FLEET_HOME" "$PY" "$FLEET_CODE"
            ;;
    esac
}

# Run the workload in its own session where the OS allows it, so that stopping
# it also stops whatever it started. The panel spawns expert loops as child
# processes; if those outlive the panel they keep WRITING into the very
# directory the final snapshot is about to archive.
_run_bg() {
    if command -v setsid > /dev/null 2>&1; then
        setsid "$@" &
        WORKLOAD_PID=$!
        USED_SETSID=1
    else
        "$@" &
        WORKLOAD_PID=$!
        USED_SETSID=0
    fi
}

# Ask the panel to stop ITSELF. ui.py:114 says exactly why this exists:
# "a terminated panel cannot run cleanup, so tests and operators call POST
# /api/shutdown instead of killing the panel: otherwise its drivers live on as
# orphans". The handler calls shutdown_children() — terminating every expert
# loop the panel started — and only then exits.
#
# SIGINT is deliberately NOT used for this, even though ui.py turns it into a
# clean KeyboardInterrupt shutdown: POSIX requires a shell with job control
# disabled (every shell in every container) to start background commands with
# SIGINT IGNORED, and a signal ignored on entry can be neither trapped nor
# reset by the child. Measured here — the first version of this script sent
# SIGINT and then sat through its entire grace period before escalating.
#
# The token is read from the environment or from the file ui.py wrote, and is
# passed in a header. It is never logged and never put in the URL.
panel_shutdown() {
    "$PY" -c 'import os, sys, urllib.error, urllib.request
port, home = sys.argv[1], sys.argv[2]
token = os.environ.get("UI_TOKEN") or ""
if not token:
    try:
        with open(os.path.join(home, "ui-token.txt"), encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        token = ""
req = urllib.request.Request("http://127.0.0.1:%s/api/shutdown" % port,
                             data=b"{}", method="POST")
req.add_header("Content-Type", "application/json")
if token:
    req.add_header("Authorization", "Bearer " + token)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()
    print("panel accepted the shutdown request")
except urllib.error.HTTPError as e:
    print("panel refused the shutdown request: HTTP %s" % e.code)
    sys.exit(1)
except Exception as e:
    print("panel did not answer: %s" % type(e).__name__)
    sys.exit(1)' "$FLEET_UI_PORT" "$FLEET_HOME"
}

# Cloudflare sends SIGTERM. Quiescing the workload BEFORE the final snapshot
# is what makes that snapshot worth having: an archive of a directory nobody
# is writing to beats a faster archive of a directory that is moving.
stop_workload() {
    if [ -z "$WORKLOAD_PID" ]; then return 0; fi
    if ! kill -0 "$WORKLOAD_PID" 2>/dev/null; then WORKLOAD_PID=""; return 0; fi
    if [ "$WORKLOAD_KIND" = panel ]; then
        log "asking the panel to shut down and reap its expert loops (POST /api/shutdown)"
        panel_shutdown || warn "the panel did not accept a clean shutdown — falling back to signals"
    else
        log "stopping the workload (SIGTERM, up to ${FLEET_DRAIN_GRACE_S}s) before snapshotting"
        kill -TERM "$WORKLOAD_PID" 2>/dev/null || true
    fi
    _w=0
    while kill -0 "$WORKLOAD_PID" 2>/dev/null; do
        if [ "$_w" -ge "$FLEET_DRAIN_GRACE_S" ]; then break; fi
        sleep 1
        _w=$((_w + 1))
    done
    if kill -0 "$WORKLOAD_PID" 2>/dev/null; then
        warn "workload still alive after ${_w}s — escalating to SIGTERM, then SIGKILL"
        kill -TERM "$WORKLOAD_PID" 2>/dev/null || true
        sleep 5
        kill -KILL "$WORKLOAD_PID" 2>/dev/null || true
    fi
    # Sweep the session, but ONLY when we know we created one: signalling a
    # process GROUP id we merely guessed could hit an unrelated group.
    if [ "$USED_SETSID" = 1 ] && kill -0 "-$WORKLOAD_PID" 2>/dev/null; then
        kill -TERM "-$WORKLOAD_PID" 2>/dev/null || true
    fi
    WORKLOAD_PID=""
    log "workload stopped — the state directory now has no writers"
}

stop_timer() {
    if [ -z "$TIMER_PID" ]; then return 0; fi
    kill -TERM "$TIMER_PID" 2>/dev/null || true
    TIMER_PID=""
}

# ================================================================== signals
on_term() {
    if [ "$SHUTTING_DOWN" = 1 ]; then return 0; fi
    SHUTTING_DOWN=1
    log "signal received — Cloudflare signals before it stops a container, so this is the last chance to save the fleet"
    stop_timer
    stop_workload           # quiesce FIRST: an archive of a tree nobody is
    snapshot final || true  # writing is worth more than a fast one
    stop_heartbeat
    release_boot_lock
    log "shutdown complete"
    exit 0
}

on_exit() { stop_heartbeat; release_boot_lock; }

trap on_term TERM INT HUP
trap on_exit EXIT

# ===================================================================== main
log "code=$FLEET_CODE home=$FLEET_HOME mode=$FLEET_MODE instance=$FLEET_INSTANCE"
acquire_boot_lock
heartbeat_loop &
HEARTBEAT_PID=$!
detect_store
restore_at_boot
seed_home_from_image

if [ "$STORE" != none ]; then
    snapshot_timer &
    TIMER_PID=$!
    log "snapshots every ${FLEET_SNAPSHOT_INTERVAL_S}s to store=$STORE, and on SIGTERM"
fi

start_workload "$@"

set +e
wait "$WORKLOAD_PID"
RC=$?
set -e

# The workload ended on its own — a completed drain, or a panel that died.
# Either way the work it did is still only on ephemeral disk until it is
# pushed, so a snapshot happens on this path too, not only on SIGTERM.
if [ "$SHUTTING_DOWN" != 1 ]; then
    log "workload exited rc=$RC"
    stop_timer
    snapshot final || true
    stop_heartbeat
    release_boot_lock
fi
exit "$RC"
