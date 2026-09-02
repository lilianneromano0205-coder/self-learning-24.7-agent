# LEARN-001 — Longitudinal inference amortization on recurring work

**Status: NOT_RUN** (live). The instrument is separately validated on mock
providers — see `LEARN-001-instrument-validation.md`, which establishes the
pipeline, never the result. **No economic claim exists until a real
provider runs this preregistration unchanged.**

Baseline: tag `phase3-verified-programs-baseline`
(`61a111f56296283472eb09bdec9977142fc45a4e`), suite 142 executed / 140
passed / 0 failed on Ubuntu + Windows × Python 3.11/3.12/3.13.

## Research question

Does accumulated verified experience reduce the marginal cognition required
for recurring work, without reducing verified reliability?

LIFT-001A compares system configurations on one pass through a corpus; it
deliberately does not measure learning BETWEEN tasks. LEARN-001 measures
exactly that: the same workload families, run repeatedly, with the
platform's learning loop on.

## Hypotheses

- **H1 (mechanics).** After a family's induced procedure is promoted
  through an owner-sealed fresh suite, marginal model calls for matching
  instances fall to zero while every instance still passes its own
  truth-recomputing gate. (Falsifier: routed instances fail gates, or
  model calls do not fall.)
- **H2 (economics — requires a real priced provider).** Cost per verified
  outcome declines from run 1 to run 20 in each family, tool/compute costs
  included. (Falsifier: flat or rising cost per verified outcome, or
  declining verified success.)
- **H0 (null).** Model calls and cost per verified outcome do not decline
  (slope ≥ 0 across the schedule), or verified success declines relative
  to run 1-2 levels.

## Task families (five, all inside the trusted-adapter universe)

| id | family | shape | gate (independent, truth-recomputing) |
|----|--------|-------|----------------------------------------|
| F1 | typed reconciliation | transform_table join/filter/select with money schema | Python recomputes the reconciliation from both ledgers, byte-compares |
| F2 | sqlite business ops | db_transaction upsert with read-after-write assertions | Python queries the db directly and compares expected rows |
| F3 | structured transform | transform_table aggregate report | Python recomputes group totals with Decimal, compares |
| F4 | recurring report | write_file weekly summary with exact expected bytes | Python recomputes the expected summary, byte-compares |
| F5 | file maintenance | copy_file-style normalize/sync via transform sort+select | Python recomputes the normalized bytes, compares |

Instance data for run *n* of each family is generated deterministically
from seed **1701** (fresh values every run — no instance repeats, so
routing must generalize over minted parameters, never replay bytes).

## Protocol

1. One expert per family, created fresh at run 0. Learning loop ON
   (default settings; `db_write` names each family's database file).
2. Runs 1..20 per family, interleaved round-robin (F1r1, F2r1, … F5r1,
   F1r2, …) so no family benefits from being last.
3. **Owner promotion protocol** (the only owner action, explicitly
   labeled): after run 2 of a family, the owner seals a 3-case fresh
   suite (one edge case) generated from held-out seed data and runs
   `procedure.evaluate`. Models never seal, never promote.
4. Measured checkpoints: runs 1, 2, 5, 10, 20. All 20 execute.
5. Live mode replaces mock scripts with a real provider on the same
   fixtures; nothing else changes. Provider spend requires the owner's
   explicit `--allow-provider`.

## Metrics (per run, per family, read from ledgers only)

verified success (the gate's verdict) · model calls (steps consumed) ·
tokens in/out · cost_usd (**stamped `simulated-mock` unless a priced
provider served the call** — mock pricing can never establish economics) ·
deterministic share (`procedure_routed`) · procedures induced / proven
(cumulative) · false-success rate (gate passed but the grader's
independent recompute disagrees) · human interruptions (`ask_human`).

## Desired curve, stated before any run

```
verified success   flat at high
model calls        down (to zero after promotion where mastered)
cost / verified    down
human attention    down
false success      zero
```

## Analysis

Per family: model-call and cost-per-verified curves across the schedule;
Wilcoxon signed-rank on (run 1-2 mean) vs (run 10-20 mean) across
families for H1/H2; report negative results verbatim. Raw receipts
(JSON, per run) are stored beside the report whatever the outcome.

## What this experiment can and cannot claim

- CAN (mock): the mechanical amortization curve — model calls fall to
  zero on mastered families under unchanged gates (H1).
- CAN (live): cost per verified outcome over 20 runs (H2), for THESE
  families, at THIS provider's prices.
- CANNOT: universal 10×/100×, cross-domain transfer, model-vs-model
  superiority (that is DOMINANCE-001's job, after LIFT-001A).

## Runner

`python learn_bench.py run --home <dir> --runs 20 --receipts out.json`
(mock) · `--provider <name> --allow-provider` (live, owner-authorized).
The runner writes one JSON receipt per task and a per-checkpoint summary;
its family generators are hashed into every receipt file.
