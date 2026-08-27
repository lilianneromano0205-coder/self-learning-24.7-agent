# The Goal System, complete — every piece, every loop, and why it is built this way

**What this document is.** The single end-to-end account of the goal system:
what happens from the moment you type a goal to the moment the system says
`verified` — every module, every loop, every file it writes, every defense,
the research each design decision stands on, and an honest list of what is
still missing. The rest of the platform (the task engine, the five
authorities, the memory institution) is covered to the depth the goal system
needs it; [ARCHITECTURE.md](ARCHITECTURE.md) and
[REFERENCE.md](REFERENCE.md) go deeper on those.

**Where the claims come from.** Every "this works" in this document names
the test that proves it, and every protection has been *broken on purpose*
(mutation testing) to prove the test would notice. 40 mutations across
the goal layers (contract, runbook, repair, swarm, mastery, steering,
freshness, the declared state machine), 40 killed. Full suite: 116
tests, green on six CI platforms (Ubuntu + Windows × Python
3.11/3.12/3.13).

---

## 0. The one paragraph

You give the system a goal and — this is the part everything else serves —
**a definition of done it cannot argue with**. The system then tries the
cheapest honest path first: if it already owns a proven, machine-executable
procedure for this kind of goal, it runs it with **zero model calls**,
verifying every step. If parts of the goal are independent and separately
proven, it **multiplies into parallel workers** — but only where you
declared independence, because the controlled evidence says guessing it
destroys work. Only at the **frontier** — the part no procedure covers —
does it spend a model: planning, working, being judged, and being
**overruled twice** if anyone (planner or judge) claims success the graders
refuse. If it gets stuck, it **repairs itself** — but every repair must be
grounded in the recorded mechanical failure, never in the model re-reading
its own work, because that is the hallucination loop with a nicer name.
Every transition is an event in an append-only ledger that can be replayed
and audited. And the only entity in the entire system that can pronounce
the word `verified` is the set of frozen acceptance tests, run by the
harness itself.

## 1. The design law everything follows

> **Never trust a self-report. Capability comes from the system around the
> model, not from the model.**

