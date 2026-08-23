# Full Build Forensic Report — Expert Fleet

A read-only forensic examination of the entire repository. Nothing in the
product was modified to produce this document. Every claim below carries an
evidence label; claims I could not establish are marked as such rather than
smoothed over.

**Evidence labels used throughout**

| Label | Meaning |
|---|---|
| `[RUN]` | I executed something and observed the output in this audit |
| `[CODE]` | I read the source line(s) and the claim follows from them directly |
| `[REPRO]` | I built an isolated reproduction and observed the behaviour |
| `[NEG]` | I hypothesised a defect, tested it, and it did **not** reproduce |
| `[INFER]` | Reasoned from code, not directly observed at runtime |
| `[DOC]` | Asserted by documentation or a docstring only — not verified by me |
| `[UNVERIFIED]` | Stated by the build; I had no way to confirm it here |

---

## 1. Build identity

| Property | Value | Evidence |
|---|---|---|
| Root | `C:/Users/redab/OneDrive/Bureau/self learning 24.7 agent/agent` | `[RUN]` |
| Version control | **None.** `git rev-parse` fails; no `.git` directory | `[RUN]` |
| Python used for audit | 3.14.0 | `[RUN]` |
| Platform | Windows-11-10.0.26200 | `[RUN]` |
| Declared version constant | `harness.HARNESS_VERSION` | `[CODE]` |
| Files in tree | 282 | `[RUN]` |
| Tree size | ~2.5 MB | `[RUN]` |

**The absence of version control is the single most consequential fact about
this build.** There is no commit history, no blame, no tags, no diff against a
known-good state, and no way to recover an accidentally overwritten file. Audit
phases that depend on history (authorship, change sequencing, regression
archaeology) could not be performed at all — not partially, not approximately.
Every statement in this report about *how the build came to be* is therefore
inference from code structure and comments, never from history. `[RUN]`

### Size

| Category | Count | Lines |
|---|---|---|
| Top-level Python modules | 58 | 19,762 |
| Test files (`tests/test_*.py`) | 81 | 10,642 |
| Test helpers (`common.py`, `run_all.py`, …) | 4 | 403 |
| Front-end (`ui.html`) | 1 | 2,698 |
| Prompt files (`prompts/*.md`) | 10 | 142 |
| Test assertions | — | 1,466 |
| Test `[section]` evidence markers | — | 316 |

`[RUN]` — counted by AST inventory over the tree.

---

## 2. What I ran, and what happened

| Command | Result | Evidence |
|---|---|---|
| `python tests/run_all.py` (1st) | exit 0 — **ALL TESTS PASSED**, 259 s | `[RUN]` |
| `python tests/run_all.py` (2nd, consecutive) | exit 0 — **ALL TESTS PASSED**, 248 s | `[RUN]` |
| `python harness.py --check` | exit 0 | `[RUN]` |
| `python doctor.py` | healthy apart from absent provider keys | `[RUN]` |
| `python toolbox.py --check` | 4 READY (pdf_text, git, node, docker), 4 MISSING | `[RUN]` |
| AST inventory over 58 modules + 81 tests | no syntax errors, no orphan tests, no phantom registrations | `[RUN]` |
| Isolated reproduction of the gate-execution hypothesis | **defect reproduced** (§5.1) | `[REPRO]` |
| Isolated reproduction of the upload-traversal hypothesis | **did not reproduce** across 9 vectors (§6.1) | `[NEG]` |
| `python backup.py create` against a synthetic fixture | **defect reproduced** — credential file archived in plaintext (§5.4) | `[REPRO]` |
| Falsification attempt: are keys stored in `settings.toml`? | **no** — only `api_key_env` names; the credential model is sound (§6.4) | `[NEG]` |

**The most important qualifier on the green suite:** every model call in every
test is a scripted mock. `[CODE]` — `tests/common.py` writes a `type = "mock"`
provider into each sandbox's settings. A passing suite is evidence that *the
harness holds*, and is no evidence at all that any provider works, that any
prompt elicits the intended behaviour, or that costs are what the ledger says.
`python loop.py check` is the only live probe in the build, and it was not run
here because no provider keys are configured. `[RUN]`

This distinction is stated by the build itself in `EVIDENCE.md` and I confirm it
is accurate rather than decorative. `[CODE]`

---

## 3. Subsystem map

58 modules resolve into eight subsystems. Full per-module detail — SHA, imports,
reverse-imports, CLI surface, whether it writes state, executes commands, or
touches the network — is in `BUILD_MANIFEST.json`.

| Subsystem | Modules | Role |
|---|---|---|
| harness-loop | 9 | `loop`, `harness`, `policy`, `effects`, `locks`, `checkpoint`, `sandbox`, `context`, `memrouter` |
| memory | 12 | `memory`, `skills`, `commons`, `recall`, `gotchas`, `premise`, `sources`, `conflicts`, `standards`, `selfmodel`, `curriculum`, `cases` |
| control-plane | 13 | `ui`, `chief`, `doctor`, `bootstrap`, `preflight`, `backup`, `providers`, `toolbox`, `mcp`, `federation`, `trace`, `uicards`, `modelrouter` |
| governance | 11 | `variants`, `approvals`, `replay`, `benchmark`, `verify`, `citecheck`, `memcheck`, `designcheck`, `candidates`, `evidence`, `confidence` |
| work-systems | 6 | `goal`, `workflows`, `consult`, `prospective`, `routines`, `research` |
| fleet-lanes | 4 | `fleet`, `quick`, `templates`, `team` |
| ingestion | 1 | `ingest` |
| support | 2 | `demo`, `package` |

`loop.py` is the hub: 2,080 lines, imported by 22 other modules. `[RUN]` Nothing
else comes close. This is the build's central structural risk — §7.

13 modules are security-sensitive (they execute commands, hold secrets, accept
network input, or gate approval): `loop`, `policy`, `sandbox`, `mcp`,
`approvals`, `effects`, `ui`, `federation`, `backup`, `skills`, `preflight`,
`verify`, `locks`. `[CODE]`

### Dependency posture

The core and the **entire test suite** run on the Python standard library
alone. `[RUN]` Optional third-party packages (`pymupdf`/`fitz`, `docling`,
`markitdown`) and optional external binaries (`ffmpeg`, `pandoc`, `yt-dlp`,
`docker`, `node`) gate specific ingestion and sandbox paths; each is guarded by
a try/except that exits with an install hint rather than a traceback. `[CODE]`
This is a real and unusual property — I verified it by import analysis across
all 139 Python files, not by trusting the README. `[RUN]`

