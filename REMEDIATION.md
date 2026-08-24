# Remediation — every audit finding, and what was done about it

The two-pass forensic audit produced 2 P0s, 12 P1s, 4 P2s and 4 P3s. This is
the disposition of each: what changed, which test holds it closed, and what
residual risk remains. Findings are numbered as in
`GAPS_RISKS_AND_UNFINISHED.md`.

**Verification for everything below:** `python tests/run_all.py` → **ALL TESTS
PASSED**, twice consecutively (93 tests); `python harness.py --check` → exit 0;
`python preflight.py` → 0 blockers.

This document now covers **three passes**: two read-only forensic audits, and
a third set of defects (`U1`–`U8`, at the end) found by *building a
specification against the running system* rather than reading it.

---

## The pattern behind the fixes

The audit's central finding was structural, not incidental:

> Every control defended the path its author was thinking about, and no control
> knew about the other paths that reached the same operation.

So the remediation is not eighteen patches. It is **three gateways** every
caller must now pass through, plus the specific holes each one closes:

| Gateway | Module | Replaces |
|---|---|---|
| Executing a command | `sandbox.run` + `policy.check`, now on the gate path too | 5 unguarded `shell=True` sites |
| Resolving a secret | `credentials.py` | 4 hand-written lists that disagreed |
| Defining "done" over the network | `gates.py` | a free-form shell string from an HTTP body |

---

## P0 — remotely exploitable

### P0-1 · Panel had no CSRF protection · **FIXED**

`ui.py` now refuses cross-origin writes. `_same_origin()` checks
`Sec-Fetch-Site` (sent by every current browser, unforgeable from script) and
`Origin` against `Host`; every `POST`/`PUT`/`DELETE`/`PATCH` to `/api` must
pass, **whether or not a token is set**. A request with neither header is not
from a browser (curl, the CLI, a test) and is allowed — the token guards
those.

*Held by:* `test_csrf.py` — replays the original attack with both browser
signals and asserts 403 plus "nothing was created", then asserts the panel's
own same-origin requests still work.

### P0-2 · CSRF escalated to arbitrary command execution · **FIXED**

The panel accepted `done_check` as a raw shell string from the request body,
and `check_done` ran it. Now `gates.py` holds a closed catalogue — `exists`,
`designcheck`, `citecheck`, `verify`, `memcheck` — and the network **names** a
gate with parameters. Parameters are validated as contained relative paths or
simple course names; the harness builds the command. A raw string is refused
with a 400 that names the alternative, even from a same-origin caller.
`GET /api/gates` publishes the catalogue so the panel can offer it.

The CLI still accepts free-form gates: an operator with a terminal already has
a shell, so refusing them there would protect nothing.

*Held by:* `test_csrf.py` (raw string refused over HTTP, named gate accepted,
traversing parameter inside a named gate still refused) and
`test_hardening.py::check_gates` (the builder itself).

---

## P1 — a stated guarantee did not hold

