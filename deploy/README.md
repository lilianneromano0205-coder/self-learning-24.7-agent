# Running the fleet in a container

This directory holds `entrypoint.sh`: the thing that stands between an agent
fleet and an ephemeral disk. Read the first section before you deploy, and
read **[The data-loss window](#the-data-loss-window)** before you trust it.

---

## 1. Why this exists, and why R2 is not mounted

Cloudflare's own words, quoted in `CLOUDFLARE.md` §3.2:

> All disk is ephemeral. When a Container instance goes to sleep, the next
> time it is started, it will have a fresh disk as defined by its container
> image.

The default `sleepAfter` is **10 minutes** of inactivity. For a platform whose
architecture is *"an expert IS a directory"* — identity, courses, skills,
failures, missions, `state.json` — a fresh disk means the fleet forgets
everything it ever studied, roughly six times an hour.

Cloudflare documents an escape hatch: mount R2 as a filesystem with FUSE.
**Do not.** `CLOUDFLARE.md` §3.2 works through why:

```
loop.py:366   fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)   # the task mutex
locks.py:47   fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
loop.py:150   tmp + fsync + os.replace                                    # every ledger write
```

Neither `O_EXCL` nor `rename` is atomic on object storage — `O_EXCL` becomes
check-then-create and `rename` becomes copy-then-delete. Putting `state.json`
on an R2-FUSE mount silently reintroduces **U15**: two loops running one task,
six queued and fourteen completions logged. That defect needed a loaded CI
runner to find on a local disk; across a network filesystem it would be
invisible.

So the split this entrypoint implements is:

| | holds | reached by |
|---|---|---|
| **container local disk** | the working state | ordinary POSIX file I/O, exactly what the test suite covers |
| **R2** | durable memory | `backup.py create` / `push` / `pull`, over HTTPS |

**R2 is never mounted.** If you find yourself adding a mount, read §3.2 again.

---

## 2. What the entrypoint does

```
boot   ── restore ─────────────────────────────────────────────────────────
        │  no store configured   → run STATELESS, with a loud banner
        │  store unreadable      → REFUSE to start (exit 69)
        │  store empty           → fresh start, not an error
        │  disk already has work → warm start, do not restore over it
        │  newest archive good   → verify every checksum, then restore
        │  newest archive broken → REFUSE to start (exit 65)
run    ── the workload: the control panel, or a one-shot drain
snap   ── every FLEET_SNAPSHOT_INTERVAL_S: create → verify → push → prune
stop   ── on SIGTERM: quiesce the workload, snapshot, push, exit
```

Three details worth knowing, because each one is a failure that was designed
out rather than a feature that was designed in:

* **An archive is verified twice before it is trusted** — once after the
  download and once before the upload. Every checksum in
  `backup-manifest.json` is recomputed both times. An archive nobody checked
  is an archive whose first checksum recomputation happens during a restore,
  at the exact moment you have nothing else left.

* **A restore never replaces the image's code.** The archive contains the
  whole fleet home, `.py` files included, so a naive extract would downgrade
  the platform to whatever version was running when the snapshot was taken.
  Only runtime-state paths are promoted, and that list is exactly the
  runtime-state section of `.gitignore` — *"The CODE is versioned; the MINDS
  are not."* The image is the source of truth for code; the archive is the
  source of truth for state.

* **The workload is stopped before the final snapshot.** An archive of a
  directory nobody is writing to is worth more than a faster archive of a
  directory that is moving. In `serve` mode the entrypoint calls
  `POST /api/shutdown`, which is the panel's own documented clean stop
  (`ui.py:114`: *"a terminated panel cannot run cleanup, so tests and
  operators call POST /api/shutdown instead of killing the panel: otherwise
  its drivers live on as orphans"*), and falls back to signals if that fails.

---

## 3. The data-loss window

**This design loses work. Here is exactly how much, and when.**

### The normal case: Cloudflare puts the instance to sleep

Cloudflare signals before it stops a container. The entrypoint catches that
signal, stops the workload, takes a snapshot of the now-quiet directory,
pushes it, and exits. **In this path the window is whatever the shutdown
misses, which should be nothing** — measured at **1.9 seconds** end to end
for a 25-file fleet against a local store (`docker stop -t 60`, exit code 0).

That number is small because the fleet was small and the store was local. A
fleet with a year of ingested courses, pushed to R2 over the internet, takes
longer. **If the platform kills the container before the push finishes, you
fall back to the crash case below.** The size of your fleet, not this script,
decides whether the shutdown fits in the grace period. Keep archives small
(leave `FLEET_WITH_LOGS=0`) and watch for `snapshot (final) pushed:` in the
container logs — if you do not see it, the shutdown did not fit.

### The crash case: no signal at all

An OOM kill, a host failure, a `SIGKILL`, a bug that takes the process out —
none of these run the shutdown path. **Everything since the last successful
push is gone.** The exposure is bounded by `FLEET_SNAPSHOT_INTERVAL_S`, which
defaults to **900 seconds**.

> Set that interval to the amount of study you are willing to make an expert
> repeat. Fifteen minutes of a re-read course is cheap. Fifteen minutes is
> not cheap if the expert spent it on a task you were billed for.

Snapshots are not free: each one walks the state directory, zips it, hashes
every file, and uploads the result. On a `lite` instance (1/16 vCPU) a large
fleet at a 60-second interval will spend a visible fraction of its life
archiving itself instead of working.

### The push-failed case

If `create` and `verify` succeed but the upload fails, the entrypoint says so
loudly and keeps running — the archive is still on the container's disk,
which dies with the container. Nothing can save that work except the next
successful push. Watch the logs for:

```
WARNING: snapshot (interval) created and verified /tmp/... but the PUSH failed: ...
WARNING: that work now exists only on ephemeral disk and dies with this container
```

### Interval snapshots are not point-in-time

An interval snapshot is taken while the loop is running. Every individual
file is intact, because this platform writes every ledger through
`tmp + fsync + os.replace` and the archiver therefore sees either the old
file or the new one, never a half-written one. But the *set* of files is not
one instant: `backup.py` walks top-down, so a `state.json` is captured before
the course notes in the directories beneath it.

The practical consequence is that a restored expert can be slightly *behind*
its own artifacts — it may redo a task whose output already exists, rather
than claim a task is done whose output is missing. That is the safer
direction of the two. **I have not exhaustively proven the write ordering of
every writer in this codebase**, so treat that as the expected behaviour
rather than a guarantee. The snapshot taken on shutdown does not have this
property at all, because the workload is stopped first.

### Two instances fork; they do not merge

If two containers run against one fleet, each restores the same archive and
then writes its own future. Archive keys are stamped with the instance name,
so they never overwrite each other — but you now have two divergent fleets
and nothing here reconciles them.

**Run one instance.** The boot lock catches the case where two containers
share one state directory (verified: the second exits 73 and the first is
unaffected), but two Cloudflare instances have two separate disks, so the
lock cannot see across them. There is no mechanism here that makes two
instances safe, and claiming otherwise would be a claim with nothing behind
it.

---

## 4. What an operator must set

### Required for durable state

| Variable | What it is |
|---|---|
| `FLEET_R2_ENDPOINT` | `https://<accountid>.r2.cloudflarestorage.com` |
| `FLEET_R2_BUCKET` | the bucket name, e.g. `fleet` |
| `R2_ACCESS_KEY_ID` | Cloudflare dashboard → R2 → **Manage API tokens** |
| `R2_SECRET_ACCESS_KEY` | issued with the access key id; store it as a **secret** |

The `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` names work too, so an
existing profile needs no renaming. Keys are resolved through
`credentials.resolve()`, which also reads `agent.env` — but in a container the
environment is the right place, because `agent.env` is deliberately excluded
from every backup and would not survive a restore.

**With none of these set the fleet runs stateless and says so in a banner you
cannot miss.** That is a supported mode for a throwaway demo and a disaster
for anything else. Set `FLEET_REQUIRE_STATE=1` to turn the warning into a
refusal (exit 78).

### Required for the control panel

| Variable | What it is |
|---|---|
| `UI_TOKEN` | the panel's bearer token |

`ui.py` auto-generates a token when it binds beyond localhost and writes it to
`ui-token.txt`. On an ephemeral disk that means **a new token on every wake**,
and `ui-token.txt` is on `backup.py`'s never-archive list, so it cannot be
restored. Set `UI_TOKEN` yourself as a container secret or you will be locked
out of your own panel every time the instance sleeps.

The panel still speaks plain HTTP. `CLOUDFLARE.md` §5.3 is the fix: put it
behind a Cloudflare Tunnel with Zero Trust access policies, which needs no
code change. Do not expose port 7777 to the internet directly.

### Worth setting

| Variable | Default | Why you would change it |
|---|---|---|
| `FLEET_HOME` | the code directory | Point it at `/home/agent/fleet` (the image creates it) and archives carry only the fleet's mind, not a copy of the code. Leave it alone for `docker-compose`, whose volume is mounted inside the code directory. |
| `FLEET_MODE` | `serve` | `drain` empties every expert's queue and exits — the shape a Durable Object alarm wants (`CLOUDFLARE.md` §6.4). Its exit code is the container's. |
| `FLEET_SNAPSHOT_INTERVAL_S` | `900` | Your crash-case exposure, in seconds. |
| `FLEET_R2_PREFIX` | *(none)* | A key prefix, so several fleets can share one bucket. |
| `FLEET_KEEP_LOCAL` | `3` | Local archives kept in the spool. The store keeps all of them; this only bounds the container's own disk, which is **2 GB** on `lite` (`CLOUDFLARE.md` §3.2). |
| `FLEET_WITH_LOGS` | `0` | `1` archives `logs/` too. Bigger archives, slower shutdown, longer data-loss window. |
| `FLEET_UI_HOST` / `FLEET_UI_PORT` | `0.0.0.0` / `7777` | Cloudflare's Worker reaches the container on a port; keep them unless you know why. |

### Escape hatches, for when something has gone wrong

| Variable | Effect |
|---|---|
| `FLEET_RESTORE_KEY` | Restore this exact key instead of the newest. The way back from a damaged newest archive. |
| `FLEET_ALLOW_DEGRADED_START` | `1` starts with an empty fleet even when the store could not be listed. **This forks the fleet away from its own memory.** Only for a deliberate rebuild. |
| `FLEET_REQUIRE_STATE` | `1` refuses to run without a durable store. |
| `FLEET_STORE` / `FLEET_STORE_DIR` | `FLEET_STORE=dir` snapshots to a directory instead of R2 — right for a VPS or `docker-compose` whose backup directory is a real persistent mount, and **worthless on Cloudflare**, where that directory is as ephemeral as everything else. |
| `FLEET_LOCK_STALE_S` | `180` — how long a lock with no heartbeat must sit before another container takes it over. |

### Exit codes

Borrowed from `sysexits.h` so a Worker reading the container's exit status can
tell these apart without parsing logs.

| Code | Meaning |
|---|---|
| `0` | clean stop, snapshot pushed |
| `64` | configured impossibly (bad `FLEET_MODE`, spool inside the home) |
| `65` | the archive is damaged — nothing was written to the state directory |
| `69` | the store is configured but could not be read |
| `73` | another entrypoint already owns this state directory |
| `78` | `FLEET_REQUIRE_STATE=1` and no store is configured |

---

## 5. Deploying

### Cloudflare Containers

1. Build and push the image (`Dockerfile` at the repository root).
2. Give the container the environment above, with `R2_SECRET_ACCESS_KEY` and
   `UI_TOKEN` as **secrets**, not plain variables.
3. **One instance.** See [Two instances fork](#two-instances-fork-they-do-not-merge).
4. Set `sleepAfter` generously. Every wake pays for a `pull` of the whole
   fleet plus a restore; a fleet that sleeps every ten minutes spends its life
   restoring itself. `CLOUDFLARE.md` §5.1 puts a `basic` instance running 24/7
   at about **$12/month**, which is usually the better trade.
5. Either let the container run continuously, or run `FLEET_MODE=drain` and
   poke it from a Durable Object alarm — Cloudflare documents alarms as
   *"guaranteed at-least-once execution"* (`CLOUDFLARE.md` §5).

> The exact `wrangler` field names for instance type, max instances and
> `sleepAfter` are deliberately not reproduced here. Nothing in this
> repository has ever been run against Cloudflare (`CLOUDFLARE.md` §7), so
> take that syntax from Cloudflare's current documentation rather than from a
> file that cannot have verified it.

### docker-compose or a VPS

`docker-compose.yml` keeps working unchanged: with no arguments the entrypoint
starts the same panel on the same port, and the `fleet-experts` volume is
still where the experts live. To get snapshots as well, add either the R2
variables or:

```yaml
environment:
  FLEET_STORE: dir
  FLEET_STORE_DIR: /backups          # must be a real persistent mount
  FLEET_SNAPSHOT_INTERVAL_S: "3600"
volumes:
  - /srv/fleet-backups:/backups
```

---

## 6. Operating it

```bash
# what is in the store
python backup.py remote-list --endpoint https://<id>.r2.cloudflarestorage.com \
                             --bucket fleet --prefix snapshots

# is a particular archive intact?
python backup.py pull <key> --dest /tmp/check --endpoint ... --bucket ...
python backup.py verify /tmp/check/<file>.zip

# recover from a damaged newest archive: pick an older one deliberately
FLEET_RESTORE_KEY=snapshots/fleet-2026-08-24-013000-cf-one.zip
```

**Test your restore before you need it.** A backup with no tested restore is
not a backup, it is a hope. The cheapest honest test is the one in §7 below:
start a second container with a fresh disk pointed at the same store and check
that your experts come back with their courses attached.

---

## 7. What was verified, and what was not

Everything below was run. Commands and full output are in the report that
accompanied this change.

**Verified on real Linux, in containers, with a real `docker stop`:**

* fresh start against an empty store — treated as a fresh fleet, not an error;
* a container minted an expert, was stopped with `SIGTERM`, and pushed a final
  snapshot in **1.9 s** (`POST /api/shutdown` accepted, exit code 0);
* a **second container with a fresh disk** restored that archive and
  `fleet.py list` showed the expert with its course, its note intact
  byte-for-byte — the Cloudflare sleep/wake cycle end to end;
* `FLEET_MODE=drain` restored the fleet, ran the real `loop.py run --drain`
  (`{"event": "drain_complete"}`), snapshotted and exited `0`;
* two containers sharing one state directory: the second refused with exit
  **73**, quoting the first's heartbeat age; the first was unaffected;
* the restored home contained `experts/`, `prompts/`, `settings.toml` — and
  **not** the archived copy of the code.

**Verified locally against a loopback server speaking the three S3 verbs:**

* the full `remote-list → pull → verify → restore` and
  `create → verify → push` paths, including `FLEET_R2_PREFIX`;
* a **truncated archive** in the store: the boot was refused with exit **65**,
  the state directory was left untouched and the store was not written to;
* `FLEET_RESTORE_KEY` then recovered the fleet from the older, good archive;
* an unreachable endpoint: refused with exit **69** rather than starting an
  empty fleet beside state it could not see;
* stateless mode with R2 unset: the banner, and no snapshots.

**NOT verified — do not read these as working:**

* **Nothing was run against real Cloudflare R2, or against Cloudflare
  Containers.** There is no account and no bucket. The loopback server does
  **not** check AWS SigV4 signatures, so it proves the plumbing and proves
  nothing about whether R2 will accept our `Authorization` header. What backs
  that is `test_backup.py`, which pins two of AWS's own published example
  signatures byte for byte. The first thing to test against a real bucket is
  a single `backup.py push`; an authentication mistake will show up there as
  an opaque `403`.
* **The image itself was not built here.** `docker build --check` reports no
  warnings, but the build runs the full test suite inside the image and other
  agents are working in this tree concurrently, so building it would have
  proved something about their work-in-progress rather than about this
  change. The entrypoint was exercised inside a stock `python:3.12-slim`
  container with the repository mounted, which is the same interpreter, the
  same `/bin/sh`, and the same signal semantics as the image.
* **Cloudflare's grace period between `SIGTERM` and `SIGKILL` was not
  measured** — no instance was ever stopped by Cloudflare. The 1.9 s figure
  above is from `docker stop` with a small fleet, and it is not a promise
  about a large one.
* **`backup.py pull` is broken, and this entrypoint works around it.**
  `pull()` ends with `rep = verify(out)` — where `verify()` returns an
  `(ok, report)` **tuple** — and then calls `rep.get("problems")`. Every
  `pull` therefore ends in `AttributeError: 'tuple' object has no attribute
  'get'`, including a pull of a perfectly good archive; the file is written
  first, so the download itself is fine. (`"problems"` is also not a key that
  `verify()`'s report ever contains, so the check would have caught nothing
  even unpacked correctly.) You will see that traceback in the container logs
  on every restore, followed by the entrypoint's own verification. The
  entrypoint gates on **its own** `backup.py verify`, never on `pull`'s exit
  status — which is the right shape after the bug is fixed too, because a
  truncated download and a corrupt archive look identical until somebody
  recomputes the checksums. `backup.py` belongs to another agent; this note
  is the handoff.