---

## 4. How the system actually executes

Traced end to end from `loop.py`.

```
task queued  →  claim_task()  →  atomic queued→running under _state_lock
             →  context.compile()  →  budgeted window + manifest on disk
             →  call_model()  →  route → attempts[] → backoff → failover
             →  tool dispatch  →  allowed_tools(role) gate
             →  finish_task  →  check_done()  →  gate verdict
             →  pass: commit    fail: _file_memory() → case + gotcha + confidence
```

**Claim atomicity.** `claim_task` performs the queued→running transition inside
`_state_lock`, an `O_EXCL` lockfile mutex. `[CODE]` `tests/test_lock.py`
exercises two tasks on one course serialising, both completing, no leftover
lock. `[RUN]` This is genuinely tested — but see §5.2 for the hole in the lock
primitive itself.

**Context compilation.** `context.compile` budgets each source (commons,
course, gotchas, premise, skills, handed files) against a per-source token
allowance, trims overflow with a pointer to read the rest, and writes a
manifest next to the transcript naming what was included and what was cut and
why. `[CODE]` This is the strongest observability decision in the build: the
window is an artefact you can read after the fact, not a black box.

**Prompt assembly.** `system_sources(role)` returns, in order:
`prompts/constitution.md` → `identity.md` → `prompts/_grounding.md` →
`prompts/<role>.md`, filtered by `os.path.isfile`. `[CODE]` A charter variant on
trial substitutes only the role file, only via the `AGENT_PROMPT_VARIANT`
environment variable, and only if the variant file exists — nothing on disk
changes until `variants.promote()` passes its gate. `[CODE]`

A missing prompt file is skipped silently at runtime (`except OSError: pass`),
but it is **not** undetected: `doctor.py` checks constitution + grounding + all
8 role prompts, and `harness.py` independently checks constitution and
grounding. `[CODE]` Detection is out-of-band (health ritual) rather than
fail-closed at call time. I record that as a design choice, not a defect.

Note: `settings.toml` declares 9 roles but there are 8 role prompt files — the
`default` role has no prompt of its own and therefore runs on constitution +
identity + grounding with no role section. `[CODE]` This appears intentional
(`default` is the generic fallback) but is nowhere stated.

**Data marking.** `_read_block` fences file content between
`<<<FILE-CONTENT>>>` markers, and the grounding prompt forbids following
directives found inside the fence. `[CODE]` I want to be precise about what
this is worth: **this is a prompt instruction, and prompt instructions are not
a security boundary.** It raises the cost of a naive injection embedded in an
ingested document. It does not prevent one. The build's own comment calls it
"spotlighting", which is the correct, modest term.

---

## 5. Confirmed defects

> **Second-pass note (deep line-by-line audit).** The findings numbered 5.1–5.8
> came from the first pass. The second pass read all 31 previously-unread
> modules plus `ui.html` line-by-line and added the findings in **§5.9–5.20**,
> including two **P0** issues that outrank everything from the first pass. The
> new headline: the first pass judged that *"prompt injection is not a security
> boundary but the mechanical controls hold."* The second pass found that the
> mechanical controls **do not hold** — the panel has no CSRF protection and a
> cross-origin web request achieves arbitrary command execution on the host.
> The recurring "secondary-path bypass" pattern is far more pervasive than three
> instances: it recurs in at least **nine** subsystems, catalogued in the new
> **Invariant Coverage Matrix (§12)**.

### 5.1 P1 — The verification gate executes model-authored shell outside every containment layer

**Reproduced.** `[REPRO]`

`loop.check_done` runs the definition-of-done check with `shell=True`. `[CODE]`
`verify.py:59` does the same for `CHECK:` commands. `[CODE]` Neither path
routes through `policy.py` (the command allow/deny layer) or `sandbox.py` (the
isolation and environment-scrubbing layer) — I grepped both files for any
policy or sandbox reference and found none. `[CODE]`

The commands are model-authored, not operator-authored:
`prompts/watcher.md` instructs the Watcher to write `CHECK:` commands into
`spec.md`, and `goal.py:170` solicits `CHECK:` lines from the planner. `[CODE]`

I built an isolated temp sandbox, planted a marker secret in the environment,
and ran both paths:

| Path | Saw the planted secret? |
|---|---|
| `check_done` (gate) | **yes** — `FAKE-KEY-VISIBLE` |
| `run_command` (normal tool path) | no — `ABSENT` |

No real credential was used; the marker was a synthetic value created for the
test. `[REPRO]`

**Consequence.** The one code path whose entire job is to *verify* the agent's
work is the path with the fewest controls on it. A model that can write a gate
command can run arbitrary shell with the full environment, including any
provider keys present. The normal tool path — the one everyone reasons about —
is correctly scrubbed, which makes this asymmetry easy to miss.

I am not proposing a fix here (this audit is read-only); the finding is
recorded in `GAPS_RISKS_AND_UNFINISHED.md` with the design options.

### 5.2 P1 — Lock release does not verify ownership

**Established by reading both implementations.** `[CODE]`

Two lock primitives exist and share the same shape:

- `locks.holding(path, timeout=10.0, stale=8.0)` — used by `approvals.py`,
  `effects.py`, `prospective.py`, `skills.py`
- `loop.Agent._state_lock(timeout=20)` — used for `state.json`

Both write `os.getpid()` into the lockfile. **Neither ever reads it back.**
`[CODE]` Both break a lock older than 8 seconds. Both release with an
unconditional `os.remove(lock)` in a `finally`.

The failure sequence:

1. Process A acquires the lock and stalls past 8 s (slow disk, OneDrive sync,
   antivirus scan, a suspended process, a VM pause).
2. Process B judges the lock stale, removes it, and creates its own.
   **A and B are now both inside the critical section.**
3. A finishes and unconditionally removes the lockfile — which is now **B's**.
4. Process C acquires immediately. B and C are now both inside.

The information needed to detect this is already written into the file and
simply never consulted. The comment explains why liveness probing was rejected
on Windows (`os.kill(pid, 0)` can terminate the target; PIDs are reused) — that
reasoning is sound, but it argues against *probing*, not against *checking that
the lockfile you are about to delete is still the one you created*.

**Why this matters more than it looks.** These are the locks protecting
`effects.jsonl` — the ledger whose stated purpose is preventing duplicated
external effects. The docstring records that this failure was once observed
live: two processes fired the same due intention twice. The mutex added to fix
that is itself not safe under a stalled holder.

