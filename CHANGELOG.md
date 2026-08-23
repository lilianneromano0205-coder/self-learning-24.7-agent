# Changelog

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
