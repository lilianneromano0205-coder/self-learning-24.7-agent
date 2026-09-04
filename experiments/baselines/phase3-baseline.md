# Phase-3 baseline — the immutable comparison point

Frozen 2026-09-02 per the external audit's checkpoint directive: measure
before building more.

| what | value |
|---|---|
| tag | `phase3-verified-programs-baseline` (annotated, pushed) |
| commit | `61a111f56296283472eb09bdec9977142fc45a4e` (main; merge of PR #6) |
| merged phases | #1 verified learning loop · #4 Semantic Operator Runtime · #5 Verifier Factory · #6 Procedure Compiler V2 |
| suite at merge | 142 executed / 140 passed / 2 skipped / 0 failed, Ubuntu + Windows × py3.11–3.13, all six CI jobs green |
| clean-clone reproduction | fresh `git clone` of the tag from GitHub on 2026-09-02: same SHA, **142 executed / 140 passed / 2 skipped / 0 failed** (skips: test_acquire.py, test_shutdown.py — docker-only, run in CI) |
| frozen evidence artifact | [`phase3-EVIDENCE.md`](phase3-EVIDENCE.md), generated from that clean-clone run: **140/142, 675 observations** |
| tag signing | unsigned — commit/tag signing requires the owner's keys (open governance item, with branch protection) |

Every future lift, learning, or superiority claim is measured AGAINST this
point, never against a moving main. The experiments that use it:

- **LIFT-001A** (`../LIFT-001A.md`) — one-pass configuration lift.
  **NOT_RUN**; instrument validated on mocks; sole blocker is a provider
  API key + owner-approved budget (verified again at freeze time: no key
  present in the environment or any agent.env).
- **LEARN-001** (`../LEARN-001.md`) — longitudinal amortization across
  runs 1..20 on five recurring families. **NOT_RUN** live; instrument
  validated on mocks at this baseline
  (`../LEARN-001-instrument-validation.md`: 100/100 verified, model calls
  4 → 0 per family after owner promotion, 0 false successes).

What green CI at this baseline proves, and does not: every model
interaction in the suite is a scripted mock, so this point certifies the
HARNESS MECHANICS — gates, authorities, learning loop, replay — and
nothing about real-model intelligence or economics. That distinction is
the reason this file exists.
