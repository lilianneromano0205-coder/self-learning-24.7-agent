# Verified learning and authority hardening implementation plan

**Goal:** Implement the supplied defensive engineering directive without weakening independent authorities or overstating intelligence evidence.

**Architecture:** Preserve the stdlib core and existing authorities. Require actual containment for model-authored shell execution; use independent sealed evaluation state; extend existing learning modules with mechanically checked interfaces. Experimental intelligence stays opt-in and produces receipts, not production claims.

**Baseline:** clean local and remote main `1b60869a5f419499c2892c5c4249c4ded4d89974`; isolated branch `codex/verified-learning-hardening`.

**Spec:** `docs/VERIFIED_LEARNING_DIRECTIVE.txt` (user supplied).

**Constraints:** No real credentials, offensive utilities, provider experiments, external writes, changed historical preregistration, weakened judges, or invented results. Every meaningful fix needs executed red/green evidence. Ordinary CI remains keyless. Unknown runtime evidence is NOT_RUN. Preserve initial main checkout.

**Execution:** Use systematic debugging and TDD. Independently investigate separate file ownership domains with the dispatching-parallel-agents skill. Integration follows the user's phase order; work on independent modules may proceed while safety tests run. Parent owns shared integration files, test registration, and final docs. Do not use the sequential subagent-driven implementation workflow for these independently owned domains.

## Task 1: Critical execution and acquisition safety (parent)
- [ ] Verify detached child, seal conflict, acquisition disclosure, hosted round-trip findings with disposable fixtures.
- [ ] Update sandbox.py, execution.py, contract.py, acquire.py and their regression tests: isolated default, explicit unsafe developer-only host mode, fail-closed control checks, minimal acquisition arena and safe removal.
- [ ] Execute focused tests and maintain existing approval, credential, and control boundaries.

## Task 2: MCP and repository/protocol safety
- [ ] Inspect mcp.py, ui.py, federation.py, effects.py, .github/ against first-party sources.
- [ ] Add least-privilege MCP env, immutable catalog/version identity, honest protocol claims, safe UI bootstrap, and pinned CI dependencies with regression tests.
- [ ] Document repository protections and live release tests without modifying remote settings or using credentials.

## Task 3: Measurement integrity and mastery
- [ ] Preregister LIFT-001A before any provider experiments; preserve LIFT-001.
- [ ] Add clean experimental arms, serious separate corpus, full metric receipts, module ablations.
- [ ] Repair mastery baseline/practice/transfer/retention split and seal/contamination rules.

## Task 4: Procedural learning and operators
- [ ] Normalize independently verified trajectories into conservative executable candidates, using mechanical checks and held-out/adversarial rehearsals.
- [ ] Add typed inputs, preconditions/effects, observable state planner, and diversity-aware trust envelope to runbooks.
- [ ] Test actual execution and rejection, never self-reported success.

## Task 5: Memory and attribution
- [ ] Hybrid provenance-preserving retrieval; calibration-ready memory benchmark adapters.
- [ ] Constrained experimental memory action policy; causal skill instrumentation and paired ablation support.
- [ ] Test temporal supersession, paraphrase retrieval, and protected evidence boundaries.

## Task 6: Cognitive scheduling and verification
- [ ] Task-conditioned empirical scheduling and expected-value sequential candidate decisions, hard ceilings.
- [ ] Mechanical-supreme verification hierarchy, calibration evaluation and global context budgeting.
- [ ] Test caller integration and accurate metrics with no provider calls.

## Task 7: Advanced learning and proof tiers
- [ ] Independent variant batteries, optional external trainer recipes with sealed evaluation and owner promotion.
- [ ] Opt-in local/logit versus closed-API approximation distinction; no unsupported claims.
- [ ] Intelligence proof tiers distinguish offline, benchmark, repeated, live and production evidence.

## Task 8: Research evidence and discovery
- [ ] Explicit subquestions/dependencies/hypotheses/gaps and claim-evidence states.
- [ ] Controlled general-web discovery alongside curated discovery, with provenance/freshness/fencing.
- [ ] Tests must distinguish retrieval from support and cover contradictory/missing evidence.

## Task 9: Integration and independent review
- [ ] Review every scoped diff for spec and quality; reconcile shared integration under the parent.
- [ ] Run complete suite, harness check, execution/model audits, mutation suite, and diff hygiene.
- [ ] Update SECURITY, CHANGELOG and finding/evaluation ledger only after executed checks.
- [ ] Report all remaining P0/P1, runtime limitations and intelligence metrics as measured or NOT_RUN.

## Cross-domain contracts
| Domains | Shared interface | Resolution |
|---|---|---|
| All / execution | sandbox.run and execution.run | Preserve signatures; default contained, tests may explicitly opt into unsafe host for disposable trusted fixtures only. |
| All / registration | tests/run_all.py | Parent alone registers new tests. |
| Routing / loop | loop.py integration | Parent alone edits loop.py after reviewing module APIs. |
| Procedures / mastery / variants | frozen grader and trust receipts | Worker cannot author evaluation or overwrite authority; candidates need independent held-out evidence. |
| All / docs | SECURITY.md, CHANGELOG.md, report | Parent alone updates final global claims after evidence. |

Ruling: user explicitly authorized implementation and supplied architecture; do not repeat a design-permission gate. Worktree creation is reversible and authorized by the task execution instructions. No provider experiments or remote governance mutation are implied.
