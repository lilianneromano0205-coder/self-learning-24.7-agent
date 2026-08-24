# Gaps, Risks and Unfinished Work

> **STATUS — REMEDIATED.** Every P0 and P1 in this document, all four P2s, and
> the eleven defects the third pass found, have been fixed and carry a
> regression test. See **`REMEDIATION.md`** for the disposition of each
> finding, the test that holds it closed, and the residual risk that remains.
> This document is preserved as the AUDIT RECORD — it says what was wrong and
> how it was proven, which is the half a changelog loses.
>
> Three passes are recorded here. Passes one and two were **read-only forensic
> audits**. The third (below, `U1`–`U11`) came from **building a specification
> against the running system**, which executed paths the audits had only read —
> and that is where five more instances of the audits' own central pattern were
> waiting.
>
> Verified after remediation: 93/93 tests pass twice consecutively,
> `harness.py --check` exits 0, `preflight.py` reports 0 blockers.
> Still open by nature, not by neglect: live-provider behaviour, Docker/E2B
> backends, real MCP/A2A servers, and 24/7 endurance — all listed under
> *Residual risk* in `REMEDIATION.md`.


Findings from the forensic audit, ranked by consequence. Each entry states what
was wrong, how it was established, what it cost, and the options that were
open at the time.

**Read this as the audit record, in the present tense of the audit.** It was
written during a read-only pass, before anything was fixed, and the wording is
deliberately left that way: the value of a finding is the evidence and the
reasoning that produced it, and rewriting those in the past tense after the
fact would quietly erase how each defect was actually proven. What happened
*next* is in `REMEDIATION.md`.

Severity scale:

- **P1** — a stated guarantee does not hold, or a security control is absent
  where one is implied
- **P2** — real defect with bounded blast radius, or a guarantee overstated
- **P3** — correctness or clarity issue that will cost someone time later
- **P4** — cosmetic

---

> **Second pass added P0-1, P0-2 and P1-6 … P1-12.** The first pass ranked
> `git init` first. That is no longer the top item: the panel's CSRF exposure
> is remotely exploitable today, on the default configuration, and yields
> arbitrary code execution. Fix order is restated at the end.

---

## P0-1 — The control panel has no CSRF protection, and its default configuration has no authentication

**Status: reproduced.**

**Where.** `ui.py` — `_authed()`, `do_POST`, and every route.

**Two facts that compose.** `_authed()` begins
`if not self.token or not path.startswith("/api"): return True`. The default
bind is `127.0.0.1` with `token = None`, so **nothing is authenticated by
default**. And no route validates `Origin`, `Referer`, `Sec-Fetch-*`, or the
request `Content-Type` — I grepped the whole file; the only `Content-Type`
occurrences are response headers. `do_POST` parses the body with
`json.loads(self._body())` regardless of declared type.

A cross-origin `text/plain` POST is a CORS *simple request*: no preflight, so
the browser sends it and the server acts. The response is opaque to the
attacker, but **the side effect happens**.

**What I ran** (sandbox panel, `Origin: https://evil.example`):

| Request | Response |
|---|---|
| `POST /api/experts` | `{"created": "csrf-probe"}` |
| `POST /api/experts/csrf-probe/task` | `{"queued": "ce81a5decd3b"}` |
| `POST /api/experts/csrf-probe/start` | `{"running": true}` |
| `POST /api/shutdown` | `{"stopped": true}` |

**Reachable by CSRF:** `/api/experts`, `/shutdown`, `/federation`, `/learner`,
`/preflight`, `/backup`, `/curriculum`, `/quick`, `/team`,
`/retired/<slug>/restore`, and the whole `/api/experts/<slug>/<verb>` dispatch.
`PUT` and `DELETE` are preflighted and therefore blocked.

**Options (not applied):**

1. Reject any `/api` request whose `Origin`/`Sec-Fetch-Site` is cross-site.
   One check at the top of `_route()`; closes the whole class.
2. Require `Content-Type: application/json` on mutating routes — this alone
   forces a preflight and blocks simple-request CSRF.
3. Require a token unconditionally, not only when the bind is non-local, and
   deliver it via header rather than query string.
4. Bind to a Unix socket / named pipe instead of a TCP port.

(1) and (2) together are the minimum; (3) is what makes the panel safe on a
shared machine.

---

## P0-2 — CSRF escalates to arbitrary command execution on the operator's machine

**Status: reproduced end to end.**

**Where.** `ui.py` `_expert_action`, action `task`:
`add_task(..., done_check=data.get("done_check") or None, ...)` — the gate
command is taken **straight from the HTTP request body**. `loop.check_done`
then runs it with `shell=True`, no policy, no sandbox, full parent environment
(P1-1).

**What I ran.** A sandbox panel with a mock provider that finishes immediately,
then three cross-origin POSTs — create, task carrying a malicious `done_check`,
start. The host executed the attacker's command and wrote the proof file:

```
RCE via cross-origin POST done_check
```

**Consequence.** An operator who merely *visits a hostile web page* while the
panel runs on its default settings gives that page arbitrary code execution
with their user privileges — including access to `agent.env`, which
`Agent.__init__` has already loaded into the environment.

`intention`, `workflow`, and `wake` accept `done_check` by the same route, so
the payload can also be **stored and fired later**, surviving a panel restart.

**Options (not applied):**

1. Fix P0-1 — that removes the delivery vehicle.
2. Refuse `done_check` from the network entirely: accept only a gate chosen
   from a server-side catalogue (file-exists, `designcheck`, `citecheck`,
   `verify`), with parameters, never a free-form command.
