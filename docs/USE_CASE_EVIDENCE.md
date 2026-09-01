# Use cases against evidence — what this platform can actually do

This document exists because the use-case universe for this platform is large
enough to invite speculation, and speculation is the one thing this repository
is built to refuse. Every verdict below is tied to a named test, a named run,
or a named absence. The rule for reading it:

- **VERIFIED** — a mechanical test holds it green in the current suite
  (136 executed, 134 passed, 0 failed; all six CI jobs green on this branch),
  or a named end-to-end run demonstrated it through the shipped CLIs.
- **COMPOSES** — every primitive it needs is individually VERIFIED, but no
  end-to-end test drives this exact composition. The claim is "the parts are
  proven and connect", not "this workload has run".
- **NEEDS X** — a named connector, adapter, credential or experiment does not
  exist yet. The gap is stated, not smoothed over.

Nothing here is a superiority claim. The proof system itself (proof.py) caps
every capability at the evidence level it has actually earned, and green CI is
deliberately unable to imply intelligence lift.

---

## 1. The primitives, and what holds each one green

Use cases are compositions. These are the parts, each with the test that
would fail if it broke:

| Primitive | Held green by |
|---|---|
| Persistent experts (memory survives sessions/model swaps) | `test_memory.py`, `test_awareness.py`, `test_resume.py` |
| Gated tasks (external definition of done; worker cannot self-accept) | `test_e2e.py`, `test_verify.py`, `test_invariants.py` |
| Goals (pursue until frozen graders pass; contract outranks judge) | `test_goal.py`, `test_contract.py` |
| Missions (weeks-long objectives, budgets, blocking) | `test_mission.py` |
| Teams (isolated specialists, controlled handoffs) | `test_team.py` |
| Workflows (gated multi-stage pipelines) | `test_workflows.py` |
| Prospective memory (WHEN condition → THEN work) | `test_prospective.py`, `test_wake.py` |
| Routines (verified work recurs on schedule) | `test_routines.py` |
| Research (retrieval ≠ support; counterevidence; dependencies) | `test_research.py`, `test_research_discovery.py` |
| Institutional memory (failures, competence, retractions, cases) | `test_memory_kinds.py`, `test_cases.py`, `test_gotcha_retire.py` |
| Causal skills (promotion ONLY by matched held-out ablation) | `test_skill_attribution.py`, `test_skillgraph.py` |
| Procedural learning (verified work → candidate procedure, auto) | `test_procedural_learning.py` (15), `test_loop_learning_controls.py` |
| Zero-model replay (proven procedure runs with no model call) | end-to-end CLI run: `procedure_route`, 0 model steps, $0.0000, against an EMPTY provider script — reproduced on a fresh clone of this branch |
| Operator composition (Dijkstra over proven operators) | `test_procedural_learning.py::test_copy_operator_composes...` |
| Model routing (per-expert evidence, exploration, per-attempt attribution) | `test_modelrouter.py` |
| Cognitive scheduler (expected-utility; shadow-by-default; outcomes recorded) | `test_scheduler_verifier.py`, `test_loop_learning_controls.py` |
| Adaptive test-time compute (EV stopping under hard ceilings) | `test_scheduler_verifier.py`, `test_candidates.py` |
| Recursive subqueries (large material via contained subcalls) | `test_harness.py`, tool declared at `loop.py:103` |
| Custom tools / toolbox | `test_toolbox.py` |
| MCP (legacy stdio; credential-isolated; pinned deps) | `test_mcp.py`, `test_mcp_hardening.py` |
| Capability Frontier (propose → falsify → acquire → prove → adopt) | `test_frontier.py`, `test_frontier_live.py`, `test_acquire.py` |
| Isolated acquisition arena (installer never sees the workspace) | `test_acquisition_arena.py` (incl. containment + 8.3-path regressions) |
| Workers / computer routing (capability-implied routing) | `test_workers.py` |
| Organizations (RBAC, personal tokens, audited actors) | `test_rbac.py`, `test_org.py`, `test_governance.py` |
| Standing grants | `test_grants.py` |
| Effect ledger (at-least-once honesty; ambiguity halts, never replays) | `test_effects.py` |
| Verification hierarchy (L0 mechanical supreme; judges logged apart) | `test_scheduler_verifier.py`, `test_loop_learning_controls.py` |
| Control plane (model-authored writes to control state revert; incl. the clock-resolution window) | `test_controlplane.py` |
| Execution authority (policy + sandbox + scrub + approval on every path) | `test_execution_containment.py`, `test_sandbox.py`, `test_invariants.py` |
| Proof system (levels derived from evidence, expire with code changes) | `test_proof.py`, `test_release_checks.py` |
| Training Lab (sealed export → external trainer → sealed eval → canary → promote/rollback) | `test_training.py`, `test_advanced_learning.py` |
| Variants (sealed three-battery evaluation before promotion) | `test_variants.py`, `test_decisions.py` |
| Federation (authenticated consult; foreign answers are evidence, not truth) | `test_federation.py` |
| Cost accounting + Amortization (deterministic share, per-family decay) | `test_metrics.py`, `test_measurement_integrity.py` |
| Capability graph (derived, never self-reported) | `test_capability_graph.py` |