**Additionally: `locks.py` has no test.** No test file imports it. `[RUN]`
`tests/test_lock.py`, despite the name, tests the *course* lock in `loop.py` —
a different mechanism. `[CODE]` The concurrency primitive guarding four mutating
ledgers is the least-tested security-sensitive module in the build.

### 5.3 P1 — Model routing cannot discover a cheaper model

**Established by tracing every call site.** `[CODE]`

`modelrouter.choose` rejects any candidate with fewer than `min_n` recorded
outcomes (default 5): *"only 0 run(s), 5 needed"*. `[CODE]` Outcomes are written
by exactly one call site — `loop.py:1751` — recording the pair that was
*actually used*. `[CODE]` `grep` for exploration, epsilon, shadow, or trial
logic in `modelrouter.py` returns nothing. `[RUN]`

Therefore a model accrues the runs it needs to become eligible **only** if it is
already reachable as the role's static `model`, its `fallback_model`, or its
`escalate_model`. A model listed *only* in `route_candidates` will never be
tried, never accrue a run, and is permanently rejected.

**Consequence.** The advertised capability — "choose the cheapest model that
clears the bar on this expert's own gated work" — is structurally inert over
exactly the set of models it was built to evaluate. It can confirm the default;
it cannot replace it. This is a cold-start lockout, not a bug in the scoring
maths, which is why the module's own test passes: `tests/test_modelrouter.py`
seeds the ledger directly via `modelrouter.record(...)`, bypassing the very
gap that makes the feature inert in production. `[CODE]`

**Attribution imprecision (P3, same module).** `record` stores
`role: task.get("role")` and the provider/model from `task["provider"]` /
`task["model"]`, set at `loop.py:1138-1139`. A task that makes calls under
several roles, or whose last step failed over to a different provider,
attributes its single outcome to the last pair used. `[CODE]`

### 5.4 P1 — Backups contain credential files in plaintext while reporting credentials excluded

**Reproduced against the product's own command.** `[REPRO]`

`backup.py:39` excludes secrets by exact basename: `agent.env`,
`ui-token.txt`, `identity.json`, `cookies.txt`, `bootstrap.json`. It never
reads `settings.toml`. `[CODE]`

But the product supports a second credential mechanism whose filename the
**operator** chooses. `settings.toml` documents it — *"Keys come from the
environment (api_key_env) or a file readable only by the agent user
(api_key_file)"* — and `loop.py:695` implements it, opening
`prov["api_key_file"]` to read the key. `[CODE]`

I built a fixture fleet home outside the repository, with synthetic values
only, and ran `python backup.py create --home <fixture> --out <fixture-out>`:

```
4 file(s), 0.0 MB, 1 expert(s): testexpert
2 credential file(s) deliberately excluded
```

| File | In the archive |
|---|---|
| `agent.env` | no — correctly excluded |
| `identity.json` | no — correctly excluded |
| **`keys/openai.key`** | **yes — plaintext, fully recoverable** |
| **`my-secret.txt`** | **yes — plaintext** |

`[REPRO]` The fixture was deleted after the test; nothing in the product tree
was touched.

The severity comes from the combination: a backup is the artefact most likely
to leave the machine (this tree already sits inside a OneDrive folder), the
command's own output implies credentials were handled, and the failure appears
only for operators who chose the option `settings.toml` presents as the more
locked-down one.

### 5.5 P2 — "Exactly-once" external effects is really at-least-once

`mcp.py:349-352` performs `result = s.call(...)` and *then* `effects.record(...)`.
`[CODE]` A crash, kill, or power loss in that window leaves the external effect
performed and unrecorded; the next run finds no ledger entry and repeats it.

The window is small and the design is otherwise sound (the ledger is keyed by
`(lineage, server, tool, sha256(args))`, which is the right key). But the
guarantee that can be honestly claimed is **at-least-once with a small
duplicate window**, not exactly-once. Documentation that says "exactly once"
overstates it.

### 5.6 P2 — Modules with no test coverage at all

By import analysis plus a subprocess-reference sweep: `[RUN]`

| Module | Coverage |
|---|---|
| `bootstrap.py` | covered via subprocess (`test_bootstrap.py`) |
| `demo.py` | covered via subprocess (`test_local.py`) |
| `memcheck.py` | covered via subprocess (3 tests) |
| `ui.py` | covered via subprocess (4 tests) + imported by `test_uicards.py` |
| `verify.py` | covered via subprocess (3 tests) |
| **`locks.py`** | **none** — see §5.2 |
| **`evidence.py`** | **none** |
| **`package.py`** | **none** |

`evidence.py` is the tool that generates the "why do you believe this works"
report — an untested reporter of correctness. `package.py` builds the
distributable. Neither is on the critical runtime path, but `locks.py` is.

### 5.7 P3 — Documentation and code disagree

| Location | Says | Code does | Evidence |
|---|---|---|---|
| `loop._state_lock` docstring | "stale after 30s" | breaks at `> 8` seconds | `[CODE]` |
| `settings.toml` | declares 19 `[agent]` keys | code reads 10 further keys never declared | `[RUN]` |
| Docs on effects | "exactly once" | at-least-once (§5.5) | `[CODE]` |
| `settings.toml` documents `api_key_file` | a supported key source | honoured by `loop.py:695`, **ignored** by `providers.py` — so the connectivity check reports a false "key absent" | `[CODE]` |
| `backup.py` output | "N credential file(s) deliberately excluded" | counts matched basenames only; says nothing about credentials it did not recognise (§5.4) | `[REPRO]` |

The 10 functional-but-undeclared keys: `auto_scan_inbox`,
`inbox_settle_seconds`, `max_task_retries`, `candidates_max`,
`candidates_on_gate_failure`, `command_env_allow`, `sandbox`,
`sandbox_network`, `sandbox_image`, `design_gate`. `[RUN]` All 19 declared keys
are read by code — there are no dead settings. `[RUN]` The asymmetry runs one
way: the file under-documents the build rather than lying about it. Two of
these (`command_env_allow`, `sandbox_network`) are security-relevant and
invisible to an operator reading only `settings.toml`.

### 5.8 P4 — Cosmetic

`tests/test_material.py` is the only file in the tree carrying a UTF-8 BOM.
`[RUN]` No functional effect observed; noted for consistency only.

---

---

## 5B. Second-pass defects (line-by-line audit of all remaining modules)

