# Running Expert Fleet on Cloudflare

This directory is the Worker half of a Cloudflare deployment: **a Durable
Object alarm that wakes the fleet on a schedule**, and **a REST sandbox** that
`sandbox.py`'s `cloudflare` backend calls. It closes items 4 and 5 of
[`CLOUDFLARE.md`](../../CLOUDFLARE.md) §6.

> **What has and has not been verified.** Every API used here was read from
> Cloudflare's own documentation on 2026-08-25, and every package version in
> `package.json` was resolved from the npm registry the same day. **Nothing in
> this directory has been deployed to a Cloudflare account.** There is no
> account, no token, and no container behind these files. `wrangler deploy`
> is the first real test, and if the Container SDK has moved under us it will
> fail there. That is stated plainly rather than left for you to discover:
> the Python side of this platform is covered by 107 tests, and this is not.

---

## The one thing that will bite you

**Container disk is ephemeral.** Cloudflare's words, not a caveat we invented:

> *"All disk is ephemeral. When a Container instance goes to sleep, the next
> time it is started, it will have a fresh disk as defined by its container
> image."*

An expert's whole mind — `state.json`, courses, notes, skills, cases,
gotchas, the commons — is files on disk. So **a Cloudflare deployment without
R2 configured silently destroys the fleet every time the container sleeps**,
and it looks like the fleet simply forgot everything.

That is why the shipped `Dockerfile` runs `deploy/entrypoint.sh`, which
restores from R2 at boot and snapshots back on an interval and on SIGTERM.
[`deploy/README.md`](../README.md) is the manual for it, including the
data-loss window between snapshots.

**Do not mount R2 as a FUSE filesystem to avoid this.** The platform's
concurrency correctness rests on `O_EXCL` and atomic `rename`, and neither is
atomic on object storage. `CLOUDFLARE.md` §3.2 works through why.

---

## What the alarm is for

A container sleeps after `sleepAfter`. Something has to start it again, or a
sleeping fleet stays asleep and the queue never drains.

A Durable Object alarm is the cheapest thing that can. It costs nothing while
it waits, and Cloudflare guarantees *"at-least-once execution"* with automatic
retries. The cycle:

```
alarm fires ─▶ reschedule the next alarm FIRST
            ─▶ POST /drain to the container
            ─▶ container empties its queue
            ─▶ container snapshots to R2 and sleeps
```

**The reschedule happens before the work, deliberately.** If a drain throws
and the reschedule sat after it, no alarm would ever be set again and the
whole deployment would stop — silently, discovered days later by someone
noticing the queue is long. Rescheduling first means a failed drain costs one
missed cycle and nothing more.

At-least-once also means the alarm can fire twice for one scheduled time.
Draining twice is harmless: the second drain finds an empty queue.

---

## Deploy

```bash
cd deploy/worker
npm install
```

**1. A dedicated secret for `/exec`** — not your Cloudflare API token.

`/exec` runs shell commands, so it is the most dangerous route in this
repository. It requires a bearer token, compared in constant time, and it
**refuses every request when the secret is unset** rather than running them
unauthenticated.

Use a random value, and *not* your account API token: that token can create
Workers, read R2 and spend money account-wide, and sending it here would mean
holding full account authority in order to run `ls`.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```bash
npx wrangler secret put FLEET_EXEC_TOKEN
```

Put the **same value** in the fleet's `agent.env`:

```
CLOUDFLARE_SANDBOX_TOKEN=<the same random value>
CLOUDFLARE_SANDBOX_URL=https://expert-fleet.<your-subdomain>.workers.dev
```

**2. Deploy.**

```bash
npx wrangler deploy
```

**3. Arm the schedule.** Idempotent, so run it after every deploy.

```bash
curl -s https://expert-fleet.<your-subdomain>.workers.dev/wake
```

```json
{ "armed": true, "next_alarm_utc": "2026-08-25T13:04:11.000Z" }
```

---

## Using the sandbox from the fleet

In the expert's `settings.toml`:

```toml
[agent]
sandbox = "cloudflare"
```

Then check it the same way you would check any other backend:

```bash
python doctor.py
```

`sandbox.py` fails closed at every stage, and the messages say what is
missing rather than falling back to running the command on the host:

| state | what you get |
|---|---|
| no `CLOUDFLARE_SANDBOX_TOKEN` | `CLOUDFLARE_SANDBOX_TOKEN is not set in the environment` |
| token but no URL | names `deploy/worker/README.md` and the two ways to set it |
| both set | `cloudflare configured via CLOUDFLARE_SANDBOX_TOKEN -> <url>` |
| a command with no endpoint | exit 127, `Nothing was run on the host.` |

That last row is the one that matters. A sandbox backend that quietly runs on
the host when it cannot reach its sandbox is worse than no sandbox at all,
because it reports isolation it is not providing.

---

## Costs

`CLOUDFLARE.md` §5.1 has the full arithmetic. The short version, with every
figure dated 2026-08-25 and re-fetchable:

- **Workers AI free allocation:** 10,000 Neurons/day, standing, not a trial.
- On `@cf/qwen/qwen3-30b-a3b-fp8` — the cheapest model that can call tools —
  that is **~493 agent steps a day for nothing**, and **$0.22 per additional
  thousand steps**.
- The container is billed for the time it runs. Sleeping between drains is
  the whole point of the alarm.

**Pick a model that supports function calling.** Every step this agent takes
is a native tool call. `CLOUDFLARE.md` §4.1 lists the ones that do and shows
what happens if you pick one that does not.

---

## Files

| file | what it is |
|---|---|
| `src/index.ts` | the Worker: `FleetContainer` (alarm + lifecycle), `/exec`, `/wake`, `/health`, and a passthrough to the container's control panel |
| `wrangler.jsonc` | container + Durable Object bindings, migrations, `max_instances: 1` |
| `package.json` | `@cloudflare/containers`, `@cloudflare/sandbox`, `wrangler` |
| `tsconfig.json` | strict TypeScript, no emit |

### Why `max_instances: 1`

Not a throughput limit — a correctness one. The platform's concurrency safety
rests on `O_EXCL` and atomic `rename` over **one** state directory. Two
containers restoring the same R2 snapshot would each promote their own copy
and then run two loops against divergent state. `entrypoint.sh` takes a boot
lock and refuses the second one, but that is a backstop, not a licence to
raise this number.