The mutation harness additionally holds 32 deliberate breakages against these
tests: 26 caught, 0 missed, 6 environment-skipped.

---

## 2. Use-case families, mapped honestly

The long-form use-case catalog (self-compiling organization, AI-native BPO,
PE portfolio OS, family office, war rooms, reconciliation meshes, media desks,
one-person conglomerate, and the rest) decomposes into a much smaller set of
capability families. Verdicts attach to families, because that is where the
evidence lives.

### A. Persistent intelligence desks
*(competitor war room, corp-dev sensing, board intelligence, scientific
desks, customer-intelligence networks, media desks, sales account research)*

**COMPOSES.** Missions + persistent experts + research (claims, dependencies,
counterevidence, freshness) + prospective triggers + exception-driven events
are each VERIFIED. What is real and load-bearing: the research system refuses
to call a retrieved page "established" (`test_research_discovery.py` pins
retrieval ≠ support), and stale sources are flagged, which is exactly what
separates a war room from an RSS feed.
**NEEDS**: a provider key (no live model has ever been attached), and for
web-heavy desks the general-web discovery lane enabled by the owner
(`[agent.discovery.general_web]` — built, tested, off by default).

### B. Recurring verified operations
*(weekly reports, reconciliations, document normalization, continuous close,
audit evidence pipelines, franchise reporting, BPO work)*

**VERIFIED for the loop; NEEDS connectors for each system of record.**
The full economic loop is demonstrated, not projected: ordinary gated tasks
are captured automatically, two independent verified runs induce a candidate
procedure (parameters inferred by the compiler itself), an owner-sealed suite
promotes it, and the next matching task executes with zero model calls while
its own gate still decides acceptance. Receipts: `test_procedural_learning.py`
and the end-to-end CLI run on a fresh clone (0 model steps, $0.0000).
The binding constraint is stated in §4: deterministic adapters currently
cover file write/copy semantics. An ERP or bank connector is an acquisition
(family C), and until a corresponding adapter is trusted, recurring work in
that system runs through agents — verified, but not yet model-free.

### C. Self-expanding capability
*(missing-capability detection, governed tool acquisition, "any computer"
workers, industrial connectors)*

**VERIFIED end to end at the mechanism level.** A capability must be proven
ABSENT by a falsifiable probe before acquisition (a probe that passes
pre-install is rejected as unfalsifiable — `test_frontier_live.py`); install
runs in an isolated arena that cannot read the workspace
(`test_acquisition_arena.py`); promotion happens only after the sealed
capability test passes; workers advertise capabilities and routing selects by
them (`test_workers.py`). Physical/industrial actuation is an authority
boundary, not a tool call (`test_universal.py` pins this).
**NEEDS**: each concrete connector still has to be acquired and proven in
the target environment — the machinery is verified, the catalog is not
pre-populated.

### D. Software estate operations
*(repo maintenance, CI triage, software immune system, thousands-of-repos)*

