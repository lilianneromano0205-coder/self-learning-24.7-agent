# DESIGN — Phase 4: Capability Signatures (shadow)

**Branch:** `phase4/capability-signatures` · **Status:** DESIGN (nothing
below is built until this document's benchmark exists) · **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision. ·
**Audit gate:** per the 2026-09-02 checkpoint audit, this phase ships in
SHADOW only — it augments the deterministic lexical matchers, changes no
routing authority, and names the measurement that must improve before any
authority ever switches.

## The problem, stated from evidence

Capability matching is still lexical: `runbook.match` requires every
substantive trigger word to appear in the goal, `skills.matching` keys on
filename tokens and KEYWORDS, and `universal.py` carries a large
hand-authored phrase table whose own comments document past false
positives and negatives. The audit rates capability generalization 4/10 —
the largest intelligence-architecture gap. Two requests with different
words and the same structure ("match Stripe payouts against Shopify
orders" / "reconcile processor settlements with ecommerce sales") cannot
find the same proven procedure today.

Meanwhile the structure already exists on one side: every compiled
procedure carries a typed input schema, a closed set of operator leaves,
effect predicate kinds, and (since Phase 3) its control shape. What is
missing is a WAY TO ASK "does this task's structure fit that procedure's
structure?" — and the discipline to measure that lens before trusting it.

## What Phase 4 builds

**`signatures.py`** — structural capability signatures, plus a shadow
matcher and its measurement ledger. No routing change of any kind.

### The signature of a procedure (computed, never authored)

```
of_runbook(rb) ->
  input_schema     {name: kind} exactly as the operator declares
  input_kinds      sorted multiset of kinds (the structural core)
  operators        sorted set of leaf tools (write_file, transform_table,
                   db_transaction, …) collected recursively through V2
                   control structures
  effect_kinds     sorted set of effect predicates (file_derives,
                   table_conforms, db_satisfies_all, …)
  control          sorted set of control kinds used (if, foreach, call, …)
  writes_db        bool
  signature_hash   digest of all of the above
```

Deterministic, derived from structure only — triggers, names and prose
never enter the hash, so rewording changes nothing.

### The structural match (shadow only)

A task is *structurally compatible* with a proven procedure when
`operators.check_inputs` accepts the task's declared typed inputs against
the procedure's schema — the same test the live route already applies
AFTER lexical matching, now asked ACROSS every proven procedure
regardless of words. `shadow_match(root, task)` returns the sorted
compatible set.

### The shadow hook and the ledger

Inside `_try_procedure_route`, after the lexical `runbook.match` result
is known, the loop logs ONE event and changes nothing:

```
signature_shadow {task, lexical: [...], structural: [...],
                  agreement: same | structural_only | lexical_only
                             | both_empty}
```

`python signatures.py report --root R` aggregates the ledger: agreement
counts, and the `structural_only` set — the procedures the words missed
but the structure found. That report IS the phase's product.

## The authority rule, preregistered

**No matcher authority changes in this phase, and none may change later
without a measured comparison.** The future gate (SIG-001, not built
here): over ≥100 live route-eligible tasks, structural-only candidates
must, when executed in a sandboxed dry evaluation, pass the tasks' own
gates at ≥ the lexical route's rate — with receipts — before a single
routing decision consults signatures. Until then the deterministic
lexical floor keeps sole authority, exactly as the audit directs:
augment, shadow, compare, only then switch.

## Benchmark (exit criterion, preregistered before build)

`tests/test_capability_signatures.py`:

1. `of_runbook` is deterministic and INVARIANT to rewording: changing a
   procedure's triggers/name/prose changes nothing in the signature hash;
   changing its input schema or steps does;
2. the paraphrase case: a PROVEN procedure whose trigger words share
   nothing with a task's goal is invisible to `runbook.match` (lexical
   []), found by `shadow_match` (structural [proc]), the
   `signature_shadow` event records `structural_only` — and the task
   still executes through the MODEL path, completing under its own gate,
   with no `procedure_route` event: shadow changed nothing;
3. the authority invariant: a lexically-matched task routes exactly as
   before with the shadow active (same `procedure_route` event, zero
   model calls), and the shadow event records `same`;
4. no false structural match: same wording, wrong typed inputs — the
   shadow does not propose the procedure;
5. the report CLI aggregates the ledger (counts by agreement class and
   the structural-only names);
6. no existing test weakened; `test_vision_preservation.py` untouched.