The first pass read the hub modules and inferred the rest from interfaces and
tests. This pass read all 31 remaining modules and all 2,698 lines of
`ui.html` in full. It found two **P0** issues and seven further **P1**s. Every
one below was reproduced against an isolated sandbox using synthetic values;
all sandboxes were deleted and all 58 product module hashes re-verified
unchanged afterwards.

### 5.9 P0 — The control panel has no CSRF protection

**Reproduced.** `[REPRO]`

`ui.py` validates **no** `Origin`, `Referer`, `Sec-Fetch-*`, or request
`Content-Type` header — I grepped the whole file; the only `Content-Type`
occurrences are *response* headers. `[RUN]` `do_POST` parses the body with
`self._data = json.loads(self._body() or b"{}")` regardless of content type.
`[CODE]` And `_authed()` short-circuits: `if not self.token or not
path.startswith("/api"): return True` — the default bind is `127.0.0.1` with
`token = None`, so **the default configuration has no authentication at all**.
`[CODE]`

A cross-origin `text/plain` POST is a CORS "simple request": no preflight, so
the browser sends it and the server acts on it. Against a sandbox panel I sent
exactly that, with `Origin: https://evil.example`:

| Cross-origin request | Server response |
|---|---|
| `POST /api/experts` | `{"created": "csrf-probe"}` |
| `POST /api/experts/csrf-probe/task` | `{"queued": "ce81a5decd3b"}` |
| `POST /api/experts/csrf-probe/start` | `{"running": true}` (real loop process spawned) |
| `POST /api/shutdown` | `{"stopped": true}` (panel killed) |

`[REPRO]` Any web page the operator visits while the panel runs can drive the
entire fleet. `PUT` and `DELETE` are *not* simple requests, so the browser
preflights and blocks those — but the POST surface alone covers expert
creation, task queueing, loop control, federation publishing, backup,
curriculum, quick-spin, team runs, and retired-expert restore.

### 5.10 P0 — CSRF escalates to arbitrary command execution on the host

**Reproduced end-to-end.** `[REPRO]`

`ui.py`'s `_expert_action` accepts `done_check` **directly from the request
body**: `add_task(..., done_check=data.get("done_check") or None, ...)`.
`[CODE]` That value is executed by `loop.check_done` with `shell=True`, no
policy, no sandbox, and the full parent environment — the defect already
established as §5.1.

Chaining §5.9 with §5.1 gives remote code execution. On a sandbox panel with a
mock provider, three cross-origin POSTs (`create` → `task` with a malicious
`done_check` → `start`) caused the host to execute the attacker's command and
write the proof file:

```
RCE via cross-origin POST done_check
```

`[REPRO]` **An operator merely visiting a hostile web page, while the panel
runs on its default settings, yields arbitrary code execution on their
machine.** This is the most severe finding of the audit. `intention`,
`workflow`, and `wake` accept `done_check` by the same route, so the payload
can also be stored and fired later.

### 5.11 P1 — `write_file` reaches config, prompts, and every ledger

**Reproduced.** `[REPRO]`

`_safe_path` is the *only* guard on `read_file`/`write_file`, and it blocks
exactly `{agent.env, agent.env.example, ui-token.txt}` plus paths containing a
`.keys` directory. `[CODE]` Verified verdicts on a fixture root:

| Path | Verdict |
|---|---|
| `agent.env`, `ui-token.txt`, `.keys/x.key` | refused |
| `keys/openai.key` (what `api_key_file` points at) | **allowed** |
| `bootstrap.json`, `cookies.txt`, `identity.json` | **allowed** (all three are credentials per `backup.py`) |
| `settings.toml`, `prompts/*.md`, `identity.md`, `state.json`, `prospective.json`, `approvals/*.json` | **writable** |

`[REPRO]` Note `.keys/` (with a dot) is protected while `keys/` is not.

Four consequences, none requiring `run_command`:

1. **Key exfiltration.** Write `settings.toml` with a hostile
   `[providers.X] base_url`. `Agent.__init__` re-reads `settings.toml` per
   instance `[CODE]`, and `loop.py:1402` POSTs to that URL with
   `Authorization: Bearer {key}` `[CODE]`. The key leaves.
2. **Shell for tool-less roles.** Write `prospective.json` with a
   `then.done_check`; when the intention fires it becomes a task whose gate
   executes it. The Consultant and Student have no `run_command` and reach
   shell this way.
3. **Forged approval.** `approvals.load()` trusts the JSON file; writing
   `{"status": "granted"}` forges the human-in-the-loop decision.
4. **Self-edited constraints.** `variants.py` defines
   `PROTECTED_ROLES = {constitution, _grounding, examiner, student}` and states
   it is *"enforced here, in code, for every caller including the panel."*
   `[CODE]` It is enforced only for callers of `spawn()`; `write_file` writes
   those prompts directly.

**Every role holds `write_file`, including the Student.** `[RUN]` The
"Rule of Two" comment withholds `run_command` from roles that read untrusted
material — but `write_file` is unrestricted in scope and reaches the very files
that *define* every other capability.

### 5.12 P1 — Ingestion reads arbitrary local files (`file://`)

**Reproduced.** `[REPRO]`

`ingest.fetch_url` calls `urllib.request.urlopen` with **no scheme allowlist**,
and `same_site_links` explicitly permits `file` alongside `http`/`https`.
`[CODE]` Fetching `file:///…/secret.txt` wrote its contents into a lesson file:
`SOURCE-URL: file:///…\n\nSYNTHETIC-LOCAL-SECRET-VALUE`. `[REPRO]`

This bypasses `_safe_path` and `SECRET_BASENAMES` entirely — a different code
path. The worst reach is the lowest-privilege input in the system: `route_file`
treats `.url`/`.urls` files as link lists and calls `add_url` for **every
line** `[CODE]`, and `scan_inbox` runs automatically. **Dropping a `.url` file
into `inbox/` containing `file:///…/agent.env` reads the provider key into
course material**, which is then injected into the model's context. The same
call reaches internal HTTP addresses (SSRF).

### 5.13 P1 — Filesystem containment escape via unsanitised `course`

**Reproduced.** `[REPRO]`

`add_task` stores `course` verbatim; nothing in the repository sanitises it.
`[RUN]` `gotchas.from_failure` with `course="../../ESCAPED"` computed
`courses/../../ESCAPED/gotchas.md` and **wrote the file outside the expert
root**, leaving the root empty. `[REPRO]`

`_safe_path` is used in only three places — `read_file`, `write_file`, and one
UI endpoint. `[RUN]` Five harness writers build course-derived paths without
it: `gotchas.py:83`, `candidates.py:165`, `conflicts.py:333`,
`curriculum.py:297`, `loop.py:515`. Because `prospective.json` is
model-writable (§5.11), the model can set `then.course` and obtain an
arbitrary-file-write primitive outside its root.

