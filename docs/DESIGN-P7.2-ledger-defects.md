# Phase 7.2 — Ledger defects (design, committed before code)

**Status: BUILT** (this document was committed first; the build commit
follows it and cites this file).

## Why this phase exists

The Capability Ledger of 2026-09-02 (a code-grounded inventory of the tree
at `main b6b9ebc`, seven read-only sweeps plus hand spot-checks) found a
set of small, specific defects that no phase owned. None is architecture;
each is a place where the code says one thing and does another, or where a
trust ledger sits where the agent can write it. The lab rule is that a
finding is closed by a test that fails before the fix, so they are closed
here together, as one branch with one benchmark.

| # | Where | Defect |
|---|---|---|
| 1 | `doctor.py:65-71` | the module import check uses `for … else` with no `break`, so "all N core modules import" prints even after an import failed; the core list omits the modules that decide authority (`org`, `controlplane`, `fileauth`, `execution`, `credentials`, `modelgateway`, `workers`, `training`, `metrics`, `gates`, `scheduler`, `procedure`, `verifier`, `verification`, `operators`, the state worlds) |
| 2 | `ui.html:2997-3022` | the new-task dialog offers "a command that must exit 0" and posts a raw string; `ui.py:_net_gate` refuses every non-empty string over HTTP by design (gates.py), so the form cannot succeed |
| 3 | `ui.html:4890-4897` | the invite dialog asks for "your email (the actor)" and posts it; the server ignores the field and uses the token identity |
| 4 | `loop.py:2350` vs `modelgateway.py:66` | sub-calls are metered with `purpose="subquery"`, which is not in the gateway's purpose list, so they are stored as `unknown` |
| 5 | `fileauth.py` zones | `memory/cases.jsonl` — the ledger that records whether a fix held, injected into windows as "verified by a gate, not by opinion" and read by the repeat-failure metric — resolves to the root zone, which the agent's file tool may write; every comparable ledger is CONTROL |
| 6 | `toolbox.py:66` | a comment promises `python toolbox.py recipes`; the CLI has no such surface |
| 7 | `fileauth.py:114` | a docstring cites `test_fileauth`, which does not exist (the assertion lives in `test_invariants.py`) |
| 8 | `harness.py:283` vs `federation.py:292` | the manifest reports an A2A version "1.0" while federation declares `a2a_task_api: false` |
| 9 | `tests/test_acquire.py:503` | the skip says "docker not available" when the condition is a settings check (`_use_docker`) or docker's absence — the evidence report quoted the wrong reason in a run where docker tests passed |
| 10 | prose | REFERENCE says twenty templates (code: 24) and four intention kinds (code: seven); the README badges say 120 tests and 56/56 mutations (code: 149 tests, 32 mutations). The Ledger also claimed MANUAL and REFERENCE undercount proof capabilities (19 versus 21); the benchmark's own count of `proof.REGISTRY` is 19, so the prose was right and the Ledger was wrong — corrected there, pinned here |

## What measurable capability this adds

Nothing new can be done. Ten places now say what they do: the doctor
reports an import failure as a problem; the panel can queue a gated task;
sub-call spend is attributable; the case ledger is out of the worker's
reach; the manifest and the prose agree with the code.

## Benchmark that must pass before this becomes permanent

`tests/test_ledger_defects.py`, preregistered here:

1. **Doctor.** With a bogus module injected into `CORE_MODULES`,
   `check_runtime` reports a PROBLEM and never prints "core modules
   import"; every authority module is in the list.
2. **Panel gate.** The task dialog carries a gate picker from
   `GET /api/gates` and no free-form command field; the object the form
   builds is accepted by `_net_gate`, and a raw string is still refused.
3. **Invite.** The invite dialog has no actor field; the body it posts has
   no `actor` key.
4. **Sub-call purpose.** `"subquery"` is a declared gateway purpose, and a
   recorded sub-call row keeps it.
5. **Case ledger.** `memory/cases.jsonl` classifies CONTROL; an agent write
   is refused and a harness write allowed; the path is enumerated in the
   promotion-leakage suite.
6. **Recipes.** `python toolbox.py --recipes` prints every pinned
   acquisition recipe.
7. **Manifest.** The harness manifest's A2A entry states what federation
   states: a card is served, the task API is not implemented.
8. **Prose.** REFERENCE names 24 templates and seven intention kinds;
   MANUAL and REFERENCE state the registry's own count of proof
   capabilities; the README badges carry the test and mutation counts the
   tree has — every number read from the tree, never typed.

## Claim envelope

Every property is a direct read of the tree or a unit call; no model, no
sandbox, no network. Excluded: whether the panel's gate picker is usable
by a person (reachability is tested, usability is not — the standing limit).

## What this phase does NOT claim

No new operator, tool, world or connector. No change to the meaning of any
verdict. The Reality Phase order stands: after this patch the next steps
need the owner (branch protection) and a provider key (smoke, LIFT-001A,
LEARN-001).
