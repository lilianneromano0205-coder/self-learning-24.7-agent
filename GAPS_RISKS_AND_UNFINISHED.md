# Gaps, Risks and Unfinished Work

Findings from the forensic audit, ranked by consequence. **Nothing here has
been fixed** — this pass was read-only by instruction. Each entry states what
is wrong, how I established it, what it costs, and the options, so the decision
stays with the owner.

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