**COMPOSES.** Execution authority, sandboxed commands, gated tasks, goals
with frozen acceptance, candidates/test-time compute, and failure cases are
VERIFIED. The immune-system shape (known failure → known fix) is HALF built:
failure signatures, recurrence counting and case lifecycles are VERIFIED
(`test_cases.py`), but `repair.py` still reasons from scratch each time — no
runtime path consults past repairs. Stated plainly: reusable repair learning
is a designed-but-unwired gap.

### E. Organization-scale structures
*(digital departments, agent/department factories, one-person conglomerate,
family office, PE portfolio OS, roll-ups)*

**COMPOSES**, with one honest asterisk. Orgs, RBAC, budgets, grants, teams,
missions and federation are individually VERIFIED. The Agent Factory chain
(sources → course → study → sealed unseen exam → measured competence) is
VERIFIED with exposure separation (`test_mastery.py` — the partial student
holding all three artifacts still scores 2/3, proving prior work cannot leak
into a sealed exam). What does NOT exist: a one-action "organization
factory" composition surface. The parts are proven; the assembly is manual.

### F. The plugged-model multiplier

This is the family the whole catalog leans on, so it gets the strictest
wording. **Demonstrated mechanically:** once a task family is mastered, its
marginal model cost is zero — the routed task consumed no model call at all,
and the gate still judged the result. For a family executed N times after
mastery, the model-cost multiplier on that family is bounded only by N. That
is the mechanism, and it is real, tested, and reproduced from a clean clone.
**Not established:** any universal "10×/100× for any plugged model" claim.
That requires LIFT-001A run live (preregistered, thresholds fixed in
advance, currently NOT_RUN for lack of a provider key) and then longitudinal
amortization on real workloads. The instrument for the second —
`metrics.amortization`, per-family, honest-null on unmetered spend — is live.
The repository's own claim boundaries forbid asserting the multiplier before
those runs, and this document obeys them.

---

## 3. Additional use cases this evidence actually supports

Added because they fall inside the verified families above, not because they
sound good:

1. **The lab that runs itself** — this repository as its own first customer:
   a mission that triages its own CI failures into cases, retires gotchas by
   probe, and compiles its own recurring maintenance into procedures. Every
   primitive is family B + D; the dogfood loop is also the cheapest source of
   real amortization data.
2. **Multilingual document operations** (e.g. French/Arabic/English business
   documents on a local machine): ingest + conversion capabilities are
   acquisition targets (family C); the mastery system can hold a sealed exam
   in the target language, so "the expert reads French invoices" becomes a
   measured claim instead of an assumption.
3. **Import/export operating desk** — supplier discovery, landed-cost
   analysis, classification research as persistent desks (family A) with the
   authority split the platform enforces anyway: research autonomous,
   commitments human.
4. **Procedure escrow for client work** — deliver a client not a report but
   a proven procedure plus its evidence envelope and sealed suite, re-validated
   in the client's environment (family B + the runbook trust model, which
   already refuses generalization claims beyond its observed envelope).

---

## 4. The boundaries, kept visible on purpose

- **Deterministic adapters are narrow**: write_file/copy_file. Browser, HTTP,
  database and spreadsheet operations run through agents today; compiling
  them to zero-model procedures requires trusted semantic adapters with
  observable pre/postconditions. This is the single highest-leverage
  engineering frontier in the repository.
- **No live provider has ever been attached.** Every intelligence-shaped
  number so far is mock-driven. `benchmark.py` refuses provider spend without
  explicit opt-in, and LIFT-001A stays NOT_RUN until a key and budget exist.
- **Unwired-by-honesty list**: calibration.py (no data producer),
  repair reuse (family D), memory_policy/adaptation (experimental,
  disabled, self-labeled), trainer serving (a promoted checkpoint changes no
  runtime behavior yet). Each says so in its own docstring rather than
  pretending.
- **MCP is the legacy stdio client**, credential-isolated and pinned, not
  Streamable HTTP.
- **Federation is authenticated custom federation**, and its card explicitly
  declines to claim A2A task-API conformance (`a2a_task_api: false`).

The reason to trust the verified rows above is precisely that this section
exists: a system that admits what it cannot do yet is the only kind whose
"VERIFIED" means anything.
