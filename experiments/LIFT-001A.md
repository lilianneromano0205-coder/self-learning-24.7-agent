# LIFT-001A — measurement protocol amendment

Preregistered 2026-08-30, before any provider experiment in this change.
Status: NOT_RUN. This is a prospective protocol, not a result. The historical
LIFT-001.md is unchanged and its original results, if any, are not reinterpreted.

## Reason for amendment

Inspection found 12 TRAIN tasks in evalsuite.py, while LIFT-001 required at least
20 across five families. benchmark.py instead ran three file-writing tasks in a
shared expert root. Its raw/full comparison omitted an ordinary iterative agent.
Mastery reused transfer tasks during baseline and retention. These are distinct
measurement defects, not evidence for or against model capability.

## Frozen comparison

Use the separate `evaluation_corpus.py` TRAIN corpus: 20 tasks, ten workload
families, two distinct instances per family. The old CI fixtures remain CI
fixtures. All local corpus tasks are public development data, never described as
secret holdouts or as external benchmark results. Browser and research fixtures
measure offline workflow components; real browser/research claims additionally
require separately installed upstream environments and official graders.

Arms A/raw (one call), B/minimal (ordinary iterative tools without persistent
intelligence), C/no_persistence (the normal verified harness without accumulated
memory, skills, or runbooks), and D/full (normal harness) use the same practitioner
provider/model, task/fixture hashes, model budget, seed schedule and cloned
starting snapshot. Provider determinism is not assumed: record seed support as
unknown unless the provider confirms it. E/reference is optional, must identify
its adapter/model/version and is reported separately, never silently substituted.
All arms retain execution/file/credential authorities and the independent final
mechanical grader. Safety is not an experimental variable.

The initial snapshot is copied once, excludes pending work/transcripts/output,
and is never written by an arm. Each task/arm/repetition receives a fresh clone.
There is no between-task learning in this matched experiment. Persistent D
capabilities come only from the declared pre-experiment snapshot; measuring
online accumulation requires a separately preregistered longitudinal design.
Randomize arm order per task using the published seed. Record full snapshot,
corpus, code and configuration hashes. Grade once independently after execution.

## Metrics and thresholds

Primary: verified useful work per dollar = mechanical passes / measured spend.
Also cost and wall time per verified success; input/output tokens; model/tool
calls; retries; verifier failures; false accepts/rejects against an independent
adjudication when supplied; human interventions; declared frontier model calls
and tokens per success; skill/runbook reuse; regression rate on matched prior
passes. Missing measurement is null with a reason, never a fabricated zero.
Mock pricing is labeled simulated and cannot establish real cost superiority.

Report all raw rows, failures, sample counts, Wilson intervals for each pass
rate, paired success differences and paired bootstrap intervals (10,000 draws,
seed 1701). Bootstrap units are task IDs, retaining repeats together. Run at
least three repetitions; interpret 20 correlated development tasks conservatively.
Primary contrast D versus B: supported on this workload only if mean verified
success improves by at least 15 percentage points, paired 95% interval excludes
zero, and measured cost per success is no greater. Partial if success improves
but cost rises or uncertainty remains. Otherwise inconclusive or refuted for
the specified contrast; never treat absent pricing as a supported cost claim.

## Ablations

Paired D versus D minus each of memory, skills, runbooks, candidates, routing,
confidence/escalation, repair, research brief, swarm, and optional verification
tiers. Same tasks/seeds/snapshot; report paired deltas and actual module exposure.
No exposure means no evidence of module value. Mandatory mechanical judges and
authorities cannot be disabled. An unsupported hook fails before experiment.

## Independent mastery

Freeze owner-authored baseline A, practice, transfer B, and retention C tasks
with disjoint IDs, normalized prompts and declared instance fingerprints. Held
evaluation runs in disposable clones and returns only graded aggregates/IDs to
the persistent expert. Graders/answers never enter training memory. Record pack
hash and consume an outside-root exposure reservation before execution, including
failed/crashed attempts. Transfer/retention sets are single-use per expert and
pack version; new independent packs are required for further exams. Report elapsed
retention interval; an immediate C run is fresh-instance performance, not evidence
of long-term retention. No repeated re-study on the same transfer exam.

## External benchmarks and claim boundary

Upstream WebArena and SWE-bench task/result adapters require explicit dataset
revision and licensing provenance plus official environment/grader receipts.
Importing tasks is not running those benchmarks. No upstream datasets are
downloaded, provider calls made, or paid resources used by this amendment.
All 10x/50x/100x efficiency and general-transfer claims remain NOT_ESTABLISHED.

Method sources checked 2026-08-30:
- ReAct: https://arxiv.org/abs/2210.03629
- AgentBench: https://arxiv.org/abs/2308.03688
- WebArena source and license: https://github.com/web-arena-x/webarena
- SWE-bench official harness: https://github.com/SWE-bench/SWE-bench
