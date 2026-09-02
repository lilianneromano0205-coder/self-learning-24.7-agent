# DESIGN — Phase 2: Verifier Factory

**Branch:** `phase2/verifier-factory` · **Status:** BUILT — the
preregistered benchmark below is `tests/test_verifier_factory.py` in the
acceptance suite; all eight properties hold. Implementation: `verifier.py`
(specs as predicate data; propose/calibrate/promote/gate; owner CLI),
worker tool `propose_verifier` (candidates with provenance, zero
authority), `check_done` verifier branch (trusted-verifier verdicts are
L0 with no shell and no model), and verifier-gated tasks enter the
learning loop like any gated work. · **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision.

## The problem, stated from evidence

The platform's strongest idea is that the worker never decides when work is
done. But today the mechanical gate is a shell `done_check` written per
task, and the predicate algebra (`file_* / table_* / db_satisfies_all`) is
reachable only through owner-sealed judges and suites. The amount of work
the platform can *genuinely know* it completed is bounded by how many gates
someone hand-writes. Phase 1 grew the observable world; Phase 2 grows how
much of it gates real work — without ever letting the thing being graded
define what passing means.

## What Phase 2 builds

**Verifiers as first-class governed objects** (`verifier.py`), with the
lifecycle the master spec demands: *candidate → calibration → evidence →
trusted* — and a factory path where the MODEL may manufacture candidates.

A verifier spec is data, never code:

```
name / version
criteria        the natural-language success statement it mechanizes
params          typed inputs (path | string | integer | number | boolean)
checks          predicate templates over the observable algebra, with
                {"input": param} placeholders — no shell, no model
provenance      who proposed it (owner CLI, or a worker task — recorded)
status          candidate | trusted   (lives in CONTROL state, never in
                anything a worker can write)
calibration     hash-bound record of the discrimination evidence
```

### The lifecycle, rule by rule

1. **Anyone may propose; proposing grants nothing.** A new worker tool,
   `propose_verifier`, files a structurally valid spec as CANDIDATE with
   its provenance. A worker cannot take over an existing name.
2. **Calibration is owner-sealed and must be falsifiable.** The owner
   supplies positive AND negative cases (arena-materialized, `.db` fixtures
   from SQL scripts as in Phase 1). A calibration set with no case the
   verifier must REJECT is refused outright — a verifier that cannot fail
   anything is not a verifier, exactly as an acquisition probe that passes
   pre-install is rejected as unfalsifiable.
3. **Discrimination decides, the owner promotes.** Only a verifier that
   accepted every positive and rejected every negative may be promoted, and
   promotion is owner-only. The calibration record is hash-bound to the
   exact spec bytes: edit the spec and trust evaporates back to candidate.
4. **Only trusted verifiers gate.** A task may carry `verifier` +
   `verifier_params` instead of (or alongside) `done_check`. The verdict is
   pure predicate observation — no shell, no model — and feeds the same L0
   slot in the verification hierarchy. A task naming a non-trusted verifier
   fails its gate, fail-closed, with the reason named.
5. **Verifier-gated work learns like gated work.** A trusted-verifier gate
   is an external mechanical verdict, so it opens trajectories, closes them
   against `verification.passed`, and qualifies tasks for the zero-model
   route — same ceilings, same sealed-suite path to proven.

### Deterministic templates (the floor, not the brain)

`verifier.suggest(criteria)` returns skeleton specs for the recurring
families (reconciliation conservation, typed report, migration counts) from
keyword stems — free and deterministic. The model may propose beyond the
templates; the lifecycle prices everything the same.

## Explicitly out of scope

Model-written verifier CODE (specs are predicate data only); learned/L1
verifier models (a later phase, and never L0); any new predicate kinds;
any network or new authority surface.

## Benchmark (exit criterion, preregistered before build)

`tests/test_verifier_factory.py`, in the acceptance suite:

1. a worker's `propose_verifier` lands a CANDIDATE with provenance, and a
   task gated by that candidate FAILS fail-closed, the refusal naming why;
2. a calibration set with no negative case is refused as unfalsifiable;
3. a verifier that accepts a should-reject case is not promotable;
4. a discriminating verifier (2+ positives accepted, 2+ negatives rejected,
   including an off-by-one-cent corruption) is promoted by the owner and
   then gates live tasks: a correct worker passes, a corrupted worker
   FAILS, with `verification.passed` recorded and the verdict path free of
   shell and model;
5. trust is hash-bound: editing the trusted spec demotes it to candidate
   and gating refuses again;
6. a worker cannot replace an existing name;
7. a verifier-gated task opens a harness_gate trajectory (the learning
   loop sees it);
8. no existing test weakened; `test_vision_preservation.py` untouched.
