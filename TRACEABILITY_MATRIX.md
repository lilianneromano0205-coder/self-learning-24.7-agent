# Traceability Matrix

Capability → implementation → test → what the test actually observed → what it
does **not** establish.

Read the last column first. Every row in this matrix is a passing test, and no
row proves as much as its name suggests. The value of a traceability matrix is
in the negative space.

**Standing qualifier on every row below.** Every model call in every test is a
scripted mock (`tests/common.py` writes a `type = "mock"` provider into each
sandbox). No row in this document is evidence that a provider works, that a
prompt elicits the intended behaviour, or that a reported cost is real.

---

## 1. Core guarantees

| Capability | Implementation | Test | Observed | Not established |
|---|---|---|---|---|
| A task is claimed exactly once | `loop.claim_task` under `_state_lock` | `test_lock`, `test_e2e` | Two tasks on one course serialise; both complete; no lock file remains | Safety when a holder stalls past 8 s — see P1-2. The lock is never released with an ownership check |
| Path containment | `loop._safe_path` | `test_paths` | Escapes outside the expert root are refused | Emits no `[section]` evidence; contributes nothing to `EVIDENCE.md` |
| Model-written commands never see credentials | `sandbox.scrub_env`, `SCOPED_GRANTS` | `test_secrets` | The normal tool path sees `ABSENT` for planted markers | **The gate path is not covered.** `check_done` sees the full environment — reproduced, P1-1 |
| Commands run where configured, failing closed | `sandbox.py` backends | `test_sandbox` | Unavailable backend refuses rather than falling back to host | Docker and E2B never exercised live; only the host backend ran |
| Side effects are governed | `policy.py` before `effects.record` | `test_effects`, `test_approvals` | Policy screens before execution; the ledger keys on `(lineage, server, tool, sha256(args))` | "Exactly-once" is at-least-once: `mcp.py:349-352` calls before recording (P2-1) |
| Kill -9 mid-lifecycle recovers | `checkpoint.py`, state journalling | `test_e2e_crash`, `test_resume`, `test_chaos` | Task resumes or fails cleanly; no half-state | `test_e2e_crash` emits no `[section]` evidence. Crash points are chosen by the test, not exhaustive |
| Corrupt ledgers are quarantined | `reliability` paths, `memcheck` | `test_reliability`, `test_faults` | Corrupt state is quarantined and rebuilt; loop keeps running | Both tests emit no `[section]` evidence |
| Context is compiled, budgeted, inspectable | `context.compile`, `memrouter` | `test_context` (35 asserts) | Per-source budgets bind; a manifest naming inclusions and exclusions is written beside the transcript | Budget correctness under genuinely huge inputs is sampled, not proven |
| Compaction loses nothing | `loop.compact_context` | `test_compaction`, `test_governance` | Middle of transcript archived verbatim before trimming | Emits no `[section]` evidence. A partial write (disk full mid-line) leaves a truncated line the reader skips |
| Closed-book exams | `memrouter` student rule + `[roles.student] tools` | `test_memory_kinds`, `test_exam` | The student rule can only remove sources; the student role has no `read_file` | **No test asserts `read_file` is absent.** One settings edit voids it with a green suite (P2-3) |
| Every loop has a stop condition | `{criteria, max_attempts, deadline, max_steps}` | `test_stop` | All four stop kinds fire; clock skew handled | Behaviour under a model that never emits `finish_task` at scale |
| Skills are promoted, not assumed | `skillgraph` candidate/proven/quarantined | `test_skillgraph`, `test_skillmd` | Quarantined skills excluded; proven outrank candidates; one-hop sub-skill pull | Promotion quality depends on gate verdicts, which depend on mocked model output |
| Model routing is earned | `modelrouter.choose` | `test_modelrouter` | Scoring maths is correct: `min_n`/`min_pass` bars enforced, cheapest qualifying wins, static fallback never strands a role | **The test seeds the ledger directly.** In production no candidate can ever accrue runs (P1-4) |
| Charter changes predict their effect | `variants.py`, `decisions` | `test_variants`, `test_decisions` | A variant must state a prediction and pass a gate before promotion; nothing on disk changes until then | Prediction *accuracy* is scored against mocked outcomes |
| Grounding is checked | `citecheck.py` | `test_material`, `test_goal` | Cited/defined ratio computed; `_wants_citations` guard prevents penalising files that should not carry citations | Citation *correctness* is not checked — only presence and shape |

