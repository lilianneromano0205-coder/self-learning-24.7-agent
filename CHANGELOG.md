# Changelog

## v9 — an outside reader found the gap between two authorities (2026-08-29)

An external audit read the implementation rather than the README and made
eleven specific claims. **Every one was reproduced before it was fixed**, and
the reproduction is what decided the priority — two of the eleven turned out
to be worse than described, and one turned out not to be a defect at all.

The headline is the one that made the rest matter.

### The control plane had two doors and one lock

`fileauth.py` puts containment in a typed ZONE, and the `write_file` tool has
refused to touch control state ever since. `policy.py` screens what a model
may run, and says in its own docstring that it reads a STRING and cannot
follow the program that string starts. Both are correct. Between them was an
invariant neither owned:

```
write_file("settings.toml", ...)                        -> REFUSED
run_command('python -c "open(\'settings.toml\',\'w\')..."')  -> exit 0, WROTE IT
```

Measured on the shipped default (`sandbox = "host"`) through a real
practitioner task: `settings.toml`, `prompts/constitution.md` and
`approvals/*.json` were all rewritten by a model-written command while the
file tool was being refused three lines earlier in the same transcript. The
roles that hold `run_command` are practitioner, examiner, ripper and the
default role — `settings.toml` gives them no `tools` list, so `allowed_tools`
grants them everything. Not a corner case; the shipping configuration.

Switching to `sandbox = "docker"` did not fix it either. The container
bind-mounted the whole expert root **read-write** at `/work`, so the container
improved host isolation and left the agent's own authority inside the mount.

**`controlplane.py`, the sixth authority.** It brackets every model-authored
execution and is honest about the difference between its backends: on docker
each control path is bound **read-only** and the write is *prevented* by the
kernel; on `host`, where there is no boundary to prevent with, the zone is
sealed before the command and verified after — a change is *reverted*, the
command is reported `exit=3` whatever it returned (so no gate can pass on a
run that edited the gate), and the attempt lands in
`logs/controlplane.jsonl`. The sealed set is **derived from `fileauth`'s
zones**, never listed a second time.

Two things the audit did not reach, found while fixing what it did:

