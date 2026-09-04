# DESIGN — Phase 6.1: Correctness hardening of the state substrate

**Branch:** `phase6.1/correctness-hardening` · **Status:** BUILT — every
finding below is closed by a named test: `check_dirty_index_refuses`
(host-git witness), the `ref_state_digest` rename with `index_clean`
evidence, `check_evidence_hashes_workbook_bytes`, five OOXML refusals in
`check_refusals`, UUID temp names, `check_same_schema_different_semantics_collide`,
`check_shadow_failures_are_logged`, the archived manifest, the widened
label grammar under `check_interleaved_logs_cannot_cry_wolf`, and
`tests/test_promotion_leakage.py` — whose first run found
`proof/observations.jsonl` agent-writable, now CONTROL. · **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision. ·
**Audit gate:** the 2026-09-02 consolidated audit rated the biggest threat
no longer as architectural drift but as **false competence** — "allowing a
procedure/operator to become PROVEN while its state semantics are
incomplete" — and ordered: *stop broad feature expansion; harden the Git
and XLSX substrates; only then let transactional contracts (Phase 7) sit on
them.* Phase 7 is built and green locally and is **held unpushed** until
this phase lands.

## The rule this phase installs

> No operation becomes trusted because the happy path works. It becomes
> trusted only after the strongest plausible pre-state, race, failure,
> crash, ambiguity and tamper cases fail to break its declared semantics.

And its corollary, now a lab rule: **a test can prove a narrower statement
than the documentation.** Every benchmark of a state world therefore carries
a *claim envelope* — property, preconditions, excluded states, oracle — and
the design documents state the same envelope, so a green test can never be
read as a broader promise than it made.

## Findings closed here (each with its test)

| # | Finding (audit) | Fix | Test / oracle |
|---|---|---|---|
| 1 | `commit` staged the requested paths then ran a plain `git commit`, which commits *everything* staged — a pre-existing staged file would ride along | **Clean-index precondition:** a semantic commit refuses, before staging, when the index already differs from HEAD (or is non-empty on an unborn branch) | `test_git_operators.check_dirty_index_refuses`: a file pre-staged with the **host's** git makes the semantic commit refuse with nothing mutated; then, from a clean index, a commit of `["notes.md"]` with another file modified in the worktree yields a commit whose tree — read by host `git show --name-only` — holds exactly `notes.md` |
| 2 | "HEAD, refs, index and worktree restored exactly" was proved only from a clean index | The envelope is now enforced by finding 1 and **stated**: restore guarantees hold from a clean index, which every semantic mutation now requires | claim envelope in the benchmark docstring and in DESIGN-P5 |
| 3 | `state_digest` covered refs + HEAD, not worktree, index or untracked files, yet read like whole-repository state | Renamed **`ref_state_digest`**; trajectory evidence records it under that name plus an explicit `index_clean` observation | `test_git_operators`: the name, and the digest unchanged by a worktree edit |
| 4 | Workbook evidence in trajectories was hashed through `read_text` (lossy decode) | `fileauth.read_bytes` / `fileauth.sha256_bytes`; `_snapshot` hashes **bytes** for the workbook argument of `xlsx_import`/`xlsx_export` | `test_xlsx_operators`: two workbooks that decode to the same text but differ in bytes get different evidence hashes |
| 5 | Malformed OOXML ambiguity was interpreted | Refuse: duplicate cell references, duplicate row numbers, row `0`, booleans other than `0`/`1`, duplicate ZIP member names | `test_xlsx_operators.check_refusals`: each by name |
| 6 | Atomic-write temp names were PID + milliseconds — not unique under concurrent same-process writes | `uuid4` in the temp name for `write_text` and `write_bytes` | `test_invariants`/`test_package` unchanged behaviour; name pattern asserted |
| 7 | Signature shadow: schema compatibility ≠ semantic match | **Documented as a limitation with a collision test**: two proven procedures with identical typed schema and identical operator/effect shape but different semantics share a signature and are both proposed — which is exactly why the shadow has no authority. The two-sided requirement/capability signature is named as the next SIG design, not built | `test_capability_signatures.check_same_schema_different_semantics_collide` |
| 8 | A failing shadow observation vanished inside a guard, biasing SIG-001 toward easy tasks | `signature_shadow_failure` event with error class, task and lexical candidates; per-runbook failures inside `shadow_match` are surfaced, not swallowed | `test_capability_signatures.check_shadow_failures_are_logged`: a corrupt proven runbook produces the event while the live route proceeds |
| 9 | `BUILD_MANIFEST.json` looked like current truth and described 2026-08-22 | Moved to `historical/audits/BUILD_MANIFEST-2026-08-22.json`; the forensic report points there and says it is a snapshot | `test_package` packaging manifest unaffected |
| 10 | `evidence.py` dropped `[label with spaces]` observations | The label grammar accepts spaces, `.`, `>`, `-`, `/` (never `:`), so every test's declared observation is counted; EVIDENCE regenerated | `test_package.check_interleaved_logs_cannot_cry_wolf` extended: spaced labels counted, `[skipped: …]` not |
| 11 | Promotion-leakage was audited once by hand | **`tests/test_promotion_leakage.py`**, permanent: every path that defines success or earned trust (trust ledgers, seals, evaluation suites, verifier registry, proof and frontier ledgers, contracts, scores, mastery events, training registry) is classified CONTROL or lives outside the expert root, and an agent-actor write to each in-root path is refused by the file authority | static zone classification + dynamic `fileauth.resolve(..., "write", "agent")` refusals |

