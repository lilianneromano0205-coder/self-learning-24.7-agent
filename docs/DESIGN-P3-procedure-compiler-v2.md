# DESIGN — Phase 3: Procedure Compiler V2

**Branch:** `phase3/procedure-compiler-v2` · **Status:** DESIGN (nothing
below is built until this document's benchmark exists) · **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision.

## The problem, stated from evidence

Compiled procedures today are straight lines: an ordered list of
deterministic adapter steps. Real recurring work branches ("create the
summary if it does not exist, otherwise extend it"), iterates over bounded
collections, retries against a precondition, composes smaller proven
pieces, and cleans up after itself. Today every one of those shapes is a
model-required barrier even when each leaf action is a trusted adapter.

## What Phase 3 builds

A **restricted, typed, total procedural IR** — data, never generated code —
plus its executor, validator, and the first control-flow induction rule.

### The IR (step kinds, all closed)

```
deterministic          the existing leaf: one trusted adapter action
{"kind": "if",    "predicate": P, "then": [steps], "else": [steps]}
                       P is an observable predicate, observed at run time
{"kind": "foreach", "items": {"input": param} | [literals],
                    "bind": name, "max": N, "body": [steps]}
                       N <= 32 enforced at validate AND at bind time; the
                       bound variable substitutes {"item": name}
                       placeholders inside the body
{"kind": "check",  "predicate": P}
                       mid-procedure assertion; false stops the run
{"kind": "retry",  "times": N (<=3), "body": [steps]}
                       bounded re-attempt; every leaf in body is a
                       deterministic adapter, so re-performing is safe
                       (writes are idempotent, db commits are gated)
{"kind": "call",   "name": runbook, "inputs": {...}}
                       composition: the callee must be PROVEN at execute
                       time (fail closed), cycles refused at validate,
                       depth capped at 4
{"kind": "compensate", "body": [steps], "on_failure": [steps]}
                       if body fails, on_failure runs (cleanup) and the
                       procedure STILL FAILS — compensation is never
                       success
```

Refused forever, per the master spec: unrestricted generated Python,
unbounded loops, hidden recursion, shell logic, model steps inside the
trusted lane. PARALLEL is deferred to a later phase: a single-process
executor offering "parallel" would be theater; declared-independence
validation arrives with real concurrency.

### Authoring paths — all priced identically

Owner CLI, teach-by-demonstration, a model proposal, or the compiler's own
induction: every source lands as CANDIDATE, and only an owner-sealed fresh
suite (edge case included) makes any of them PROVEN. Same ceilings as
Phase 0-2.

### The first control-flow induction rule (deliberately narrow)

When trajectories in one family refuse straight-line alignment, the
compiler attempts exactly one structure: a two-way IF.

- Group trajectories by their tool-sequence signature; exactly two groups,
  each internally aligned, each contributing independent evidence.
- Guard search is deterministic and closed: for each write-target path
  shared by the groups' steps, test whether `file_exists(target)` was
  uniformly TRUE before one group's runs and uniformly FALSE before the
  other's (read from the recorded before-snapshots — never re-imagined).
- Exactly one discriminating guard → emit `if guard then <group-A steps>
  else <group-B steps>` as a CANDIDATE. Zero guards or ambiguity → refuse
  with the reason, exactly as unaligned compiles refuse today.

FOR EACH / RETRY / CALL / COMPENSATE are authorable in V2 but not yet
induced — stated honestly here and in the module docstring.

## Benchmark (exit criterion, preregistered before build)

`tests/test_procedure_v2.py`, in the acceptance suite:

1. the validator refuses: unknown kinds, unbounded/over-cap loops
   (foreach without max, max>32, retry times>3), cyclic CALL graphs,
   over-deep CALL chains, model steps inside control flow;
2. IF observes its predicate at run time and takes the correct branch —
   both arms exercised across two executions;
3. FOREACH iterates a typed list input, bounded: an over-cap list refuses
   at bind time before any side effect;
4. CHECK false stops the run with the predicate named; RETRY attempts
   exactly N times and fails honestly when the body never succeeds;
5. COMPENSATE runs its cleanup on failure, the cleanup's effects are
   observed, and the procedure still FAILS;
6. CALL composes two PROVEN procedures; a candidate callee refuses fail
   closed at execute time;
7. lifecycle: an authored V2 procedure (IF + FOREACH + CHECK) lands
   candidate, goes PROVEN through an owner-sealed fresh suite with an
   edge case, and then completes a live task with ZERO model calls (empty
   provider script) under the task's own gate — both IF branches proven
   and replayed;
8. induction: two straight-line-refusing groups of gate-captured
   trajectories with a discriminating existence guard compile into an IF
   procedure (CANDIDATE); an ambiguous split (no discriminating guard)
   refuses with the reason;
9. no existing test weakened; `test_vision_preservation.py` untouched.