### 5.14 P1 — `package.py` ships credentials and the federation secret

`package.py`'s `SKIP_FILES` is a fixed basename list that **omits
`identity.json`** — which `backup.py` classifies as a secret — and knows
nothing of `api_key_file` or an inline `api_key`. `[CODE]` `federation/` is not
in `SKIP_DIRS`, so `federation/identity.json`, which holds the fleet's HMAC
`secret`, is included in the distributable. `[CODE]` The command prints
*"no private data included."*

This is the third mutually-inconsistent credential list in the repository
(§5.16).

### 5.15 P1 — Cost ceilings protect one of four model-call paths

`call_model` contains no spend recording and no budget check. `[CODE]`
`_record_spend` appears exactly twice in `loop.py` — one definition, one call
site — and `_budget_exceeded()` is checked at exactly one place. `[RUN]`

| `call_model` site | Spend recorded | Budget checked |
|---|---|---|
| `loop.py:1136` — the main task step | yes | via the run loop |
| `loop.py:1058` — **the compaction summarizer** | **no** | **no** |
| `replay.py:83` | **no** | **no** |
| `benchmark.py:112` | **no** | **no** |

`[CODE]` Compaction is on the *primary* path and fires on the longest, most
expensive tasks, so `max_task_usd` and `daily_budget_usd` systematically
under-count — worst exactly where the money is. `modelrouter`'s per-model
`avg_cost_usd` inherits the same understatement.

### 5.16 P1 — Four credential sources, six subsystems, no shared model

