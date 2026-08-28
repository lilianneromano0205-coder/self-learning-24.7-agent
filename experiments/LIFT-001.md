# LIFT-001 — pre-registered: does this harness make a cheap model smarter and cheaper, or dumber and more expensive?

**Status: PRE-REGISTERED, NOT YET RUN.** This file is committed before any
provider key exists in this installation, which is the point: the hypothesis,
the arms, the metrics and the pass/fail thresholds are frozen in git history
*before* any data exists, so the results — whichever way they fall — cannot
be met with moved goalposts. If the numbers come out against the platform,
this file is the proof that we said in advance what failure would look like,
and the finding gets published in this same directory, not buried.

## The question

Scaffolding costs tokens on every step. It could make a model *worse per
dollar*: overhead, retry loops, routing errors. The platform's central claim
is the opposite — that verification, memory and the zero-token machine path
turn a cheap model's per-call ability into system capability it cannot have
alone, at a lower cost per *correct* outcome. That claim is worthless until
this experiment runs.

## Arms (only the harness varies)

* **ARM A — BARE.** One call to the model, accepted as-is. No gates, no
  retries, no verification, no memory. This is what "just use the model"
  actually means, and it is the honest baseline — not a strawman with the
  temperature sabotaged.
* **ARM B — HARNESS.** The same model, same prompt budget category, inside
  the loop: definition-of-done gate, bounded retries, mechanical
  verification, memory and the machine path enabled.

Same model ID in both arms. Same task list in both arms. Runner:
`python benchmark.py` (arms as implemented there), task corpus from
`evalsuite.py`'s TRAIN split only — the HOLDOUT stays sealed for later
regression measurement, and every holdout peek is recorded.

## Model

The cheapest tools-capable rail configured at run time (the house lane:
a sub-$1/Mtok model). Deliberately NOT a frontier model: the claim under
test is about lift on cheap models, so a cheap model is the subject.

## Metrics (all three reported; none optional)

1. **Verified-pass rate** per arm: tasks whose *mechanical* checks pass.
   Graders are sealed before any arm runs; no model judges any output.
2. **Cost per verified outcome** per arm: total provider spend divided by
   verified passes. Spend read from the platform's own metering ledgers,
   never estimated.
3. **Wall-clock per verified outcome** per arm (reported, not thresholded —
   the harness is expected to be slower; the question is what the time buys).

## Frozen thresholds — written before any data exists

* **SUPPORTED** if ARM B's verified-pass rate exceeds ARM A's by ≥ 15
  percentage points **and** ARM B's cost per verified outcome is ≤ ARM A's.
* **PARTIAL** if ARM B passes more but costs more per verified outcome: the
  harness adds capability at a price; the price gets printed, and the
  machine-path/runbook ratio becomes the next optimisation target with a
  follow-up experiment (LIFT-002) registered before tuning.
* **REFUTED** if ARM B's verified-pass rate is within 5 points of ARM A's or
  below it. Then the platform's central claim is wrong for this model class,
  the result is published here, and the roadmap changes — verification stays
  (it is a safety property, not a performance one), but the cost story stops
  being told until it is true.

## Task corpus

≥ 20 tasks from the TRAIN split spanning at least 5 of the platform's
capability families, each carrying a mechanical done-check authored before
the experiment. No task may be edited after the first arm runs; a broken
task is dropped from BOTH arms and named in the report.

## What gets published

The full per-task table (task, arm, verdict, tokens, dollars, seconds), the
model ID, the code hash, both arms' raw ledgers, and the verdict against the
thresholds above — in this directory, whatever the verdict is.

## What this experiment cannot show (stated in advance)

One model class, one task corpus, TRAIN-split only: a SUPPORTED verdict here
is evidence, not proof, of generality. Long-horizon compounding (runbooks
earning trust over weeks) is explicitly out of scope for LIFT-001 and needs
a longitudinal design. And the arms share a machine, so infrastructure noise
is uncontrolled below ~5% cost differences.