| # | Finding | Fix | Held by |
|---|---|---|---|
| **P1-1** | The verification gate ran model-authored shell with no policy, no sandbox, and the full environment | `check_done`, `verify.py` and `goal.py`'s milestone checks now all screen through `policy.check` and execute through `sandbox.run`. Verification is not a lesser path than work | manual reproduction: the gate now reports the same withheld-credential notice as `run_command` |
| **P1-2** | Lock release did not verify ownership; a stalled holder deleted its replacement's lock | Both `locks.holding` and `loop._state_lock` write a per-**acquisition** token and only remove the lockfile if it still contains that token. `locks.held_by_me()` added for long sections | `test_hardening.py::check_locks` |
| **P1-3** | `locks.py` had no test (`test_lock.py` covers a different mechanism) | Direct coverage added, including the stalled-holder scenario and per-acquisition token uniqueness | `test_hardening.py::check_locks` |
| **P1-4** | Routing could never promote a cheaper model — a candidate needed runs it could never accrue | Deterministic exploration: every Nth task of a role goes to the least-evidenced candidate (`route_explore_every`, default 7). Verified end to end — a challenger earned 6 runs and then won on merit | measured: `static-fallback → explore → auto` |
| **P1-5** | Backups archived credentials while reporting them excluded | `backup.py` delegates exclusion to `credentials.is_secret`, which knows the conventional names **and** the files `settings.toml` points at. Inline `api_key` is redacted on the way into the archive. The report line no longer implies completeness | `test_hardening.py::check_secrets`, `test_backup.py` |
| **P1-6** | `write_file` reached `settings.toml`, prompts, approvals and ledgers | `_safe_path(rel, write=True)` refuses the files that define the agent's own permissions. Reads use the shared credential model, so `keys/*.key`, `cookies.txt`, `bootstrap.json` and `identity.json` are all withheld | `test_hardening.py::check_writes` |
| **P1-7** | Ingestion read arbitrary local files via `file://` | `http`/`https` only, on `fetch_url` and on same-site crawling. A refused scheme is permanent — it no longer queues a Ripper to retry it | `test_url.py` (now asserts the refusal), `test_hardening.py::check_scheme` |
| **P1-8** | An unsanitised `course` escaped the expert root | `loop.safe_course()` slugifies at `add_task`, the single point a course enters the system | `test_hardening.py::check_course` |
| **P1-9** | `package.py` shipped the federation HMAC secret | Exclusion delegated to `credentials.is_secret`; `federation/` and other stateful directories skipped; inline keys redacted; the "no private data included" claim replaced with what actually happened | `test_hardening.py::check_secrets` |
| **P1-10** | Cost ceilings covered 1 of 4 model-call paths | Spend is recorded inside `call_model`, so compaction, `replay.py` and `benchmark.py` are all counted. The mock path records too, which is what makes the breaker testable | `test_guardrails.py` (the daily breaker) |
| **P1-11** | Four credential sources, six subsystems, no two agreeing | `credentials.py` is the one model: `resolve`, `key_present`, `sources_for`, `is_secret`, `redact`. `loop`, `providers`, `chief`, `backup`, `package` and `_safe_path` all use it | `test_hardening.py::check_secrets` |
| **P1-12** | A skill file could declare itself trusted | Trust comes from the graph only. A self-claim may be *more* cautious (`community`) but never less; an unregistered folder skill is third-party until the owner promotes it. `routines.save` registers what it writes | `test_hardening.py::check_skill_trust`, `test_skillmd.py` |

---

## P2 / P3

| # | Finding | Fix |
|---|---|---|
| **P2-1** | "Exactly-once" effects was at-least-once | `effects.begin()` writes intent **before** the call; `effects.unfinished()` surfaces an effect that started and never resolved, and `mcp.py` refuses to repeat it — it asks the owner instead. `history()` collapses to one entry per effect |
| **P2-2** | Ten functional settings keys undeclared | All ten documented in `settings.toml`, with the two containment-relevant ones (`sandbox`, `command_env_allow`) explained where an operator will read them |
| **P2-3** | Closed-book was config-enforced at the tool layer | Now mechanically reinforced: the Student holds `write_file`, but `write_file` can no longer rewrite `settings.toml`, so it cannot grant itself `read_file` for the next exam |
| **P2-4** | Source authority could be inflated or spoofed | Owner rules match the **host** exactly, as the built-in table already did; kind is judged from host + final path segment; an unrecognised origin is capped at instructional, so nothing ranks itself; `by_ref` is exact |
| **P3-1** | `_state_lock` docstring said 30 s, code said 8 s | Docstring corrected and now also states the ownership rule |
| **P3-2** | Routing outcome attribution is imprecise | **Not fixed** — see residual risk below |
| **P3-3** | Health check ignored `api_key_file` | `providers.py` and `chief.py` use `credentials.key_present`, so a working provider is never reported unfunded |
| **P3-4** | 11 tests emitted no evidence markers | All 11 now emit a `[section]` line; `EVIDENCE.md` went from 316 to 341 observations, 83/83 tests classified |
| **P4-1** | UTF-8 BOM in `test_material.py` | Stripped; a repo-wide sweep found no others |

### Also fixed, found in passing

- **No version control** — the audit's #1 recommendation. `git init` with a
  `.gitignore` that excludes every credential shape and all per-expert state;
  187 files tracked, no secret among them.
- **`replay.jsonl` had no writer** — `modelrouter` read a file nothing
  produced, so replay agreement was permanently dead. `replay.py` writes it.
- **`failure_id` was unstable** — `hash()` is randomised per process, so the id
  written into every gotcha line could never be looked up. Now `sha256`.
