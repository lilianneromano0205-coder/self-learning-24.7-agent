# Phase 9a — Reconcilers: the cluster-controller pattern as a standing responsibility (design, committed before code)

**Status: BUILT** (this document was committed first; the build commit
follows it and cites this file; the benchmark below is green in the
acceptance suite, on its first run). **Branch:** `phase9a/reconcilers`.

## The direction this phase opens

The owner's order of 2026-09-03: *the pre-AI agents that did regulated,
hard work reliably — crawlers, spacecraft autonomy, workflow engines,
cluster controllers — were not intelligent; the work was written down as
executable procedure and the machine replayed it, verifying as it went.
Take the best of those systems, build them beneath the model, and put the
model only at the frontier — without removing or breaking anything already
built.*

The platform already holds a foothold in each lineage, and this series
makes each one a standing, first-class mechanism rather than a shape a
test happens to exercise:

| Lineage | What exists today | What the series adds |
|---|---|---|
| cluster controllers (desired state, observe, reconcile, level-triggered, backoff) | `runbook.reconcile` — one goal, one pursuit, then it stops | **9a: reconcilers** — a declared state kept true forever, with backoff and halt |
| spacecraft fault protection (limits, safe mode, watchdogs) | budgets, breakers, heartbeat, stop conditions | **9b: watchdog and safe mode** — declared limits and a fleet-wide safe mode |
| crawlers (frontier, change detection, politeness, checkpoints) | ingestion crawl with checkpoints; freshness scans | **9c: change sentinels** — hash-diff watches over files and owner endpoints that fire gated work |
| workflow engines (durable steps, timers, compensation, idempotency) | workflows, procedures v2 (retry, compensate), effects ledger | already present; 9-series adds nothing here beyond what 9a–9c consume |

Every addition is deterministic and model-free by construction. The model
is reached only where these mechanisms stop: a drift no proven procedure
can repair, a limit that trips, a change whose meaning must be judged.

## What a reconciler is

An owner declares, in `reconcilers.json` (CONTROL state — the worker's
file tool cannot write it):

```json
{"id": "rc-…", "name": "config-pinned",
 "desired": [{"predicate": "file_equals", "path": "out/config.txt", "value": "v1\n"}],
 "restore": "proc-pin-config",           # a PROVEN runbook or compiled procedure
 "inputs": {},                           # typed inputs for a compiled procedure
 "every_s": 300, "backoff": {"base_s": 60, "max_s": 3600},
 "max_failures": 3, "status": "armed", "failures": 0, "next_due": 0}
```

`desired` is a list of predicates over the observable algebra
(`operators.validate_predicate`); `restore` names a procedure whose trust
is read from the runbook trust ledger at every tick.

## The controller loop (level-triggered, like every controller that lasted)

`reconciler.tick(root, agent=None)` — one held critical section per expert,
skipped when another process holds it — evaluates every armed reconciler
whose `next_due` has passed:

1. **Observe.** Every desired predicate, through `operators.observe`. All
   true → record `in_spec`, reset `failures`, `next_due = now + every_s`.
   Nothing runs.
2. **Trust.** The restore procedure must be `proven`. A candidate or
   quarantined one → record `blocked`, back off, run nothing: an unproven
   procedure does not act unsupervised, exactly as in `runbook.reconcile`.
3. **Act.** `runbook.run(root, restore, inputs, authority=owner grant,
   accept=re-observe desired)` — the same executor every proven procedure
   uses, under the same authority the zero-model route grants
   (`workspace-write` plus the owner's `db_write`, `git_write`,
   `http_write` tokens), with the acceptance callback being the desired
   state itself, so the trust ledger records an *accepted* win only when
   the state was actually restored.
4. **Verify.** Re-observe. All true → `repaired`, failures reset. Else →
   `failed`, `failures += 1`, `next_due = now + min(max_s, base_s ×
   2^failures)`.
5. **Halt (fault protection).** `failures >= max_failures` → status
   `halted`, a question appended to `blocked.md` naming the reconciler and
   the failing predicates, and no further action until the owner runs
   `reconciler.py resume`. A controller that cannot converge stops rather
   than loops — the same rule `runbook.reconcile` applies to a goal.