* **`identity.md` was agent-writable through the ordinary file tool.** It is a
  system-prompt source — `system_sources()` puts it in every window, right
  after the constitution — and the panel writes it *for the owner*, with a
  backup and a `"by": "owner"` history line. It classified as ZONE_ROOT, so
  even the Rule-of-Two roles that hold no shell could rewrite their own
  charter. `acquisitions.json` (the ledger whose own docstring says "the OWNER
  grants trust. Never the agent") and `training/` were in the same position.
* **`goals/*/events.jsonl` cannot be treated as append-only.** The first
  version of the seal allowed ledgers to grow. But `contract.replay` rebuilds
  a contract's state purely from that ledger and lets it overrule the
  snapshot — so an appended line is a verdict, not a note, and "it only
  appended" would have let a worker append `{"kind":"state","to":"verified"}`.
  Growth is now exempt only when the harness itself declared the append.

`tests/test_controlplane.py` is the regression the audit asked for: every
control path `fileauth` declares, crossed with every way a shell changes a
file, driven through a real loop task by a role that really holds
`run_command`. **100 attacks, zero durable changes.** With the seal disabled it
fails on every control path, so it is a test of the fix rather than of the intent.

And it stays cheap. The first seal re-read every control file on every
command: on a fleet with three thousand approvals that measured **27 seconds
per command**, and a runbook issues one per step. Stat-gated caches took the
same fleet to **373 ms**, a new expert to 5.5 ms — with an asserted ceiling in
the test, because a safety control that gets slower every month is one
somebody eventually turns off.

### The other ten

| # | Defect | Measured |
|---|---|---|
| 1 | **The course lock was not part of the claim.** `can_lock` ran outside the mutex that claimed the task, and `next_task`'s resume branch never consulted it at all. | Two loops on one course: the queued-vs-queued race needed a ~0.5 ms window; the **resume** path needed no luck and was reproduced end-to-end with two ordinary `loop.py run --drain` processes. |
| 2 | **`step_failed` matched `"exit=1"` with `startswith`.** | Exit 2, 3, 5, 7, 42 and 255 all read as SUCCESS; 13, 124 and 127 were caught by accident of their first digit. So a visibly failed command never moved the escalation counter, and gotcha retirement could take a failed step as proof the gotcha was gone. |
| 3 | **A re-exam was marked done when the task was QUEUED.** | scheduled → queued → permanently done, whether the examination succeeded, failed, or never ran. `schedule.json` came out byte-identical in the success case and the total-failure case, which is why the existing test could not see it. |
| 4 | **`memory.search`'s expert filter was `pass` where it needed `continue`.** | An alpha-scoped query returned the fleet home's own courses — *and stamped them with alpha's name*, so the obvious assertion ("every hit is expert X") passed while it leaked. |
| 5 | **"Every provider call is metered" was false.** | Five model-provider call sites in the tree; one metered. Groq Whisper transcription and the OpenRouter vision rail spent real money outside every ledger, and `loop.py check` billed a live token per role. The `model-gateway` proof boundary listed `modelgateway.py` and `modelrouter.py` — neither of which calls a provider. |
| 6 | **`sources.PROOF` expected arXiv at tier 1** while the registry had been corrected to tier 2. | The self-test whose stated job is "a future edit that quietly re-rates the web fails here, in one second" had **no caller** — not in tests, CI, `doctor.py` or `preflight.py`. A self-test nobody runs is a comment. |
| 7 | **Charter trials shared a root.** Base always first, nothing reset between arms. | A battery gated on `test -f out/thing` is satisfied for the variant by the file the *base* wrote. The confound was systematic, not noisy, so it pointed the same way every time and read as a result. |
| 8 | **The training registry governed a bare number.** | A caller-supplied `eval_score` with nothing behind it; `promote` compared it to a baseline and called that a held-out gate. |
| 9 | **A runbook earned trust from its own `verify` lines.** The docstring already promised "AND the caller's own acceptance test passed after". | `test_swarm.py` builds exactly the failing case — a procedure that verifies its own step and produces the artifact the graders reject — asserts the contract is not verified, and never looked at the trust counter, which went up on the same run. |
| 10 | *(not a defect)* The held-out suite's tasks are in source. | `evalsuite.py` says so itself: "This module cannot stop you peeking; it can refuse to let you forget that you did." No overclaim to fix. |

Fixes, in the same order: the course lock is taken inside the state mutex that
claims the task, and `adopt_task` consults it too; `step_failed` parses the
exit code and a run_command result is judged by that code alone; a re-exam
entry closes on the task's terminal status and a failure re-queues, bounded,
then records `outcome: "failed"` — *unexamined* being a different and more
honest thing than *passed*; the filter continues; every provider call site is
metered and `modelgateway.audit_sources()` makes the invariant checkable the
way `execution.audit_sources()` already did for the shell, with the two
genuinely free sites declared by name; the proof table is corrected **and
wired into the suite**; each trial arm runs in its own clone of the expert, so
arm order can no longer explain a result; `training.register` requires the
evaluation's own output and pins its sha256 beside the score, records
`score_origin: "declared"` in as many words, and refuses from inside an agent
task along with every other owner-level CLI; and a runbook win counts toward
`proven` only when the CALLER'S acceptance test passed afterwards, with the
swarm's reducer — not its workers — filing the outcome.

### The second wave: what the fix pass itself turned up

Closing the eleven above meant reading the neighbourhood around each one, and
that found **eighteen more**, every one reproduced before it was fixed. Two
were worse than anything the external audit reached.

**A second control-plane bypass, needing no shell at all.** `candidates.py`
is the best-of-N engine: it stashes each attempt's artifacts and restores the
winner. It reached the filesystem with `os.path.join` and never asked the File
Authority — and the artifact list comes from the task's own `write_file`
STEPS, where a *refused* write is still recorded. `candidates/` classified as
ZONE_ROOT, so a worker could write
`candidates/<id>/<n>/score.json` declaring `artifacts:
["prompts/constitution.md"]`, drop its own constitution beside it, and let the
loop's own `_promote_best_attempt` copy that over **the first block of every
system prompt**. Naming `../../../../OUT.txt` as an artifact made `promote()`
write outside the expert root entirely — the reproduction created a file in
the user's home directory. Both reachable with `write_file` alone, so the
Rule-of-Two roles that are deliberately denied a shell could do it. Every path
in that module now crosses `fileauth.resolve` with the agent's own rights.

**A duplicate dict key deleted a capability — one this pass had just added.**
`proof.REGISTRY` already used `"control-plane"` for the panel. The new
worker-authority entry took the same name ninety lines above it, and Python
keeps the last of two identical keys and says nothing: both read fine in the
source, one did not exist at runtime. `check_registry_keys_are_unique` now
parses every dict literal in the platform's AST, because `in REGISTRY` cannot
catch a collision that has already resolved.

**Seven more paths were read into a prompt or a decision while the agent could
write them.** The same walk that found `identity.md`: `commons-digest.md` (the
fleet-lessons block of the agent's own context), `missions/*/mission.json` (the
objective `context.compile` recompiles into every window "so it cannot
drift"), `mastery/*/events.jsonl` (what `verdict` computes MASTERED from),
`commons/quarantine.md` (a fleet-attributed "this claim was withdrawn" the
premise checker tells the next window to obey), `capabilities/` (the isolated
install the capability probe imports from), `identity.history.jsonl` and the
`identity.md.bak-*` rollback copies. All CONTROL now.

`courses/*/sources.json` could not be zoned — the agent runs `ingest.py
add-url` itself and that records sources — so the **tier is derived instead of
trusted**: recomputed from `classify()` on read, which is the answer
`record()` stored honestly and not the one a forger stored. A genuine owner
override moved to `courses/*/source-overrides.json`, which is control-zoned.
Before: a worker could rate a forum thread tier 1 and forge `override: {"by":
"owner"}`, and this module's own docstring calls false authority in the
learning pipeline "the one contamination that compounds".

**Exactly-once was three steps with nothing between them.** `mcp.guarded_call`
did `lookup` → `unfinished` → `begin`, each locking only its own read or
append — so the ledger was never corrupt and the guarantee was never there.
Two processes retrying one task could both find nothing recorded and both hit
the world: a second wire transfer, a second email. Now one per-effect lock
spans the whole claim, released before the call so a sibling arriving mid-call
sees the `started` row and stops.

| # | Defect | What it cost |
|---|---|---|
| S1 | **The community-skill script guard was a substring test.** | Four ordinary spellings ran the untrusted script: `cd skills/x/scripts && python run.py`, `python -m skills.x.scripts.run`, a doubled separator, and `sh -c`. All measured. Now normalised and matched at a path boundary. |
| S2 | **The SSRF guard judged IPv6 by string prefix.** | `::ffff:169.254.169.254` and `0:0:0:0:0:ffff:a9fe:a9fe` — both the cloud metadata endpoint — passed, as did `http://2130706433/` and `http://0x7f000001/`. Ingestion is the lowest-privilege input here: one line in a `.url` file dropped in `inbox/`. `ipaddress` replaced the hand-written table. |
| S3 | `is_video_url` matched VIDEO_HOSTS against netloc **and path**. | An article titled "why-tiktok.com-is-dying" was routed to the video downloader and never fetched as a page. |
| S4 | `_probe`'s malformed-response check raises `IndexError`; its handler tuple listed `KeyError`. | One provider answering 200 with an empty `choices` killed the whole `loop.py check` sweep, from a function whose docstring says it "reports reality". |
| S9 | `designcheck.thresholds_for` had **no monotone combiner for `require_responsive`**, so it fell through to a raw assignment. | Its first line promises "a course's standards can RAISE the bar, never lower it" — and a worker failing the design gate could write `require_responsive: false` into its own `standards.md`, which lives in the workspace. An unknown key is now refused rather than trusted. |
| S10 | `context._Source.add_text` truncated with a bare slice and recorded `"trimmed": False`. | The Context Window Viewer reported a block as fully included while the model got it cut mid-sentence with no pointer to the rest — and a gotchas block is a BINDING instruction. |
| S11 | **The panel never wrote to the org audit trail.** `ui._may` called `org.check` and nothing recorded that the actor then did it. | `org.py` opens with "every mutation attributable". In a shared fleet a named member could mint experts and queue work through the panel and `org/audit.jsonl` gained zero rows. |
| S12 | `evalsuite.py` documented a two-arm bare-vs-harness comparison. | There is no bare arm; `run_split` hardcodes `arm: "harness"`. The docstring now says so and points at `benchmark.py`, which really does run both. |
| S21/S24 | `contract.transition` was an unlocked read-modify-write over a **shared `.tmp`**. | Measured with two threads on one contract: the losing transition died on `PermissionError` — a legitimate move failing with a rights error instead of a contract rule — and on a kernel without delete-pending semantics both could have written, recording a jump out of a terminal state that `TRANSITIONS` exists to refuse. The acceptance **seal** append was unlocked too, and a lost seal row makes a goal permanently unverifiable. |
| S23/S26 | `blocked.md` and the whole gotcha ledger were unlocked appends, and `gotchas.py` was the one ledger with **neither a lock nor a unique temp**. | A lost `ask_human` append is an escalation lost: the task is marked blocked unconditionally, so it waits forever on a question the owner was never asked. |
| S27 | `_exam_tick` recorded an exam as dispatched **on the same beat as `add_task`** — the defect just fixed for re-exams, in its sibling function. | A Student task that died terminally left the exam recorded with a matching content hash and the tick skipped it forever: a course that quietly stopped being examined while the panel kept showing the last score. |
| S28 | The swarm's RULE-4 lease was keyed by **group**; the thing that must not run twice is the **runbook**. | The fan-out gate requires two distinct runbooks across the plan, not per pair — so three groups served by two procedures could run one procedure twice at once, with real `do` commands and real side effects. |
| S8 | Three proof capabilities' `code` boundaries excluded the file that enforces their invariant. | Delete `CONTROL_PATHS` from `fileauth` and an agent marks its own skill proven while `skills-provenance` stays green. Same shape as the model-gateway boundary above. |

Refuted, and worth recording as refuted: `sources.classify` does **not** tier a
lookalike host (all four spellings came back tier 3); `memory.retire` has no
prefix-matching handler loop; `prospective.py check` does **not** consume an
armed intention when it runs without an agent — it returns 0 and changes
nothing.

**The suite: 120 executed, 116 passed, 4 skipped, 0 failed.**

## v8 — three runs on computers we do not own (2026-08-23)

v7 shipped with a green suite and an honest limits list whose twelfth entry
read: *"Windows and OneDrive were the development environment... A CI
workflow now runs the suite on Linux and Windows across Python 3.11–3.13, but
it has never been executed on a real runner from here."*

It has now. **Four of the six jobs failed**, and not one failure was a CI
artefact. Every one was a defect that had been in the codebase the whole
time, invisible because a single Windows laptop cannot see it.

| Job | Result |
|---|---|
| ubuntu-latest 3.11 | **fail** — U15, U16, U17 |
| ubuntu-latest 3.12 | **fail** — U15, U16, U17 |
| ubuntu-latest 3.13 | **fail** — U16, U17 |
| windows-latest 3.11 | pass |
| windows-latest 3.12 | **fail** — U15 |
| windows-latest 3.13 | pass |

Each was then reproduced **locally**, in a Linux container on the development
machine, so every fix was verified against a failing case before it was
pushed. Running the whole suite in that container found two more defects that
CI itself had passed by luck.

**U15 — a task was taken from a live loop and executed twice.** `claim_task`
is a correct cross-process mutex and every *queued* task goes through it.
`next_task` returned any task marked `running` on the theory that a running
task must be one a dead loop abandoned — and the running branch skips the
mutex by design, because a resumed task is already claimed. So a second loop
picked up its live sibling's work and ran it concurrently: six tasks queued,
**fourteen `task_end` events**, one loop crashing into the other, and a
phantom `RETRY` of work that had actually succeeded. A task now records its
owner (`runner_id`, pid, host, timestamp); resumption is conditional on that
owner being *gone*; and the check is re-run under the state mutex so two
loops cannot revive one corpse. On this host liveness is the whole answer —
a loop parked in a twenty-minute provider call is healthy, not stale — while
a lease covers the case liveness cannot answer, another host sharing the
storage. Liveness never calls `os.kill` on Windows, where CPython implements
it with `TerminateProcess`: the POSIX idiom for *is this alive* would have
killed the sibling it was asking about.

The old test could not have caught it. Its exactly-once assertion counted
`task_start` log lines, and the stolen-resume path never logs one — the check
written to prove exactly-once execution was blind to the only path that broke
it. The rule is now asserted deterministically, every branch of it, because a
race that only opens under load is not something to leave to chance.

**U16 — the sandbox handed back a workspace the agent could not write to.**
`docker run` carried no `--user`, so commands ran as root inside the
container. On Linux a bind mount is a real host directory, so the agent's own
`out/` came back owned by `root` and the agent could no longer rewrite,
gate, archive or clean what it had just produced — in the backend the manual
recommends for untrusted work. Docker Desktop remaps ownership, which is why
this was invisible on Windows. Now `--user <uid>:<gid>` on POSIX, with
`HOME=/tmp` for a uid that has no passwd entry. Dropping root inside a
container that holds a bind mount is better isolation as well.

**U17 — a secret created world-readable, caught by the platform's own
preflight.** `preflight.py` exited 2 on Linux with *"ui-token.txt is readable
by other users (mode 0o644)"*. That check is gated on `os.name != "nt"` and
had **never executed once** in the project's life. It was right: the platform
was correct and a *test* had written the token with a bare `open()`. The gap
underneath was real though — `credentials.py` could recognise a secret but
had no way to create one, so three modules each rolled their own `open` +
`chmod` and a fourth writer forgot. `credentials.write_secret()` is now the
one way: the file is created `0600` rather than corrected afterwards, and the
replacement is atomic. `federation.py` had the subtler version — it wrote
through `atomic_write_json` and chmodded after, but `os.replace` carries the
*temp* file's mode onto the destination, so that chmod was closing a door the
file had already walked through.

**U18 — an evidence sentence that was false wherever it ran.**
`test_docker_live.py` printed "on a Windows host" unconditionally, and these
sentences are quoted verbatim into the published `EVIDENCE.md`. The logic was
wrong too: a Debian `os-release` proves isolation on a Windows laptop and
proves nothing on a Debian host. Isolation is now proven by a fact that holds
anywhere — the container answers under its own hostname, not this machine's —
and the host's name and absolute paths are deliberately kept out of the
published report.

**U19 and U20 — staleness decided by comparing two files' timestamps.** Found
by the local Linux reproduction, not by CI. `conflicts.refresh` rescanned only
if the newest `notes.md` was modified after `conflicts.json`; `commons.digest`
re-curated only if `lessons.md` was modified after `lessons.curated.md`. Both
read like caches and behave like races. Measured inside a container: **200
files written back to back produced nine distinct timestamps**, and two
consecutive writes routinely land on the identical `st_mtime_ns`. On
overlayfs — every container, including this project's own Dockerfile — the
clock behind file timestamps is cached, not read per write. So new course
material was silently un-scanned, and new fleet lessons never reached the
block injected into every agent's context. Both now answer from a SHA-256 of
the material. A hash cannot be fooled by a clock.

**The class is now barred, not just the two instances.**
`test_invariants.py` parses every module in the platform and fails the build
if any comparison has a file timestamp on both sides. Comparing a file's age
to the wall clock stays allowed — that is how every lock here expires. Run
against the previous release it names `commons.py:284` and
`conflicts.py:322`, and nothing else.

**Five mutations added**, 10 → 15. Three are declared POSIX-only and skipped
out loud on Windows rather than reported as passes, and each now states its
own reason rather than sharing a blanket one — two because modes are not the
mechanism there, the third because the container cannot even start. On a
platform where the property does not apply, MISSED would be a false alarm and
CAUGHT would be a lie; the only honest verdict is a refusal to score.

**U21 — and then the mutation harness itself was caught lying.** With the six
above fixed, CI went from four failing jobs to one, and the survivor failed at
a different step: not the suite, which was green on all six, but the mutation
check on ubuntu-3.12. `docker: credentials passed through` came back MISSED
after four releases of CAUGHT on Windows.

Applying it locally and reading the failure rather than the verdict:

    line 90, check_it_runs_somewhere_else
    AssertionError: (127, '', 'exec: "sh": executable file not found in $PATH')

The mutation forwards the host's whole environment into the container. On
Windows that injects `PATH=C:\...` into Linux, `sh` is not found, and the
container never boots — the test died at its FIRST check and the credential
assertions never ran. The green row was certifying a test that had not
executed. It was also aimed at the wrong layer: `sandbox.run` scrubs
credentials before `_docker` is reached, so the mutation broke the second of
two redundant filters and the property survived on its own. Linux was right.

Fixed by asserting what that second filter actually defends — the docker test
now enumerates every variable the container received and requires each to be
`AGENT_*`, `PYTHONUTF8`, or the image's own, using the `HARMLESS_SETTING`
probe that had been planted in the test's environment and never checked — by
renaming the mutation to what it breaks and marking it POSIX-only with its own
stated reason, and by adding a mutation that attacks the control which really
defends credentials: `scrub_env` removed from `run()`, caught by
`test_secrets.py` in one second on both platforms.

The lesson is the reason U21 is the longest entry in the audit record: a
mutation harness reports two things and only one was being checked — whether
the test failed, and whether it failed **for the reason claimed**.

**U22 — a settle window of zero behaved as a window of forever.** Run three:
five jobs green, and windows-3.12 — which had passed run two — failed on a
bare `assert n == 1`. The platform's own log line named it:

    reading list.urls: still settling (modified <0s ago), next scan

`scan_inbox` skips a file still being copied in, via `time.time() -
getmtime(src) < settle`. At `settle = 0` that guard is inert only while the
age is non-negative — and the filesystem's clock is not `time.time()`. On a
virtualised host a file written a moment ago carries an mtime a hair AHEAD of
the wall clock, the age goes negative, and a setting documented as "no
settling required" means "never ingest this file". The shipped default of 10
absorbs it; an operator who reads 0 as "off" gets an inbox that silently
stops working.

Writing 3000 files on the development machine and stat'ing each immediately
produced **zero** negative ages, worst skew 0.000 ms. The defect is not rare
on this hardware, it is invisible on it.

The regression test does not wait for the skew, because waiting is exactly
what does not work: it forces one with `os.utime(f, time.time() + 5)`,
asserts the mtime really is in the future, and requires ingestion anyway —
then proves the fix did not simply disable the feature, by holding a fresh
file back for a 30-second window and releasing it once it ages.

U22 sits in the case the new AST invariant deliberately **permits**: it bans
comparing two files' timestamps and allows comparing one against the wall
clock, because an age is sound. An age is sound; assuming it cannot be
negative is not. The invariant's docstring now records that edge, and the
sentence it prints into `EVIDENCE.md` no longer claims the remaining sites
are beyond corruption — one of them was.

**A small proof that the proof system is not decorative.** Late in this pass a
*comment* was edited in `conflicts.py` — no behaviour changed at all. The next
`python proof.py` reported `memory-institution` at **IMPLEMENTED (expired
evidence)** rather than OFFLINE VERIFIED, because that file is one of the six
the capability is built from and the recorded evidence was bound to the old
code hash. The badge returned only once the evidence had been re-earned by
re-running it. Nobody could have typed it green: levels bind to 37 source
files, no endpoint accepts a level, and documentation is deliberately not
among those files — so editing this changelog cannot move one.

## v7 — the interface stops being the architecture (2026-08-23)

Implements the **UI/UX Product Redesign Specification v1** end to end, on top
of the Five Authorities and the Proof System that the forensic audit's
remediation added (see `REMEDIATION.md`). 90 → 93 acceptance tests, all
passing.

The spec's diagnosis was blunt and correct: the app exposed the implementation
map instead of the user's job. Seven top-level areas and seven per-agent views
forced an operator to understand *Teach / Board / Mind / Ask / Identity /
Wiring*, memory internals, model names and system machinery before they could
get any work done. Nothing in this release was deleted to fix that. Every view
that existed still exists and still does the same thing; what changed is where
it is filed and what it is called.

**Navigation follows jobs (§2, §16).** `Home · Work · Agents · Resources ·
Proof · Admin`, each with a stated purpose in `NAV_PURPOSE`. Memory became
Resources → Knowledge; Models and System became Admin tabs; Guide became
contextual help reachable from the palette. `tests/test_frontend.py` now
asserts the migration itself: every retired top-level view must still be
routed AND reachable from a control a person can click. A redesign that
silently drops a screen loses whatever only that screen could do.

**Home answers "what can I ask it to do?" first (§3).** A command bar, four
primary actions, an Active Work card that shows each mission's objective,
progress against its criteria, current action, cost and next blocker, a
Recently Completed list with proof, and a Platform Health line that says
"Ready", "1 blocker" or "2 risks" and links to Admin and Proof.

**Creating an agent no longer requires knowing the taxonomy (§4).** Five
intent questions map invisibly to the five lanes, then six steps — Job,
Knowledge, Access, Quality, Cost, Review — ending in a plain-language summary
of what the agent will be able to know, do, spend and change. The lane is
named once, at the end, as a footnote. Lanes that have their own well-made
dialog are handed straight to it: §4's point is that nobody must know the
taxonomy, not that every path must have six steps.

**"Mind" is gone (§5).** It split into **Knowledge**, **Skills**,
**Performance** and **Advanced**. Performance is new: verified success rate,
false successes, the case ledger, cost by purpose, which model actually works
for *this* agent, tool error rates and which computers its work ran on.
Advanced holds identity/prompts, model wiring and the raw file tree — all of
which existed, none of which was reachable without knowing an internal view
name.

**The mission page is the centre of the product (§6).** Objective and
fingerprint, the success-criteria checklist with its evidence, binding
constraints, explicit non-goals, "Needs you" separated from "Blocked on", the
bound-action count, and the contract exactly as the agent sees it under
Advanced. `mission.compile_state` now also derives the current action, the
plan (every action under the criterion it serves) and the cost — so one
request answers every question §15 says a supervisor must answer in fifteen
seconds.

**Computers explain themselves (§7).** Resources → Computers shows zone,
capability, cost, scale-to-zero, last use and who may access each machine, and
the router answers *"Using Office Windows PC because excel + internal-network
are required"* — with a disclosure naming why every other computer was passed
over. A routing decision nobody can disagree with is one nobody can correct.

**Proof is a place (§9).** Work Proof and Platform Proof. Fifteen capabilities,
each with its level, the reason for it, the invariants it must hold, the code
hash the evidence is bound to and the exact command that reproduces it. No
endpoint accepts a level: the panel can re-run evidence and nothing else.

**Training reads as certification (§10).** Sources → Coverage → Gaps →
Exercises → Exams → Competence, per course. The API refuses to compute a
percentage: it returns numerators and denominators, so the page physically
cannot print "100% learned".

**Models became a policy, not a name (§11).** *Cheapest*, *Balanced*,
*Highest quality* or a custom bar — each a name for the two numbers the router
already read. `route_prefer` is new and real: "the cheapest that clears the
bar" and "the best that clears the bar" are different answers to the same
evidence, and the owner is entitled to say which. Every model card carries its
sample size, and a profile under five samples is shown as unrankable rather
than ranked badly.

**Failures say who failed (§12).** One `diagnose()` translates a task record
into *which part failed* (the verifier, the platform, the provider, the budget
breaker, the command, the agent, or you), *what happens next*, and *what you
can do*. Nine classes, each complete. The raw error moved under an Advanced
disclosure; the board shows state **and** reason.

**Onboarding is seven steps that read reality (§13).** Progress comes from
state, not from clicks — creating an agent from the terminal ticks the box
just as well as doing it in the panel. Dismissible, resumable, and it collapses
to one line when finished.

`tests/test_ux.py` is the spec's own §15 acceptance table, executed: eight
flows, each asserting that the information the flow needs is reachable rather
than that the page looks tidy.

### Two things the engineering manual asked for that did not exist

**Roles that actually govern (manual §21).** See defect 6 below — this is the
fix, and it is also a feature: members hold personal panel tokens, every write
is checked against the role behind the credential, and a fleet that belongs to
an organization auto-enables a token because without one there is nothing to
check.

**`metrics.py` (manual §29).** The twelve numbers that say whether any of this
is working — verified success, false success, recovery, goal fidelity,
autonomy, interruptions per mission, cost per verified task, repeat-failure,
tool acquisition and calibration — each read from a ledger another subsystem
already writes, each carrying its numerator and denominator, and each marked
when the sample is too small to mean anything.

The interesting half is what it refuses. Three of §29's metrics cannot be
computed here, and the module names them with the reason rather than
approximating: **supervision-hours** (the denominator is a person's time, which
nothing here observes), **90-day retention** (the structure exists; the elapsed
time does not), and a **safety-violation rate** (every refusal this platform
records is a control *working*; counting refusals as violations would be the
most flattering possible mistake). The autonomy figure names itself an upper
bound for the same reason.

It also reports the **harness contribution** the manual's §14 asks about — a
count of every moment the fleet changed the outcome (a gate refusing a
finish-claim, a retry carrying the failure back in, a gotcha filed, a crash
resumed) with what a bare model would have done instead. Deliberately counts,
never a ratio: §14's "100x" multiplier is *verified output per dollar versus
the same raw model without the fleet*, that needs the same work run twice, the
baseline half has never been run, and interventions-over-completions is a
number that reads as a multiplier and is not one.

Building it found **two defects in itself**, both of the kind this whole pass
has been about — a number that looked right and measured something else:

- verified success counted *tasks* and false success counted *events*, so a
  retried task made three false-success records against one attempt and the two
  rates could sum past 100%. Both are now derived in one pass over
  `state.json`;
- the autonomy ratio read the task record for a marker of having been blocked.
  There is none — a task that stopped, was answered and then finished is
  indistinguishable from one that never stopped — so the metric was silently
  reporting the success rate under a name that promised something else. It now
  reads the log, where `approval_required` and `task_unblocked` are written at
  the moment a person was needed, and the test appends one and requires the
  number to move. (`tests/test_metrics.py`)

### Defects this pass found and fixed

Building against the spec meant driving every path, and five real bugs fell
out of that — none of which a green suite had caught.

1. **A fleet home that was never bootstrapped crashed expert creation.**
   `fleet.create` copies `prompts/` into each new expert, and only
   `bootstrap.py` prepared that directory first. The CLI's `--home <fresh dir>`
   died with a raw `FileNotFoundError`, and the panel's `POST /api/experts`
   turned the same thing into a 500. Four callers, one of them correct — the
   seeding moved into `fleet.create` itself, which is the single gateway all
   four go through. A home that genuinely cannot be prepared now refuses with
   a sentence instead of a stack trace.
   `tests/test_invariants.py::check_expert_birth_paths` enumerates the callers.

2. **An expert could pass an exam and not know it.** The loop's completion
   check reads the canonical `SCORE: 95` line; `selfmodel._exam` looked only
   for a percent *sign*, which that line does not carry. So a course could
   pass at 95, the loop would agree it was complete, and the expert's own
   self-model — the block injected into every context window, and the number
   the panel prints — reported no score at all. Fixed, with an invariant test
   that writes the file in every format the platform has produced and requires
   every reader to return the same number.

3. **Every folder in the file tree was drawn as a clickable file.** The API
   sends `d` for "is a directory"; the panel read `e.dir`, which is always
   undefined. Clicking a folder answered "approvals is a directory". The tree
   now has one implementation, shared by Skills and Advanced, that accepts
   either spelling.

4. **A GPU worker could not be chosen for GPU work.** A machine registered
   with `--kind gpu-worker` was refused unless somebody had also typed "gpu"
   into its capability list — the registry already knew what it was. Every
   kind now declares what it implies, implied capabilities are shown
   separately from declared ones, and implying still cannot paper over a
   capability that is genuinely absent.

5. **The worker routing endpoint returned an object where the panel expected a
   sentence**, so the reason rendered as `[object Object]`. It now returns the
   sentence, the requirements, and what each rejected computer could not do.

6. **`org.check` — "the single question every mutating path asks" — was asked
   by nothing but `org.py` and its own test.** Not by `ui.py`, which is the
   main mutating path with 17 POST routes, a PUT and a DELETE. The reason was
   structural: the panel authenticated with one shared token, so it had no
   subject to check. Creating an organization therefore did almost nothing —
   roles were enforced on the command line, and the audit trail's author came
   from a request field, so anyone with the panel token had every permission
   and could attribute their actions to somebody else by typing their address.
   Members now hold **personal bearer tokens** (stored as a SHA-256, returned
   once, compared in constant time); `_authed` resolves the token to a member
   before every request; `_may_write` looks the required permission up in a
   **declared table** whose default is strict, so a route added tomorrow is
   refused for a viewer rather than waved through; the audit records the
   credential's owner; and an authorisation refusal is a 403 rather than a
   500. A solo install is untouched. (`tests/test_rbac.py`)

7. **`except KeyError -> 404 "unknown expert"` also caught a missing request
   field**, so a POST that forgot `role` answered "unknown expert" about an
   expert that plainly existed. `NoSuchExpert` is now its own type and a
   missing field is a 400 that names the field.

8. **The panel scrolled sideways on a phone.** A CSS grid item keeps
   `min-width:auto` and refuses to shrink below its widest child, so the
   Performance tab's table pushed the document 81 px sideways at 375 px — the
   table's own scroll container could not help, because the *column* was what
   would not narrow. Two tables also had no scroll container at all; the
   wrapper moved into `taskTable()` so it is correct wherever it is dropped.

## v5 — the harness becomes an inspectable object (2026-08-21)

Research-led pass over harness, loop, context, memory, sandbox, skills and
UI, applied to all six systems. 53 → 70 acceptance tests, all passing.

**Harness (M1).** `harness.py`: a machine-readable manifest of every tool,
gate, policy, memory tier, budget, loop event and file hash;
`check_contracts()` and a sub-300 ms `integrity()` health ritual the loop
performs at start (`logs/health.json`). `doctor.readiness()` prints the
numbered list of what stands between this install and a real run — naming
ENV VARS, never values. `tests/test_faults.py` deliberately breaks each
validator to prove the validators themselves work.

**Loop (M2).** Tasks carry a declared `stop` condition (criteria, max
attempts, deadline, max steps) that the harness enforces and compaction
preserves. `checkpoint.py` gives long tool work fiber-style recovery — a
transcription that dies at chunk 17 resumes at 18. `POST /api/experts/<s>/wake`
lets any external system wake an agent; armed `event` intentions fire at once
with the payload fenced as data.

**Context (M3).** `context.py` compiles every window from budgeted sources
and writes a manifest (`contexts/<id>.compile.json`); over-budget files are
trimmed with a pointer to read the rest. Compaction now clears large tool
results to an archive pointer before summarizing. The panel shows the exact
window per task.

**Memory (M4).** Environment gotchas and premise awareness became first-class
memory kinds; a memory router decides which kinds each role may see (the
student stays closed-book even against an owner override); the commons
adopted ACE-style grow-and-refine curation over an append-only ledger.

**Sandbox & skills (M5).** `sandbox.py` makes execution a backend interface
(host/docker/e2b/daytona) that fails closed. Skills adopted the open
`SKILL.md` folder format with import/export, plus provenance tiers —
community skills are injected with a warning and their bundled scripts are
refused until the owner promotes them.

**Governance & routing (M6).** Charter variants may declare a prediction;
promotion is refused when it does not hold. `modelrouter.py` routes to the
cheapest model that has earned the bar on this expert's own gated work.
`routines.py` turns a finished task into a skill plus a schedule.
`trace.py` builds one trace per task and per-tool error rates.

**UI (M7).** A live SSE event stream replaces polling; teammate rail; team
runs read as threads; goal plans and workflow pipelines are visible; approval
cards carry what was done / this step / what's next; agents may return
structured cards from a closed catalogue; the owner can edit an agent's
identity and pin fleet-wide rules; phone-first layout with a bottom nav.

**Run it today (M8).** `bootstrap.py` — one idempotent command from an empty
folder to a running panel, exit 2 with a numbered TODO when something blocks.
`MANUAL.md` documents every module, setting, endpoint and event name.

### Defects found by verifying instead of assuming

Driving the real panel in a real browser, and chasing two suite flakes to
their root, turned up four bugs that no green test had caught:

1. **Mobile navigation covered the entire screen.** The bottom-bar rule set
   `position:fixed; bottom:0` but inherited `top:0; height:100vh` from the
   desktop sidebar, so the nav stretched over the page. (`top:auto`.)
2. **A consultation id had one-second resolution** (`c-%Y%m%d-%H%M%S`), so
   two consultations arriving in the same second shared a directory and the
   second overwrote the first's question and answer. This also made
   `test_federation` pass or fail depending on whether two calls landed
   inside the same second. Ids now carry a random suffix, and the federation
   round trip is driven deterministically.
3. **An approval decision reported itself as an error.** `answer_task` raises
   `SystemExit`, which `except Exception` does not catch, so granting an
   approval whose task had already finished returned HTTP 400 — the decision
   was recorded, but the owner was told it failed. The endpoint now reports
   the decision and, separately, whether a task was waiting on it.
4. **Capability routing was frozen for the life of the process** (cached per
   role with no expiry) — wrong for a loop that runs for weeks. It now
   re-evaluates every ten minutes.

Two smaller ones: the System page's routines card said "pick an agent first"
in a fleet-level view, and two tests wrote `[agent]` keys past the end of a
`settings.toml`, where they landed inside a `[roles.*]` table and were
silently ignored (a `tests/common.py` helper now places them correctly).

## Awareness, evidence and the design gate

Five new modules, and one security hole closed.

**The hole first.** Every model-written command was handed the whole
environment, so any agent could run `env` and read every API key the platform
holds. DeepSeek Harness names this exact class in its defensive-patterns doc;
the rule is now enforced in `sandbox.py`: credential-shaped variable names are
withheld from every command, the platform's own helpers get exactly the one
key they need for that command shape, and `[agent] command_env_allow` is the
only other way through. A killed command now also reports its timeout
separately from its exit code and keeps the output it produced first, instead
of throwing both away.

**Sources have authority.** `sources.py` records every ingested source with a
tier — normative, professional, instructional, anecdotal — inferred from its
origin and overridable by the owner with a reason.

**Contradictions get ruled on.** `conflicts.py` finds where an expert's own
material disagrees with itself and classifies each case: *authority* (a spec
outranks a blog post), *superseded* (2026 beats 2018), *context* (both hold,
under different conditions) or *contested* (equals — no winner). A contested
point may not be asserted as settled, and the gate refuses answers that try.

**Standards become checkable.** `standards.py` promotes normative claims to a
per-course bar, carrying the tier of the source they came from. A contested
point can never become a standard. Numeric rules raise the design gate.

**The agent knows itself.** `selfmodel.py` compiles a factual self-model into
every context window: what it has verified, its measured competence, its
failure record, its quarantined playbooks, the courses it was never examined
on, and the constraints of the current run. Read from the ledgers, so it
cannot flatter itself — one lucky success reads as "insufficient evidence".

**Taste is enforced by specifics.** `designcheck.py` gates interface work on
contrast, one type and spacing scale, tokens, real breakpoints, the
accessibility floor, and the fingerprints of unconsidered output (the default
indigo gradient, emoji headings, lorem ipsum, everything centred). It is wired
automatically as the definition of done for interface deliverables, so an
agent that calls slop finished gets refused.

Also: a suite flake fixed properly — `test_events` waited on a wall-clock
window for a drain that a loaded machine could delay, and now waits for the
event it actually cares about.

## The complete reference, and what writing it found

`REFERENCE.md` documents the whole build end to end: the harness and its
contracts, the loop step by step with every brake and its default, the five
tools and the four layers that guard them, the context compiler's ten
budgeted sources, all nine memory kinds, the five creation lanes, governance,
the control plane, interop, the on-disk layout, every settings key, every
command, every endpoint, every event name — and section 20, an honest list of
ten things the platform does NOT do.

Writing it was itself a test, because every claim was checked against the
code rather than memory. That found four defects:

* `chief.py --help` and `ui.py --help` crashed with a UnicodeEncodeError on
  Windows — their help text contains an arrow, and the console defaults to
  cp1252. The first command anyone types ended in a traceback. Both now
  reconfigure stdout to UTF-8.
* Four documented CLI invocations were wrong (`goal.py`, `consult.py`,
  `quick.py` and `variants.py` take subcommands the older docs omitted), and
  MCP servers are configured in `mcp.json`, not in `settings.toml` as the
  draft claimed. All 48 documented invocations are now executed as a check.
* Two endpoints were listed as GET when they are POST. All 32 GET endpoints
  are now verified against a live panel.

A third fix to `test_events`, and this one was the real defect. Adding
`health_ritual` to the panel's feed put extra rows ahead of `task_end` in the
stream's replay, and the test asserted `task_end` was among the FIRST TWO
events it read. The two earlier changes (waiting for the event you care about
instead of a wall-clock window) were treating the symptom; the assertion
itself was assuming a position it never had any right to assume.

## Production readiness

An operational audit of the whole build, then the gaps it found, closed.

Already sound and left alone: atomic writes with crash resume, cross-process
locks, log rotation, spend caps on by default and inherited by every new
expert, auto-token when the panel binds beyond localhost, a resource-limited
compose file, systemd units, policy + path containment + env scrubbing.

**`preflight.py`** is new, and it answers the question the other two health
commands do not: if this runs unattended for a month, what will hurt? It
audits cost caps, credential permissions, backups (existence, age, checksums,
expert coverage), disk headroom, provider fallbacks, sandbox choice, harness
contracts, CI, and work waiting on a human. Every finding is a BLOCKER, RISK
or NOTE carrying the exact command that fixes it, and the exit code is the
verdict: 0 ready, 1 risks, 2 blocked. A check that throws is reported as a
failed check rather than taking the audit down.

**`backup.py`** is new, because a platform without a tested restore has hopes
rather than backups. It carries the memory that cannot be re-downloaded —
identities, courses, cited notes, skills, the commons, state, archives — and
never carries credentials, since backups get synced and emailed. Every file
is checksummed; `verify` recomputes them; `restore` refuses a damaged
archive, a non-empty destination, and any entry whose path escapes the
destination.

Smaller fixes: `ui-token.txt` is now written mode 0600 (that token is the
whole fleet), and a corrupted archive is now reported as a blocker instead of
surfacing as "the check itself failed".

CI arrives as `.github/workflows/tests.yml`: Ubuntu and Windows, Python
3.11/3.12/3.13, asserting no dependency file has appeared, importing every
core module, checking harness contracts, running the suite, and building the
package with an assertion that it carries no secrets and no expert data. It
has never run on a real runner from here — the assertions were executed
locally instead.

`REFERENCE.md` gains section 21, Running it in production: the preflight, the
backup procedure and how to schedule it, exposure and access, cost control,
the upgrade procedure, CI, and an incident table. Section 20 gains an
eleventh honest limit: access is single-owner, one token grants everything.

## Prove it, sharpen it, make it drivable

Three asks: stop asserting green and prove it, apply the research where it
genuinely fits, and make the panel drivable.

**Chaos found a real production defect.** `call_model` classified HTTP errors
properly but treated every network error as transient — five retries with
backoff, 60 seconds before the fallback provider was tried. Connection
refused, unknown host and a bad certificate cannot succeed on retry, so one
misconfigured `base_url` cost a minute per step, forever. `permanent_net_error`
now separates verdicts from weather: the first fail over immediately and log
`provider_unreachable`, the second keep the full backoff. The attack that
exposed it used to time out at 60s; the whole seven-attack suite now runs in
20 seconds.

**`tests/test_chaos.py`** attacks on purpose: kill -9 mid-task, six ledgers
corrupted in turn, a dead provider, two loops racing one expert, a write
failing with ENOSPC, an 11 MB input against 1,000 atoms and 200 skills, and
clock skew in both directions. All seven survive — resume, quarantine, fail
over, claim exactly once, keep the old state byte-identical, bind the window,
and honour the stop condition.

**`evidence.py`** replaces "all tests passed" with why. It runs every
registered test, captures the sentence each prints about what it proved, maps
those to the six systems, and writes `EVIDENCE.md` with a **blind spot** per
system. Two rules keep it honest: an unclassified test fails the report, and a
system with no tests prints UNPROVEN. It immediately caught a test I had
claimed but never written, and its first run exposed a buffering bug — the
suite's headers are block-buffered to a pipe and flushed after the output they
label, so attribution was destroyed. Evidence now runs each test itself.

**`candidates.py`** is test-time compute, adaptive and on by default: one
attempt until something fails its gate, then 3, then 5, inside the existing
cost ceilings. Nothing asks a model whether an answer is good — candidates are
scored by the gates that already exist, each applying only where it means
something, with the task's own done_check hard and disqualifying.

**`curriculum.py`** is the fix for learning the dumb way. Material was studied
in arrival order; now the tier-1 specification is studied before the tutorial
covering the same ground, prerequisites are pulled forward by which lesson
defines the atoms others cite, near-duplicates are skimmed for only what they
add, and off-mission material is never studied in depth — each with its reason
recorded before anything is queued. Two metrics were fixed by measurement
rather than taste: 5-word shingles cannot see a paraphrase (0.02 where content
words score 0.38), and Jaccard structurally punishes a long lesson against a
short mission, so relevance is containment instead.

**The panel is drivable.** A command palette on Ctrl/⌘-K searches every
action and shows the terminal command for each, so the panel teaches the CLI
instead of hiding it. Home gains a **six-systems map** — what each system is,
where it lives in the panel, what to type, and what it currently holds. The
production verdict and a verified backup are now one click each.

### Agentic retrieval (the plan's P3, finished)

`research.py` turns a question into an investigation before it is answered:
decompose it into the facts it rests on, retrieve for each separately, and
hand the consultant both what was found and — the part that matters — what
was NOT. A compound question about contrast, focus behaviour and a refund
policy becomes three sub-questions; the two design parts come back with their
atoms and citations, and the refund part comes back as NOTHING FOUND with an
instruction to declare the gap rather than fill it.

Decomposition is deterministic — the grammar of the question and its content
words, no model call — so the same question always produces the same plan.
That is weaker than a model at nuance and stronger at being predictable,
inspectable and free; the retrieval, not the decomposition, is where the
value is. `consult.py` runs it automatically and falls back to the previous
single-shot path if anything goes wrong.

## Confidence, cases, and an independent critic

Answering "what is still useful from the research but not implemented?" —
three things were, and are now built. Everything else in that corpus either
already existed here or requires training weights, which this platform does
not do.

**`confidence.py`** — compute should follow doubt, and we only had the crude
half: escalation on errors and gate failures, never on uncertainty. Every
finished task now carries a measured confidence built from eight signals the
harness already checked (grounding, evidence coverage, contested points,
premise warnings, measured competence, prior experience, gate friction).
Nothing asks a model how sure it is. The band decides what happens next:
high ships, medium earns more attempts, low escalates.

**`cases.py`** — the failure ledger recorded what went wrong and never
whether the fix HELD. A failure now opens a case; a later task that passes
its gate closes it, recording what it did differently; and the same failure
after a fix is logged as RECURRED, which is the most valuable state in the
ledger because it says the obvious fix was wrong. A returning problem carries
that history into its context.

**Critic independence** — nothing stopped every role pointing at the same
model, which turns review into theatre. The preflight now names it.

Three defects of my own, caught by these tests rather than by luck:

* grounding was applied to ANY file an agent wrote, so a practitioner's note
  that cites nothing scored zero and a task that PASSED could rank below one
  that FAILED. Citation grounding now applies only where citations are
  claimed or required — the same flaw existed in `candidates.py`.
* the confidence band never persisted: it was set after the task had already
  been committed, so it lived only in memory.
* a heredoc turned `\b` into a literal backspace byte, leaving a regex that
  parsed, imported and matched NOTHING — silently disabling the citation
  guard entirely. Only the acceptance suite caught it. Every source file is
  now swept for control-character damage.