---

## 2. Full test index

All 81 tests, with the claim each makes (its own docstring), the assertion
count, and the number of `[section]` evidence markers it emits.

**`0s` matters.** `evidence.py` builds `EVIDENCE.md` from `[section]` prints.
The 11 tests emitting none contribute nothing to the evidence report even
though they pass — and they include the adversarial ones (`e2e_crash`,
`faults`, `paths`, `reliability`, `layers`, `retry`). The evidence report is
therefore quietest exactly where the hardest claims live.

| Test | Asserts | Sections | Claim | Modules exercised |
|---|---|---|---|---|
| `test_approvals.py` | 21 | 4 | Approval-gated side effects, end to end through the real loop. | `approvals`, `chief`, `fleet`, `loop`, `mcp` |
| `test_associative.py` | 8 | 2 | Associative memory expansion in recall (RippleMem/CABLE, 2026-08). | `recall` |
| `test_audit.py` | 13 | 3 | Adversarial audit findings, kept as permanent regression tests. | `fleet`, `ingest`, `loop` |
| `test_awareness.py` | 25 | 5 | The agent works from an accurate model of ITSELF (M9). | `context`, `fleet`, `loop`, `memory`, `selfmodel`, `skills`, +1 |
| `test_backup.py` | 23 | 6 | A platform without a tested restore has hopes, not backups (M11). | `backup`, `fleet` |
| `test_benchmark.py` | 12 | 3 | The lift benchmark: measuring what the harness adds, instead of asserting it. | `benchmark`, `fleet`, `loop` |
| `test_blocked.py` | 9 | 1 | Blocked-task resume (ask_human round trip). | (subprocess only) |
| `test_bootstrap.py` | 29 | 5 | ONE COMMAND, AND IT RUNS (M8). | (subprocess only) |
| `test_candidates.py` | 23 | 8 | TEST-TIME COMPUTE: make several, keep the best, and say why (P1). | `candidates`, `conflicts`, `loop`, `sources` |
| `test_cases.py` | 28 | 6 | Did the fix actually WORK? - the half a failure log never records. | `cases`, `confidence`, `context`, `fleet`, `loop` |
| `test_chaos.py` | 26 | 7 | CHAOS: attack the platform on purpose and watch what survives (P0). | `context`, `loop` |
| `test_check.py` | 6 | 2 | Provider connectivity check (`loop.py check`). | (subprocess only) |
| `test_checkpoint.py` | 15 | 3 | Fiber-style checkpoints (M2-L2): long tool work recovers, never restarts. | `checkpoint`, `ingest` |
| `test_chief.py` | 17 | 3 | The Chief of Staff briefing: "what should I do today?" answered from the | `chief`, `fleet`, `prospective`, `skills`, `templates` |
| `test_compaction.py` | 4 | **0** | Context compaction slicing sanity check (Part 5 B3). | `loop` |
| `test_conflicts.py` | 31 | 5 | When the material disagrees with itself, the harness rules on it (M9). | `conflicts`, `context`, `loop`, `sources` |
| `test_consult.py` | 13 | 2 | Consultant mode: the expert for fields no agent can execute. | `citecheck`, `consult` |
| `test_context.py` | 35 | 5 | The context window is COMPILED, budgeted and inspectable (M3). | `context`, `fleet`, `loop` |
| `test_course.py` | 12 | 1 | Exit criterion + spaced re-exams (Part 8). | `loop` |
| `test_curriculum.py` | 22 | 7 | Study in a considered order, not the order things arrived (P2). | `curriculum`, `loop`, `sources` |
| `test_decisions.py` | 15 | 5 | DECISION OBSERVABILITY: a charter change must predict its own effect (M6). | `fleet`, `variants` |
| `test_design.py` | 25 | 5 | Taste is not enforceable; SPECIFICS are (M10). | `conflicts`, `designcheck`, `quick`, `sources`, `standards` |
| `test_doctor.py` | 13 | 4 | The platform health check, and creation that never leaves a half-expert. | `doctor`, `fleet` |
| `test_e2e.py` | 9 | 3 | End-to-end lifecycle: the whole choreography, no human in the middle. | `loop` |
| `test_e2e_crash.py` | 8 | **0** | The hardest reliability claim: kill -9 in the MIDDLE of the full lifecycle, | `loop` |
| `test_ecosystem.py` | 24 | 9 | THE BEAST TEST - every subsystem, one organism, cross-checked. | `chief`, `fleet`, `loop`, `memory`, `prospective`, `recall`, +2 |
| `test_effects.py` | 26 | 4 | Side effects, governed: exactly-once across retries, policy before the | `effects`, `mcp`, `policy` |
| `test_events.py` | 16 | 4 | The panel WATCHES instead of asking (M7): a live SSE event stream. | `fleet`, `loop` |
| `test_exam.py` | 16 | 3 | Hidden exams as machinery (Part 8 layer 3). | (subprocess only) |
| `test_faults.py` | 22 | **0** | Fault injection: break every contract on purpose and prove the validator | `approvals`, `citecheck`, `effects`, `fleet`, `loop`, `mcp`, +2 |
| `test_federation.py` | 37 | 7 | The three ideas worth taking from the EDEN corpus, implemented and proven. | `commons`, `federation`, `fleet`, `team` |
| `test_fleet.py` | 11 | 3 | The expert fleet: one-command duplication, private identity, isolated memory. | `fleet`, `loop` |
| `test_frontend.py` | 15 | 5 | The frontend itself: the page is served from ui.html, wires every tab to a | (subprocess only) |
| `test_goal.py` | 24 | 6 | Goal pursuit + the commons: the smart loop that will not stop early. | `commons`, `fleet`, `goal`, `loop` |
| `test_governance.py` | 11 | 3 | Governance of the learner, and compaction as a contract. | `loop`, `variants` |
| `test_guardrails.py` | 20 | 5 | Community-researched guardrails: the failure modes agent builders report | `loop` |
| `test_harness.py` | 27 | 4 | The harness as an inspectable, self-auditing object (M1). | `fleet`, `harness`, `loop` |
| `test_inbox.py` | 15 | 6 | Inbox scanner + real extraction (Part 4 ingestion, offline parts). | (subprocess only) |
| `test_json_toolcall.py` | 4 | **0** | Inline-JSON tool calls (the grounding-header format). | (subprocess only) |
| `test_lanes.py` | 30 | 4 | The five agent-creation lanes - and every framework behind the panel - | `federation` |
| `test_layers.py` | 23 | **0** | The seven-layer agent contract, enforced as constraints rather than prompts. | `loop` |
| `test_local.py` | 10 | 3 | Local-testing ecosystem: agent.env auto-loading, the daemon scanning its | `loop` |
| `test_lock.py` | 10 | 2 | Single-writer course lock (Part 5 B7). | `loop` |
| `test_material.py` | 26 | 6 | (no docstring first line) | (subprocess only) |
| `test_mcp.py` | 19 | 5 | Plug ANY MCP tool server into the fleet - proven against a faithful | `federation`, `fleet`, `mcp`, `toolbox` |
| `test_memcheck.py` | 4 | 2 | Memory integrity (memcheck.py). | (subprocess only) |
| `test_memory.py` | 34 | 6 | The memory institution: the categories that outlive models and agents. | `fleet`, `loop`, `memory` |
| `test_memory_kinds.py` | 38 | 6 | Memory has KINDS, and the harness routes between them (M4). | `commons`, `context`, `fleet`, `gotchas`, `loop`, `memrouter`, +1 |
| `test_modelrouter.py` | 19 | 6 | Model routing is EARNED, not declared (M6). | `fleet`, `loop`, `modelrouter` |
| `test_panel_v2.py` | 34 | 5 | The control plane's second half (M7): edit what the agent IS, read what | `approvals`, `commons`, `context`, `fleet`, `loop` |
| `test_paths.py` | 6 | **0** | Path containment (constitution rule 3, mechanically enforced). | (subprocess only) |
| `test_preflight.py` | 28 | 8 | The production audit tells the truth about THIS installation (M11). | `backup`, `fleet`, `preflight` |
| `test_prospective.py` | 21 | 6 | Prospective memory: remembering to ACT later, executed by the scheduler - | `loop`, `prospective` |
| `test_providers.py` | 26 | 5 | Plug in any model, from any platform - and any tool you provide. | `fleet`, `loop`, `providers`, `toolbox` |
| `test_quick.py` | 24 | 4 | Quick Specialists: spun up in seconds, still caged by every gate. | `quick` |
| `test_recall.py` | 9 | 2 | The three-tier memory contract (MemGPT/Letta pattern): context that leaves | `loop`, `recall` |
| `test_reflector.py` | 4 | **0** | Reflection chain (Part 9 mechanism 2). | (subprocess only) |
| `test_reliability.py` | 5 | **0** | Corrupt-state quarantine. | `loop` |
| `test_remote.py` | 7 | 3 | Remote access: token auth on the control panel. | (subprocess only) |
| `test_replay.py` | 10 | 2 | Trajectory replay - a number for "how much does this model agree with our | `replay` |
| `test_research.py` | 20 | 5 | Establish the facts BEFORE answering the question (P3). | `consult`, `research` |
| `test_resume.py` | 9 | 1 | Acceptance test B (Part 12): kill-and-resume. | (subprocess only) |
| `test_retention.py` | 19 | 5 | Durability under months of operation - the hardening that keeps a 24/7 | `fleet`, `loop`, `recall` |
| `test_retry.py` | 13 | **0** | Failure retries (the endurance promise). | (subprocess only) |
| `test_routines.py` | 24 | 4 | ROUTINES: show the work once, then it is a standing arrangement (M6). | `context`, `fleet`, `loop`, `prospective`, `routines` |
| `test_sandbox.py` | 17 | 7 | WHERE commands run is a setting, and it FAILS CLOSED (M5). | `loop`, `sandbox` |
| `test_secrets.py` | 23 | 5 | A model-written command NEVER sees the harness's credentials (M9). | `loop`, `sandbox` |
| `test_skillgraph.py` | 20 | 5 | The Skill Graph: procedural memory with a promotion gate (HyperSkill + | `skills` |
| `test_skillmd.py` | 36 | 5 | Skills as folders (the Agent Skills standard) with PROVENANCE (M5). | `context`, `fleet`, `loop`, `skills` |
| `test_skills.py` | 5 | **0** | Acceptance test F analog (Part 12): skills compounding, the plumbing half. | (subprocess only) |
| `test_stop.py` | 17 | 5 | Every loop is defined by its STOP CONDITION (M2-L1): declared on the | `fleet`, `loop`, `memory` |
| `test_team.py` | 13 | 4 | Teams: chosen specialists collaborate - lead decomposes, workers run | `fleet`, `team` |
| `test_toolbox.py` | 15 | 3 | Toolbox + pre-built specialists: agents are TOLD what tools exist, and the | `quick`, `templates`, `toolbox` |
| `test_trace.py` | 24 | 5 | ONE TRACE PER TASK, and tool errors counted apart from model errors (M6). | `fleet`, `loop`, `trace` |
| `test_ui.py` | 28 | 12 | The control panel: create an expert with one click, teach it a link and a | (subprocess only) |
| `test_uicards.py` | 25 | 6 | GENERATIVE UI FROM A CLOSED CATALOGUE (M7). | `fleet`, `loop`, `uicards` |
| `test_url.py` | 10 | 3 | Any-link learning. | `ingest` |
| `test_variants.py` | 14 | 5 | Charter evolution with a promotion gate - the Agent Selection Farm idea, | `variants` |
| `test_verify.py` | 7 | **0** | Mechanical spec verification (Part 8 layer 1). | (subprocess only) |
| `test_wake.py` | 16 | 4 | Wake-on-event (M2-L3): an external system delivers an event and the | `fleet`, `prospective` |
| `test_workflows.py` | 14 | 3 | Deterministic workflows: fixed stages, each a gated task, each firing the | `workflows` |

---

## 3. Modules with no test

| Module | Status | Consequence |
|---|---|---|
| `locks.py` | **No test of any kind.** No test file imports it | The primitive guarding `effects.jsonl`, `approvals.json`, `prospective.json` and `skills/graph.json`. Its ownership defect (P1-2) is exactly what a direct test would catch |
| `evidence.py` | No test | The tool that generates the correctness report is itself unverified |
| `package.py` | No test | Builds the distributable; failure is visible at build time |

`tests/test_lock.py` does **not** cover `locks.py` — it tests the course lock
inside `loop.py`, a separate implementation. The name is misleading.

Five further modules are covered only as subprocesses, which is legitimate but
means their internals are exercised through a CLI surface rather than directly:
`bootstrap.py`, `demo.py`, `memcheck.py`, `ui.py`, `verify.py`.

---

## 4. Capabilities with no test at all

| Capability | Why unproven |
|---|---|
| Any live model provider | No keys configured; every call is a mock. `python loop.py check` is the only live probe and was not run |
| Docker / E2B / Daytona sandbox backends | Only the host backend executed. The fail-closed path for the others is read-from-source |
| MCP against a real server | Tested against an in-process fake |
| A2A federation against a real peer | Tested against an in-process fake |
| 24/7 endurance | Longest observation in this audit: a 259-second suite run. Memory growth, ledger size, log rotation and lock contention over days are unmeasured |
| `backup.py` restore from a real backup set | Not executed in this pass |
| `docs_convert`, `video_download`, `transcribe`, `vision` | Report MISSING — optional external binaries absent. Guarded, not broken |

---

## 5. How to read the two coverage numbers

**Assertions (1,466 total)** measure how much each test checks. **Sections
(316 total)** measure how much each test can *explain* — they are the sentences
`evidence.py` harvests into `EVIDENCE.md`.

A test can be assertion-rich and section-poor: `test_faults` makes 22
assertions and emits zero sections, so it defends 22 contracts and contributes
nothing to the document whose job is to say why the build is believed to work.
`test_layers` (23 asserts, 0 sections) and `test_retry` (13 asserts, 0
sections) are the same shape.

This is not a correctness problem. It is a reporting gap, and it biases the
evidence report toward the well-instrumented feature tests and away from the
adversarial ones — the opposite of what an evidence report should emphasise.

---

## 6. Test-overstatement audit (second pass)

The first pass found one case where a test's name implied coverage it did not
have (`test_lock.py` tests the *course* lock, leaving `locks.py` untested).
The second pass hunted that pattern across all 81 tests. It recurs.

| # | Test | What it implies | What it actually covers | Consequence |
|---|---|---|---|---|
| 1 | `test_guardrails.py` — prints *"secrets refused"* | complete secret containment | asserts `_safe_path` refuses `agent.env` and `ui-token.txt` **only** | `keys/openai.key`, `bootstrap.json`, `cookies.txt`, `identity.json` are readable — reproduced. The test paints full containment over a 3-name list |
| 2 | `test_url.py`, `test_ui.py` | URL ingestion works | use `file://` as a **positive fixture** (*"same code path as https"*) | The `file://` local-file read is baked into the suite as intended behaviour. **No test asserts `file://` should be refused** |
| 3 | `test_paths.py`, `test_material.py` | filesystem containment | cover `read_file` traversal and zip-slip (both genuinely hold) | Neither covers the 5 harness writers that build paths from an unsanitised `course` — the path that actually escapes |
| 4 | `test_lock.py` | `locks.py` is covered | tests the course lock inside `loop.py` | `locks.py` — the primitive guarding 4 mutating ledgers — has no test at all |
| 5 | `test_modelrouter.py` | routing is proven | seeds the outcome ledger directly via `modelrouter.record(...)` | Bypasses precisely the cold-start gap that makes routing inert in production |
| 6 | `test_remote.py` | panel auth is proven | asserts token presence when a token is set | No test sends a cross-origin or wrong-`Content-Type` request; the CSRF→RCE path is entirely uncovered |
| 7 | `test_skillmd.py` | provenance is enforced | exercises the CLI import path (which does write a graph entry) | Does not assert that a graph-less, self-declared `provenance: own` is refused — it isn't |

**Zero-reference checks.** Terms that appear in **no** test file:
`api_key_file` (0), `_record_spend` at the compaction site (0), `Origin`/CSRF
(0 — the one `test_retry.py` hit is the word "Original").

**The honest summary.** For six guarantees, a test can pass while the
advertised property is false: secret containment, single-writer effects,
closed-book isolation, exactly-once effects, backups-exclude-credentials, and
panel authorisation. In each case the test exercises the well-defended primary
path and the defect lives on an alternate path the test never visits — the same
shape as the product defects themselves.
