# Measurement repair — self-review and evidence ledger

This records local engineering checks and a separate read-only agent review,
not external review or release approval.

## Reproduced before implementation

`test_final_rows_never_select_rules` failed on main f025a3d: the observed
validation call contained 24 final-test IDs in its 100-row fixture. The assertion
failed because of shared data, not because a new API was missing.

## Important challenges to the original plan

- Removing answers from hashes cannot retroactively prove pre-outcome enrollment.
  This repair explicitly labels all scores retrospective; prospective collection
  and unseen real-human cohorts remain open.
- Exact scenario equality is not semantic independence. Near-duplicate scenarios,
  source families and temporal dependence need a later preregistered protocol.
- Frozen evaluation receipts are not owner-approved immutable model releases.
- `supported` retains the existing empirical threshold for compatibility; it is
  not a powered statistical claim. No replacement threshold was selected after
  looking at final scores.
- The original drift test exposed a cold-start freeze after three unfamiliar
  predictions. The new rule excludes novel decisions from policy drift while
  retaining their errors, and still detects changes on familiar decisions.
- Style, retest consistency and correction-speed side diagnostics remain limited
  by the earlier audit. The repaired choice pipeline does not validate them.
- Receipt history grows with evaluations and status binding scans local state.
  No large-fleet latency, retention or long-duration claim has been tested.
- Receipt digests detect edits under an existing address within the CONTROL
  boundary. They are not signatures against an authorized owner rewriting all
  files or a replacement for external learning-authority sealing.

## Executed so far

- New measurement suite: eleven cases passed after review corrections.
- Original Twin benchmark: passed, including unchanged synthetic accuracy bar.
- Seven measurement mutations: all caught, none skipped or missed.
- Four existing Twin safety mutations: all caught, none skipped or missed.
- Execution audit: 118 modules, zero violations.
- Harness contract check: zero contract problems; Docker unavailable health item.

Full-suite results, final patch fingerprint and remaining release gates are
recorded in the completion report after validation finishes. No remote CI or
deployment proof is claimed here.

## Review corrections

A separate read-only reviewer found two P2 defects: evaluation bypassed malformed
record validation after fitting, and archival reread auxiliary inputs after their
diagnostics were computed. Both targeted regressions failed before correction.
Evaluation now validates its snapshot and archival refuses intervening changes,
binding the original captured auxiliary inputs and runtime. Both regressions and
the full eleven-case measurement file then passed. The reviewer rechecked the
patch and identified no remaining important blocker in this focused review;
that reviewer did not independently execute tests.

This is optimistic change detection, not transactional isolation. Writes after
the check invalidate current status against the captured receipt. Historical
replay recomputes individual choice predictions and scores; aggregate and
auxiliary diagnostics are returned from the integrity-checked receipt, not
independently recalculated.

## Broad-run correction

The first complete local run reported 150 passed, four skipped and one failed
among 155 test scripts. The failure was the older documentation check requiring
a static README badge to say "passing". Its exact-count assertions now check
"registered", separating inventory from execution evidence. The full targeted
ledger-defects file passed after this correction; a separate review found no
unjustified weakening. A fresh full sweep is still required before claiming a
clean final local suite.

The fresh sweep completed: 151 passed, four skipped, zero failed, exit 0
(`measurement-suite-final.log`). The evidence generator then exposed a separate
SKIP/PASS precedence bug: Docker's skipped file printed PASS afterward and was
counted as passing. Both output-order regressions failed before the parser fix;
the full package test file passed afterward. Regenerated EVIDENCE.md now agrees
with the suite (151/155, 831 observations). The full sweep preceded this final
reporting-only change; post-change verification is the complete package test and
evidence regeneration, not another full sweep. Independent re-review of this
last reporting correction was unavailable due to the reviewer's usage limit.

## PR 22 review corrections

CodeRabbit identified five actionable issues on d27e423. New regressions
reproduced acceptance of duplicate normalized option IDs and inflation of the
headline observation count by skipped tests. The split now refuses ambiguous
IDs in either order; the evidence headline counts the same passing classified
ledger as its system rows. Rendering redacts user-home names (and discloses
that transformation). Archive output distinguishes all non-test Python files,
including nested support scripts, from root module inventory. The badge check
now compares the actual suite registry with the test files and rejects duplicate
registrations. Three registered mutations exercise these load-bearing checks.
The earlier 831-observation statement above is historical, not the corrected
count. Fresh full-suite evidence and remote CI are required for this revision.

The first correction sweep retained one setup failure: Windows could not
recreate an old Git-operator fixture directory. A direct rerun reproduced that
setup error; using a new AGENT_TEST_TMP directory passed the exact test without
product changes. The failed log remains local. A subsequent complete sweep in
a fresh isolated fixture directory passed **153/155**, with **two skips and zero
failures** (`measurement-review-isolated-suite.log`). The skips are
`test_shutdown.py` and `test_acquire.py`; Docker was available for this run.
Generated EVIDENCE.md contains **841 observations**, exactly the sum of its
passing classified system rows. All three new mutations were caught, none
missed or skipped. The final execution audit reported zero violations across
118 modules. Remote CI must still validate this exact correction commit.

## Local UI observation (prior revision)

Served the existing synthetic Twin fixture on loopback port 7789 with no expert
loop started. Browser inspection of learner / Skills showed "retrospective
diagnostic: STALE" and suppressed the old choice score. After CLI reevaluation
of this disposable fixture and browser refresh, it showed the retrospective
high tier and rounded 96% synthetic choice score, with the OWNER block stating
"not validated human fidelity". The tab and temporary server were closed.
This establishes this display transition only, not autonomous browser operation,
native desktop capability, live-provider quality or responsive-layout quality.
