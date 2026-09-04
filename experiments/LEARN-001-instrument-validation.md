# LEARN-001 — instrument validation (mock providers)

**This is the pipeline proving it can measure, not the experiment.** Every
model call below was a scripted mock; every receipt is stamped
`"pricing": "simulated-mock"`, and per the preregistration no economic
claim (H2) can be made from this run. What it validates is the
INSTRUMENT and the MECHANICS (H1): the schedule executes, the ledgers are
read not narrated, the owner-promotion protocol works, the false-success
detector runs on every row, and the amortization curve the preregistration
predicts is what the machinery actually produces.

## The run

- Date: 2026-09-02 · Baseline code: tag `phase3-verified-programs-baseline`
  (`61a111f…`) plus the LEARN-001 instrument itself
- Command: `python learn_bench.py run --home <short-path> --runs 20
  --receipts receipts.json`
- Seed 1701 · generator `LEARN-001-generators-v1` · five families ×
  20 runs = **100 tasks**, interleaved round-robin
- Raw receipts: `LEARN-001-validation-receipts.json` (one row per task,
  read from `state.json`/trust ledgers)

## Result: the preregistered H1 curve, in every family

| family | verified | calls, runs 1–2 | calls, runs 3–20 | routed runs 3–20 | false successes |
|---|---|---|---|---|---|
| f1recon (typed money reconciliation) | 20/20 | 4 | **0** | 18/18 | 0 |
| f2upsert (sqlite read-after-write) | 20/20 | 4 | **0** | 18/18 | 0 |
| f3report (aggregate totals) | 20/20 | 4 | **0** | 18/18 | 0 |
| f4triage (filter/select report) | 20/20 | 4 | **0** | 18/18 | 0 |
| f5normalize (sort/rename) | 20/20 | 4 | **0** | 18/18 | 0 |

Totals: **100/100 verified, 90/100 routed zero-model, 0 false successes,
0 human interruptions.** After each family's run 2, the owner sealed a
3-case held-out suite (one edge each — empty reconciliation, zero-cents
upsert, empty tables) and `procedure.evaluate` promoted the induced
candidate to proven (`accepted=True status=proven`, printed per family in
the run log). Every instance used FRESH seed-derived data — no run
repeats another's bytes, so routing generalized over minted parameters
rather than replaying answers, and every routed run still passed its own
truth-recomputing gate (plain-Python/Decimal/sqlite recompute,
independent of both the worker and the procedure).

## What this run established, and what it did not

- ESTABLISHED: the instrument executes the preregistered schedule end to
  end and produces the H1 mechanics — marginal model calls fall to zero
  on mastered recurring families under unchanged independent gates, with
  zero false successes across 100 ledger-verified rows.
- NOT ESTABLISHED: anything about cost (mock pricing is simulated), about
  real-model behavior on runs 1–2 (a live model may fail instances a
  script cannot), or about families outside the trusted-adapter universe.
  **LEARN-001 itself remains NOT_RUN** until a real priced provider
  executes this same preregistration — sole blocker: a provider API key
  and owner-approved budget (`--provider <name> --allow-provider`).

## Operational note

Windows MAX_PATH: a deep `--home` breaks the org-boundary ledger's
temp-file writes (`FileNotFoundError` on a ~270-char path). Use a short
home directory; the runner's docstring says so.