`loop.py` accepts four credential sources: the environment, `agent.env`
(loaded *into* the environment at `Agent.__init__`, which is why the gate in
§5.1 sees keys), **`api_key` inline in `settings.toml`**, and `api_key_file`.
`[CODE]` The inline form directly contradicts `settings.toml`'s own comment
(*"never from this repo"*) and `providers.py:80` (*"Keys live in agent.env —
never in this file"*).

| Subsystem | env | `agent.env` | inline `api_key` | `api_key_file` |
|---|---|---|---|---|
| `loop.py` resolution | yes | yes | **yes** | **yes** |
| `providers.py` health check | yes | yes | no | no |
| `chief.py` "unfunded" | yes | yes | no | no |
| `backup.py` exclusion | n/a | excluded | **not excluded** | **not excluded** |
| `package.py` exclusion | n/a | excluded | **not excluded** | **not excluded** |
| `_safe_path` model guard | n/a | blocked | **readable** | **readable** |

`[CODE]` `settings.toml` is excluded by nothing, readable by the model, and can
hold a key. Four divergent secret lists exist — `loop.SECRET_BASENAMES` (3
names), `backup.SECRET_NAMES` (5), `package.SKIP_FILES` (5),
`sandbox.SECRET_MARKERS` (env patterns) — and **no two agree**.

### 5.17 P1 — A skill file can declare itself trusted

**Reproduced.** `[REPRO]`

`skills.py` states: *"a third-party file must never be able to declare itself
trusted."* `[CODE]` But `discover()` passes the file's own frontmatter as the
default to `provenance_of()`, which returns `graph_entry or default`. With no
graph entry, **the skill's own `provenance:` line is authoritative**:

| Frontmatter | Effective provenance | `script_guard` verdict |
|---|---|---|
| `provenance: own` | own | **None — scripts allowed** |
| `provenance: community` | community | REFUSED |

`[REPRO]` `import_skill` always writes a graph entry, so the CLI import path is
safe; every other arrival path (model `write_file`, `routines.save`, manual
copy, backup restore, unzip) leaves none.

Separately, `script_guard` is a substring test (`"skills/" in cmd and
"/scripts/" in cmd`) over model-authored text, and is defeated by any path
encoding — two `chr()`-concatenation and `glob` variants were **allowed**.
`[REPRO]` It is also called from exactly one place, `loop.py:953` inside
`run_command`; the gate path never consults it. `[RUN]`

### 5.18 P2 — Locking is inconsistent, and abandoned under contention

- **`prospective.json` has three writers and only one takes the lock.**
  `check()` holds `locks.holding`; `add()` and `cancel()` do load-modify-save
  unlocked. `[CODE]` A lock only works if every writer takes it.
- **`skills.py` abandons its lock exactly when it matters.** `record_use` and
  `set_provenance` catch `TimeoutError` and then perform the read-modify-write
  **anyway, unlocked**. `[CODE]` Contention is the condition the lock exists
  for.
- **`checkpoint.py` uses no lock at all** and writes through a *fixed* `.tmp`
  filename, so two processes checkpointing the same key race on the same temp
  file. `[CODE]` The fixed-`.tmp` pattern recurs in `checkpoint.py`,
  `prospective.py`, `skills.py`, `gotchas.py`, and `variants.py`.
- `approvals.decide()` reads the record and checks `status != "pending"`
  **outside** the lock, locking only the write — so *"decisions are final; no
  flip-flop"* is not atomic. `[CODE]`

### 5.19 P2 — Command strings built by interpolation; injectable inputs

`done_check` values are assembled with f-strings that embed caller-supplied
paths into shell commands. Where the path is internally generated
(`consult.py`, `quick.py:164`) this is safe. Where it is user-supplied it is
not: `team.py --id` (also a path-traversal vector into `teamwork/<run_id>`),
`quick.py --deliverable`, and `workflows.py`'s workflow **name**, which is
sanitised only by replacing spaces before being interpolated into
`r'{out_rel}'`. `[CODE]` A `workflows` spec's `done_check` is arbitrary shell
by design.

### 5.20 P3 — Smaller confirmed defects

| Finding | Evidence |
|---|---|
| **`replay.jsonl` has no writer.** `modelrouter._replay_agreement()` reads it; nothing in the repo — including `replay.py` itself — ever writes it, so that routing signal is permanently dead | `[RUN]` |
| **`failure_id` is not stable.** `abs(hash(sig))` uses per-process-randomised string hashing; the same signature produced `4785584188` and `4616996899` in two processes. Recurrence dedup uses `signature` so counting is correct, but the id embedded in every gotcha line can't be cross-referenced | `[RUN]` |
| **Federation replay.** The signed payload carries a `nonce` that is never stored or checked, and no timestamp is signed — a captured `/ask` body is replayable indefinitely | `[CODE]` |
| **`a2a_card` reads a key `make_card` never writes** (`identity` vs `specialty`), so every A2A skill description degrades to "specialist" | `[CODE]` |
| **`commons.digest` truncation inverts its own priority.** Parts are ordered pins → lessons → quarantine → directory, but overflow keeps `text[-limit:]`, discarding the owner's pins — documented as outranking everything — first | `[CODE]` |
| **`demo.py --dir` runs an unconfirmed `shutil.rmtree`** on any operator-supplied path | `[CODE]` |
| **`bootstrap.py --key NAME=VALUE`** puts a secret on the command line (visible in the process list and shell history); the "never printed" claim covers stdout only | `[CODE]` |
| **UI/CLI asymmetry.** `fleet.py delete` requires `--confirm`; `DELETE /api/experts/<slug>?purge=1` hard-deletes with only a "stop the loop first" check | `[CODE]` |
| **`memory.py:476`** spells `"score"` as `chr(115)+chr(99)+…` (a nested-quote workaround) — obfuscated source in a hot path | `[CODE]` |
| **`chief.py` false "FUND" advice** for providers using `api_key_file` | `[CODE]` |

### 5.21 P2 — Source authority can be inflated or spoofed

`sources.py` assigns the tier that decides who wins a contradiction
(`conflicts.py`) and what may become a gate-checked standard
(`standards.extract`). Three defects in that assignment:

1. **Path keywords inflate the tier.** `_kind()` runs its regexes over the
   *whole* lowercased reference, not the host. `[CODE]` So an unrecognised
   domain whose **path** contains `api`, `guide`, `docs`, `reference` or
   `documentation` is classified `docs` → `KIND_TIERS["docs"] = 2`
   (*professional*). `https://random-blog.example/my-api-guide` is rated a
   tier-2 source on the strength of its URL path.
2. **The owner table matches as a substring of the whole reference.** The
   override loop is `if str(dom).lower() in low`, where `low` is the entire
   reference. `[CODE]` A URL containing a trusted domain anywhere in its path
   or query — `https://evil.example/?ref=w3.org` against an owner rule for
   `w3.org` — inherits that rule's tier. The *built-in* `DOMAIN_TIERS`
   matching is correct by contrast (`host == d or host.endswith("." + d)`,
   with a comment explaining the `lstrip` trap it avoids), which makes the
   owner path the weaker of the two.
3. **`by_ref` matches fuzzily.** `if r["ref"] in ref or ref in r["ref"]`
   `[CODE]` — so `tier_of` can return a different source's tier whenever one
   reference is a substring of another (`a.md` matches `data.md`).

The consequence is the same in all three: a tier is the input to conflict
rulings and to `standards.extract`, so an inflated source can win a ruling
against genuine material and can promote its claim into a gate-checked
standard. The build's own defence-in-depth (`designcheck.STRICTER`, §AD-13)
prevents a spoofed standard from *loosening* a numeric gate, which bounds the
damage — but not the ruling.

`sources.json` is also written load-modify-save with no lock, like the other
ledgers (§5.18).

---

## 6. Hypotheses I tested that did *not* reproduce

Reporting these matters as much as the confirmed findings — an audit that only
lists hits is not measuring its own false-positive rate.

### 6.1 Upload path traversal — `[NEG]`

`ui.py` `do_PUT /api/experts/<slug>/file` accepts an operator-supplied path. I
replicated its sanitisation exactly and attacked it with 9 vectors: `../../`,
`..\..\`, Windows drive letters (`C:\Windows\evil.txt`, `C:/abs.txt`,
`C:evil.txt`), absolute POSIX (`/etc/passwd`), the dot-collapse trick
(`....//escape.txt`), and legitimate nested paths.

Every vector resolved inside the expert root. The sanitiser normalises
backslashes to `/`, splits, and drops any component that is empty, `.`, `..`,
or begins with `.` — which also removes the drive-letter component. The
hypothesis was wrong; the control holds. `[REPRO]`

### 6.2 Closed-book exam isolation — holds, with a caveat worth stating

The Student role must not read its own notes during an exam. This is enforced
at **two layers of different strength**:

- **Context layer — code.** `memrouter`'s student rule excludes commons,
  skills, gotchas and the rest, and the rule is written so it can only
  *remove* sources, never add. `[CODE]` `tests/test_memory_kinds.py` asserts
  this. `[RUN]`
- **Tool layer — configuration.** `allowed_tools()` returns
  `set(tools) | {"finish_task", "ask_human"}`, and
  `[roles.student] tools = ["write_file", "finish_task", "ask_human"]`. The
  Student has no `read_file` at all and therefore cannot open a note even if
  one were compiled in. `[CODE]`

The mechanism is real and mechanically enforced — not a prompt instruction.
The caveat: the second layer is a settings value. Nothing in code prevents
`read_file` from being added to the student role, and no test asserts that it
is absent. `[RUN]` The guarantee is code-enforced at the context layer and
config-enforced at the tool layer, and those are not the same strength.

### 6.3 Are credentials stored in `settings.toml`? — `[NEG]`

The obvious way a build like this leaks keys is by putting them in the config
file that gets copied around. I checked, and the credential model is sound:
`settings.toml` contains only `api_key_env` — the *name* of an environment
variable — never a value. `[RUN]` `providers.py:80` states the rule explicitly:
*"Keys live in agent.env (api_key_env) — never in this file."* `[CODE]`

The hypothesis was wrong. The design is deliberate and correct. It was pulling
on this thread, though, that surfaced §5.4 — the *second* supported key source
is the one that leaks.

### 6.4 Compaction losing context

`compact_context` appends the middle of the transcript verbatim to
`archive.jsonl` before trimming. The append is **not** wrapped in try/except,
so an `OSError` propagates to the task-level handler and fails the task rather
than silently dropping history. `[CODE]` That is the correct failure mode.

The residual edge case I could not rule out: a write that fails *partway*
(disk full mid-line) leaves a truncated final line in the archive, which the
reader skips as malformed JSON. Nothing corrupts, but "nothing is lost" is
true only up to that line. `[INFER]` — reasoned from code, not reproduced.

---

### 6.5 Second-pass hypotheses that did not reproduce

Reported because an audit that lists only hits is not measuring its own
false-positive rate. Four controls were attacked and **held**:

- **Zip-slip in `ingest.unpack_archive` — `[NEG]`.** I built an archive with
  `../escape1.txt`, `../../escape2.txt`, `..\escape3.txt`, and
  `sub/../../escape4.txt`. All four were refused; only the legitimate member
  extracted, and nothing was written outside the course directory. `[REPRO]`
  The realpath + `startswith(real_dest + os.sep)` check is correct, and its
  comment names the sibling-prefix pitfall it avoids. Escaping members are
  dropped silently, with no log — the only weakness.
- **XSS in `ui.html` — `[NEG]`.** `esc()` escapes `& < > " '`, and every one of
  the 75 `innerHTML` sites routes free text through it at the insertion point.
  `renderCard` escapes every model-authored field and drops unknown card types,
  so `uicards.py`'s delegation (*"every string is escaped by the client"*) is
  honoured. `openFile` escapes arbitrary file content. I flagged
  `ui.html:1305-07` as a suspected raw interpolation and **was wrong** — the
  call site is `${esc(when(x.when))}`, escaping one level up. `[RUN]`
- **Credentials in `settings.toml` — `[NEG]`.** The *documented* model is sound:
  `settings.toml` carries only `api_key_env` names, never values. `[RUN]` The
  hypothesis was wrong; pulling the thread is what exposed §5.16 — the
  *undocumented* inline `api_key` and `api_key_file` paths.
- **Commons poisoning — `[NEG]`, by reachability.** `commons.note()`'s
  promotion rule is weak in the abstract (any non-empty `src` promotes
  immediately, and "a second, different expert" is decided by a caller-supplied
  string). But `note()` has **zero callers in product code** `[RUN]`, the UI
  exposes no write endpoint, and `_safe_path` confines the model to its expert
  root while the commons lives at the fleet home. The invariant holds
  mechanically even though the API would not survive being exposed.

---

## 7. Structural observations

**`loop.py` is a 2,080-line hub imported by 22 modules.** `[RUN]` It holds the
task schema, claim protocol, state mutex, path safety, gate execution, model
calls, compaction, tool dispatch, and failure filing. Everything else in the
build is small and single-purpose by comparison. This concentration is the
build's principal maintainability risk: it is the file where a change is most
likely to have an unanticipated effect, and it is the file with the most
reasons to change.

**The verifier stack is genuinely independent, and that is unusual.**
`citecheck`, `designcheck`, `memcheck`, `conflicts`, `verify` and the gate are
separate deterministic modules, and `candidates.py` scores attempts by reusing
them rather than by asking a model to judge. `[CODE]` A build that scores its
own output with the same model that produced it learns nothing; this one does
not do that. This is the strongest single design decision in the repository.

**Failure is a first-class object.** A gate failure runs `_file_memory`, which
records the failure, opens a case in `cases.py`, files a gotcha, scores
confidence, and commits the task. `[CODE]` Repeat failures are detected as
`RECURRED` rather than filed again. `[CODE]` Most systems discard this
information.

**Observability is real, not decorative.** Compile manifests, effects ledger,
decision logs with `why` strings on routing choices, `[section]` markers in
tests feeding `evidence.py`, the harness manifest. `[CODE]` The build can
explain most of its own decisions after the fact, which is what made this audit
possible at the depth it reached.

---

## 8. What I could not verify

Stated plainly, because a report that omits its own blind spots is not an audit.

1. **Nothing was verified against a live model provider.** No keys configured;
   every test call is a mock. `[RUN]` All behavioural claims about prompt
   effectiveness, output quality, real token costs, and provider failover under
   genuine API errors are **unverified**.
2. **No history.** Not a git repository — authorship, change sequencing, and
   regression archaeology were impossible. `[RUN]`
3. **Docker and E2B sandbox backends were not exercised.** `docker` reports
   READY as a binary, but no containerised run was performed. The fail-closed
   path for unavailable backends is `[CODE]` only.
4. **The UI was not driven live in this audit pass.** Endpoint inventory is
   from source; behaviour under a real browser session was verified earlier in
   the project by `test_frontend.py`, not re-verified here.
5. **Federation (A2A) and MCP against real servers.** Both are tested against
   in-process fakes. `[CODE]` No third-party server was contacted.
6. **Long-run behaviour.** The 24/7 claim — memory growth, ledger sizes, lock
   contention over days, log rotation — is untested at duration. The longest
   observation in this audit is a 259-second suite run.
7. **`backup.py` restore was not executed against a real backup set** in this
   pass; `verify` never raising is `[CODE]`.

---

## 8B. Invariant Coverage Matrix

For every major invariant: all code paths that can reach the protected
operation, whether the primary path is defended, whether the alternates are,
and what happened when I tried to break it.

**Legend** — ✅ protected · ❌ unprotected · ⚠️ partial/config-only · — n/a

| Invariant | Write/execute paths | Primary protected? | Alternate paths protected? | Tests | Falsification attempted | Result |
|---|---|---|---|---|---|---|
| **Secrets never reach model-authored commands** | `run_command`; `check_done`; `verify.py`; MCP; sandbox backends | ✅ `run_command` scrubbed via `sandbox.scrub_env` | ❌ `check_done` + `verify.py` inherit the full env, incl. `agent.env` loaded into `os.environ` | `test_secrets` (tool path only) | Planted env marker, both paths | **BROKEN** — gate saw the marker, tool path saw `ABSENT` (§5.1) |
| **Commands cannot bypass the sandbox** | `run_command`; `check_done`; `verify.py:59`; `goal.py:261`; `benchmark.py:84`; `toolbox.py:85` | ✅ `run_command` only | ❌ 5 of 6 `shell=True` sites never call `sandbox` | `test_sandbox` (host backend only) | Grep + reproduction | **BROKEN** (§5.1, §5.19) |
| **Commands cannot bypass policy** | same six sites | ✅ `run_command` calls `policy.check` | ❌ gate/verify/goal/benchmark/toolbox do not | `test_policy` paths | Code trace | **BROKEN** (§5.1) |
| **Filesystem containment** | `read_file`/`write_file`; UI file API; upload PUT; zip extract; ingestion; gotchas/candidates/conflicts/curriculum/course-lock; backup restore | ⚠️ `_safe_path` guards only 3 call sites | ❌ 5 harness writers use unsanitised `course`; ✅ zip-slip holds; ✅ upload holds | `test_paths`, `test_material`, `test_guardrails` | 9 upload vectors, 4 zip vectors, `course` traversal | **MIXED** — upload ✅, zip ✅, `course` **BROKEN** (§5.13) |
| **Student stays closed-book** | context compile; `read_file`; `run_command`; `recall.py`; team handoff; consultation; UI-written memory | ✅ `memrouter` student rule can only *remove* | ⚠️ tool layer is **configuration**; Student holds `write_file` → `settings.toml` → grants itself tools for the next exam | `test_memory_kinds`, `test_exam` | Enumerated all 7 acquisition paths | **HOLDS within one exam**; erodes across exams (§5.11) |
| **Destructive effects require approval** | MCP `effects`; `approvals/*.json`; UI POST actions; CLI; `done_check` | ✅ MCP path gated | ❌ approval files are model-writable (forgeable); ❌ `done_check` reaches shell with no approval | `test_approvals`, `test_effects` | Write-path analysis + RCE repro | **BROKEN** (§5.10, §5.11) |
| **Effects don't duplicate** | `mcp.call` → `effects.record`; prospective firing; retries | ⚠️ ledger key is correct `(lineage, server, tool, sha256(args))` | ❌ call precedes record → crash window; ❌ `prospective.add`/`cancel` unlocked | `test_effects` | Code trace | **at-least-once**, not exactly-once (§5.5, §5.18) |
| **Backups exclude credentials** | `backup.py`; `package.py` | ⚠️ excludes 5 fixed basenames | ❌ misses `api_key_file`, inline `api_key`, `settings.toml`; `package.py` also misses `identity.json` + ships the federation secret | none (`api_key_file`: 0 test refs) | Ran `backup.py create` on a fixture | **BROKEN** — key archived in plaintext while reporting "2 credential file(s) excluded" (§5.4, §5.14) |
| **Task state single-writer integrity** | `claim_task`; `commit_task`; UI; team; goal drivers | ✅ `_state_lock` O_EXCL mutex | ❌ release never verifies ownership; a >8 s stall splits the mutex | `test_lock` (course lock, *not* `locks.py`) | Code trace both impls | **BROKEN under stall** (§5.2); `locks.py` untested (§5.6) |
| **Skill graph integrity** | `record_use`; `set_provenance`; `import_skill`; `routines.save`; `write_file` | ✅ promotion/quarantine maths is deterministic | ❌ self-declared provenance wins with no graph entry; ❌ lock abandoned on timeout | `test_skillgraph`, `test_skillmd` | Fixture with `provenance: own` | **BROKEN** (§5.17, §5.18) |
| **Commons promotion rules** | `commons.note`; `commons.learn`; `write_file` | ✅ unreachable by the model (fleet home is outside `_safe_path`) | ✅ no UI write endpoint; `note()` has no product caller | `test_memory` | Reachability analysis | **HOLDS** — by reachability, not by the API's own strength (§6.5) |
| **Contested claims cannot ship as settled** | `conflicts.check` gate; `standards.extract`; `premise.check` | ✅ `conflicts.check` is a real gate; `extract` skips contested *and* defeated | ⚠️ `premise` is advisory by design (documented) | `test_conflicts`, `test_awareness` | Code read | **HOLDS** (mechanical where it claims to be) |
| **Retraction precedence** | `commons.quarantine`; `premise.check`; context injection | ❌ quarantine.md is injected with "Never cite these" — a *prompt instruction* | ❌ the original claim remains in `knowledge/<topic>.md` | `test_memory` | Code read | **PROMPT-ENFORCED ONLY**, not mechanical |
| **Context archive preservation** | `compact_context` → `archive.jsonl` | ✅ verbatim append precedes the trim; an `OSError` fails the task rather than dropping history | ⚠️ a partial write leaves a truncated final line the reader skips | `test_compaction` (**0 evidence markers**) | Code read | **HOLDS** with a stated edge case |
| **Cost ceilings** | 4 `call_model` sites | ✅ main task step only | ❌ compaction, `replay.py`, `benchmark.py` all unaccounted | 0 test refs to `_record_spend` | Call-site enumeration | **BROKEN** — 1 of 4 paths covered (§5.15) |
| **Provider identity / cost attribution** | `modelrouter.record`; `task["provider"]` | ⚠️ records the actually-used pair | ❌ last-step attribution; compaction cost invisible; `replay.jsonl` never written | `test_modelrouter` (seeds the ledger directly) | Call-site trace | **UNRELIABLE** (§5.15, §5.20) |
| **Evaluator independence** | `[agent.chain]` examiner; `candidates` critic; `variants.PROTECTED_ROLES` | ✅ verifiers are deterministic code, never a model judging itself | ❌ `PROTECTED_ROLES` enforced only in `spawn()`; `write_file` and `promote()` both bypass it | `test_decisions`, `test_variants` | Code trace | **CONFIG/CODE MIXED** — the good design is bypassable (§5.11) |
| **Sandbox fails closed** | `sandbox.py` backends | ✅ unavailable backend refuses rather than falling back to host | ❌ the gate path never enters `sandbox` at all | `test_sandbox` (host only) | Code read | **HOLDS where invoked**; not invoked on the gate path |
| **External peer quarantine** | `federation.handle_ask`/`handle_fetch`; `record_evidence` | ✅ HMAC verify before any model; exposure allowlist; ticket ownership; answers fenced + labelled untrusted | ❌ `nonce` never checked → replayable; ⚠️ `do_POST` 500s leak `str(e)` | `test_federation` (37 asserts) | Code read | **MOSTLY HOLDS**; replay window open (§5.20) |
| **Panel authorisation** | every `/api` route | ❌ default localhost bind has `token = None` → no auth | ❌ no `Origin`/`Content-Type`/CSRF check on any route | `test_remote` (token presence only) | Cross-origin POSTs | **BROKEN → RCE** (§5.9, §5.10) |

**Reading the matrix.** Of 20 invariants: **4 hold**, **3 hold with stated
limits**, **2 are prompt- or config-enforced rather than mechanical**, and
**11 are broken on at least one path**. In every broken case but one
(`retraction precedence`, which was never mechanical) the *primary* path is
correctly defended and an *alternate* path is not — the pattern the second pass
was commissioned to hunt, now confirmed across nine subsystems.

---

## 9. Companion artifacts

| File | Contents |
|---|---|
| `BUILD_MANIFEST.json` | Machine-readable: every module and test, SHA, subsystem, imports, reverse-imports, CLI surface, security flags, coverage |
| `TRACEABILITY_MATRIX.md` | Capability → implementation → test → evidence, with unproven rows named |
| `ARCHITECTURE_DECISIONS.md` | The decisions the code embodies, with the alternative rejected and the cost paid |
| `GAPS_RISKS_AND_UNFINISHED.md` | Every finding, ranked P1–P4, with reproduction and options |
| `SYSTEM_DIAGRAMS.md` | Execution, memory, governance, and trust-boundary diagrams |