## Claim envelopes (the narrower statements the tests actually prove)

**Git (Phase 5)**

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| deterministic commit | same bytes, same verbs, adapter-initialized repo | hostile concurrent mutation | commit hash in two arenas |
| exact commit | clean index (enforced) | dirty index (refused) | host `git show --name-only` |
| restore on failed effect | clean index, adapter-initialized repo | process kill mid-verb | HEAD/refs/index/worktree comparison via host git |
| conflict refusal | clean tracked worktree (enforced) | — | host git: no `MERGE_HEAD`, same HEAD |
| tamper fail-closed | control files as the adapter wrote them | a tamper that mimics the canonical bytes exactly | refusal before any git invocation |

**XLSX (Phase 6)**

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| byte determinism | same table, same sheet name | — | bytes in two arenas |
| exact round trip | values the adapter wrote | formulas, merges, errors (refused) | CSV text equality |
| foreign import | well-formed OOXML without the refused features | ambiguous OOXML (refused) | hand-built fixture |
| evidence hashing | — | — | byte digest, not text |

**Transactional contracts (Phase 7, held)**

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| precondition refuses | one SQLite connection, `BEGIN IMMEDIATE` | — | independent sqlite3 read |
| invariant rolls back | same | — | same |
| two files, one commit | all files rollback-journaled (WAL refused) | process kill between journal and commit (SQLite's own guarantee, not re-tested here); file + database + git groupings (**do not exist** — a step is one world) | independent sqlite3 read of both files |

## Evidence independence, graded

Weak — the tool reports its own success. Better — the same adapter reads
back. Strong — a *different implementation* checks the state. This phase
raises the Git exact-commit and dirty-index oracles to **strong** (host
git), keeps the XLSX fixture oracle strong (hand-built archive), and the
Phase 7 gate strong (raw `sqlite3`).

## Out of scope, named

Durable journaling and restart recovery for cross-world groupings: not
built, because no cross-world atomic grouping is offered — a procedure step
mutates one world and Phase 7's multi-file atomicity is SQLite's own. If a
later phase groups worlds, it needs the journal the audit describes, and
until then the honest name for any such grouping is *compensated
multi-resource execution*. Repository governance (branch protection,
required checks, signed tags) is an owner action and is reported, not
self-granted.