An LLM with a shell forgets, drifts, and — most expensively — *says the job
is finished when it is not*. That last failure is not fixable inside the
model, because the model is the thing being asked. Your own words for the
requirement: achieve the goal "not in a dumb way, like an AI hallucinating
and thinking it really did the job." The research record agrees and is
cited throughout: models asked to self-correct without an external signal
get **worse** ([Huang et al., ICLR 2024](https://arxiv.org/abs/2310.01798)).

So every layer of the goal system is an answer to one question: *who is
allowed to say something worked, and what stops everyone else?*

| Who might lie | What stops them | Where |
|---|---|---|
| The worker ("I finished") | `finish_task` runs the task's gate command; non-zero exit = refused | `loop.py` |
| The planner (writes easy checks for itself) | frozen acceptance tests it cannot write or edit | `contract.py` |
| The judge ("ACHIEVED") | overruled by milestone checks AND by the acceptance tests | `goal.py` |
| A runbook ("I'm proven") | trust is earned in a CONTROL-zone ledger only the harness writes | `runbook.py` |
| A swarm worker ("my part worked") | workers have no vote; the central graders re-run everything | `swarm.py` |
| A repair ("I fixed it") | repair can move `blocked→running`, never to `verified` | `repair.py` |
| Anyone editing the record | append-only event ledger + replay divergence detection + seals outside the root | `contract.py` |

## 2. Anatomy: where a goal physically lives

Everything is files — no database, no framework, Python stdlib only. One
expert is one directory; one goal is one directory inside it:

```
<home>/                              the fleet home
  org/
    contract-seals.jsonl             ← acceptance-test seals (OUTSIDE any expert)
    grants.json / grant-uses.jsonl   owner authority grants + usage log
  commons/                           fleet-wide shared lessons
  experts/<slug>/                    ONE EXPERT
    settings.toml                    providers, roles, budgets, sandbox
    state.json                       the task queue (the task engine's state)
    goals/<gid>/                     ONE GOAL
      contract.json                  the contract          [CONTROL: worker cannot write]
      events.jsonl                   append-only ledger    [CONTROL]
      goal.json                      pursuit record        [CONTROL]
      goal.md, toolbox.md            what the planner reads
      plan-N.md                      the model's plan for cycle N   [workspace]
      mN-K.md                        milestone evidence notes       [workspace]
      assessment-N.md                the judge's verdict            [workspace]
      repair.md                      the repair signal (small, verbatim errors)
      swarm-<group>.lock             per-group worker leases
    runbooks/
      <name>.json                    machine-executable procedures  [workspace]
      <name>-v2.json                 revisions, beside their parents
      trust.json                     earned trust ledger   [CONTROL]
    courses/, skills/, cases/, gotchas/   the memory institution
```

The zone split is load-bearing: the worker's file tools can write its plans
and evidence (workspace) but are **refused** on the contract, the ledgers,
and the trust file (CONTROL — `fileauth.py`). And because a worker with a
shell could edit files anyway on the host sandbox, the *reference* copies
(seal hashes) live in `<home>/org/`, outside the root the worker operates
in — editing the contract then produces a **TAMPER** verdict, not a pass.

## 3. The lifecycle, end to end

```
  you:  python goal.py pursue "produce the weekly report" --expert builder --drive \
            --accept "report exists::python checkreport.py::gr" \
            --accept "figures render::python checkfigs.py::gf"  \
            --max-usd 2.50 --max-minutes 180
        │
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. CONTRACT (contract.py)                                                │
│    create → acceptance tests recorded → freeze → hash SEALED in          │
│    <home>/org/ → state: draft → ready.  The graders now exist and        │
│    nobody inside the pursuit can change them.                            │
└──────────────────────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 2. THE MACHINE PATH FIRST (swarm.auto → runbook.reconcile)   zero tokens │
│    observe: run all acceptance tests                                     │
│    ├─ all pass → settle → VERIFIED. Done. (a repeat goal costs pennies)  │
│    ├─ ≥2 DECLARED groups failing, each with its own DISTINCT proven      │
│    │  runbook → SWARM: one leased worker per group, no worker-to-worker  │
│    │  channel, then the central graders re-run everything                │
│    ├─ a proven runbook matches → RECONCILE: apply → re-verify → repeat   │
│    │  (bounded rounds; each runbook step is do+verify, policy-screened)  │
│    └─ nothing matches → this is the FRONTIER → fall through to 3         │
└──────────────────────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 3. THE MODEL LOOP (goal.py pursue — cycles, budget-checked each cycle)   │
│    PLAN   a planner task writes plan-N.md: ≤8 milestones, each with a    │
│           mechanical CHECK where possible (learning goals get the        │
│           study shape: gather → cited notes → spec → closed-book exam)   │
│    WORK   each milestone runs as a real gated task in the task engine:   │
│           the model emits ONE tool call per step; finish_task is         │
│           REFUSED until the milestone's gate exits 0                     │
│    JUDGE  an examiner on a DIFFERENT model family inspects artifacts,    │
│           runs the checks, writes VERDICT: ACHIEVED | NOT ACHIEVED       │
│    OVERRULE #1  ACHIEVED while a milestone check fails → NOT ACHIEVED    │
│    OVERRULE #2  ACHIEVED while a FROZEN ACCEPTANCE TEST fails → NOT      │
│           ACHIEVED, failure list feeds the next cycle's planning         │
│    LOOP GUARDS  budget exceeded → BLOCKED by name.                       │
│           same milestone failing the same check twice in a row →         │
│           BLOCKED("no convergence"), remaining cycles NOT burned         │
└──────────────────────────────────────────────────────────────────────────┘
        ▼                                    ▲
┌──────────────────────────────────────────┐ │ resume (blocked → running)
│ 4. REPAIR (repair.py) — when BLOCKED     │ │
│    diagnose from the LEDGER (never the   │ │
│    model's opinion) → plan typed actions,│ │
│    each carrying the failing check and   │ │
│    its recorded stderr VERBATIM:         │ │
│      study      → discover.py catalogues │ │
│      capability → pinned recipe / owner  │ │
│      revise_runbook → child BESIDE parent│ │
│      retry_with_signal → repair.md into  │─┘
│           the resumed planner's context  │
│    budget/tamper → OWNER, always.        │
│    identical repair twice → stop.        │
└──────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 5. TERMINAL STATES — what the record can honestly say                    │
│    verified   every frozen acceptance test passed, run by the harness    │
│    partial    judge said achieved but no mechanical graders existed —    │
│               the ceiling is printed, never silently upgraded            │
│    blocked    budget / oscillation / tamper / frontier — NAMED; the one  │
│               resumable state                                            │
│    exhausted  cycles spent, tests still failing                          │
│    failed     the pursuit itself broke                                   │
│    …and a VERIFIED pursuit can be distilled: runbook.py draft emits a    │
│    skeleton (proven verifications kept, `do` steps as TODOs) so the      │
│    NEXT similar goal runs on the machine path for free                   │
└──────────────────────────────────────────────────────────────────────────┘
```

That last arrow is the flywheel and the whole economic argument: **the
model is spent once, at the frontier; every success becomes deterministic
capability; the system does less model-work per goal as its library grows.**

## 4. The modules, one by one

### `contract.py` — what "done" means, frozen before work begins
The audit that drove this found the hole in every self-checking agent
design: *the planner writes its own graders*. Milestone checks are authored
by the same model family that satisfies them — `test -f notes.md` where the
goal needed "the exam scored 90" — and the judge can't help because the
judge reads the same plan. The contract fixes it structurally: acceptance
tests come from the **caller**, are hashed at freeze, sealed **outside the
expert's root**, and run only by the harness. A state machine
(`draft→ready→running→verified|partial|blocked|exhausted|failed`) refuses
illegal jumps; an empty acceptance set is *not* vacuously passing; budgets
(`max_usd` from real task costs, `max_minutes`, `max_cycles`) end pursuits
blocked by name. Every transition is an event; `replay()` rebuilds state
purely from events and flags snapshot forgery as divergence.
*Test:* `test_contract.py` (10 properties, incl. two full pursuits).
*Mutations killed:* 8/8 — including "ignore the seal", "empty set passes",
"acceptance authority unwired", "seal moved inside the root".

### `runbook.py` — the power that needs no model at all
Your directive, and the correct one: pre-AI agents (crawlers, spacecraft
autonomy, workflow engines, cluster controllers) did regulated work
reliably because **the work was written down as executable procedure and
the machine replayed it, verifying as it went**. A runbook is typed steps,
each `do` + `verify`; every `do` runs under the full model-command stack
(policy screen, sandbox, approval tier — `rm -rf /` in a runbook is
refused, not run) and a step that fails its own verify stops the run.
**Trust is earned**: authoring is open (that's where the model's
intelligence lands), but the trust ledger is CONTROL-zone — 3 all-verified
wins promote candidate→proven, 2 straight losses quarantine, and a
self-declared `"status": "proven"` inside the file is ignored.
`reconcile()` is the model-free goal loop (observe→apply→verify, bounded);
`settle()` is the single definition of "the graders decide"; `draft()`
turns a verified pursuit into a skeleton whose `do` steps are TODOs that
validation refuses until filled — the machine recovers *what* was proven,
not *how*. *Test:* `test_runbook.py` — including a pursuit that ended
VERIFIED with **zero tasks created against a provider rigged to fail any
task**, so the model path could not explain the outcome even by accident.
*Mutations killed:* 7/7.

### `swarm.py` — multiplication only where the evidence says it pays
You asked for an agent that multiplies itself until the goal is achieved.
The controlled evidence
([Nature MI 2026](https://www.nature.com/articles/s42256-026-01268-y), 260
experiments) says centralized coordination gains up to **+81% on
decomposable** work and **loses 39–70% on sequential** work; the
[MAST taxonomy](https://arxiv.org/abs/2503.13657) says multi-agent systems
die of inter-agent misalignment and self-certified success. So: RULE 1 —
sequential by default; independence is **declared** by the caller
(`--accept "what::cmd::group"`), never guessed. RULE 2 — fan out only when
≥2 groups each have their own *distinct* proven runbook; frontier groups
are named, never improvised. RULE 3 — workers have one immutable assignment,
**no channel to each other**, and no vote: the only reducer re-runs all the
frozen graders centrally. RULE 4 — one worker per group ever, via leases
(O_EXCL, stale-broken, ownership-verified release). `goal.pursue` routes
through `swarm.auto`, so callers never care which path won.
*Test:* `test_swarm.py` — including "all workers reported success and the
swarm still failed because the graders refused."
*Mutations killed:* 6/6 — the ledger-lock mutant killed **by count**
("100 events emitted, ledger holds 97").

### `repair.py` — self-modification without the hallucination
When a pursuit blocks, the agent must fix *what blocked it* — your words:
not "thinking it did a good job" while hallucinating. Four laws, each a
cited result: **LAW 1** no repair without a signal — every action carries
the failing check and its recorded stderr verbatim from the ledger
(intrinsic self-correction makes models worse — Huang et al. 2024).
**LAW 2** repair never grades itself — it may move `blocked→running`;
`verified` can only come from the graders, and the test asserts the ledger
ORDER (a passing verify event precedes the state change) — keep-only-what's
-validated is the Darwin Gödel Machine result. **LAW 3** the machine never
lifts its own ceiling — budget and tamper route to the OWNER; the budget is
asserted bit-for-bit unchanged after a repair pass. **LAW 4** revision
keeps lineage — a failing runbook's revision is written *beside* its parent
as a zero-trust candidate carrying the failure it must answer; the parent's
file and earned trust are untouched. The retry signal (`repair.md`, <2KB,
verbatim errors, "the harness re-runs every check itself") is injected into
the resumed planner's context — small and explicit, per the
feedback-friction result (arXiv:2506.11930). Repair watches itself:
attempts bounded, identical plan twice → "not converging".
*Test:* `test_repair.py`. *Mutations killed:* 6/6.

### `goal.py` — the model loop (PLAN → WORK → JUDGE → learn → repeat)
The supervisor above the task engine. Plans are bounded (≤8 milestones);
every milestone runs as a *real gated task*; the judge sits on a different
model family and its verdict is re-checked against the milestone checks
(overrule #1) and against the frozen acceptance tests (overrule #2 — the
contract outranks the judge). Failed milestones become fleet lessons in the
commons so no expert repeats them. Budget check at each cycle top;
oscillation ends non-convergence early; a repaired pursuit opens with the
repair signal in context. *Test:* `test_goal.py` + the end-to-end halves of
`test_contract/runbook/swarm/repair`.

### `capability.py` + `mastery.py` — competence proven on unseen work
Both external audits converged on the same missing piece: the platform
learned *information* (sources → cited notes → closed-book exam) but never
proved *procedural competence* — an expert is not an expert because it
scores 95% on a quiz; it must **build something it has never seen and pass
graders it cannot touch**. A **Capability Pack** (`capability.py`) is a
sealed exam definition: competencies (each with a study query and a stated
*why*), practice exercises, **sealed transfer tasks** the student meets for
the first time at exam-time, and stdlib validator scripts — all living in
`<home>/packs/<name>/`, **outside every expert's root** where the worker's
file tools cannot resolve (read *or* write — the student can neither edit
nor pre-read its exam), content-hashed at freeze into
`org/pack-seals.jsonl` exactly like a contract. Validation refuses a pack
whose competency has no sealed transfer task ("mastery of an unexamined
competency is memorisation wearing a medal") and a task with no acceptance.
`mastery.py` conducts the loop over existing primitives: **pretest**
(sealed baseline *before* study — improvement claims need a floor),
**study** (per-competency discovery + learning pursuits), **practice**
(exercises as contract pursuits), **exam** (the sealed set, fresh contract
per task), **diagnose** (failing tasks → competencies, carrying the failing
checks as evidence — repair's LAW 1 one level up), bounded
oscillation-aware **targeted re-study**, a **verdict** computed only from
harness-run grader results against the pack's frozen thresholds (recorded
with its ceiling: "the pack's MECHANICAL FLOOR"), **distill** (verified
practice → runbook drafts), and **retest** (same sealed tasks, fresh ids,
no study artifacts injected — retention measured, not assumed).
*Test:* `test_mastery.py` — 9 laws, run against a provider rigged to fail
every task so any PASS proves the machine path; it caught a real `goal.py`
bug (the cheap path required a runbook match before even *observing*, so a
pre-satisfied contract still paid for a model loop — fixed: observe first).
First shipped pack: `packs/responsive-pricing/` (4 competencies, 4
exercises, 3 sealed transfer tasks, 4 stdlib validators).
*Mutations killed:* 5/5 — "unexamined competency validates anyway",
"an edited pack still grades", "every task passes regardless of the
graders", "mastered unconditionally", "identical failure signatures
never stop the loop".

### `steer.py` — the owner's voice in a running pursuit
Between "let it finish wrong" and "kill it" there was no third option: the
owner could start a pursuit and stop one, and was mute in between. A steer
note lands **verbatim** in the planner's context at the top of the next
cycle (goal.pursue refreshes it per cycle), so a course correction costs a
sentence instead of a restart. The laws, because a guidance channel is an
attack surface: (1) advice never grades — a note cannot touch the
acceptance, the state, or a verdict, and test_steer proves the grader
results are bit-identical with and without a hostile "mark it verified"
note; (2) the worker cannot write its own guidance — steering.jsonl and
steering.md are CONTROL-zoned inside goals/ (a worker that could forge
"the owner says ship it" has promoted itself to owner); (3) every note is
a `steered` event on the contract ledger — influence is recorded, never
invisible; (4) notes are capped and rendered newest-last, per the
feedback-friction result. *Test:* `test_steer.py` (5 laws).

### `freshness.py` — learned claims age, get superseded, get retracted
Register #26: a cited atom, once earned, was true forever — remembering by
embalming. Three additive marks and one ledger fix it: `[expires: date]`
flags a claim past its window; `[supersedes: C-01]` flags the OLD atom and
names its successor (lineage kept, like runbook revisions); and
`org/retractions.jsonl` — CONTROL-zoned, so an agent cannot retract the
source of a claim it would rather not defend — flags every atom whose
`[src:]` contains a retracted ref. `scan()` reads the SAME notes files
citecheck validates (one walker — the two-walkers bug stays fixed) and
FLAGS, never deletes. `check_doi()` live-probes Crossref's update-to
relation for retraction notices, keyless; the verdict is a pure function
tested offline. *Test:* `test_freshness.py`.

### `universal.py` + `discover.py` — readiness and learning
Before pursuing, `universal.assess` answers "can this expert do this yet,
and if not, what exactly is missing?" from mechanical probes — capability
(live toolbox scan), knowledge (cited atoms on disk, tier-rated),
authority (never self-resolved; grants are scoped, expiring, and every use
is logged). `discover.py` is how the agent *finds things to learn*:
eleven keyless curated catalogues (OpenAlex, Crossref, DOAJ, PubMed,
Zenodo, Software Heritage, GitHub, EU open data, Library of Congress,
Wikidata, arXiv) — **deliberately not a web search**, because a general
index is ranked for engagement and citing it cites nothing; search-engine
hosts are pinned to the bottom tier and can never become cited atoms. The
goal is reduced to its subject before querying, and off-topic results are
dropped *and counted* (an off-topic paper reached by a trusted route
becomes a cited atom — a wrong belief with a real citation attached).

### The floor under all of it (one paragraph each)
**`loop.py` — the task engine**: one tool call per step; five tools; gates
decide done; retries, escalation between model tiers, cost brakes per task
and per day, Retry-After honored with jitter, graceful SIGTERM drain,
context compiled fresh every task (measured flat at ~1083 tokens while
fleet history grows). **The five authorities**: Execution (every subprocess
in 85 modules flows through one gateway — audited, 0 violations), File
(zones: workspace/control/runtime), Credential (4 sources, excluded from
packaging/backups/model-visible env), Model Gateway (every call metered and
ledgered), Effect (external side effects get idempotency keys and
approvals). **The memory institution**: courses with cited atoms (tier-
gated sources), skills promoted on gated outcomes, cases that record
whether a fix *held*, gotchas with earned retirement (a later success on
the same probe withdraws the warning; recurrence un-retires it), a
knowledge graph derived from the same notes the citation checker validates
— one walker, after the bug where two walkers disagreed and the graph was
silently empty. **Readiness**: one computation (`doctor.readiness`),
rendered by doctor, preflight, and the panel — a keyless fleet is NOT READY
on every surface with identical words.

## 5. The file formats (so you can read any goal by hand)

**`contract.json`** — `{gid, goal, criteria, non_goals, acceptance:
[{id, what, check, group?}], budget: {max_usd, max_minutes, max_cycles},
state, state_why, accept_hash, sealed:{where,at}, created}`.

**`events.jsonl`** — one JSON object per line, append-only, written under
the platform lock. Kinds: `contract_created, acceptance_frozen,
cycle_started, milestone_done, milestone_failed (n, cycle, check, error),
spent (usd, task), verdict (cycle, verdict, overruled),
acceptance_overruled (cycle, failed), verify (tamper, mechanical, all,
passed, failed), state (to, why), resumed, repair_applied (plan_hash,
kinds), repair_not_converging, runbook_applied, swarm_started (workers,
groups, capped_out), swarm_worker (group, runbook, ok, why),
reconcile_fell_through, verify_tamper`.

**`runbooks/<name>.json`** — `{name, triggers: [words], steps: [{do,
verify, timeout?}], provenance?: {parent, reason, at}}`. Status lives in
`trust.json` (`{name: {status, wins, losses, streak_losses, history}}`),
never in the runbook file.

**`org/contract-seals.jsonl`** — `{at, gid, accept_hash, n, where}` —
the outside reference `verify()` checks the contract against.

## 6. The thinking — why it is built this way

1. **The verifier and the worker must have different authors.** Everything
   else follows. The task gate is the owner's; the acceptance tests are the
   caller's; the trust ledger is the harness's; the judge is another
   family; the reducer is central. Wherever author and grader coincided,
   the audit found the exploit — so the design separates them everywhere.
2. **Detection where prevention is impossible.** On the host sandbox a
   shell can edit any file. So the design makes forged state *worthless*
   rather than impossible: seals outside the root, append-only ledgers,
   replay divergence, tamper verdicts that run nothing. (Real containment
   is one settings line: `sandbox = "docker"`.)
3. **Declared beats inferred.** Independence of subtasks (swarm groups),
   source authority overrides, acceptance itself — the caller states them;
   the machine never guesses on questions where a wrong guess is
   catastrophic and a right guess saves seconds.
4. **Sequential and deterministic by default; model and parallelism as
   deliberate, gated escalations.** This is the exact inversion of most
   agent frameworks, and it is what the measured evidence supports.
5. **Every success becomes cheaper.** The frontier costs model tokens
   once; the library replays it forever for compute pennies. That — not a
   bigger model — is the honest mechanism behind "a cheap model made 100×
   more useful", and it is measurable the day a key is configured.
6. **One truth, one writer.** The recurring defect this codebase finds in
   itself — found 15+ times — is "two descriptions of one truth and
   nothing comparing them." Hence: one atom walker, one settle(), one
   readiness computation, one lock primitive, one execution gateway.
7. **Numbers from runs, not from memory.** Every count in the docs comes
   from a command; the evidence artifact quotes tests verbatim from a real
   run; skipped tests are a third outcome, counted and named. The suite
   ends with numbers, never with one green phrase.

## 7. What is missing — the honest list

1. **The 100× number.** Architecture complete, measurement absent: it
   needs one API key (`agent.env`), then the paired experiment on
   `evalsuite`'s sealed holdout — same frozen cheap model, bare vs
   in-system. Until then the multiplier is an argument, not a fact.
2. **Live learning at scale.** Discovery works live (tested against the
   real catalogues); *studying* — notes, atoms, exams — needs a model key.
   Multi-GB, multi-hour ingestion is unproven.
3. **Capability packs — what remains of E51**: the pack artifact, the
   mastery loop, pack DRAFTING for new domains (`capability.py draft` +
   the author law), typed runbook applicability (`when.not`,
   `when.requires`) and HTN-style composition (`{"run": sub}` steps) all
   exist and are mutation-tested. Still open: full domain ontologies, and
   a **live** mastery run against a real provider (the shipped tests
   prove the laws with a rigged provider; the pretest→exam lift with a
   real model is unmeasured).
4. **Cross-machine scale.** Leases are single-host; distributed fencing
   tokens, multi-host reducers, and horizontal scaling are not built.
5. **Time-scale evidence.** Endurance is minutes; 24h/7d/30d soaks, DST
   scheduling, retention-at-months need a machine left running.
6. **The frontier still needs a model.** A goal with no matching runbook
   and no key ends `blocked` with the frontier named. That is by design —
   the alternative is improvisation, which is how deterministic agents
   became brittle the first time around — but it means "achieve literally
   any goal" honestly reads: *any goal that is mechanically checkable and
   either already proven, or reachable by a model working under these
   graders*. Goals that cannot be mechanically checked cap at `partial`,
   loudly.
7. **Browser / transcription / vision on this machine** wait on one owner
   command or key each (`mcp.py enable playwright`; GROQ/OpenRouter keys)
   — routed honestly by `toolbox.recipe` instead of pretending an
   installer can fix a missing credential.

## 8. Run it

```bash
python bootstrap.py                      # first-time setup, tells you what's missing
python tests/run_all.py                  # 111 tests, explicit pass/skip/fail counts

# a goal with graders, budgets, and declared-independent halves
python goal.py pursue "produce the weekly report" --expert builder --drive \
    --accept "report exists::python checkreport.py::gr" \
    --accept "figures render::python checkfigs.py::gf" \
    --max-usd 2.50 --max-minutes 180

python contract.py show    experts/builder <gid>     # the contract
python contract.py events  experts/builder <gid>     # everything that happened
python contract.py verify  experts/builder <gid>     # re-run the graders now
python runbook.py  list    experts/builder           # the proven library
python runbook.py  draft   experts/builder <gid>     # distill a win
python swarm.py    plan    experts/builder <gid>     # would it fan out, and why
python repair.py   apply   experts/builder <gid> --resume   # fix what blocked it
python evidence.py                                   # regenerate the proof artifact
```