3. Route `check_done` through `sandbox.run` + `policy.check` (P1-1's fix), so
   even an accepted command is contained.

(2) is the decisive one: a free-form shell string arriving over HTTP is the
root of this, and the four gates the platform actually uses are all
parameterisable.

---

## P1-6 — `write_file` reaches settings, prompts, and every ledger

**Status: reproduced.**

`_safe_path` is the only guard on the file tools and blocks exactly
`{agent.env, agent.env.example, ui-token.txt}` plus any path inside a `.keys`
directory. Verified on a fixture: `keys/openai.key`, `bootstrap.json`,
`cookies.txt`, `identity.json` are **readable**; `settings.toml`,
`prompts/*.md`, `identity.md`, `state.json`, `prospective.json`, and
`approvals/*.json` are **writable**. Note `.keys/` is protected but `keys/` —
the far likelier spelling — is not.

**Four chains, none needing `run_command`:**

1. **Key exfiltration** — write `[providers.X] base_url` in `settings.toml`;
   `Agent.__init__` re-reads it per instance and `loop.py:1402` POSTs
   `Authorization: Bearer {key}` to that URL.
2. **Shell without the shell tool** — write `prospective.json` with a
   `then.done_check`; it fires later as a task gate. The Consultant and Student
   have no `run_command` and reach shell this way.
3. **Forged approval** — `approvals.load()` trusts the file; write
   `{"status": "granted"}`.
4. **Self-edited constraints** — `variants.PROTECTED_ROLES` (constitution,
   _grounding, examiner, student) is enforced *only* inside `spawn()`, though
   its comment claims "for every caller including the panel". `write_file`
   writes those prompts directly, and `promote()` never re-checks the list
   against a model-writable `variants/manifest.json`.

**Every role holds `write_file`, including the Student.** The "Rule of Two"
comment withholds `run_command` from roles that read untrusted material, but
`write_file` is unrestricted and reaches the files that *define* every other
capability.

**Options:** a protected-path list for `write_file` (settings, prompts,
ledgers, approvals) — the mirror of `SECRET_BASENAMES` for writes; or route
harness-owned files out of the agent root entirely.

---

## P1-7 — Ingestion reads arbitrary local files (`file://`), and the inbox is the delivery path

**Status: reproduced.**

`ingest.fetch_url` has no scheme allowlist; `same_site_links` explicitly
permits `file`. Fetching `file:///…/secret.txt` wrote its contents into a
lesson. This bypasses `_safe_path` and `SECRET_BASENAMES` — a different code
path entirely.

**The worst reach is the lowest-privilege input in the system.** `route_file`
treats `.url`/`.urls` files as link lists and calls `add_url` for every line;
`scan_inbox` runs automatically. A `.url` file dropped in `inbox/` containing
`file:///…/agent.env` reads the provider key into course material, which is
then injected into the model's context. The same call reaches internal HTTP
addresses (SSRF).

**Options:** allowlist `http`/`https` in `fetch_url`; drop `file` from
`same_site_links`; refuse link targets that resolve to loopback/link-local.

---

## P1-8 — Filesystem containment escape via unsanitised `course`

**Status: reproduced.**

`add_task` stores `course` verbatim and nothing in the repository sanitises it.
`gotchas.from_failure` with `course="../../ESCAPED"` wrote its file **outside
the expert root**, leaving the root empty.

`_safe_path` is used in only three places. Five harness writers build
course-derived paths without it: `gotchas.py:83`, `candidates.py:165`,
`conflicts.py:333`, `curriculum.py:297`, `loop.py:515`. Since
`prospective.json` is model-writable (P1-6), `then.course` gives the model an
arbitrary-file-write primitive outside its root.

**Options:** slugify `course` at `add_task` (the codebase already has
`fleet.slugify` and `ingest.slugify`); or route every harness write through
`_safe_path`.

---

## P1-9 — `package.py` ships credentials and the federation secret

`SKIP_FILES` omits `identity.json` (which `backup.py` treats as a secret) and
knows nothing of `api_key_file` or inline `api_key`. `federation/` is not in
`SKIP_DIRS`, so `federation/identity.json` — holding the fleet's HMAC
`secret` — lands in the distributable. The command prints *"no private data
included."*

---

## P1-10 — Cost ceilings protect one of four model-call paths

`call_model` contains no spend recording and no budget check; `_record_spend`
has exactly one call site and `_budget_exceeded()` one check site.

| `call_model` site | Recorded | Checked |
|---|---|---|
| `loop.py:1136` main step | yes | yes |
| `loop.py:1058` **compaction** | no | no |
| `replay.py:83` | no | no |
| `benchmark.py:112` | no | no |

Compaction is on the primary path and fires on the longest tasks, so both
ceilings under-count worst exactly where spend is highest.
`modelrouter`'s `avg_cost_usd` inherits the understatement.

---

## P1-11 — Four credential sources, six subsystems, no shared model

`loop.py` accepts the environment, `agent.env`, **inline `api_key` in
`settings.toml`**, and `api_key_file`. The inline form contradicts
`settings.toml`'s own comment and `providers.py:80`. `settings.toml` is
excluded by neither `backup.py` nor `package.py`, and is readable by the model.

Four divergent secret lists exist — `loop.SECRET_BASENAMES` (3),
`backup.SECRET_NAMES` (5), `package.SKIP_FILES` (5), `sandbox.SECRET_MARKERS`
(env patterns) — and no two agree. Five subsystems ignore `api_key_file`
entirely (`providers.py`, `chief.py`, `backup.py`, `package.py`, `_safe_path`).

**Option:** one `credentials.py` that resolves *and* enumerates every
configured secret path, which every other subsystem consults.

---

## P1-12 — A skill file can declare itself trusted

**Status: reproduced.**

`skills.py` states *"a third-party file must never be able to declare itself
trusted"*, but `discover()` passes the file's own frontmatter as the default to
`provenance_of()`. With no graph entry, `provenance: own` in the file is
authoritative — verified: `script_guard` returned `None` (scripts allowed) for
a self-declared `own` skill, and `REFUSED` for the same file declaring
`community`.

`import_skill` always writes a graph entry, so the CLI path is safe. Every
other arrival path leaves none: model `write_file`, `routines.save`, manual
copy, backup restore, unzip.

Separately `script_guard` is a substring test over model-authored text and is
defeated by any path encoding (two `chr()`/`glob` variants were allowed), and
it is consulted only from `run_command` — never from the gate path.

---

## P1-1 — The verification gate executes model-authored shell with no policy, no sandbox, and the full environment

**Status: reproduced.**

**Where.** `loop.check_done` (uses `shell=True`); `verify.py:59` (same, for
`CHECK:` commands).

**Why it matters.** These commands are written by the model, not the operator.
`prompts/watcher.md` instructs the Watcher to write `CHECK:` commands into
`spec.md`; `goal.py:170` solicits `CHECK:` lines from the planner. Both files
are then read back and executed.

**What I did.** Built an isolated temp sandbox, planted a synthetic marker
value in the environment (no real credential was ever used), and ran both code
paths:

| Path | Saw the planted marker |
|---|---|
| `check_done` — the gate | **yes** (`FAKE-KEY-VISIBLE`) |
| `run_command` — the normal tool path | no (`ABSENT`) |

I also grepped `check_done` and `verify.py` for any reference to `policy` or
`sandbox`. There is none.

**The shape of the problem.** The normal tool path is correctly defended:
`policy.py` screens commands, `sandbox.py` scrubs the environment down to
scoped grants. The *verification* path — the one whose entire job is to decide
whether work is acceptable — has neither. The asymmetry is easy to miss
precisely because the well-defended path is the one everybody reasons about.

**Options (not applied):**

1. Route `check_done` and `verify.py` through `sandbox.run` so they inherit
   environment scrubbing and backend isolation. Highest value, and it makes the
   two paths symmetric.
2. Screen gate commands through `policy.py` before execution. Cheaper, but
   allow-listing shell is a weaker control than scrubbing the environment.
3. Drop `shell=True` in favour of argument-vector execution. Removes shell
   metacharacter interpretation; does not by itself fix environment exposure.
4. Treat `spec.md` `CHECK:` lines as requiring operator approval before first
   execution (the `approvals.py` mechanism already exists).

Options 1 and 4 compose and address different halves — containment and
authorship.

---

## P1-2 — Lock release does not verify ownership; a stalled holder splits the mutex

**Status: established from source, not reproduced** (reproducing it requires
inducing a multi-second stall inside a critical section).

**Where.** `locks.holding()` (`locks.py`) and `loop.Agent._state_lock()`
(`loop.py:332`). Both implementations, independently, have the same hole.

**The sequence.**

1. Process A holds the lock and stalls past the 8-second stale threshold —
   OneDrive sync, antivirus scan, slow disk, suspended process, VM pause. On
   this machine the tree lives inside a OneDrive folder, which makes multi-
   second file-IO stalls a realistic event, not a theoretical one.
2. Process B judges the lock stale, removes it, creates its own.
   **A and B are now both inside the critical section.**
3. A completes and runs `finally: os.remove(lock)` — removing **B's** lockfile.
4. C acquires immediately. B and C are now both inside.

**What makes this fixable cheaply.** Both implementations already write
`os.getpid()` into the lockfile and **never read it back**. The information
needed to detect the split is on disk and unused.

The code comment rejects PID liveness probing on Windows — `os.kill(pid, 0)`
can terminate the target, PIDs are reused. That reasoning is correct, and it
argues against *probing a foreign PID*. It does not argue against *reading the
lockfile you are about to delete and confirming it still contains your own
token*.

**Blast radius.** These locks protect `effects.jsonl` (duplicate external
effects), `approvals.json`, `prospective.json`, `skills/graph.json`, and
`state.json` (the task queue). The docstring records that this exact failure
class was once observed live — a due intention fired twice, queueing the
owner's action double. The mutex added to prevent that recurrence is itself not
safe under a stalled holder.

**Options (not applied):**

1. Write a unique token (PID + creation nonce) and, in `finally`, read the file
   and only remove it if the token matches. Closes step 3.
2. Additionally re-check the token after any long operation; abort the critical
   section if it changed. Closes step 2's damage.
3. Raise `stale` well above any plausible stall, accepting longer recovery from
   genuine crashes. Weakest option — trades one failure for another.

---

## P1-3 — `locks.py` has no test

**Status: verified.**

No test file imports `locks`. `tests/test_lock.py`, despite the name, tests the
*course* lock inside `loop.py` — a different mechanism with a different
implementation.

So the concurrency primitive guarding four mutating ledgers is the least-tested
security-sensitive module in the build, and the defect in P1-2 is exactly the
kind a direct test would have surfaced.

**Also untested:** `evidence.py` (the tool that generates the correctness
report — an untested reporter of correctness) and `package.py` (builds the
distributable). Neither is on the critical runtime path.

---

## P1-4 — Model routing is structurally incapable of promoting a cheaper model

**Status: established by tracing every call site.**

`modelrouter.choose` rejects candidates with fewer than `min_n` recorded
outcomes (default 5). Outcomes are written by exactly one call site —
`loop.py:1751` — and only for the pair actually used. There is no exploration
mechanism anywhere in the module (no epsilon-greedy, no forced trial, no shadow
call).

Therefore a model accrues eligibility runs **only** if it is already reachable
as the role's static `model`, `fallback_model`, or `escalate_model`. A model
listed *only* in `route_candidates` is tried never, accrues nothing, and is
rejected forever with *"only 0 run(s), 5 needed"*.

The feature can confirm the configured default. It cannot replace it — which is
the thing it was built to do.

**Why the test passes.** `tests/test_modelrouter.py` seeds the outcome ledger
directly by calling `modelrouter.record(...)`, which bypasses precisely the gap
that makes the feature inert in production. The scoring maths is correct and
well tested; the acquisition of the data it scores is not modelled at all.

**Options (not applied):**

1. Explicit exploration budget: route a small fraction of low-risk tasks to an
   unproven candidate until it reaches `min_n`. Standard, and it fits the
   existing ledger without schema change.
2. Shadow evaluation: run the candidate alongside the incumbent on the same
   task, score both with the existing verifier stack, record the candidate's
   outcome without using its output. Costs double tokens on sampled tasks;
   carries no correctness risk.
3. Seed from `benchmark.py`, which already has an arm structure for running the
   same tasks under different configurations.
4. Document the feature honestly as "confirm or fall back", and require the
   operator to promote candidates manually.

---

## P1-5 — Backups include credential files in plaintext while reporting that credentials were excluded

**Status: reproduced against the product's own `backup.py`, using synthetic
values in an isolated fixture outside the repository.**

**Where.** `backup.py:39` — `SECRET_NAMES` is a fixed list of five basenames:
`agent.env`, `ui-token.txt`, `identity.json`, `cookies.txt`, `bootstrap.json`.
Exclusion is by exact basename match. `backup.py` never reads `settings.toml`.

**The gap.** The product supports a second credential mechanism.
`settings.toml` documents it — *"Keys come from the environment (api_key_env)
or a file readable only by the agent user (api_key_file)"* — and it is
implemented at `loop.py:695`, which opens `prov["api_key_file"]` and reads the
key from it. **The operator chooses that filename.** Any name outside the five
is backed up.

**What I ran.** Built a fixture fleet home containing an expert with
`agent.env`, `identity.json`, `keys/openai.key` (the shape `api_key_file`
points at), and `my-secret.txt`. All values synthetic; no real credential was
involved. Then ran the product's own command:

```
python backup.py create --home <fixture> --out <fixture-out>
```

Output: `4 file(s), 0.0 MB, 1 expert(s)` / **`2 credential file(s)
deliberately excluded`**

Archive contents:

| File | In archive |
|---|---|
| `experts/testexpert/agent.env` | no — correctly excluded |
| `experts/testexpert/identity.json` | no — correctly excluded |
| **`experts/testexpert/keys/openai.key`** | **yes — 20 bytes, plaintext, fully recoverable** |
| **`experts/testexpert/my-secret.txt`** | **yes — plaintext** |

**Why this is P1 rather than P2.** Three things compound:

1. A backup archive is the artefact most likely to leave the machine — copied
   to external storage, synced to cloud, emailed, handed to someone restoring
   a fleet. This tree already lives inside a OneDrive folder.
2. The command **reports** "2 credential file(s) deliberately excluded". That
   message reads as an assurance that credentials were handled. An operator has
   no reason to open the zip and check.
3. The excluded-by-default mechanism (`api_key_env` + `agent.env`) is safe, so
   the failure only appears for operators who followed the *other* documented
   option — the one `settings.toml` describes as the more locked-down choice.

**Options (not applied):**

1. Read `settings.toml` at backup time, resolve every `api_key_file` value, and
   exclude those paths explicitly. Directly closes the documented mechanism.
2. Exclude by content heuristic as well as name — the `SECRET_MARKERS` list
   already exists in `sandbox.py` and could be reused to skip any file whose
   contents look like a credential.
3. Exclude by extension (`.key`, `.pem`, `.secret`) in addition to basename.
   Partial: does not catch `my-secret.txt`.
4. At minimum, change the report line so it states what was excluded rather
   than implying completeness — a count of matched names is not evidence that
   no credential remains.

Options 1 and 2 compose and are the only ones that close the mechanism rather
than widening the list.

---

## P2-1 — "Exactly-once" external effects is at-least-once

**Where.** `mcp.py:349-352`: `result = s.call(...)` executes, and only then
does `effects.record(...)` write the ledger entry.

A crash between those two statements leaves the external effect performed and
unrecorded. The next run finds no entry and repeats it.

The ledger key — `(lineage, server, tool, sha256(args))` — is well chosen, and
the window is small. The honest claim is **at-least-once with a small duplicate
window**. Documentation asserting exactly-once should be corrected, or the
write-ahead ordering changed (record intent → call → mark complete), which is
the only way to actually earn the stronger claim.

---

## P2-2 — Ten functional settings keys are undeclared in `settings.toml`

All 19 declared `[agent]` keys are read by code — there are no dead settings.
The asymmetry runs the other way: code reads 10 keys the file never mentions.

`auto_scan_inbox`, `inbox_settle_seconds`, `max_task_retries`,
`candidates_max`, `candidates_on_gate_failure`, `command_env_allow`,
`sandbox`, `sandbox_network`, `sandbox_image`, `design_gate`

Two are security-relevant — `command_env_allow` (what leaks into a child
process) and `sandbox_network` (whether sandboxed work reaches the network) —
and an operator reading only `settings.toml` cannot discover that they exist or
what they currently default to.

---

## P2-3 — Closed-book isolation is code-enforced at one layer and config-enforced at the other

The Student cannot consult its notes during an exam. Two mechanisms:

- **Context layer (code).** `memrouter`'s student rule can only *remove*
  sources. Asserted by `tests/test_memory_kinds.py`.
- **Tool layer (configuration).** `[roles.student] tools = ["write_file",
  "finish_task", "ask_human"]` — no `read_file`, and `allowed_tools()` adds
  only `finish_task`/`ask_human`.

Both are mechanical — neither is a prompt instruction, which is the right
design. But the tool layer is a settings value, nothing in code prevents
`read_file` being added to the student role, and **no test asserts its
absence**. A one-word edit to `settings.toml` silently voids the guarantee with
a green suite.

**Option:** an assertion in the test suite that the student role's resolved
tool set excludes every read capability. Cheap, and it converts a convention
into a checked invariant.

---

## P3-1 — Docstring and code disagree on the stale-lock threshold

`loop._state_lock`'s docstring says "stale after 30s"; the code breaks locks at
`> 8` seconds. The inline comment further down says 8 s and explains the
reasoning, so the docstring is the stale artefact. Anyone reasoning about
contention from the docstring will be wrong by a factor of ~4.

---

## P3-2 — Routing outcome attribution is imprecise

`modelrouter.record` stores `role: task.get("role")` and the provider/model
from `task["provider"]`/`task["model"]`, set at `loop.py:1138-1139`. A task
that makes calls under several roles, or whose final step failed over to a
different provider, attributes its single pass/fail outcome to the last pair
used. Profiles are keyed by role, so cross-role contamination is bounded, but
the failover case mis-credits the fallback model with the task's verdict.

---

## P3-3 — The connectivity check does not honour `api_key_file`, so the only live probe can report a false failure

`loop.py:695` resolves a provider key from `api_key_file` when configured.
`providers.py:136-148` — the code behind the connectivity check — does **not**:
it reads `os.environ[api_key_env]` and then falls back to scanning `agent.env`
in the expert root and in `HOME`. `api_key_file` appears nowhere in
`providers.py`.

Consequence: an operator who configures `api_key_file` has working model calls
and a connectivity check that reports the key absent. `python loop.py check` is
described throughout the build as the only live probe of provider health, which
makes a false negative there more costly than it first appears — it points
diagnosis at the wrong thing.

---

## P3-4 — Eleven tests contribute nothing to the evidence report, and they are the adversarial ones

`evidence.py` builds `EVIDENCE.md` by harvesting `[section]` markers printed by
tests. Eleven of 81 tests print none:

`test_compaction`, `test_e2e_crash`, `test_faults`, `test_json_toolcall`,
`test_layers`, `test_paths`, `test_reflector`, `test_reliability`,
`test_retry`, `test_skills`, `test_verify`

These are not weak tests — `test_faults` makes 22 assertions, `test_layers` 23,
`test_retry` 13. They defend contracts and say nothing about it. The tests that
emit no evidence include the crash test, the fault-injection test, the path-
containment test and the corrupt-state test: precisely the adversarial claims a
reader of `EVIDENCE.md` would most want substantiated.

The result is a reporting bias, not a correctness problem. The document whose
job is to answer *"why do you believe this works"* is quietest exactly where
the hardest claims live.

---

## P4-1 — UTF-8 BOM in one test file

`tests/test_material.py` is the only file in the tree carrying a BOM. No
functional effect observed.

---

## Unfinished / unverifiable, not defects

These are limits of what this build has been shown to do, not things that are
broken.

| Area | State |
|---|---|
| Live provider behaviour | **Never verified.** Every test call is a scripted mock. Prompt effectiveness, real costs, and genuine API failover are unmeasured. `python loop.py check` is the only live probe and needs keys. |
| Docker / E2B sandbox backends | `docker` present as a binary; no containerised run performed. Fail-closed path is read-from-source only. |
| MCP and A2A federation | Tested against in-process fakes only. No third-party server contacted. |
| Long-run 24/7 behaviour | Untested at duration. Memory growth, ledger size, log rotation, and lock contention over days are unknown. Longest observation: a 259-second suite run. |
| `backup.py` restore | Not executed against a real backup set in this pass. |
| Version control | **Absent.** No history, no blame, no diff against known-good, no recovery from an accidental overwrite. This is the highest-leverage unfinished item in the repository and costs nothing to fix. |
| 4 toolbox capabilities | `docs_convert`, `video_download`, `transcribe`, `vision` report MISSING — optional external binaries not installed. Guarded, not broken. |

---

## If I were ranking the work

**Revised after the second pass.** The order below was written before the P0s
were found. The corrected order is:

0. **P0-1 + P0-2 (CSRF → RCE).** Remotely exploitable today, on the default
   configuration, by a web page the operator merely visits. One `Origin` check
   plus a `Content-Type` requirement removes the delivery vehicle; refusing
   free-form `done_check` over HTTP removes the payload. Everything else on
   this list is reachable only by someone who already has access.
0b. **P1-6 (`write_file` scope)** and **P1-8 (`course` traversal)** — together
   they give the model an arbitrary-write primitive that reaches the files
   defining every other control.
0c. **`git init`** — still the cheapest item, and it makes every fix below
   revertible.

Then the original ordering:

1. ~~**`git init`**~~ (moved to 0c).
2. **P1-5** (credentials in backups) — reproduced, and the artefact involved is
   the one most likely to leave the machine. Smallest fix on this list with the
   largest downside if left.
3. **P1-1** (gate execution) — a security control absent from the path that
   most needs one, and reproduced.
4. **P1-2 + P1-3** (lock ownership + no test) — one fix and one test, and they
   belong together.
5. **P1-4** (routing exploration) — decide whether to build exploration or
   document the feature honestly. Either is acceptable; the current state,
   where the docs imply a capability the mechanism cannot reach, is not.
6. **P2-1, P2-2, P2-3, P3-3** — correct the claim, declare the keys, assert the
   invariant, and make the connectivity check agree with the runtime.

**A pattern worth naming across P1-1, P1-5 and P3-3.** All three are the same
mistake in different modules: a control was built against the *default* path
and never extended to the *second supported* path. The sandbox guards the work
path but not the verification path. The backup excludes `agent.env` but not
`api_key_file`. The runtime honours `api_key_file` but the health check does
not. Each is small in isolation; together they suggest the second configuration
option is where to look first in any future review.

---

## P2-4 — Source authority can be inflated or spoofed (`sources.py`)

The tier assigned here decides who wins a contradiction (`conflicts.py`) and
what may become a gate-checked standard (`standards.extract`). Three defects:

1. **Path keywords inflate the tier.** `_kind()` regexes the whole reference,
   not the host, so any unrecognised domain with `api`, `guide`, `docs`,
   `reference` or `documentation` in its **path** is rated `docs` → tier 2
   (*professional*).
2. **The owner table matches as a substring of the whole reference**
   (`if str(dom).lower() in low`), so a URL carrying a trusted domain in its
   path or query inherits that rule's tier. The built-in `DOMAIN_TIERS`
   matching is correct by contrast — `host == d or host.endswith("." + d)` —
   which makes the owner-configured path the weaker one.
3. **`by_ref` matches fuzzily** (`r["ref"] in ref or ref in r["ref"]`), so
   `tier_of` can return another source's tier when one reference is a
   substring of another.

**Bounded by:** `designcheck.STRICTER` means a spoofed standard cannot *lower*
a numeric gate. The conflict ruling itself is not bounded.

**Options:** classify `_kind` from the host plus the final path segment only;
match the owner table against the parsed hostname exactly, as `DOMAIN_TIERS`
already does; make `by_ref` exact.

---

# Third pass — defects found while building the UI/UX redesign (2026-08-23)

The first two passes were read-only forensic audits. This set is different in
kind: it came from **implementing a specification against the running system**,
which meant driving paths the audits had read but never executed. All seven
are fixed and carry a regression test; the disposition is in `REMEDIATION.md`.

The pattern the audits named — *a control defends the path its author was
thinking about, and does not know about the other paths* — held again in five
of the seven. Two are new shapes: **two readers of the same file that disagree**,
and **documentation that promises a command the CLI refuses**.

---

## U1 — A fleet home that was never bootstrapped crashes expert creation

**Severity:** P1 (a stated guarantee does not hold: `fleet.py create --home
<dir>` is documented and does not work).

`fleet.create()` copies `home/prompts/` into every new expert. Only
`bootstrap.py` calls `bootstrap.seed_home()` first. There are four callers:

| Caller | Seeds the home first? |
|---|---|
| `bootstrap.py` | yes |
| `fleet.py` CLI | **no** |
| `quick.py` | **no** |
| `ui.py` POST `/api/experts` | **no** |

**Observed:** `python fleet.py create "X" --home <fresh dir>` →
`FileNotFoundError` from `shutil.copytree`, with a full traceback. The panel's
create route turned the same exception into HTTP 500.

**Second failure in the same code path:** a home whose parent is a file (a
plausible typo) raised `FileNotFoundError` from `os.makedirs` rather than
refusing with a sentence.

**Fixed by** moving the seeding into `fleet.create()` — the single gateway all
four callers already pass through — and catching `OSError` around both
`makedirs` and `seed_home`. `bootstrap.seed_home` stays the one implementation
of what a fleet home contains.

**Test:** `tests/test_invariants.py::check_expert_birth_paths` enumerates the
callers from the source tree, exercises the gateway on an unprepared
directory, proves seeding is idempotent and does not clobber owner edits, runs
the CLI from an unrelated working directory, and requires a sentence rather
than a traceback for an impossible home.

---

## U2 — An expert can pass an exam and not know it

**Severity:** P1 (the agent's own self-description, injected into every context
window, contradicts the loop's own completion check).

Two readers of `courses/<c>/exam-results.md` disagreed about its format:

| Reader | Pattern | Matches `SCORE: 95`? |
|---|---|---|
| `loop.Agent.course_status` | `^\s*SCORE:\s*(\d+)` | yes |
| `selfmodel._exam` | `(\d{1,3})\s*%` | **no** |

**Consequence:** a course could pass at 95, `loop` would agree it was
complete, and the self-model block — the text the agent reads about itself on
every task, and the number the panel prints — reported no score at all. An
expert describing itself as never examined, having been examined and passed.

**Fixed by** reading the canonical line first and keeping the percent form as a
fallback for anything already written that way.

**Test:** `tests/test_invariants.py::check_exam_readers_agree` writes the file
in four recorded formats and requires the loop, the self-model and the rendered
context block to return the same number for each.

---

## U3 — Every directory in the file tree was a clickable file

**Severity:** P3 (correctness and clarity; nothing unsafe).

`expert_tree()` sends `{"p": …, "d": true, "s": …}`. The panel read `e.dir`,
which is always `undefined`, so every folder rendered as a file. Clicking one
answered *"approvals is a directory"*.

**Fixed by** one shared `fileTreeHtml()` used by both the Skills tab and the
new Advanced → Raw files pane, accepting either spelling and showing file
sizes. Two copies of that markup would have drifted the first time a class
changed, and the second copy is the one nobody would remember to fix.

**Test:** `tests/test_ux.py::check_advanced_still_reachable` asserts the field
read and that the API sends both directories and files.

---

## U4 — A GPU worker could not be chosen for GPU work

**Severity:** P2 (a real defect with bounded blast radius: the work is refused,
not misrouted).

`workers.choose` matched a task's requirements against a machine's *typed*
capability list only. A machine registered `--kind gpu-worker` with
`--can cuda` was refused for "fine-tune on the gpu", because nobody had also
typed `gpu`. The registry already knew what the machine was.

**Fixed by** giving every `KINDS` entry an `implies` tuple and one
`capabilities_of(row)` helper used by both `requirements()` and `choose()`.
Implied capabilities are reported separately from declared ones, so
*"why does it claim to do that?"* has an answer. Implying still cannot paper
over a capability that is genuinely absent.

**Test:** `tests/test_workers.py::check_kind_implies_capability` walks the
whole `KINDS` table, registers a bare instance of each kind and requires it to
be routable for what that kind *is*.

---

## U5 — The worker-routing endpoint returned an object where the panel showed a sentence

**Severity:** P3.

`workers.choose` returns `(worker, {chosen, needed, considered, why})`. The
panel rendered `r.why` directly, producing `[object Object]` — the one string
UI spec §7 says must be readable.

**Fixed by** flattening at the endpoint: the sentence, the requirements, and
what each rejected computer could not do. A routing decision nobody can
disagree with is one nobody can correct.

**Test:** `tests/test_ux.py::check_worker_connection`.

---

## U6 — `acquire.py --help` could not print on a Windows console

**Severity:** P3 (the module is unusable from the CLI on the platform this
runs on).

The module docstring contains `→`. `argparse` writes the description through
`sys.stdout`, which defaults to cp1252 on a Windows console, so
`python acquire.py --help` died with `UnicodeEncodeError` before printing a
word. `chief.py`, `mission.py` and `ui.py` already carried the
`sys.stdout.reconfigure` guard; `acquire.py` did not.

**Fixed by** adding the same guard.

**Test:** `tests/test_invariants.py::check_documented_cli_exists` runs
`--help` for every module the manual names, with `PYTHONUTF8=0`.

---

## U7 — The manual promised eight commands the CLI refuses

**Severity:** P2 (a documented recovery path that does not exist is worse than
none, because it is consulted at the moment it is needed).

`MANUAL.md` named `acquire.py search/inspect/install/test`,
`mission.py meet/block`, `training.py capture/rollback` and
`proof.py refresh`. The library functions existed; the CLI had never been
given them, and `proof.py` takes `--refresh` as a flag.

**Fixed by** adding seven subcommands that genuinely belong on a terminal
(`acquire search/inspect/install/test`, `mission meet/block/close`,
`training rollback`), and correcting the two manual entries that were simply
wrong (`training capture` is done by the loop, not by hand; `proof --refresh`
is a flag). Adding the commands also surfaced a smaller defect: three of
`acquire.py`'s existing branches caught `Refused` and three did not, so half
its commands refused with a sentence and half with a traceback — the module's
own CLI failing the standard the module enforces. There is now one refusal
path for the whole CLI.

**Test:** `tests/test_invariants.py::check_documented_cli_exists` parses every
`` `python <mod>.py <sub>` `` in the manual — including bracketed optional
subcommands, which the first version of the check skipped and which is exactly
how `proof.py [refresh]` slipped past — and requires argparse to accept each.

---

## U8 — Two test files shared one sandbox directory

**Severity:** P2 (an intermittent red suite that points at the wrong test).

`test_guardrails.py` and `test_secrets.py` both called
`make_sandbox("secrets")`, so they shared one directory under the suite's temp
root. Each passed alone. In the suite the second to run raced the first's
leftover directory and died with `FileExistsError` — and only once the suite
had grown long enough to shift the timing.

**Fixed by** renaming one, and by asserting the property rather than the
incident.

**Test:** `tests/test_invariants.py::check_sandbox_names_are_unique` parses
every test file with `ast` (not a regex — this very docstring names the call,
and a checker that cannot tell code from prose reports itself) and requires
each of the 137 sandbox names to be claimed by exactly one file.

---

## U9 — The panel scrolled sideways on a phone, and two tables had no scroll container

**Severity:** P3 (a phone is where §14 says supervision happens, and sideways
scrolling makes a status page unusable there).

Driven at 375 px, two pre-existing layout defects appeared:

1. **A CSS grid item refuses to shrink below its widest child.** `.wswrap`
   collapses to one column on a phone, but the column kept `min-width:auto`,
   so the Performance tab's wide table pushed the whole document sideways by
   81 px. The table's own `.tablewrap` could not help: the thing that would
   not narrow was the *column*, not the table.
2. **Two tables had no scroll container at all** — the harness manifest's
   budgets table, and `taskTable()`, which two call sites wrapped and the
   helper itself did not.

**Fixed by** `.wswrap>*,.mindwrap>*{min-width:0}`, a `.tablewrap` on the
budgets table, and moving the wrapper *into* `taskTable()` so it is correct
wherever it is dropped rather than only where a caller remembered — the same
gateway argument as U1, applied to markup.

**Test:** `tests/test_ux.py::check_mobile_layout` asserts the shrink rule, the
bottom-bar rules, the 40 px target rule, and that **every** `<table>` in the
page has a scroll container within 220 characters before it. That last check
is what found the two bare tables; it was written for the phone and caught a
defect on every screen size.

---

## U10 — `org.check` was called by nothing but `org.py` and its own test

**Severity:** P1 (a stated invariant does not hold, and the control it names
is an authorization control).

`org.py`'s own docstring says:

> `check()` is the single question every mutating path asks: may THIS user do
> THIS thing to THIS object?

**Established by grep, in one line:**

```
$ grep -rn "org.check" --include=*.py . | grep -v tests/
./org.py:...        # its own definition
```

Nothing else called it. Not `ui.py` — which is the *main* mutating path, with
17 POST routes, a PUT and a DELETE. The reason is structural rather than an
oversight: the panel authenticated with **one shared token**, so it had no way
to know who was calling, and a permission check needs a subject.

The consequence is not that anything was exploitable on a solo install — with
no organization `org.check` returns True by design, which is correct. It is
that **creating an organization did almost nothing**. Roles were enforced on
the command line and recorded in an audit trail whose author came from a
request field, so anyone with the panel token had every permission regardless
of the role they had been given, and could attribute their actions to somebody
else by typing their address.

This is the audits' own central pattern, in the one place it is most
expensive: *a control defends the path its author was thinking about, and does
not know about the other path.*

**Fixed by**

1. **Personal bearer tokens** (`org.issue_token` / `org.user_for_token`).
   The value is returned once and never stored — only its SHA-256 — and the
   comparison is constant-time, because the alternative is a timing oracle
   over a credential and "nobody would bother locally" is how that argument
   always starts.
2. **`_authed` resolves the token to a member** before every request, and
   `_may_write` looks up the permission in a **declared table**. A route with
   no entry falls through to `create_agent`, so a route added tomorrow is
   refused for a viewer rather than waved through.
3. **The audit records the resolved actor**, never one the body claims.
4. **`Denied` maps to 403**, not 500: an authorisation refusal is the system
   working, and reporting it as a server fault sends the reader to the wrong
   place.

**And the trap that would have swallowed the fix:** with an organization but
**no** panel token, `_authed` returns early because there is nothing to check,
so every caller resolves to the owner and the whole model governs nothing. A
fleet that belongs to an organization now auto-enables a token on start-up —
for the same reason an exposed one does — and says why.

**Still true, and stated as a limit:** whoever holds the token the panel was
*started* with resolves to the owner. That is not a hole so much as an
identity — the master token already implies control of the process — and
`REFERENCE.md` §20 now says so.

**Also fixed in passing:** `except KeyError -> 404 "unknown expert"` caught a
**missing request field** as well, so a POST that forgot `role` answered
"unknown expert" about an expert that plainly existed. `NoSuchExpert` is now a
distinct type, and a missing field is a 400 that names the field.

**Test:** `tests/test_rbac.py` — solo install unaffected; tokens personal and
unstored; a viewer refused all 8 write routes with the reason; the
operator/builder boundaries in both directions; **every** POST route in
`ui.py` gated (by table or by a strict default); and a request claiming a
different author recorded against the token's real owner.

---

## U11 — two metrics that measured something other than their name

**Severity:** P2 (a number that is wrong is worse than a number that is
missing, because it is acted on).

Both were introduced by this pass, in `metrics.py`, and both were caught by
running the module against real data rather than by reading it — which is the
same lesson as `U1`–`U10`, applied to code written an hour earlier.

**1. Two rates that could sum past 100%.** Verified success came from
`memory.competence`, which counts TASKS. False success came from
`memory.failure_summary`, which counts EVENTS. A task retried twice therefore
filed three false-success records against one competence attempt, and the
demo fleet reported *67% verified success* alongside *100% false success*.

The module's own docstring says "nothing is computed twice… two counts of the
same thing eventually disagree". It was doing exactly that on its second and
third lines. Both rates now come from one pass over `state.json`: verified
success over gated tasks, false success over finish-*claims* — two honest
units, derived together, neither able to exceed one.

**2. An autonomy ratio that was really a success rate.** It read the task
record for a marker of having been blocked. There is none: a task that
stopped, was answered by a person and then finished is byte-for-byte
indistinguishable from one that never stopped. So the metric counted
`status == "done"` and reported it as autonomy.

It now reads the log, where `approval_required` and `task_unblocked` are
written at the moment a person was actually needed.

**Test:** `tests/test_metrics.py` — the reliability check asserts that neither
numerator can exceed its denominator and that both come from `state.json`;
the autonomy check **appends one `approval_required` event and requires the
number to move**, which is the only way to prove a metric is reading anything
at all.

**Why this is in the audit record at all.** Because the alternative is a
changelog that lists ten defects found in somebody else's code and none in the
code written to fix them. Both of these shipped as green tests for the length
of an afternoon.

---

# Fourth pass — closing the paths nothing had ever executed (2026-08-23)

Before handing this build a real API key, the honest question is: *which code
will run for the first time when that key arrives?* Four answers, and each was
closed by making it runnable offline.

| Path | Lines that had never executed | Now |
|---|---|---|
| The live provider HTTP client | ~90 | `tests/fake_provider.py` + `test_live_provider.py` |
| `loop.py check`, the only live probe | ~30 | `test_first_day.py` |
| The docker sandbox | ~40 | `test_docker_live.py` — real containers |
| The E2B / Daytona REST client | ~35 | `test_hosted_sandbox.py` |

Two real defects fell out.

---

## U12 — a timed-out command left its container running

**Severity:** P1 for a 24/7 fleet (unbounded resource leak), found the first
time the docker backend was ever executed.

`_docker` ran `subprocess.run(argv, timeout=…)`. That timeout kills the
**docker client**, and `docker run` is only a client — the container keeps
running on the daemon.

**Observed:** a `sleep 60` under a 6-second ceiling was still up half a minute
later, holding its 1 GB memory allowance and its 256 pids:

```
$ docker ps
9db1c33f6a96  python:3.12-slim  Up 24 seconds  "sh -lc 'sleep 60'"
```

On a fleet running 24/7 every timed-out command leaks one, forever, until the
machine stops. And the backend this affects is the one the documentation
recommends for untrusted work.

**Fixed by** naming every container (`--name fleet-<uuid>`) and, on
`TimeoutExpired`, `docker rm -f`-ing it before the exception propagates.
`rm -f` rather than `stop`, because the command has already blown its deadline
and a graceful shutdown period would only extend the overrun.

**Test:** `test_docker_live.py::check_a_timeout_kills_the_container` snapshots
`docker ps` before and after and fails on any container the run added.

---

## U13 — a soak check that measured zero and called it bounded

**Severity:** P3, and it was in the test written an hour earlier.

The endurance check for context growth read `total_chars` from the compile
manifest. The manifest has no such key — it carries `total_tokens`, a
`system.tokens` block and per-source `used_tokens`. Every window therefore
measured 0, early and late, and `0 <= 0 * 2.5` passed:

```
[context] across 42 compiled windows the median size went 0 -> 0 characters
```

A check whose numbers are all zero passes whatever the system does. Fixed to
read the keys the manifest actually has, **and** to assert `early > 0` first —
so the same mistake fails loudly instead of passing quietly. The real figure
is flat at 1083 tokens across 42 windows, which is the property that was
being claimed.

This is the third time in two passes that a green check turned out to be
reading a field that does not exist (`U2` selfmodel, `U3` the file tree,
now this). It is worth naming as a pattern: **when a check reads a key from
another subsystem's data, assert the value is non-trivial before asserting
anything about it.**

---

## U14 — a garbled provider response killed the task and never tried the fallback

**Severity:** P1 for anyone with a real key. Found by tightening an assertion
in my own test that could not fail.

`test_live_provider.py` contained this:

```python
except Exception as e:
    assert type(e).__name__ != "NameError", e
```

That is true of essentially every exception. Replacing it with the assertion
that actually matters — *the message must name the provider* — turned the
test red and exposed the defect underneath.

**The defect.** When a provider returns HTTP 200 with a body that is not a
chat completion, `call_model` did:

```python
resp = json.loads(r.read().decode("utf-8"))
msg = resp["choices"][0]["message"]
```

`JSONDecodeError` and `KeyError` are not in the `except` clauses of the retry
ladder (`HTTPError`, `URLError`, `TimeoutError`, `OSError`), so they escaped
`call_model` entirely. Consequences, in order of cost:

1. **The fallback provider was never tried** — the one situation a fallback
   exists for.
2. The retry ladder was skipped, though a garbled body is usually transient:
   a proxy's HTML error page, a truncated stream, a gateway answering 200
   with `{"error": ...}`.
3. The operator got `Expecting value: line 1 column 1 (char 0)` with **no
   provider named**. With four providers configured, that is unactionable.

This is the shape a real provider produces during an incident, so it would
have surfaced on a bad afternoon rather than in a test.

**Fixed by** catching `(ValueError, KeyError, IndexError, TypeError)` around
the parse inside the ladder, treating it as the transient failure it is —
retry, then fail over — and logging `provider_malformed` with the provider,
the model, the exception and the first 200 bytes of the body.

**Test:** `test_live_provider.py::check_a_malformed_response_is_not_a_crash`
now stands up two servers, makes the first return garbage five times, and
requires the call to come back from the **fallback**, with the full ladder
attempted and `provider_malformed` logged against the provider that sent it.

---

## Vacuous assertions — five checks that could not fail

Not a defect in the platform; a defect in its evidence, which is worse in a
different way. A sweep for tautologies found five assertions that were always
true:

| File | The assertion | Why it could not fail |
|---|---|---|
| `test_docker_live.py` | `assert rc != 0 or "fork" in … or True` | `or True` |
| `test_hosted_sandbox.py` | `assert … or True` | `or True` |
| `test_ux.py` | `assert "cannot be edited" not in body or True` | `or True` |
| `test_harness.py` | `assert "secret" not in json.dumps(r).lower() or True` | `or True` — **pre-existing**; the readiness report could have carried any secret |
| `test_live_provider.py` | `assert type(e).__name__ != "NameError"` | true of nearly every exception |

Four were written during this build. All five now assert something that can
fail, and each replacement is stronger than a literal fix of the original:

- the docker pid ceiling is asked to be **exceeded** and the process count
  measured, rather than merely found on the argv;
- the hosted backend's two availability messages must **differ**, and the
  one with a key present may not contain "reachable", "verified" or
  "working" — a key present is not a service contacted;
- the proof routes the page POSTs to are **enumerated** and must be a subset
  of `{/api/proof/refresh}`;
- the readiness payload is scanned for anything key-shaped at all, under two
  different environments;
- the malformed-body branch must name the provider and attempt the ladder —
  which is what found `U14`.

---

# Fifth pass — what the first CI run on another computer found (2026-08-23)

Every finding above was made on one machine: Windows 11, Python 3.14, one
Docker Desktop daemon. The suite had been green there twice consecutively,
and the honest-limits list said exactly that. Then the repository was
published and GitHub Actions ran the same suite on runners this code had
never touched — Ubuntu and Windows × Python 3.11, 3.12, 3.13.

**Four of the six jobs failed.** Not one failure was a CI artefact.

| Job | Verdict |
|---|---|
| ubuntu-latest 3.11 | **fail** — U15, U16, U17 |
| ubuntu-latest 3.12 | **fail** — U15, U16, U17 |
| ubuntu-latest 3.13 | **fail** — U16, U17 |
| windows-latest 3.11 | pass |
| windows-latest 3.12 | **fail** — U15 |
| windows-latest 3.13 | pass |

That U15 struck Windows 3.12 while 3.11 and 3.13 passed is the tell: it is
not a version problem, it is a **race**, and a loaded shared runner opens
windows an idle laptop never does.

Each defect was then reproduced **locally**, in a Linux container on the
development machine, so the diagnosis comes from a debugger rather than from
a log, and every fix was verified before it was pushed. Running the suite in
that container also found a sixth defect (U19) that CI itself got lucky on.

The single most useful thing this project has done for its own reliability
was to run its tests on a computer it does not own.

---

## U15 — a task was taken from a live loop and executed twice

**Severity:** P1. The most serious defect found in the platform to date.

**How it surfaced.** `test_audit.py` asserted `len(tasks) == len(ids)` and
reported `lost tasks: -1`. Not lost — **one too many**. Reproduced locally at
`docker run --cpus 1`: 3 failures in 12 runs, from code that had never failed
once on an idle machine.

The state at the moment of failure says the whole thing:

```
tasks: 7                       (6 were queued)
  d2a2fbb9baad att=1 done steps=2 task_start x1 | job 0
  2ce897349d87 att=2 done steps=2 task_start x1 | RETRY 2 of 3: the previous
                                                   attempt (d2a2fbb9baad) failed
  step_crash = 1     task_end = 14      <- fourteen endings for seven tasks
```

**The defect.** `claim_task` is a correct cross-process mutex and every
queued task goes through it. `next_task` did this:

```python
for t in state["tasks"]:
    if t["status"] == "running":
        return t          # crash recovery
```

A task marked `running` means one of two opposite things: *a loop is working
on it right now*, or *a loop died holding it*. Nothing recorded which. The
running branch of the run loop skips `claim_task` by design — a resumed task
is already claimed — so a second loop picked up its live sibling's task and
ran it concurrently. Both wrote steps; one crashed into the other; the crash
marked the shared task `failed`; `_maybe_retry` queued a **retry of work that
had in fact succeeded**; and the surviving loop then wrote `done` over the
failure. The ledger ends up self-consistent and wrong.

This is the same shape as the finding that motivated the Five Authorities:
*a control defends the path its author was thinking about and does not know
about the other paths.* The mutex was written for claiming. Resuming is also
claiming, and nobody told the mutex.

**Why the existing test could not see it.** The audit's headline assertion:

```python
claims = log.count(f'"task_start", "task": "{t["id"]}"')
assert claims == 1, "must be exactly once"
```

`task_start` is logged in the **queued** branch only. A stolen resume emits
no start line, so the check written to prove exactly-once execution was
structurally blind to the only path that ever broke it — it passed on every
failing run. The suite noticed at all only through an incidental count.

**Fixed by** recording ownership on the task and making resumption
conditional:

- every loop process mints a `runner_id` for its lifetime;
- `claim_task` stamps `{id, pid, host, ts}` on the task;
- `commit_task` refreshes `ts` once per step, so a long task never looks
  abandoned while it is working;
- `_may_resume` decides. **On this host liveness is the whole answer** — an
  alive owner is never overtaken (a loop parked in a twenty-minute provider
  call has a stale timestamp and is perfectly healthy), and a dead one is
  recovered immediately. For another host, whose pid numbers mean nothing
  here, a lease (`runner_lease_seconds`, default 900) is the only thing that
  can free the task;
- `adopt_task` re-checks all of it **under the state mutex**, so two loops
  cannot both revive one corpse;
- and liveness never calls `os.kill` on Windows, where CPython implements it
  with `TerminateProcess`: the POSIX idiom for *is this process alive* would
  have killed the sibling it was asking about.

**Tests.** `test_audit.py` now asserts that no task exists which nobody
queued, that each task has exactly one `task_end` (two executions leave two),
and that no loop crashed inside a step. Because the race only opens under
load, the ownership rule is also checked **deterministically**, every branch
of it: a live sibling's task is refused by the predicate, by `adopt_task` and
by the scheduler; a dead owner, an unstamped legacy task and an expired
foreign lease all remain recoverable; and a live owner with a deliberately
ancient timestamp is still not overtaken. Crash recovery — the behaviour the
unconditional resume existed for — is asserted to have survived the fix.

**Mutation:** `loop: a running task is stolen from a live sibling` restores
the unconditional resume; `test_audit.py` fails in 4 s.

**Verified:** 30 consecutive passes at `--cpus 1` on Linux, where the unfixed
code failed 3 times in 12. At that rate, 30 clean runs is p ≈ 0.02 %.

**Residual, stated rather than glossed.** Two cases the fix answers
conservatively rather than exactly:

- *Pid reuse.* If a loop dies and the operating system hands its pid to an
  unrelated process, the dead owner looks alive and its task waits for the
  lease instead of recovering at once. That is slower recovery, never a
  double run — the failure mode points the safe way. Distinguishing the two
  needs a process start-time, which has no stdlib route that works on both
  platforms, and the cost of getting it wrong is the defect this whole entry
  is about.
- *Two `Agent` objects inside one process.* They share a pid and hold
  different runner ids, so neither will take the other's task. Correct, and
  the reason `_may_resume` treats "same host" as a liveness question rather
  than an identity one.

---

## U16 — the sandbox handed back a workspace the agent could not write to

**Severity:** P1 on Linux, which is where a 24/7 fleet actually runs.

**How it surfaced.** All three Ubuntu jobs:
`PermissionError: [Errno 13] Permission denied: '/tmp/agent-suite/docker-live/out/from_host.txt'`

**The defect.** `docker run` was called with no `--user`, so the command ran
as **root inside the container**. On Linux a bind mount is a real host
directory, so `mkdir -p out` created `out/` owned by `root:root` on the host.
The agent — an ordinary user — could then no longer write into, rewrite or
clean its own workspace. The gate, `verify.py`, `designcheck.py`, `backup.py`
and `package.py` all run host-side as that user, on those files.

Docker Desktop remaps ownership on Windows, so this was invisible on the
machine it was written on. It was live in **the backend the manual recommends
for untrusted work**, on the platform people actually deploy on.

**Fixed by** passing `--user <uid>:<gid>` on POSIX, plus `HOME=/tmp` so a uid
with no passwd entry gets a writable, disposable home instead of scattering
dotfiles into the expert root. This also *improves* isolation: container root
writing through a bind mount is a way to touch host files as root.

**Test:** the mount check now asserts the created directory is owned by the
agent's own uid, then deletes and rewrites the file the container produced —
reading it back was never the property that mattered. The argv check asserts
`--user` is present and correct on POSIX.

**Mutation:** `docker: the container runs as root in the mount`.

---

## U17 — a secret created world-readable, caught by the platform's own preflight

**Severity:** P2, and the finding is a credit to the system rather than a
hole in it.

**How it surfaced.** All three Ubuntu jobs: `preflight.py` exited 2 with
`ui-token.txt is readable by other users (mode 0o644)`. That check is gated
on `os.name != "nt"`, so it had **never once executed** — every prior run in
this project's life was on Windows.

**What it caught.** The offending write was in `test_preflight.py` itself: a
bare `open(..., "w")` under the default umask. The platform's own writer
(`ui.py`) chmodded correctly. So preflight was right, the platform was right,
and the test manufactured the exact finding it then asserted was absent.

**The real gap underneath.** `credentials.py` — the Credential Authority —
could *recognise* a secret (`is_secret`, `looks_like_key`) but had no way to
*create* one. Three modules each rolled their own `open` + `chmod`, and a
fourth writer forgot. That is the scattered-control pattern the Five
Authorities exist to eliminate, still present inside the authority that
exists to eliminate it. Worse: `federation.py` wrote its fleet secret through
`atomic_write_json` and chmodded afterwards — but `os.replace` carries the
**temp file's** mode onto the destination, so that chmod was closing a door
the file had already walked through.

**Fixed by** adding `credentials.write_secret(path, text)` as the one way to
create a credential file. The temp file is created `0600` — the mode is set
as the file is created, not corrected afterwards, so the secret is never
world-readable on disk, not even for the instant between write and chmod —
and the replacement is atomic, so a crash mid-write leaves the previous
credential intact rather than a truncated one. `bootstrap.py`, `ui.py`,
`federation.py` and the test now all go through it.

**Mutation:** `credentials: a secret written under the umask`. Declared
POSIX-only and **skipped out loud** on Windows, where modes are not the
mechanism: calling it MISSED there would be a false alarm, and calling it
CAUGHT would be a lie.

---

## U18 — an evidence sentence that was false wherever it ran

**Severity:** P3 as a bug, P1 as a matter of principle.

`test_docker_live.py` printed, unconditionally:

> the command ran inside a Debian container on python 3.12.14, **on a Windows
> host** — this is not the host backend wearing a different name

On Ubuntu that sentence is simply untrue, and these sentences are quoted
**verbatim** into `EVIDENCE.md`, which is published. A platform whose whole
thesis is *evidence, not assertion* had an assertion hard-coded into its
evidence.

The logic was wrong too, not only the prose: a Debian `os-release` proves
isolation on a Windows laptop and proves **nothing** on a Debian or Ubuntu
host, where the host would answer the same way.

The same file's containment check probed `ls /c`, described as "the Windows
C: drive". On Linux that asks whether a path nobody has is absent — a check
that cannot fail, dressed as containment. It is the sixth vacuous assertion
found in this codebase, and the second one written by me.

**Fixed by** proving isolation with a fact that holds on every host — the
container's hostname is its own and is not this machine's — probing a
directory that really exists on the host it is running on, and reporting the
real platform. The host's name and absolute paths are deliberately **not**
printed: an evidence file that gets published should not carry the operator's
machine name or username.

---

## U19 — new material silently un-scanned on the filesystem containers use

**Severity:** P2. Found by the local Linux reproduction, **not** by CI —
which passed this test by luck.

**How it surfaced.** Running the full suite in a Linux container:
`test_conflicts.py` failed on `assert conflicts.refresh(sb, "design") is True,
"new material must rescan"`. It failed identically on the pristine published
commit, so it was pre-existing rather than introduced by the fixes above.

**The defect.** `conflicts.refresh` decided whether material had changed by
comparing two file timestamps:

```python
stamp  = os.path.getmtime(conflicts.json)     # the ledger
newest = max(mtime of every notes.md)
if stamp and newest <= stamp + max_age_s:
    return False                              # nothing changed
```

That is a race dressed as a cache. Measured inside the container:

```
200 files written back to back -> 9 distinct timestamps
two consecutive writes         -> identical st_mtime_ns
```

On **overlayfs** the clock behind file timestamps is cached rather than read
per write. The ledger and the notes written immediately after it look
simultaneous, `newest <= stamp` is true, and new material is silently
un-scanned — the one outcome the function's own docstring promised could not
happen: *"New material must never be silently un-scanned."*

Overlayfs is what every container runs on, including this project's own
`Dockerfile`, so the defect was live in the containerised deployment. On NTFS
the two writes usually land on different ticks, which is why a year of runs
on one Windows machine never showed it.

**Fixed by** recording **what** was scanned instead of **when**: `write()`
stores a SHA-256 of the material (every `notes.md`, path and bytes) in
`conflicts-scan.json`, and `refresh()` rescans when that digest differs. A
hash cannot be fooled by a clock. `max_age_s` is kept, now as an explicit
debounce.

**What it costs**, measured rather than asserted: 29 ms on a 40-lesson,
844 KB course — over four times larger than the 50,000-token context budget
that would have to load it — against roughly 1 ms for the two timestamps.
`refresh()` runs once per context compile, next to a model call measured in
seconds, so it is under a percent of a step. The first draft of this entry
said "microseconds", which is the kind of unchecked number this document
exists to stop; the figure above came from running it.

**The general lesson**, worth more than the fix: *deriving "did it change?"
from a comparison between two different files' timestamps is unsound.* The
codebase is now checked for that pattern by an invariant test.

---

## U20 — the fleet's shared lessons stopped reaching every agent's context

**Severity:** P2. The same unsound test as U19, in a second module, found by
enumerating the pattern rather than by noticing it twice.

`commons.digest()` builds the block of hard-won fleet lessons that is injected
into **every agent's context window**. Before injecting it, it refreshed the
curated view:

```python
led = os.path.getmtime(os.path.join(d, "lessons.md"))
cur = os.path.getmtime(os.path.join(d, CURATED))
if led > cur:
    curate(home)
```

`lessons.md` is the append-only ledger; `lessons.curated.md` is the merged
view derived from it. When a new lesson is appended and the curated view is
rewritten in the same filesystem tick — which on overlayfs is anything within
about a tenth of a second — the two timestamps come out **equal**, `led > cur`
is false, and the view is never rebuilt. The lesson exists on disk and reaches
no agent. Nothing errors; the block is simply one lesson short, forever.

This is worse than U19 in reach and better in luck: worse because the commons
digest is injected into every context of every expert in the fleet rather than
one course's conflict scan, and better because a later unrelated edit to
`lessons.md` eventually lands on a different tick and repairs it silently.
"Eventually self-healing by accident" is not a property to rely on for the
mechanism whose entire job is that a lesson paid for once is not paid for
twice.

**Demonstrated on the published code**, not inferred. Forcing the two files to
share an mtime — exactly what the container produces naturally:

```
PRISTINE CODE — mtimes identical: True
PRISTINE CODE — new lesson reaches the injected digest: False
```

and after the fix, on the same input:

```
mtimes identical: True
stale detected  : True
new lesson reaches the injected digest: True
```

**Fixed by** `_curation_is_stale()`, which compares a SHA-256 of `lessons.md`
against the digest recorded in `lessons.curated.md.stamp` when the view was
built. The curated view now knows *what* it was built from instead of *when*.

**Found by** writing the U19 fix and then asking whether the same mistake
existed elsewhere, which produced the AST invariant now in
`test_invariants.py`. It named `commons.py:284` and `conflicts.py:322` and
nothing else. Neither module's author would have looked at the other; the
enumeration did.

---

## U21 — a mutation that certified a test as meaningful when it was not

**Severity:** P2 as a defect, and the most instructive finding in this pass.
It is a failure of the thing built to detect failures.

**How it surfaced.** With U15–U20 fixed, CI went from four failing jobs to
one, and the survivor failed at a different step: not the acceptance suite,
which was green everywhere, but **Mutation check** on ubuntu-3.12.

```
MISSED  docker: credentials passed through
13 mutations: 12 caught, 1 missed
```

A `MISSED` row means the feature was removed and the test passed anyway. This
row had been reported `CAUGHT` on Windows in every previous run.

**Why it differed by platform — the experiment.** Applying the mutation
locally on Windows and reading the failure rather than the verdict:

```
File "tests/test_docker_live.py", line 90, in check_it_runs_somewhere_else
AssertionError: (127, '', 'docker: Error response from daemon: ...
  exec: "sh": executable file not found in $PATH')
```

The mutation forwards the **host's entire environment** into the container.
On Windows that includes `PATH=C:\...;C:\...`, which inside a Linux container
means `sh` cannot be found and the container never boots. The test died at
its FIRST check. The credential assertions at line 229 never executed.

So the green `CAUGHT` row was not the credential scrub being noticed. It was
a container failing to start, for a reason with nothing to do with the
property the row claimed to certify. On Linux, where the host `PATH` is a
valid Linux path, the container boots, the credential checks run — and pass.
Linux was telling the truth.

**And the mutation was aimed at the wrong layer anyway.** `sandbox.run` does:

```python
env, dropped = scrub_env({**os.environ, **(env or {})}, cfg, cmd)   # line 270
```

The credentials are gone **before** `_docker` is reached. The mutation broke
`_agent_env`, the SECOND of two independent filters, so the credential
property survived on its own. Against that property the mutation is an
equivalent mutant — a change with no observable effect — and reporting it as
MISSED overstates the problem as much as CAUGHT understated it.

But `_agent_env` does defend a real and narrower promise that nothing
asserted: **only agent-scoped variables enter the container at all.** That is
strictly stronger than "no credentials do", because it stops a credential
whose *name* the scrub failed to recognise — the residual this codebase has
already admitted it cannot close by pattern-matching alone.

**Fixed by** three changes, none of which is "delete the row":

1. The docker test now asserts the second filter. `HARMLESS_SETTING` was
   already planted in the test's environment and never checked; it is exactly
   the right probe, being a variable no scrub would call secret which must
   still not travel. The test additionally enumerates every variable the
   container received and requires each to be `AGENT_*`, `PYTHONUTF8`, or one
   of the image's own.
2. The mutation is renamed to what it actually breaks — *every host variable
   forwarded into the container* — and declared **POSIX-only**, because on
   Windows any mutation that forwards the host environment kills the
   container before an assertion can run, and a row that cannot be reached is
   not a row that passed.
3. A new mutation attacks the control that really defends credentials:
   `scrub_env` is removed from `run()`, so keys reach every backend. Paired
   with `test_secrets.py`, which tests the scrub directly and end to end.
   **CAUGHT in 1 s, on both platforms.**

**The lesson, which is the reason this entry is long.** Mutation testing was
adopted here to answer "would this test fail if the feature were removed?"
This row answered *yes* for four releases while the honest answer was *the
question was never asked* — the test never got far enough to answer. A
mutation harness reports two things, and only one of them was being checked:
whether the test failed, and **whether it failed for the reason claimed.**
The second is now part of the procedure: when a mutation flips a verdict
between platforms, read the failure, not the verdict.

Five of the twenty-one numbered defects are now defects in this project's
own verification machinery rather than in the platform it verifies: U8, U13,
U17, U18 and this one.

---

## U22 — a settle window of zero behaved as a window of forever

**Severity:** P3 in the default configuration, P1 for anyone who sets
`inbox_settle_seconds = 0`. Found by the third CI run, on the one job that
had passed the second.

**How it surfaced.** With U21 fixed, five of six jobs were green and
windows-3.12 failed — the job that had passed the run before. A bare
`AssertionError` with no message, at `test_url.py:99`:

```python
n = ingest.scan_inbox(sb)
assert n == 1
```

The platform's own log line, twenty lines further down, said everything:

```
reading list.urls: still settling (modified <0s ago), next scan
```

**The defect.** `scan_inbox` skips a file that is still being copied in:

```python
if time.time() - os.path.getmtime(src) < settle:
    continue
```

With `settle = 0` that guard should be inert — nothing is less than zero. It
is inert only while the age is non-negative, and the age is **not** always
non-negative. The filesystem's timestamp and `time.time()` do not come from
the same clock, and on a virtualised host they disagree by milliseconds. A
file written a moment ago can carry an mtime a hair *ahead* of the wall
clock, the age goes negative, and `age < 0` is true. A setting documented as
"no settling required" then means "never ingest this file" until something
touches it again.

**Why one machine could not find it.** Writing 3000 files on the development
host and stat'ing each immediately produced **zero** negative ages, worst
skew 0.000 ms. The defect is not rare on the right hardware and absent on
the wrong hardware — it is invisible on the wrong hardware. Three CI runs
were needed to see it once, because it needs a runner whose clocks disagree.

**Impact in production.** The shipped default is `inbox_settle_seconds = 10`,
where a negative age costs one scan cycle and nothing else. The operator who
reads the setting as "off" and sets it to `0` gets a `inbox/` that silently
stops working for exactly the files that arrive when the clocks disagree.
Silence is the whole problem: no error, no warning, and a file sitting in a
watched directory forever.

**Fixed by** making zero mean zero:

```python
age = time.time() - os.path.getmtime(src)
if settle > 0 and age < settle:
```

The message now prints the real age and the window it needed, instead of
`modified <0s ago` — which was the log line that solved this, and would have
solved it faster had it said `-0.003s`.

**Test.** `test_url.py` does not wait for the skew, because waiting is what
does not work: it **forces** it with `os.utime(f, (time.time() + 5, ...))`,
asserts the mtime really is in the future, and requires `scan_inbox` to
ingest the file anyway at `settle = 0`. It then proves the fix did not simply
disable the feature — a 30-second window still holds a freshly written file
back, and releases it once the file is old enough.

**Mutation:** `inbox: a zero settle window can still hold a file back`
restores the original comparison; `test_url.py` fails in 1 s.

**Relation to U19 and U20.** Same family — a decision derived from a file
timestamp — and specifically the case the AST invariant *permits*. That
invariant bans comparing two files' timestamps and allows comparing one
against `time.time()`, on the grounds that an age is sound. An age is sound;
what is not sound is assuming it cannot be negative. The invariant's
docstring now says so, because an allowance whose edge nobody wrote down is
the next defect waiting.

**A note on the fix to `tests/common.py` that came with it.** Writing the
regression test needed `agent_setting(sb, "inbox_settle_seconds = 30")` on a
key the sandbox already defines, which inserted a *second* copy and made
tomllib refuse the file outright. The helper's docstring already explained
that it exists to avoid a silent no-op; this was the next trap along the same
path, failing in the loader rather than at the call site. It now replaces an
existing key in place and inserts only a genuinely new one.
