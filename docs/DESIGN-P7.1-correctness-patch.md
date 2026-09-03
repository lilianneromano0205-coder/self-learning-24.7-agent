# Phase 7.1 — Correctness patch (design, committed before code)

**Status: BUILT** (this document was committed first; the build commit
follows it and cites this file).

## Why this phase exists

The owner's fresh repo-wide verdict of 2026-09-02 named two P0 findings and
two hardening items inside the trusted procedure path, and ordered them
closed as a *tiny correctness patch, no new concepts* before any pilot.
All four were confirmed in the code at `main b6b9ebc` before this document
was written (see the Reality Phase Dossier's verification log):

| Id | Finding | Where it was true |
|---|---|---|
| P0-A | a guarded transaction against a **missing** main database creates an empty file before the precondition refuses, so "precondition false → nothing was mutated" had an edge case | `dbstate.py:250-255` (`_uri` adds only `?mode=ro`), `:323` (connect), no existence check in `transact` while `query` has one |
| P0-B | procedure applicability was inferred by parsing English — any failure text containing the word "precondition" counted as *not applicable* | `loop.py:3564` `inapplicable = "precondition" in why`; the guard is raised as `ProcedureError("step precondition changed")` at `procedure.py:966, 1104`; SQLite's own runtime refusal text also matched |
| P1-A | a bare invariant compares ordered rows, but row order without ORDER BY is not a guarantee SQLite makes — equal data could fail | `dbstate.py:337, 355` plain list inequality |
| P1-B | byte evidence hashing loaded whole files into memory | `fileauth.py:313-323` |

## What measurable capability this adds

Nothing new can be *done*; four things can now be *trusted* that could not:

1. A proven procedure's refusal is a **typed verdict** — `status` in
   {`ok`, `inapplicable`, `failed`} with a `reason_code` from a closed set —
   so the route's "not applicable, do not count it against the procedure"
   decision can never be triggered by prose, and can never miss a guard
   whose message did not happen to contain the word.
2. A false precondition on a database that does not exist leaves **no file
   behind**; observation paths open `mode=ro`, mutation paths `mode=rw`,
   and creation is a separate explicit operation (`run_script`).
3. An invariant either carries `ORDER BY` or declares `"unordered": true`;
   the unordered form compares multisets. Equal data can no longer fail.
4. Byte evidence is hashed in 1 MiB chunks.

## The closed set of reason codes

| Code | Status | Raised when |
|---|---|---|
| `PRECONDITION_MISMATCH` | inapplicable | a step or operator precondition/invariant observed false before the step ran |
| `AUTHORITY_MISSING` | inapplicable | a required `db-write:` / `git-write:` / declared token was not granted — the environment, not the procedure |
| `MODEL_REQUIRED` | inapplicable | a v1 procedure reached a model step; deterministic execution stops |
| `EFFECT_FAILED` | failed | a step, copy, invariant-after or final effect did not verify |
| `CHECK_FAILED` | failed | a v2 `check` predicate observed false |
| `BOUND_EXCEEDED` | failed | a `foreach` received more items than its declared bound |
| `CALL_FAILED` | failed | a `call` cycle, depth, unproven target, or a callee that failed |
| `EXECUTION_ERROR` | failed | anything else: an adapter refusal, an OS error, a bad input |

*Inapplicable* means "the world or the grant is not the one the procedure was
learned on"; it is logged as `procedure_route_refused … applicable: false`
with the code, and **records no loss** — in the loop and in `runbook.run`.
Everything else is a failure and counts.

## Benchmark that must pass before this becomes permanent

`tests/test_correctness_patch.py`, preregistered here, four properties plus
registration. Each property FAILS on the tree before its fix:

1. **Structured verdict.** A v2 procedure whose step precondition is false
   returns `status == "inapplicable"`, `reason_code == "PRECONDITION_MISMATCH"`,
   and touches nothing; a step whose effect cannot verify returns
   `status == "failed"`, `reason_code == "EFFECT_FAILED"`; a db step without
   its token returns `AUTHORITY_MISSING` (inapplicable) before any database
   access; `procedure.route_verdict` classifies from the code — a failure
   whose prose contains the word "precondition" is still a failure, and a
   verdict with no status is a failure (fail closed); two consecutive
   inapplicable replays through `runbook.run` do **not** quarantine.
2. **Missing database.** `transact` against a path that does not exist
   refuses naming the reason and the path is still absent afterwards;
   `query` likewise creates nothing; `run_script` remains the creation path,
   and a transaction on the created file commits.
3. **Invariant order.** A bare invariant without ORDER BY is refused at
   canonicalization naming the remedy; with `"unordered": true` a
   delete-and-reinsert (which flips SQLite's natural scan order — proven by
   an independent sqlite3 read) commits; the ORDER BY form commits on the
   same mutation; an unordered invariant that is actually broken rolls back
   whole.
4. **Streaming hash.** A 3 MiB file hashes to the same digest as
   `hashlib.sha256` over its bytes, and still does after the whole-file
   reader is replaced with one that raises — the hash never loads the file.
5. **Registration.** The test is declared in `tests/run_all.py`,
   `evidence.py` and `proof.py`; prose counts move 147 → 148.

## Claim envelope (per docs/DESIGN-P6.1)

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| typed verdict | every refusal in `procedure.execute` passes through `_refuse(code, …)` | a refusal raised as a bare `ValueError` from an adapter is `EXECUTION_ERROR` — a failure, never inapplicable | `procedure.execute` result fields; `runbook.status` after two inapplicable runs |
| no file on refusal | main database checked with `os.path.isfile` before connect; attached siblings already checked | a race that creates the file between check and connect (the transaction then runs against an empty database and its precondition decides) | `os.path.exists` after the refusal |
| ordering | the invariant query carries ORDER BY, or is declared unordered | assertions and preconditions keep ordered comparison (their claim envelope, Phase 1/7, is "these exact rows"); authors ORDER BY there | independent `sqlite3` read showing the flipped natural order |
| streaming | 1 MiB chunks | memory is not measured, only the property that the whole-file reader is never called | monkeypatched `read_bytes` that raises |

## What this phase does NOT claim

No new operator, tool, predicate or world. No change to what an assertion
or precondition means. No real-model result. The reason-code set is closed
and documented above; a future code must be added here first.
