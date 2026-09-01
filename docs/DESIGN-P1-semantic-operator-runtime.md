# DESIGN — Phase 1: Semantic Operator Runtime

**Branch:** `phase1/semantic-operator-runtime` · **Status:** BUILT — the
preregistered exit benchmark below is `tests/test_operator_runtime.py` in
the acceptance suite: all five workflows run verified→candidate→sealed
suite→PROVEN→zero-model replay, and every named refusal path is
unit-tested. Implementation: `tabletypes.py` (typed columns incl.
money(currency,scale), constraints; predicates `table_conforms`,
`table_satisfies`), `dbstate.py` (screened deterministic SQLite,
effect-gated transactions; predicate `db_satisfies_all`; worker tools
`db_transaction`/`db_query`), owner allowlist `[agent] db_write` (empty
default, fail closed), per-file `db-write:<path>` authority derived from
bound steps at execute time. · **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision below.

## The problem, stated from evidence

The platform can already run the full loop — verified work → candidate
procedure → owner-sealed promotion → zero-model replay under the original
gate (`tests/test_use_cases.py`, CI-held). But the mechanically representable
world is still small: predicates over files (`file_exists/absent/equals/
derives`) and three trusted adapters (`write_file`, `copy_file`,
`transform_table`). Everything else is a model-required barrier. The system
can *learn* far more than it can *represent*, and that — not model quality —
is the binding constraint on how much work can ever become infrastructure.

## What Phase 1 builds

One common contract for trusted operators, and the first two state domains
that use it.

### The Operator Contract

Every trusted operator declares, as data:

```
identity        name, version, contract hash
inputs          typed schema (string | integer | number | boolean | path |
                decimal | date | table-ref …)
state domain    which world this operator reads/writes (file, table, sql…)
preconditions   observable predicates that must hold before
observations    what it reads (never trusted from memory — re-observed)
effects         observable predicates guaranteed after, re-checkable later
invariants      predicates that must hold before AND after
side effects    none | workspace | external  (external ⇒ effect ledger)
idempotency     idempotent | keyed | non-idempotent
reversibility   reversible | conditional | irreversible
compensation    the operator that undoes this one, if any
authority       required grants (workspace-write, db-write, network-read…)
privacy         data classes this operator may touch
cost / latency  measured, never declared
failure modes   enumerated refusals — ambiguity always refuses
verifier        how a third party re-derives/derives-checks the effect
provenance      where this operator came from, and its evidence
```

The existing adapters are grandfathered INTO the contract (they already
satisfy it implicitly); the contract makes the shape explicit so domains
B–H plug in without touching the compiler.

### Domain A — exact tabular/financial state (extends `tabular.py`)

Typed columns as a declared schema — `string | integer | decimal(scale) |
money(currency, scale) | date | datetime | boolean | identifier |
nullable<T>` — with:

- declared rounding per column; money never touches binary floats
  (the decimal substrate landed in `459e7c2`; this adds TYPES on top);
- schema validation as a predicate (`table_conforms`) usable in gates,
  suite checks, and compiled procedure effects;
- constraint predicates: unique(column), non-null(column), foreign
  presence across two tables, sum-conservation between tables — the
  reconciliation mesh's native vocabulary;
- null semantics that refuse silently-dropped rows.

### Domain B — SQL/database state (SQLite first, stdlib-only)

Operators `db.select` (observation), `db.insert / db.update / db.delete`
(mutations inside `db.transaction`), `db.assert` (predicate), with:

- every mutation wrapped in a transaction whose commit is gated on the
  operator's declared effects re-observing true — else rollback;
- row-count / key-preservation / constraint predicates as first-class
  observables (the migration-verifier vocabulary);
- authority `db-write` distinct from `workspace-write`, granted per
  database file, fail-closed.

### Explicitly deferred (their own phases, per the contract)

Git, XLSX, HTTP-read, transactional APIs, browser, infrastructure. Each
needs its own design and its own benchmark; none may ride in here.

## The rule that overrides everything

**The operator layer must never become the brain.** No operator for an
action ⇒ ordinary model execution, exactly as today. `test_vision_
preservation.py` already pins this; Phase 1 adds the same check for the
new domains: an un-modeled action still reaches the model.

## Benchmark (the phase's exit criterion, preregistered before build)

1. Five materially different recurring workflows representable without
   model-authored shell semantics: two tabular-financial (typed
   reconciliation with money columns; constraint-checked report), two SQL
   (gated migration with key-preservation proof; transactional upsert with
   read-after-write), one mixed (CSV→SQL load with conservation check).
2. Each demonstrated end to end through the loop: verified runs → induced
   candidate → sealed fresh suite → proven → zero-model replay under the
   task's own gate — the `test_use_cases.py` standard, extended to the new
   domains and held green in CI.
3. Every new refusal path unit-tested (typed-column mismatch, constraint
   violation, transaction effect failure ⇒ rollback, authority absent).
4. No existing test weakened; `test_vision_preservation.py` untouched and
   green.

## What Phase 1 must NOT do

- No new claim of lift, cost superiority, or "financial AI" — the phase
  produces representable state and proofs, not marketing.
- No network egress (HTTP is a later phase with its own authority design).
- No model-generated code in the trusted lane.
- No weakening of any fail-closed control to make a domain fit.
