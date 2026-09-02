# DESIGN — Phase 7: Transactional contracts (broader SQL operations)

**Branch:** `phase7/transactional-contracts` · **Status:** DESIGN (committed
before any code; flips to BUILT only when the preregistered benchmark
below is green in the acceptance suite) · **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision. ·
**Audit order:** the 2026-09-02 checkpoint audit's operator-universe order
after XLSX — *"3. Broader SQL transactional operations — the current
SQLite substrate is already surprisingly good; build more database
adapters around the same semantics"* — and its list of what induction
still cannot learn, which ends with *transactional business operations*.

## The problem, stated from evidence

`db_transaction` gates a mutation on its POST-state: every declared
assertion must observe true inside the transaction or it rolls back. Three
things a business transaction needs are still missing:

1. **A precondition.** "Transfer 100 from A to B" is only correct if A
   holds 100 *before*. Today the worker can only discover that after the
   UPDATE, by asserting the post-state and paying a rollback; the
   procedure compiler, which sees only what happened, cannot learn that
   the step *applies only when* the ledger is in a stated condition.
2. **An invariant.** "The sum of all balances is unchanged" is a statement
   about before AND after. Assertions can only pin a value the worker
   already knows; they cannot say *whatever it was, it still is*.
3. **More than one file.** A reconciliation writes the ledger and the
   audit log; a period close touches the journal and the balances file.
   `ATTACH` is banned from worker SQL for containment reasons — correctly —
   so a two-file business operation cannot be atomic today, and the model
   falls back to `run_command`.

The repository is stdlib-only by design, so "more database adapters" does
not mean PostgreSQL drivers; it means widening what the trusted SQLite
substrate can *promise*, around the same commit-or-untouched semantics.

## What Phase 7 builds — measurable capability

`db_transaction` (and `dbstate.transact`) gain three optional, screened,
canonical inputs:

```
preconditions   [{query, equals}]        observed BEFORE any statement;
                                         one false -> refuse, nothing mutated
invariants      [{query}] | [{query, equals}]
                                         observed before and after; a bare
                                         query must return the SAME rows
                                         both times, one with `equals` must
                                         return exactly those rows both times
attach          {alias: {path, mode}}    sibling databases joined to the ONE
                                         transaction under adapter-issued
                                         ATTACH; mode read | write
```

The capability in one sentence: **transactional business operations —
guarded transfers, conservation invariants, atomic multi-file writes —
become gated actions the compiler can turn into proven procedures whose
replay refuses, before any mutation, when the state it was learned on no
longer holds.**

### Semantics (dbstate.transact)

```
attach every sibling (read mode as a mode=ro URI, which SQLite enforces)
refuse if any journal mode is WAL (multi-file commits are atomic only
    under the rollback journal; the adapter checks, the worker cannot)
BEGIN IMMEDIATE
observe preconditions  -> mismatch: ROLLBACK, refuse "precondition did not
                          hold — nothing was mutated"
observe invariants (before)
execute statements
observe assertions     -> mismatch: ROLLBACK (as today)
observe invariants (after) -> differs from before / from equals: ROLLBACK
COMMIT
```

Worker SQL keeps the same screen: `ATTACH` stays banned there — the adapter
attaches, from data the owner's allowlist governs. Aliases are screened
(`[a-z][a-z0-9_]{0,15}`, never `main`/`temp`); statements, assertions,
preconditions and invariants may reference `alias.table`.

### Authority

An attached database in **write** mode demands its own `db-write:<path>`
token exactly as the main database does — per leaf in V2, derived per
static walk in V1, and from the owner's `[agent] db_write` allowlist at
the worker tool. **Read** mode demands workspace read only, and SQLite's
`mode=ro` makes the promise mechanical: a statement that writes a
read-attached file fails inside the transaction and rolls it back.

### The algebra and the compiler

`db_satisfies_all` gains an optional `attach` field so an assertion over
`alias.table` can be re-observed later exactly as it was gated (read-only
attach at observation time). The compiler emits, for a step that carried
preconditions, a **`db_satisfies_all` step precondition** — the first
state precondition in the IR beyond file existence — so a replayed
procedure refuses at `step precondition changed` before touching the
database when the ledger is not in the condition the step was learned
on. Invariants become step effects only when they carry `equals` (a bare
"unchanged" invariant is a property of the transition, not of the state
after it, and is verified inside the transaction, where it belongs).

### Wiring (each a bounded extension of an existing seam)

- `dbstate.py` — `canonical_conditions` (preconditions), `canonical_invariants`,
  `canonical_attach`; `transact(..., preconditions, invariants, attach)`;
  `check_assertions(..., attach)`; `_attach` helper with URI read-only.
- `operators.py` — `db_satisfies_all` accepts `attach`; `observe` passes it.
- `procedure.py` — `_normalize` canonicalizes the three new args;
  `_snapshot` hashes attached files too; `finish_action`/`_perform` pass
  them; `_compile_aligned` emits the precondition and threads `attach`
  into the effect; `_run_leaf` and the V1 walk demand tokens for every
  write-attached path.
- `loop.py` — `db_transaction` accepts the three optional args; the
  allowlist check covers every write-attached path; route grant unchanged.

## Benchmark (exit criterion, preregistered before build)

`tests/test_transactional_contracts.py`:

1. **Precondition refuses before mutation:** a transfer whose declared
   precondition (A ≥ 100) does not hold refuses with the reason; both
   balances unchanged; no rollback receipt needed because nothing began.
2. **Invariant rolls back:** an UPDATE that would break "sum of balances
   unchanged" rolls back whole; a transfer that conserves it commits; an
   `equals` invariant pins the total both before and after.
3. **Two files, one commit:** ledger.db and audit.db written in one
   transaction; a failing assertion on the audit side leaves BOTH files
   untouched (the ledger row is not there either).
4. **Read attach is read-only:** a statement writing a read-attached file
   fails and the transaction rolls back; WAL journal mode on any file
   refuses the attach; worker SQL containing ATTACH is still refused by
   the screen; bad aliases (`main`, `temp`, `x;y`) refuse.
5. **Authority per file:** a write attach demands `db-write:<that path>`
   (V2 leaf and V1 walk); the worker tool refuses an attach outside
   `[agent] db_write`; a read attach demands nothing more.
6. **End to end:** the "guarded transfer batch" family — two gated
   trajectories with preconditions and an invariant compile into a
   candidate whose step carries a `db_satisfies_all` PRECONDITION; an
   owner-sealed fresh suite (edge: a transfer of the exact balance) takes
   it to PROVEN; a silent worker replays with **zero model calls**; and a
   replay against a ledger that no longer satisfies the precondition is
   refused at `step precondition changed` with the database untouched —
   verified by an independent sqlite3 gate.
7. No existing test weakened; `test_vision_preservation.py` untouched;
   prose counts and registrations updated (no new module: this phase
   widens `dbstate.py`).

## What this phase does NOT claim

No real-model result. No network databases: the repository stays
stdlib-only, and the audit's "more adapters" is answered here as more
*semantics* on the substrate that exists. Multi-file atomicity is SQLite's
rollback-journal guarantee, stated as such and enforced by refusing WAL —
not a distributed transaction.
