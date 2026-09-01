# LIFT-001A pipeline validation — 2026-08-31

**This is not the experiment.** LIFT-001A itself remains `NOT_RUN`. This
record establishes only that the preregistered INSTRUMENT executes end to end
and cannot produce a flattering number by accident. No provider was called,
no finding about model lift exists, and none is claimed.

## What ran

`benchmark.py run` against a fresh fleet with a mock provider, one
repetition, all four preregistered arms, over the full 20-task / 10-family
`evaluation_corpus` (corpus hash `d25b1f4800ac2ad0…`).

Wall time 76 seconds. Exit 0. Full report captured, receipt ledger written
(`experiments/lift-001a-*.jsonl` in the run home).

## What it established

- **All four arms execute over the whole corpus**: raw, minimal,
  no_persistence, full — 80 graded rows, each in a fresh clone, ablation
  policy rewritten per arm.
- **The grader does not flatter.** A static mock script cannot genuinely
  solve 20 distinct tasks, and the result was 0/20 in EVERY arm — including
  `full`. Symmetric refusal under a provider that cannot think is exactly the
  null behaviour a matched instrument must show; an instrument that gave the
  harness arm free passes here would be measuring itself.
- **The preregistered analysis runs**: paired success delta 0.0 with
  bootstrap CI [0.0, 0.0], 20 task clusters, seed 1701 — the exact analysis
  LIFT-001A specifies, executed on real rows.
- **Honesty fields behave as declared**: every row carries
  `pricing_evidence: "simulated-mock"` (the protocol forbids mock pricing
  from establishing cost superiority), and unmeasurable quantities
  (false accepts/rejects, regression rate) are explicit nulls with reasons,
  never fabricated zeros.
- **Provenance is pinned**: the report records `code_hash` and
  `corpus_hash`, so a future real run can prove it measured the same
  instrument.

## What still blocks the real experiment

One thing: a provider API key and an owner-approved budget.
`benchmark.py` refuses non-mock providers without `--allow-provider`, by
design. When a key exists, the run is:

    python benchmark.py run --expert <expert> --home <home> --repeat 3 --allow-provider

with the thresholds already frozen in `LIFT-001A.md`: the D-vs-B contrast is
supported only if verified success improves by ≥15 percentage points, the
paired 95% interval excludes zero, and measured cost per success is no
greater. Anything less is recorded as partial, inconclusive or refuted.
