# Phase 9b — Watchdog and safe mode: spacecraft fault protection beneath the model (design, committed before code)

**Status: BUILT** (this document was committed first; the build commit
follows it and cites this file; the benchmark below is green in the
acceptance suite). **Branch:** `phase9b/watchdog`. One thing the benchmark
settled while being built: a resumed task must not re-trip on the streak
that entered safe mode, so `safe_mode_entered` and `task_resumed` both reset
the refusal streak — a fault already responded to is not a new fault. **Series:**
docs/DESIGN-P9a-reconcilers.md maps the lineages; this is the second piece.

## The lineage

A spacecraft does not reason about a fault. Fault protection is a small,
deterministic monitor with declared limits — a current, a temperature, a
count of resets — and one response when a limit trips: **safe mode**. The
vehicle sheds everything non-essential, keeps attitude control and the
radio, and waits for the ground. Nothing intelligent happens on board; the
intelligence is in the *declaration* of the limits and in the humans who
clear the mode. Decades of missions ran on that shape.

The platform already has the pieces of a monitor scattered as brakes:
per-task step and cost ceilings, a daily budget breaker, a repetition
breaker, a heartbeat, consecutive-error escalation. What it does not have
is the response: a **fleet-level state** that the model cannot argue with,
cannot clear, and that every path consults. This phase adds it, additively.

## What a watchdog is

`[agent.watchdog]` in `settings.toml` (owner state; `enabled = false` by
default, so nothing already built changes behaviour until the owner turns
it on):

```toml
[agent.watchdog]
enabled = false
window_calls = 50            # the last N tool results considered
tool_error_rate_max = 0.6    # errors / calls over the window
crash_max = 3                # step_crash events inside window_s
refusal_streak_max = 8       # consecutive done_refused (a task claiming done and being caught)
spend_usd_per_hour_max = 0   # 0 = off; today's spend divided by hours elapsed
disk_free_gb_min = 1.0
window_s = 3600
```

`watchdog.evaluate(root, cfg, now)` reads the tail of `logs/agent.log`,
today's spend file and the disk, computes every metric, and returns the
limits that tripped, each with the observed value and the ceiling. It reads
ledgers the harness already writes; it adds no instrumentation to the
loop and asks no model anything.

## Safe mode

`safe_mode.json` in the expert root — CONTROL state: written by the
harness when a limit trips (`watchdog.enter`), cleared by the owner only
(`watchdog.clear --why`, refused inside an agent task), enumerated in the
promotion-leakage suite. It holds the time, the tripped limits and who
entered it; clearing archives the episode to `logs/safe-mode.jsonl`.

While safe mode is active the loop:

- **claims no new task** — queued work stays queued, and says so once a
  minute (`safe_mode_active`);
- **stops a running task at its next step boundary**, exactly as a
  shutdown request does: state committed, lock released, task resumable;
- **keeps the heartbeat** (note `safe_mode`) — a vehicle in safe mode is
  alive and reporting;
- **keeps the model-free ticks**: prospective intentions still arm and
  queue (nothing runs), reconcilers still observe and, being proven and
  model-free, still restore — the invariants the owner declared are the
  attitude control, and are not shed;
- in `--drain` mode, returns with `drain_safe_mode_stop` rather than
  waiting.

The loop evaluates the watchdog before claiming a task and before each
step, throttled to once per 30 s; a trip while a task runs enters safe
mode and the task stops at the boundary. The doctor reports an active safe
mode as a BLOCKING readiness item with the clear command; the chief's
briefing ranks `RESTORE` above every other verb while any expert is in
safe mode.

## What measurable capability this adds

A fleet that misbehaves stops itself: a burst of tool errors, repeated
crashes, a task that keeps claiming done and being caught, spend running
faster than the owner allowed, a disk filling up — each becomes a declared
limit with one response, and the response is not the model's to override.
Before this phase those signals were counts in a log; after it, they are
the fleet's fault protection.

## Benchmark that must pass before this becomes permanent

`tests/test_watchdog.py`, preregistered:

1. **Control state.** `safe_mode.json` classifies CONTROL; an agent write
   is refused, a harness write allowed; it is enumerated in the
   promotion-leakage suite; `clear` refuses inside an agent task.
2. **Limits from ledgers.** From a synthetic `agent.log` and spend file:
   a tool-error rate over the window trips at the declared ceiling and
   not below it; a crash count trips; a refusal streak trips and a broken
   streak does not; spend velocity trips; every metric is reported with its
   observed value even when nothing trips; `enabled = false` evaluates to
   no trips whatever the ledgers say.
3. **Enter, hold, clear.** `enter` writes the mode with its trips; `active`
   reads it; a second trip does not overwrite the first episode; `clear`
   (owner) archives the episode with the reason and removes the mode.
4. **The loop sheds work.** With safe mode active and a task queued, a
   `--drain` run claims nothing, logs `safe_mode_active` and
   `drain_safe_mode_stop`, keeps the heartbeat; after `clear` the same
   drain runs the task to done.
5. **A live trip stops the task at the boundary.** With `refusal_streak_max
   = 2`, a scripted task that claims done twice against a failing gate
   enters safe mode mid-task; the loop stops at the step boundary with the
   task left resumable (not failed, not done); after `clear`, the resumed
   task takes its next scripted step and finishes.
6. **Invariants survive safe mode.** A reconciler with a drifted state is
   still repaired by the idle tick while safe mode is active, model-free.
7. **Registration.** Test declared in `run_all`, `evidence`, `proof`; the
   manual names the commands; the doctor imports the module; prose counts.

## Claim envelope (per docs/DESIGN-P6.1)

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| a limit trips | the metric is in a ledger the harness writes (agent.log, spend file, disk) | a fault that leaves no ledger row (a hung provider call is the heartbeat's job, not this monitor's) | synthetic ledgers with known counts |
| the model cannot clear it | `safe_mode.json` is CONTROL and `clear` is owner-only | the host sandbox's detect-and-revert limit (REMEDIATION): a shell edit is reverted, not prevented, unless docker | `fileauth.resolve` refusal; `controlplane.owner_only` |
| stops at a boundary | the loop checks before each step | a step already inside a provider call finishes that call first | the task's status after the drain |
| invariants kept | reconcilers are model-free and proven | a reconciler whose restore is the thing misbehaving (it halts on its own ceiling) | the repaired file during safe mode |

## What this phase does NOT claim

No diagnosis: the watchdog says which limit tripped, never why. No
automatic recovery from safe mode — a human clears it, by design. No
cross-machine supervision (the heartbeat and an external timer remain the
answer for a dead process). Limits are the owner's numbers; the defaults
are generous and the feature is off until turned on.