Every tick appends a row to `logs/reconciler.jsonl` and, when run from the
loop, logs `reconciler_observed | reconciler_repaired | reconciler_failed |
reconciler_blocked | reconciler_halted` events. The loop runs the tick on
its idle cycle beside the prospective tick; `python reconciler.py tick`
runs it from cron or a systemd timer without a loop at all.

**No model is called at any point.** A compiled procedure that reaches a
model step returns `MODEL_REQUIRED` (inapplicable) and the reconciler
records `blocked` — a restore that needs a model is not a reconciler's job,
it is the frontier.

## Owner surface

`python reconciler.py add --root R --name N --desired '[…]' --restore P
[--inputs '{}'] [--every-s 300] [--max-failures 3]` (owner-only:
declarations are control state) · `list` · `tick` · `pause` · `resume` ·
`remove` · `status`. No panel surface in this phase.

## What measurable capability this adds

A proven procedure becomes a **standing invariant**: a state the owner
declares is kept true continuously with zero model calls, and the moment
it cannot be kept the machine stops and says so. Before this phase a proven
procedure ran when a matching task arrived; after it, the state it produces
is *owned*.

## Benchmark that must pass before this becomes permanent

`tests/test_reconciler.py`, preregistered:

1. **Control state.** `reconcilers.json` classifies CONTROL; an agent
   write is refused, a harness write allowed; it is enumerated in the
   harness ledgers and the promotion-leakage suite; `add` refuses inside an
   agent task; a malformed desired predicate refuses at `add`.
2. **In spec, no action.** Desired true → the tick records `in_spec`, the
   restore never runs, the trust ledger is untouched.
3. **Drift repaired, model-free.** A file drift under a PROVEN restore
   runbook → the tick runs it, re-observes, records `repaired`; the trust
   ledger records an accepted win; the model-call ledger is untouched.
4. **Fail closed on trust.** The same drift under a CANDIDATE restore →
   `blocked`, nothing runs, the file stays drifted.
5. **Backoff and halt.** A restore that cannot make the state true →
   `failed` with exponentially growing `next_due`; at `max_failures` the
   reconciler is `halted`, `blocked.md` gains the question, further ticks
   run nothing; `resume` re-arms with failures reset.
6. **Loop integration.** A `--drain` run with an armed reconciler and a
   drifted file repairs it from the idle tick with zero model calls and
   logs `reconciler_repaired`.
7. **Registration.** Test declared in `run_all`, `evidence`, `proof`; the
   manual's command table names every subcommand; prose counts move.

## Claim envelope (per docs/DESIGN-P6.1)

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| kept true | predicates observable through the algebra; a proven restore | a state the algebra cannot express (browser, GUI, a remote without an endpoint) | independent read of the file / database / fixture |
| model-free | `runbook.run` and `procedure.execute` never call a model | a restore with a model step — refused as blocked | the model-call ledger unchanged |
| halts, never loops | `max_failures` finite | a restore that flaps (succeeds, then drifts again within `every_s`) is repaired each time and counted — flapping is visible in the ledger, not prevented | the ledger rows and `blocked.md` |
| single controller | one held lock per tick | two experts declaring reconcilers over one shared file (each converges independently; they may fight — the owner's declarations, not the platform's) | lock semantics |

## What CI found on this branch

The pull-request run of PR #16 failed on one job (windows-latest, Python
3.11) while the push run of the same commit and the five other jobs
passed: `test_swarm`'s ledger hammer — four threads appending 25 events
each to a goal's event ledger — lost one thread to `TimeoutError: lock
busy` and the ledger held 75 rows. Not a reconciler defect: the lock's
spin slept a fixed 50 ms, so waiters woke in lockstep and the same
appender kept losing the race; on a loaded runner it starved past the
10 s deadline, and `contract.event` let the timeout kill the thread and
drop its rows. Locally the same hammer at 12 × 50 finishes 600/600 in
under five seconds, three rounds running — the defect needs a slow disk,
which is why a computer this project does not own found it. Two changes,
neither weakening a control: the lock's spin is jittered (20–80 ms), and a
timed-out acquisition in `contract.event` is retried a bounded number of
times before it is allowed to raise — the retry happens before the append,
so it can never double-write, and a row is never silently lost.

## What this phase does NOT claim

No new state world, no new predicate, no model behaviour. No panel. No
multi-machine controller. Convergence is only as good as the proven
procedure; a reconciler is a way to *own* a state, not to learn one.
