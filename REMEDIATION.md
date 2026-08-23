# Remediation — every audit finding, and what was done about it

The two-pass forensic audit produced 2 P0s, 12 P1s, 4 P2s and 4 P3s. This is
the disposition of each: what changed, which test holds it closed, and what
residual risk remains. Findings are numbered as in
`GAPS_RISKS_AND_UNFINISHED.md`.

**Verification for everything below:** `python tests/run_all.py` → **ALL TESTS
PASSED**, twice consecutively (83 tests, 341 evidence observations);
`python harness.py --check` → exit 0; `python preflight.py` → 0 blockers.

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
| Live provider behaviour | **Unverified** | No keys configured. Every test call is still a scripted mock. Prompt effectiveness, real costs and genuine API failover remain unmeasured — `python loop.py check` is the only live probe |
| Docker / E2B / Daytona backends | **Unexercised** | Only the host backend has ever run. The fail-closed path is read-from-source |
| MCP and A2A against real servers | **Unexercised** | Both are tested against in-process fakes |
| 24/7 endurance | **Untested at duration** | Longest observation is a full suite run. Memory growth, ledger size, log rotation and lock contention over days are unknown |
| P3-2 routing attribution | **Open** | A task's outcome is credited to the last provider used. Bounded (profiles are keyed by role) and it mis-credits only after a failover; fixing it means per-call attribution, which is a schema change |
| `package.py`, `evidence.py` | **Untested** | Neither is on the critical runtime path. `locks.py` — which was — now has direct coverage |
| A secret in prose | **Undetectable** | `credentials.is_secret` catches conventional names, configured key files, key extensions and whole-file tokens. A credential written mid-sentence in a note is not discoverable by any rule, and `backup.py` now says so rather than implying completeness |
| Prompt injection | **Not a boundary** | `_read_block` fencing remains what it always was: a cost increase, not a control. The real containment is the tool allow-list, path containment, environment scrubbing and the approval gate — all of which are now consistent across paths |

---

## What changed, by file

**New:** `credentials.py` (the one credential model), `gates.py` (the done-check
catalogue), `tests/test_hardening.py` (8 audit findings kept closed),
`tests/test_csrf.py` (live cross-origin attack), `.gitignore`.

**Changed:** `ui.py`, `loop.py`, `verify.py`, `goal.py`, `locks.py`,
`ingest.py`, `skills.py`, `backup.py`, `package.py`, `providers.py`,
`chief.py`, `effects.py`, `mcp.py`, `modelrouter.py`, `sources.py`,
`memory.py`, `replay.py`, `federation.py`, `commons.py`, `approvals.py`,
`prospective.py`, `checkpoint.py`, `routines.py`, `demo.py`, `evidence.py`,
`settings.toml`, and 14 test files.
