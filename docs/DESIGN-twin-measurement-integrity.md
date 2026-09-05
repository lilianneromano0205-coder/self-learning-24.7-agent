# Twin measurement integrity — first repair

Base: origin/main f025a3dd3c0c6a8efbfb3816110b037c89e07c2b.
Scope: correct retrospective choice diagnostics, not certify a human clone.

The current final holdout is used to select rules. Default episode IDs also
include the answer. Old fidelity reports can survive changes to the predictor.
First reproduce these failures with independent assertions before fixing.

## Contract

- Group decisions by normalized situation, option definitions and counterpart,
  excluding outcome, explanation, time, episode ID and source. This keeps exact
  repeated situations together, including legacy rows. It is an inferred group,
  not evidence of pre-outcome assignment or semantic near-duplicate isolation.
- Deterministic 60/20/20 train/validation/test partitions. Fit features, numerical
  model, rule candidates and social state only on training. Validate rules only
  on validation; never score those validation rows as the final choice test.
- Freeze training neighbors inside each new fitted version. All default
  predictions use these neighbors; test decisions cannot leak back through the
  live ledger. Legacy versions remain readable but require refitting for a new
  diagnostic. Calibration remains a diagnostic, not a calibrated model claim.
- Hash the full fitted body, excluding version/time labels. Bind each evaluation
  receipt to the full kernel, dataset, predictor constants and source digests.
  Store immutable, content-addressed evaluation receipts under twin/ (CONTROL),
  containing the snapshot and choice predictions. Replaying unchanged receipt
  inputs reproduces the scores; live changes mark the displayed report stale.
- Track reuse of test groups across differing predictor snapshots. Never claim
  untouched prospective generalization, even on a first retrospective run.
- Existing behavioral rule 'proven' is a legacy status, not scientific proof.
  Rename new fits' status to 'supported'; retain compatibility when reading old
  fits. No arbitrary support threshold can establish a human policy here.

## Acceptance benchmark

1. Change only final labels: model/rules/social state/training neighbors and
   fitted-body digest must stay identical. Spy on actual fitting and validation
   inputs, not merely assert disjoint metadata lists.
2. Change choices, IDs, explanation and outcome: exact scenario group stays in
   the same partition. Explicitly report inferred/retrospective provenance.
3. Duplicate/retest groups never cross partitions. Input ordering does not change
   the group assignment. Missing or malformed records fail visibly.
4. Alter live test labels or append test rows: default predictions from the
   fitted snapshot do not change. Tamper with a stored fit => evaluation refuses.
5. Receipt replay survives later live updates; tampered receipt refuses. Current
   status/render labels old evidence stale on kernel/data/code/config changes.
6. A repeated test cohort with a changed predictor is explicitly marked reused.
7. Insufficient independent test groups is an explicit outcome. Always retain
   diagnostic scope; high internal accuracy is not validated behavioral science.
8. Existing consent, shadow, abstention, drift, style, context and UI tests remain
   covered. Acceptance registration, mutation registration and docs agree.

Mutations: feed test labels into rule validation; include choice in group key;
read live neighbors; bypass evaluation binding. Each must fail on a meaningful
assertion rather than unrelated syntax/import failure.

## Limits and subsequent phases

Regression discovered during implementation: separated training made the existing
cold-start defect reproducible. Three unfamiliar shadow decisions triggered drift
and froze a barely fitted model. Keep those losses as evidence but exclude novel
decisions from policy-change detection. A dedicated test must still trip drift
on loss growth for familiar decisions; do not alter detector thresholds.

No prospective enrollment, statistically powered rule promotion, immutable
owner-approved releases, explanation-to-policy learning, temporal reconstruction,
transaction overhaul, browser runtime or Phase 10.1 merge in this repair.
The broader continuation contract remains open for these follow-up phases.
Full local suite and applicable mutations are required; remote CI and independent
review remain separate release evidence. No push or merge is needed to inspect
the local result. Preserve all other worktrees and existing ledgers.