- **Federation replay** — the signed `nonce` was carried and never checked. A
  bounded seen-nonce ring refuses replayed requests with 409.
- **`a2a_card` read a key `make_card` never writes**, so every A2A skill
  description degraded to "specialist".
- **`commons.digest` truncation discarded the owner's pins first** — the exact
  content it documents as outranking everything. Pins are kept whole.
- **`demo.py --dir` did an unconfirmed `rmtree`** on any path. A previous demo
  run is moved aside; anything else needs `--force`.
- **`approvals.decide`/`request` were TOCTOU** — read, check and write are now
  one held section, so a decision cannot be silently overwritten.

---

## Residual risk — honestly stated

These are **not fixed**, and the reasons differ:

| Item | Status | Why |
|---|---|---|
| Live provider **behaviour** | **Unverified** | No keys configured. Prompt effectiveness, real token costs, real rate limits and genuine cross-provider failover remain unmeasured — `python loop.py check` is still the only live probe |
| Live provider **HTTP client** | **Verified offline** | `tests/fake_provider.py` is a loopback server speaking the OpenAI-compatible contract. `test_live_provider.py` drives the real 90-line HTTP path: payload, auth header, extra headers, usage-based cost, the 429/5xx ladder, the non-retryable break, instant failover on a refused connection, the timeout bound, malformed bodies and inline tools. `test_first_day.py` rehearses bootstrap → `loop.py check` → first task against it |
| Docker backend | **Exercised for real, on two operating systems** | `test_docker_live.py` starts real containers: isolation confirmed by the container's own hostname (which holds on any host) plus a Debian os-release, the mount in both directions **and the agent able to rewrite what the container wrote**, the host filesystem invisible, egress refused by default, credentials withheld, resource ceilings on the argv, and a gated task completed end to end. Until CI ran it on Ubuntu the container ran as root and handed back a workspace the agent could not write to (U16) — Docker Desktop had been remapping ownership and hiding it. Two operating systems now, still one image and one daemon version |
| The verification machinery itself | **One row was lying, and Linux found it** | `mutate_check.py` reported `docker: credentials passed through` as CAUGHT for four releases. It was counting a container that failed to boot — a Windows `PATH` forwarded into a Linux image means `sh` is not found, so the test died at its first check and the credential assertions never ran. The first Linux run reported MISSED, correctly. Retargeted at the control that actually defends credentials, and each POSIX-only skip now states its own reason. **A mutation harness reports two things and only one was being checked: whether the test failed, and whether it failed for the reason claimed** (U21) |
| Cross-platform behaviour | **Now evidenced, and it cost six defects** | The suite ran on runners this code had never touched — Ubuntu and Windows × Python 3.11/3.12/3.13 — and four of six jobs failed. U15 (a task executed twice), U16 (root-owned workspace), U17 (a world-readable secret), U18 (a false evidence sentence); reproducing them locally in a Linux container found U19 and U20 (staleness decided by comparing two files' timestamps, which overlayfs makes unsound). All six are fixed, each held closed by a test, and the timestamp class is now barred by an AST invariant over every module |
| E2B / Daytona | **Client verified, services never contacted** | `test_hosted_sandbox.py` drives the REST client against a stand-in: no key refuses and runs nothing locally, the request carries the contract, credentials do not travel, both response spellings are read, four failure shapes are reported rather than raised. Neither service has ever received a request from this codebase |
| MCP and A2A against real servers | **Partly — the transport is real** | *This line previously said "in-process fakes", which was wrong.* `mcp.Server` spawns a real subprocess and speaks newline-delimited JSON-RPC over real stdio pipes; `tests/mock_mcp_server.py` implements the actual protocol (initialize → notifications/initialized → tools/list → tools/call). What is untested is a THIRD-PARTY server — someone else's implementation, with its own quirks |
| 24/7 endurance | **Growth measured, duration not** | `test_endurance.py` drives 120 real tasks through 6 loop restarts and measures what would end a long run: the hot queue stays at its retention bound with nothing lost to the archive, per-task latency is flat (0.13s across all six batches), logs rotate at a 29 MB ceiling, no lock outlives its holder, ~11 KB per task, and the compiled context window is flat at 1083 tokens. That rules out growth which is O(total work). It cannot rule out a leak that needs days |
| P3-2 routing attribution | **Open** | A task's outcome is credited to the last provider used. Bounded (profiles are keyed by role) and it mis-credits only after a failover; fixing it means per-call attribution, which is a schema change |
| `package.py`, `evidence.py` | **Now tested** | `test_package.py` checks the shipped archive four ways for credentials (basename, directory, extension, and by reading every text member), plants three decoy key files and proves each is excluded by file AND by value, confirms a fresh unzip passes `harness --check` with no setup, and holds `evidence.py` to naming every registered test with no drift and no ghosts |
| A secret in prose | **Undetectable** | `credentials.is_secret` catches conventional names, configured key files, key extensions and whole-file tokens. A credential written mid-sentence in a note is not discoverable by any rule, and `backup.py` now says so rather than implying completeness |
| Prompt injection | **Not a boundary** | `_read_block` fencing remains what it always was: a cost increase, not a control. The real containment is the tool allow-list, path containment, environment scrubbing and the approval gate — all of which are now consistent across paths |

---

## What changed, by file

**New:** `credentials.py` (the one credential model), `gates.py` (the done-check
catalogue), `tests/test_hardening.py` (8 audit findings kept closed),
`tests/test_csrf.py` (live cross-origin attack), `.gitignore`.

**New in the third pass:** `tests/test_ux.py` (the UI spec's own §15
acceptance table, executed), plus four checks added to
`tests/test_invariants.py`: expert-birth paths, exam-reader agreement,
sandbox-name uniqueness, and documented-CLI existence.

**Changed in the third pass:** `ui.html` (the whole redesign), `ui.py`
(`performance()`, `training_view()`, the policy and mission routes, the
flattened worker choice), `fleet.py` (seeding at the gateway), `selfmodel.py`
(the exam score), `workers.py` (kind-implied capabilities),
`modelrouter.py` (named policies and the quality tie-break), `mission.py`
(current action, plan, cost, and the meet/block/close CLI), `acquire.py`
(the console guard, four subcommands, one refusal path), `training.py`
(the rollback CLI), `MANUAL.md`, `REFERENCE.md`, `CHANGELOG.md`,
`GAPS_RISKS_AND_UNFINISHED.md`, and 3 test files.

**Changed:** `ui.py`, `loop.py`, `verify.py`, `goal.py`, `locks.py`,
`ingest.py`, `skills.py`, `backup.py`, `package.py`, `providers.py`,
`chief.py`, `effects.py`, `mcp.py`, `modelrouter.py`, `sources.py`,
`memory.py`, `replay.py`, `federation.py`, `commons.py`, `approvals.py`,
`prospective.py`, `checkpoint.py`, `routines.py`, `demo.py`, `evidence.py`,
`settings.toml`, and 14 test files.

---

## Third and fourth passes — U1…U14, found while building the UI/UX redesign

The first two passes read the code. This one **executed** it, against a
specification written by somebody else, which is a different instrument: it
drove paths the audits had inspected but never run. Eleven defects, all fixed, all with a regression test. U10 is a P1 — an
authorization control that no caller called — and U11 is two defects in the
code written during this pass, included because a report that finds faults
only in other people's work is not an audit.

| # | Defect | Severity | Fixed by | Test that holds it closed |
|---|---|---|---|---|
| U1 | A never-bootstrapped fleet home crashes expert creation on 3 of 4 callers | P1 | seeding moved into `fleet.create`, the single gateway; `OSError` refused with a sentence | `test_invariants.py::check_expert_birth_paths` |
| U2 | Two readers of `exam-results.md` disagree, so an expert can pass an exam and not know it | P1 | `selfmodel._exam` reads the canonical `SCORE:` line first | `test_invariants.py::check_exam_readers_agree` |
| U3 | Every directory in the file tree rendered as a clickable file | P3 | one shared `fileTreeHtml()`, accepting either field spelling | `test_ux.py::check_advanced_still_reachable` |
| U4 | A `gpu-worker` could not be chosen for GPU work | P2 | every `KINDS` entry declares what it implies; one `capabilities_of()` | `test_workers.py::check_kind_implies_capability` |
| U5 | `/api/workers/choose` returned an object where the panel showed a sentence | P3 | flattened at the endpoint, with the rejected alternatives | `test_ux.py::check_worker_connection` |
| U6 | `acquire.py --help` crashed on a cp1252 console | P3 | the `sys.stdout.reconfigure` guard the other modules already had | `test_invariants.py::check_documented_cli_exists` |
| U7 | The manual promised eight commands the CLI refuses | P2 | seven subcommands added, two manual entries corrected, one refusal path for `acquire.py`'s whole CLI | `test_invariants.py::check_documented_cli_exists` |
| U8 | Two test files shared one sandbox directory | P2 | renamed; the property asserted by `ast` across all 93 test files | `test_invariants.py::check_sandbox_names_are_unique` |
| U9 | The panel scrolled sideways at 375 px; two tables had no scroll container | P3 | `min-width:0` on grid items, and the wrapper moved INTO `taskTable()` | `test_ux.py::check_mobile_layout` |
| U10 | `org.check` — "the single question every mutating path asks" — was asked by nothing but `org.py` and its own test | **P1** | personal bearer tokens, actor resolved from the credential, a declared permission table with a strict default, `Denied` → 403 | `test_rbac.py` (whole file) |
| U12 | a timed-out command left its docker container running — an unbounded leak on a 24/7 fleet | **P1** | containers are named and `docker rm -f`'d when the client is killed | `test_docker_live.py::check_a_timeout_kills_the_container` |
| U14 | a garbled provider body escaped the retry ladder: the task died and the fallback provider was never tried | **P1** | the parse is inside the ladder, retried, failed over, and logged as `provider_malformed` with the provider named | `test_live_provider.py::check_a_malformed_response_is_not_a_crash` |
| — | five test assertions that could not fail (`or True` × 4, plus one always-true type check); four written during this build, one pre-existing in `test_harness.py` | P2 | each replaced with an assertion that can fail, and stronger than a literal fix | the five tests named in `GAPS…md` |
| U13 | an endurance check read a manifest key that does not exist, measured 0 and passed | P3 | reads the real keys, and asserts the value is non-trivial before asserting anything about it | `test_endurance.py::check_context_does_not_grow_with_history` |
| U11 | two new metrics measured something other than their name — rates that could sum past 100%, and an autonomy ratio that was a success rate | P2 | both derived in one pass over one ledger; autonomy reads the events that record a person being needed | `test_metrics.py` (the autonomy check moves the number) |

### What this pass says about the audits

Five of the eight (U1, U2, U4, U6, U7) are the audits' own central pattern:

> a control, a reader, or a promise defends the path its author was thinking
> about, and does not know about the other paths.

The audits found that pattern in **execution, credentials, filesystem
containment and authorization**. It turns out to hold in three more places
nobody had thought to look:

- **Object construction.** Four callers mint an expert; one prepared the
  ground first. The fix was the same shape as the authorities: move the work
  into the gateway they all pass through.
- **Reading a file.** Two readers, two regexes, one file. Neither was wrong on
  its own terms; together they made an expert misdescribe itself. The
  invariant test writes the file in every format the platform has produced and
  requires every reader to agree — the file-format equivalent of enumerating
  every path.
- **Documentation.** A command the manual promises is a path a person will
  take. `MANUAL.md` named eight that argparse refuses. This is now checked
  mechanically, including bracketed optional subcommands — the first version of
  the check skipped those, and that is precisely how `proof.py [refresh]`
  slipped past it.

### Two invariants that did not exist before

Both are the "enumerate, don't exemplify" form the manual's §25.11 asks for,
applied to things that are not code paths:

- **Every documented command exists** — parses `MANUAL.md`, runs each
  subcommand's `--help` with `PYTHONUTF8=0`, and fails on `invalid choice` or
  on a module that cannot print its own help on a non-UTF-8 console.
- **Every sandbox name is claimed once** — parses all 93 test files with `ast`
  rather than a regex, because the check's own docstring names the call it
  looks for, and a checker that cannot tell code from prose reports itself.

### The Proof System demonstrated itself again

Editing `acquire.py`, `mission.py`, `modelrouter.py`, `selfmodel.py`,
`training.py`, `workers.py` and `ui.py` automatically dropped seven
capabilities from **OFFLINE VERIFIED** to **IMPLEMENTED** — nobody decided
that, and nobody could have prevented it without re-running the evidence.
That is the property the level exists to have.
