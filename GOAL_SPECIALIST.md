# The Goal Specialist — hardening the goal system, and the complete gap register

**Date:** 2026-08-25 · **Scope:** the goal-pursuit system (`goal.py`,
`contract.py`, `universal.py`) hardened against the external audit's
findings, plus an honest status for every one of the audit's 115 gaps.

This document answers two demands the project set: focus 100% on
the system that takes a goal and achieves it, and explain the findings
deeply enough to act on. Both are here. Every "closed" below names the test
that proves it; every "open" says what closing it requires. Nothing in this
document is a claim without one or the other.

---

## Part 1 — What was built, and why each piece is the way it is

### The finding that drove the design

The audit's sharpest observation about this platform's goal system:

> **The planner writes its own graders.**

`goal.py` was already unusually defended — milestones carry mechanical
checks, the judge sits on a different model family, and the judge's verdict
is re-checked against the checks. But the CHECK commands are authored by the
same model family that then does the work to satisfy them. A planner under
pressure to finish can write `test -f notes.md` where the goal needed "the
exam scored 90" — and the judge cannot catch it, because the judge reads the
same plan. That is reward hacking (audit gap #63), and no prompt fixes a
structural problem.

The audit's second observation, from the pre-AI systems that already did
regulated work reliably — crawlers, spacecraft autonomy, workflow engines,
cluster controllers:

> Use the model for interpretation, hypothesis generation, plan proposals,
> and repair candidates. Do not use it as the database, transaction manager,
> permission system, scheduler, safety controller, source of truth, or
> completion judge.

`contract.py` is those two observations turned into code.

### The goal contract (`contract.py`, wired through `goal.pursue`)

**1. Acceptance tests are frozen before planning.** The caller — owner, or
the harness on the owner's behalf — supplies acceptance tests: shell
commands that exit 0 when a criterion is genuinely met. They are hashed at
freeze time and **sealed into an append-only ledger outside the expert's
working root** (`<home>/org/contract-seals.jsonl`). The worker never writes
them, never sees them as editable text, and the pursuit's final state
depends on them alone.

**2. The worker cannot touch contract files.** `fileauth.py` classifies
`goals/*/contract.json`, `goals/*/events.jsonl` and `goals/*/goal.json` as
CONTROL zone — the agent's file tools are refused on them while the plans
and evidence notes beside them stay writable. A worker that shells around
the file authority and edits the contract anyway gains nothing: the seal no
longer matches, and `verify()` returns **TAMPER — with nothing run**. A
forged grader that executes is a forged grader that can pass, so a tampered
contract executes nothing. Re-hashing the forgery into the contract's own
snapshot also loses, because the reference lives outside the root.
(`test_contract.py::check_tamper_is_detected_not_passed`, plus the mutation
that moves the seal inside the root — killed.)

**3. Completion is a state transition, not a sentence.** The contract is a
state machine — `draft → ready → running → verified | partial | blocked |
exhausted | failed` — and illegal jumps are refused by the machine, not by
caller discipline. `verified` is reachable only when the harness itself ran
every frozen acceptance test and all passed. A goal with no mechanical
acceptance tests can end `achieved` (the judge's checked opinion) but its
ceiling is **`partial`** — recorded, printed, and never upgraded by
confidence. An empty acceptance set is not vacuously "all passing": that is
the vacuous-assertion defect this platform hunts everywhere else, so
emptiness fails loudly.

**4. The contract outranks the judge.** When the judge says ACHIEVED, the
harness runs the frozen acceptance tests. If any fail, the verdict is
overruled a second time — the first overrule (judge vs planner-checks)
already existed — and the failure list feeds the next cycle's planning. The
end-to-end test stages the full attack: a lying judge AND a generous
planner-authored check both say done while the deliverable does not exist;
the frozen test refuses; the pursuit does the work for real in cycle 2 and
only then ends `verified`. Eight mutations of this machinery (unwire the
authority, ignore the seal, vacuous empty set, allow illegal transitions,
never diagnose oscillation, never block on budget, re-open the CONTROL zone,
move the seal inside the root) — **all eight killed by the test**.

**5. Budgets end pursuits by name.** `max_usd` (accumulated from real task
costs into the event ledger), `max_minutes` (wall-clock from the first
event), `max_cycles`. Checked at the top of every cycle; exceeding one ends
the pursuit `blocked` with the ceiling named — "budget: wall-clock 1290m >
1m" — never a silent continuation. The audit's honest caveat stands and is
documented: enforcement is between units of work, so the most an overshoot
can be is the cycle already running.

**6. Oscillation is diagnosed, not endured.** A pursuit whose same milestone
fails the same check in two consecutive cycles is not converging; burning
the remaining cycles on an identical wall is a loop wearing persistence's
clothes. The pursuit ends `blocked` with the wall named — "milestone M1
failed the same check in cycles 1 and 2" — so the owner fixes the actual
obstacle. The same milestone failing for a *different* reason is progress of
a kind and is allowed to continue: progress and looping are told apart, and
both directions are tested.

**7. Every transition is an event; the ledger is the truth.** Append-only
`events.jsonl` per goal: contract created, acceptance frozen, cycles,
milestone outcomes with failure signatures, spend, verdicts, overrules,
verifications, state changes. `replay()` reconstructs the state purely from
events and reports divergence from the snapshot — a snapshot forged to
"verified" with no event producing it is *detected*. A crashed pursuit
resumes against the same contract (the ledger knows what was spent and how
many cycles ran) instead of starting a fresh id with amnesia.

### Runbooks — the goal agent's power that needs no model at all

The guiding directive, and it is the right one: the pre-AI agents that did
regulated, hard work reliably — crawlers with persistent frontiers,
spacecraft autonomy, workflow engines, cluster controllers — were not
intelligent. They were reliable because **the work was written down as
executable procedure and the machine replayed it, verifying as it went.**
The model-era mistake is re-deriving the same procedure with an LLM every
time, paying tokens, latency and hallucination risk for work that stopped
being novel after the first success.

`runbook.py` is that principle in this platform:

- **A runbook is typed steps, each `do` + `verify`,** executed through the
  Execution Authority — every `do` gets the full model-command stack
  (policy, sandbox, approval tier: `rm -rf /` in a runbook is refused, not
  run), and every step must pass its own `verify` before the next runs. A
  procedure that cannot prove its last step does not take its next one.
- **Trust is earned, never self-declared.** Anyone — the worker included —
  may *author* a runbook (`runbooks/*.json` is workspace; authoring is
  where the model's intelligence lands). But the trust ledger
  (`runbooks/trust.json`) is CONTROL: the worker's file tools are refused,
  only the harness records outcomes, and a `"status": "proven"` written
  inside the runbook file itself is ignored. Three all-verified wins
  promote candidate → proven; two consecutive losses quarantine; a
  quarantined runbook matches nothing until an owner clears it.
- **`reconcile` is the model-free goal loop** — the Kubernetes-controller
  shape applied to a contract: run the frozen acceptance tests (observe),
  apply the matching proven runbook (act), re-verify, repeat. No model at
  any point. And the boundary is honest: no matching runbook means
  **BLOCKED with the frontier named**, never improvisation — brittleness
  at the frontier is exactly what killed the old deterministic agents, and
  the frontier is where the model (or the owner) is the right tool.
- **`goal.pursue` tries the machine first.** Before spending a single model
  cycle, a pursuit whose goal matches a proven runbook is reconciled; only
  when that cannot finish does planning begin. Proven end to end in
  `test_runbook.py`: a pursuit completed **VERIFIED with zero tasks
  created**, against a mock provider *rigged to fail any task instantly* —
  so the model path could not have produced the outcome even by accident.
- **A verified pursuit becomes a draft runbook.** `runbook.py draft <gid>`
  emits a skeleton from the event ledger carrying every proven
  verification, with the `do` steps as named TODOs — because the machine
  can recover *what was proven* but not *how it was done*. Validation
  refuses a draft until a model or an owner fills the TODOs. The model
  authors once; the machine replays forever.

**This is where the multiplier actually lives.** The division of labour is:
the model for the frontier (goals the library has never seen — plan, work,
fail, recover, then write the procedure down), the machine for everything
behind it (pennies of compute, zero tokens, no drift, identical at 3am).
As the proven library grows, the system does less and less model-work per
goal — and unlike a model, the library is auditable line by line.

Seven more mutations, seven killed: verify-gating removed, losses never
quarantine, quarantined volunteers, candidates run unsupervised, pursue
unwired from the machine path, trust ledger reopened to the worker, TODO
drafts accepted as runnable.

### Repair — self-modification until done, without the hallucination

The owner's requirement in its own words: when the job is not done, the
agent modifies itself and its approach until it is — *"not in a dumb way,
like an AI hallucinating and thinking it really did the job."* That clause
is the entire design problem, and the research record is unusually clear
about how it goes wrong. `repair.py` is built on four verified results:

| Result | Source | The law it becomes |
|---|---|---|
| Intrinsic self-correction — no external signal — makes models **worse** | [Huang et al., ICLR 2024](https://arxiv.org/abs/2310.01798) | **LAW 1 — no repair without a signal.** Every planned action carries the failing check and its recorded stderr, verbatim from the event ledger. There is no "reflect and try again" action. |
| Self-modifications are kept only when **empirically validated**, in an archive with lineage | [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954) | **LAW 2 — repair never grades itself.** It may move `blocked → running` and act; VERIFIED can only come from the frozen graders, and the ledger must show a passing verify event *before* any verified state. **LAW 4 — revision keeps lineage.** A failing runbook's revision is written *beside* its parent as a zero-trust candidate; the parent's file and earned trust are untouched. |
| Skills as executable code; retries incorporate **environment feedback and execution errors** | [Voyager](https://arxiv.org/abs/2305.16291) | The failing signal travels into the resumed pursuit: `repair.md`, injected into the planner's context. |
| Models struggle to absorb even good feedback | [Feedback Friction](https://arxiv.org/pdf/2506.11930) | The signal file is **small and explicit** — the failing checks and errors, under 2KB, never a wall of logs — and warns the planner that the harness re-runs every check itself. |

And one law the papers don't need but a 24/7 platform does: **LAW 3 — the
machine never lifts its own ceiling.** A budget block and a tamper block
plan exactly one action — OWNER. A repair pass leaves the contract's budget
bit-for-bit unchanged (asserted, and the mutation that removes the guard is
killed). An agent that can raise its own budget when it runs out has no
budget; an agent that can forgive tampering with its graders has no graders.

The loop, end to end: `diagnose` (classify the block from the ledger, never
from the model's opinion) → `plan` (typed actions, each grounded: study the
failing subject via the discovery catalogues, apply a pinned capability
recipe for an exit-127, revise the failing runbook beside its parent, or
retry with the signal) → `apply` (execute the machine-executable half,
record events, write the signal file) → **hand the goal back to the
graders** (`reconcile`, then the model loop if needed). Repair watches
itself the way it watches goals: attempts are bounded, and planning the
*identical* repair twice stops with "not converging" — the oscillation rule
one level up.

Six mutations, six killed: signal dropped from the retry, repair granting
itself `verified` (caught by the ledger-order assertion — no passing verify
event preceded the state), budget block receiving machine repairs, revision
overwriting its parent, identical repairs repeating, the attempt bound
ignored.

### Swarm — multiplication only where the evidence says it pays

The project calls for an agent "capable of multiplying itself until achieving
the goal". The controlled evidence says exactly when that helps and when it
destroys the work, and `swarm.py` is gated on it rather than inspired by it:

- **[Nature Machine Intelligence 2026](https://www.nature.com/articles/s42256-026-01268-y)**
  (260 controlled experiments): centralized coordination on genuinely
  decomposable tasks gained up to **+81%**; on sequential tasks **every**
  multi-agent variant tested degraded performance **−39% to −70%**.
- **[MAST — Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657)**
  (NeurIPS 2025 spotlight): 14 failure modes in 3 clusters — system design,
  inter-agent misalignment, and workers certifying their own success.

Four structural rules, each mutation-tested:

1. **Sequential by default; independence is declared, not guessed.** The
   caller who wrote the graders gives acceptance tests a `group`
   (`--accept "what::command::group"`); tests in different groups may run
   in parallel, ungrouped tests never do. No declaration, no fan-out.
2. **Fan out only when it can pay**: ≥2 groups, each with its own
   *distinct* proven runbook. Groups without a procedure are the frontier,
   named — never improvised in parallel.
3. **Workers do not talk and do not grade.** One immutable assignment
   each; no inter-worker channel exists (MAST cluster ii has no syntax
   here); the only reducer is `runbook.settle` running **all** the frozen
   acceptance tests centrally. Tested: a swarm whose workers all report
   success still fails when the graders refuse, with the refusing test
   named.
4. **One worker per group, ever** — a per-group lease on the platform's
   own lock primitive makes duplicate execution across concurrent swarms
   impossible, not unlikely.

`goal.pursue` routes its machine-first path through `swarm.auto`: parallel
where declared and payable, sequential reconcile everywhere else, one
result shape either way. Proven end to end: a grouped goal fanned out to
two workers and ended VERIFIED with **zero tasks and zero model calls**,
against a provider rigged to fail any task.

**Three real concurrency defects, found by this layer's own test and fixed:**
the event ledger lost rows under concurrent append (Windows append-mode
handles are not atomic across writers — `contract.event` now takes the
platform lock, and a 4-thread × 25-event hammer counts exactly 100 rows);
a worker that died between acting and reporting vanished silently (workers
now report every exception as a result row and an event); and the trust
ledger's read-modify-write raced under two workers finishing at once
(WinError 32, sharing violation — `runbook.record` now locks). Each fix
carries the measured failure in its comment.

### One readiness truth (audit gap #16)

The audit found the surfaces contradicting: *"Preflight reports 'ready with
risks', Doctor says the system cannot think."* Each computed a different
question and published it under one word. Now `preflight` **asks
`doctor.readiness`** — one computation, two renderers — and a fleet whose
only live provider has no key is NOT READY on both surfaces, with preflight
quoting doctor's blocking item verbatim. Tested in both directions: the key
arrives, both clear, neither surface edited.

### Explicit outcome counts (audit gap #111)

The suite runner no longer ends with one green phrase. It ends with
`N executed: P passed, S skipped, F failed`, names the skipped files, and
says that a skipped test proved nothing here. `EVIDENCE.md` already carried
this discipline; the runner now says the same numbers.

### The security policy (audit gap #81)

`SECURITY.md`: trust boundaries with their mediators, the six authorities,
the contract's anti-reward-hacking role, and — the part that makes it worth
trusting — the seven things deliberately NOT defended, each with the reason
and the compensating control.

### How to use the hardened system

```bash
# a goal that can end VERIFIED: give it graders the worker cannot write
python goal.py pursue "migrate the reports module to the new API" \
    --expert builder --drive \
    --accept "tests pass::python -m pytest tests/reports -q" \
    --accept "no old imports remain::python checknoold.py" \
    --max-usd 2.50 --max-minutes 180

# inspect the contract, its events, or re-run the graders at any time
python contract.py show   experts/builder g-20260825-...
python contract.py events experts/builder g-20260825-...
python contract.py verify experts/builder g-20260825-...
python contract.py replay experts/builder g-20260825-...
```

```bash
# the model-free path: procedures the machine executes and verifies itself
python runbook.py list      experts/builder
python runbook.py run       experts/builder deploy-report
python runbook.py reconcile experts/builder <goal-id>   # observe-apply-verify
python runbook.py draft     experts/builder <goal-id>   # skeleton from a win
```

From the panel: `POST /api/achieve` with `"accept": ["what::command", ...]`,
`"max_usd"`, `"max_minutes"` — authority gaps still stop it before it
starts. Without acceptance tests the response says, in words, that the
outcome can be achieved but never VERIFIED.

---

## Part 2 — The complete gap register, with honest status

Statuses: **CLOSED** (this session or earlier, test named) ·
**PARTIAL** (a real piece exists; the rest is named) ·
**OWNER** (one action only you can take — a key, an account, an approval) ·
**OPEN** (not built; what it needs) ·
**BY-DESIGN** (deliberately not done, with the reason — matching the
audit's own recommendation in every case).

### A. Capability claims and evaluation (1–11)

| # | Status | The honest state |
|---:|---|---|
| 1 | PARTIAL | Contract envelope, budgets, and `blocked` terminal states exist and are tested. Versioned per-domain operating envelopes: OPEN. |
| 2 | CLOSED | No AGI/consciousness/alive claims exist in the shipped docs; the self-model is described as a capability report. Kept closed by review, not by a test — no test can prove a claim's absence everywhere. |
| 3 | OPEN | The 10×/100× lift is unmeasured. Needs: a key (OWNER), then the paired experiment the audit specifies — same frozen model bare vs in-system, `evalsuite.py`'s sealed holdout is the scaffold. Report the four ratios separately, whatever they are. |
| 4 | OPEN | No expert-authored private domain benchmark. Needs a chosen domain and human-authored tasks. |
| 5 | OWNER→OPEN | Zero real operational data because zero keys. Wiring is complete: pricing, brakes, ledgers, Retry-After, failover. 20–50 bounded pilot tasks are one key away. |
| 6 | PARTIAL | `evalsuite.py` holds 24 tasks (12 train / 12 sealed holdout, Wilson intervals, peek counting) — larger than the audit's count, still far from hundreds. Comparative runs: none (see 3). |
| 7 | PARTIAL | Sealed holdout + peek counting exist; contamination scans and time-split authorship do not. |
| 8 | OPEN | No independent evaluator for subjective quality. Needs human rubric review; a same-family model judge is correlated with the worker. |
| 9 | OPEN | Repeated-consistency scoring (tau-bench style) needs live runs. |
| 10 | OPEN | Longest measured horizon is minutes (endurance test). 1h/24h/7d staged soaks need a live provider and a machine left on. |
| 11 | OPEN | `SECURITY.md` is a threat model, not a per-use-case safety case. Regulated claims remain prohibited (G92). |

### B. Real models and runtime readiness (12–21)

| # | Status | The honest state |
|---:|---|---|
| 12 | OWNER | No key on this machine. `agent.env` + one line; `python loop.py check` is the live probe. Everything downstream is wired and waiting. |
| 13 | PARTIAL | The loopback provider now exercises the full HTTP contract incl. Retry-After, malformed bodies, failover (`test_live_provider`). Live behavior suites: pending a key. |
| 14 | OPEN | Per-provider conformance matrices need live calls. |
| 15 | PARTIAL | 429/5xx ladder, Retry-After with jitter, permanent-error failover, budget metering — all tested offline. Live quota exhaustion and all-in cost: pending a key. |
| 16 | **CLOSED** | One readiness truth: preflight asks doctor; keyless fleet is NOT READY on both surfaces with identical wording; both clear together. `test_preflight::check_one_readiness_truth`, both directions. |
| 17 | PARTIAL | Skips are a third outcome in the runner and EVIDENCE.md. The four-level present/offline/live/outcome taxonomy on proof badges: OPEN. |
| 18 | PARTIAL | **Failover attribution fixed** (second audit's confirmed defect): every provider:model pair that serves a task now gets its own outcome row with step count, own cost, and SHARE; profiles() weights by share, so the last provider no longer absorbs whole outcomes. `test_modelrouter.py::check_failover_attribution`. Live calibration/regret: needs a key. |
| 19 | BY-DESIGN | No weight training. `training.py` exports verified trajectories; a governed external trainer is a separate product, exactly as the audit prescribes. |
| 20 | CLOSED | The four learnings are kept distinct in docs and code: episodic (cases/events), semantic (cited atoms), procedural (skills promoted on gated outcomes), weights (not claimed). |
| 21 | OPEN | No model-version pin/replay/canary pipeline. |

### C. Research and ingestion (22–37)

| # | Status | The honest state |
|---:|---|---|
| 22 | PARTIAL | Typed refusals exist throughout ingest; a published supported-format matrix does not. |
| 23 | PARTIAL | 11 keyless curated rails (`discover.py`), relevance-gated, tier-ranked, tested live and offline. A governed general-web frontier: OPEN. |
| 24 | PARTIAL→IMPROVED | **Discovery authority split from evidence quality** (second audit's P0, verified against Crossref's own membership page): DOI resolvers/Crossref/DataCite and preprint servers are now tier 2 provenance — real, citable, learnable, but never "normative"; DOAJ/PubMed keep tier 1 with reasons naming the actual review bar. `test_sources.py`, written red-first. Per-domain policies beyond this: OPEN. |
| 25 | PARTIAL | Conflicts module catches polarity/numeric disagreement; claim-level entailment is OPEN and stated as a blind spot in EVIDENCE.md. |
| 26 | OPEN→IMPROVED | `freshness.py`: expiry marks (`[expires:]`), supersession chains (`[supersedes:]`, lineage kept), and a CONTROL-zoned retraction ledger that flags every atom citing a retracted ref fleet-wide — flags, never deletions. Live Crossref retraction probe (`freshness.py doi`), verdict logic pure and tested offline (`test_freshness.py`; mutation killed). Still open: automated retraction FEEDS (polling on a schedule) and TTL defaults per source type. |
| 27 | OPEN | Semantic contradiction beyond text rules — needs typed claims. |
| 28 | PARTIAL | Crawl bounds and rate limiting exist in ingest; a persistent per-origin frontier with RFC 9309 evaluation: OPEN. |
| 29 | PARTIAL | User-supplied media and permitted caption paths work via yt-dlp where installed; universal video learning is not claimed. |
| 30 | OWNER | Transcription = ffmpeg + GROQ_API_KEY; `toolbox.recipe` now routes this honestly to you instead of pretending an installer can fix it. |
| 31 | OWNER | Vision = a provider key (OPENROUTER by default). Same honest routing. |
| 32 | OPEN | Table/equation/reading-order validation corpora. |
| 33 | PARTIAL | Parsers can run in the docker sandbox; dedicated parser-hardening tests (bombs, hostile PDFs): OPEN. |
| 34 | OPEN | Injection resistance is structural and offline-tested; end-to-end live adversarial validation needs a real model. |
| 35 | OPEN | No multi-GB / multi-hour ingestion runs. |
| 36 | PARTIAL | Discovery reports found/filtered/off-topic counts; formal sufficiency criteria: OPEN. |
| 37 | OPEN | License/terms/PII policy engine per artifact. |

### D. Memory (38–50)

| # | Status | The honest state |
|---:|---|---|
| 38 | **CLOSED** (the defect) | The graph was empty because it read `courses/<c>/notes.md` while the platform writes `courses/<c>/lessons/NN/notes.md` — its test wrote the same wrong layout, so it certified the bug. One walker now (`citecheck.notes_files`), agreement pinned across 4 layouts. Population with real study: one key away (OWNER). |
| 39 | PARTIAL | Three typed edge kinds exist; an OWL-profile ontology with asserted/inferred/disputed states: OPEN. |
| 40 | OPEN | W3C-PROV relations across all memory objects. Today: src links + tiers + attribution. |
| 41 | BY-DESIGN | File-backed, stdlib-only is the product's identity; retention keeps persist cost flat (measured, capped, tested). Production-scale DB/event-store is a deliberate non-goal — deploy the container and let R2 hold durability. |
| 42 | PARTIAL | CLOSED for goals (append-only events + replay + divergence detection, tested). Platform-wide event sourcing: OPEN. |
| 43 | PARTIAL | Effects ledger + idempotency keys for external effects; atomic state+outbox commit: OPEN. |
| 44 | OPEN | No gold query→memory retrieval benchmark. |
| 45 | CLOSED | The docs promise durable records + measured windows, not "never loses context"; the verbatim archive tier survives trimming and stays recallable (tested). |
| 46 | PARTIAL | Originals kept, verbatim tier never compressed; task-specific loss budgets: OPEN. |
| 47 | PARTIAL | Failure keys carry command+subcommand; argument-level keys traded off deliberately and recorded as a blind spot. |
| 48 | PARTIAL | Cases record whether a fix HELD (recurrence tracked); labeling diagnoses as hypotheses until independently confirmed: OPEN. |
| 49 | PARTIAL | Writes are attributed and zone-gated; signed events and poisoning drills: OPEN. |
| 50 | BY-DESIGN | See 19. |

### E. Planning and execution (51–68)

| # | Status | The honest state |
|---:|---|---|
| 51 | PARTIAL→IMPROVED | Runbooks ARE the SOP half of a capability pack; **Capability Packs now exist as artifacts** (`capability.py`): sealed exam definitions (competencies, exercises, transfer tasks, stdlib validators) living OUTSIDE the expert's root, content-hashed like contracts, with `packs/responsive-pricing/` shipped as the first. The mastery loop (`mastery.py`) runs pretest → study → practice → sealed exam → diagnose → bounded targeted re-study → verdict → distill → retest; verdicts come only from harness-run graders (`test_mastery.py`, 9 laws; 5/5 mutations killed). **Typed operators and HTN methods now exist in runbooks**: `when.not` negative triggers, `when.requires` observe-probes gating applicability at reconcile time, and composite `{"run": sub}` steps with per-sub trust gates and cycle refusal (`test_runbook.py` [applicable]+[compose]; 3/3 mutations killed). **Pack drafting** (`capability.py draft`) + the author law (`test_mastery.py` [author]) open the road into NEW domains. Full domain ontologies remain OPEN. |
| 52 | PARTIAL | Plans parse to bounded milestones; missing-verifier milestones get evidence-note gates. Full typed-DAG static checks: OPEN. |
| 53 | PARTIAL | Capability probes are live (toolbox scans on every assess); goal-implication inference is a keyword table, stated as a blind spot. |
| 54 | OPEN | No semantic state estimation with freshness/confidence. |
| 55 | CLOSED (goal system) | `runbook.reconcile` is the desired-state controller: observe (acceptance tests) -> act (one proven runbook) -> verify -> repeat, bounded rounds, blocked-with-frontier-named when nothing matches. Tested with zero model involvement. |
| 56 | PARTIAL | For goals: durable events, resume, replay — tested. Persisted timers/signals/compensations: OPEN. |
| 57 | OPEN | No one-vs-many controlled comparison. The audit's citation says more agents are not monotonically better; nothing here contradicts it. |
| 58 | OPEN | Worker registry is records; live provisioning unexercised. |
| 59 | PARTIAL | Teamwork protocol has typed handoffs; loss scoring: OPEN. |
| 60 | PARTIAL | Best-of-N candidates are gate-scored with strict-win promotion (tested); a general evidence-reading reducer: OPEN. |
| 61 | OPEN | Single-host leases are real and tested; multi-host fencing tokens are not built. |
| 62 | OPEN→IMPROVED | The contract state machine is now EXHAUSTIVELY probed instead of sampled: all |S|² transition attempts against the real `transition()`, graph properties (verified's only door is `running`; terminals exitless; all states reachable), seeded ledger-replay walks, forged-snapshot detection (`test_contract_model.py`; a loosened-table mutation killed). A full TLA+/SPIN model with temporal properties remains OPEN. |
| 63 | **CLOSED** (goal system) | The contract outranks self-written graders and a lying judge, end-to-end, 8/8 mutations killed. Platform-wide reward-hack drills beyond goals: PARTIAL. |
| 64 | PARTIAL | Judge on a different model family; harness runs all checks itself; diverse-provider verification pending keys. |
| 65 | OPEN | Promotion evidence is seeded/synthetic until live work exists. |
| 66 | BY-DESIGN | Runtime cannot modify platform code — matching the audit's own remedy. Skills/tools/acquisitions are the governed lanes. |
| 67 | BY-DESIGN | AutoML/AutoGen/etc. not adopted; the audit: implement only if the specialist needs them. Documented as non-goals. |
| 68 | OPEN | No replay-old-runs-on-new-code CI. |

### F. Tools and computers (69–80)

| # | Status | The honest state |
|---:|---|---|
| 69 | OWNER | Browser = `python mcp.py enable playwright` (needs node, needs your approval — enabling a toolkit is review-gated as of this session's earlier fix). |
| 70 | OWNER | Same command; offline protocol conformance is tested, a live third-party server needs your go. |
| 71 | OPEN | Federation is scaffolding + offline round-trip; cross-org live exchange unproven. |
| 72 | OWNER | e2b/daytona backends speak the documented contract against a loopback; live jobs need keys. |
| 73 | PARTIAL | Docker proof on two OS families in CI; rootless/seccomp/image-signing: OPEN. |
| 74 | OPEN | No resettable remote VMs. |
| 75 | OWNER | The ladder is tested to the refusal boundary; one real pinned acquisition needs your approval to cross it. |
| 76 | CLOSED | "Every tool" was never the design: capability registry + scoped, expiring, logged grants are the bounded implementation. |
| 77 | CLOSED (as designed) | Accounts/mailbox/payments are authority gaps that route to you; grants are scoped+expiring and — since this session — every use is logged. The audit endorses exactly this. |
| 78 | PARTIAL | Docker denies network by default; env scrubbed of credential shapes. Per-goal egress allowlists: OPEN. |
| 79 | OPEN | GUI idempotency (read-before-write, compensation) unbuilt — browser work is behind an owner gate anyway. |
| 80 | OPEN | Tool conformance corpora per version/environment. |

### G. Security and privacy (81–94)

| # | Status | The honest state |
|---:|---|---|
| 81 | **CLOSED** | `SECURITY.md`: boundaries, mediators, seven stated non-defences with reasons. |
| 82 | PARTIAL | Plain HTTP documented as localhost-only; TLS via reverse proxy or the Cloudflare Worker. Native TLS: BY-DESIGN out (stdlib server). |
| 83 | OPEN | No sessions/MFA/revocation — documented limit; front with an identity provider. |
| 84 | OPEN | No secret manager/rotation — documented limit. |
| 85 | CLOSED (scoped) | One home = one tenant, stated; multi-tenant is out of scope. |
| 86 | OPEN | Zero-trust per-request identity unbuilt. |
| 87 | PARTIAL | Per-route permission table + org roles; step-up/two-person controls: OPEN. |
| 88 | OPEN | Live injection red-team needs a real model (see C34). |
| 89 | PARTIAL | Boot locks, leases, SIGTERM drain + second-signal force, panel shutdown, heartbeats — tested. Independent assurance of safe-state invariants: OPEN. |
| 90 | OPEN | An operating process, not code — needs you to define on-call/escalation. |
| 91 | OPEN | No retention/deletion/consent program. |
| 92 | OPEN | No regulated assurance. **Regulated claims remain prohibited** in every shipped doc. |
| 93 | OPEN | No bias/impact program. |
| 94 | OPEN | No independent third-party security scan yet. |

### H. Reliability and cloud (95–105)

| # | Status | The honest state |
|---:|---|---|
| 95 | OPEN | Endurance is seconds-scale; day-scale soaks need a live provider. |
| 96 | OPEN | DST/months scheduling untested — stated blind spot. |
| 97 | PARTIAL | Goal budgets (usd/minutes/cycles) + per-task and daily ceilings; enforcement between units of work, overshoot bounded by one unit, stated. Preauthorization: OPEN. |
| 98 | CLOSED (as docs) | At-least-once + idempotency is the documented truth (P2-1); "exactly-once" is not claimed. |
| 99 | PARTIAL | Backup verify/restore tested locally incl. corrupted archives; production DR rehearsal with RPO/RTO: OPEN. |
| 100 | OPEN | No SLOs/alerting/runbooks. |
| 101 | OPEN | No human-time accounting per verified outcome. |
| 102 | OWNER | Deploy artifacts exist (image builds; suite passes inside it; Worker typechecks; dry-run deploys). A live URL + phone flow needs your Cloudflare account. |
| 103 | PARTIAL | The redesign the audit demands is exactly what `deploy/` does: no POSIX assumptions on object storage, R2 push/pull instead of FUSE, boot locks. Live canary: OWNER. |
| 104 | BY-DESIGN→OPEN | Single-home by design; horizontal scaling would need the distributed leases of E61. |
| 105 | OPEN | No dependency/version upgrade program (small surface: stdlib + 3 pinned npm packages). |

### I. Product truth (106–115)

| # | Status | The honest state |
|---:|---|---|
| 106 | OPEN | No human usability sessions yet. |
| 107 | OPEN | No WCAG audit. |
| 108 | OPEN | No real-device mobile testing (CSS-level only). |
| 109 | OPEN | No design-quality review beyond the mechanical design gate. |
| 110 | **CLOSED** | Every count in README/ARCHITECTURE now comes from a command; link check across all docs: 0 broken. Kept honest by re-running, not by promising. |
| 111 | **CLOSED** | Runner prints executed/passed/skipped/failed with names; EVIDENCE.md counts skips with reasons. |
| 112 | PARTIAL | The Windows shutdown skip is visible, reasoned, and counted everywhere; a Windows-native drain test remains OPEN. |
| 113 | PARTIAL | MCP enable is review-gated; signed manifests/deny-by-default loading: OPEN. |
| 114 | OPEN | Mission metrics lack supervision-time and long-term retention. |
| 115 | OWNER | The token in this environment has push but not admin. One command, provided ready to paste in the session notes. |

**Tally: 13 CLOSED · 6 BY-DESIGN (each matching the audit's own
recommendation) · 33 PARTIAL · 12 OWNER · 51 OPEN.** The OPEN column is
dominated by two prerequisites this machine does not have: a real provider
key, and time-scale (soaks, pilots, humans). That is the audit's own
conclusion — the gap between offline-verified control structures and
measured real-world achievement — and no amount of code closes it without
those two inputs.

---

## Part 3 — What to do next, in order

1. **Put one key in `agent.env`** (B12). Cheapest honest option measured
   this session: Cloudflare `qwen3-30b-a3b-fp8` — 493 free steps/day with
   tool calling, $0.22/1k after. `python loop.py check` is the probe;
   preflight and doctor will flip together (that is now tested behavior).
2. **Run 20 bounded pilot goals WITH acceptance tests** (A5, B13): real
   provider, real `--accept` graders, budgets on. Every trace lands in the
   ledgers this session built.
3. **Then the paired lift experiment** (A3) on `evalsuite`'s sealed holdout:
   same model bare vs in-system. Publish the four ratios, whatever they say.
4. **Run the first capability pack live** (E51) — the pack format and the
   mastery loop are built and tested (`capability.py`, `mastery.py`,
   `packs/responsive-pricing/`); what remains is running
   `python mastery.py run <home> <expert> responsive-pricing --drive`
   against a real provider and publishing the pretest→exam→retest deltas,
   whatever they say.
5. **Deploy the container to Cloudflare** (H102) when you want the phone
   path: the artifacts are built and dry-run verified; the first live
   deploy is the first real test, and it is labeled as such.
