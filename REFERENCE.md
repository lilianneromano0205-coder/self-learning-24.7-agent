# Expert Fleet — the complete reference

Everything in this platform, explained end to end: what each part is, the
logic it runs, how you interact with it, and what it does **not** do.

`MANUAL.md` is the short practical guide. This is the deep one. It was
written by reading the code, not from memory; where a claim could rot, the
test that keeps it honest is named.

**Scale, so you know what you are reading about:** 112 Python modules,
one HTML file for the whole UI, 145 acceptance tests, zero third-party
dependencies. Python 3.11+ and your own API keys.

---

## Table of contents

1. [The shape of the thing](#1-the-shape-of-the-thing)
2. [The harness](#2-the-harness)
3. [The loop, step by step](#3-the-loop-step-by-step)
4. [The five tools, and what guards them](#4-the-five-tools-and-what-guards-them)
5. [The context compiler](#5-the-context-compiler)
6. [The memory institution](#6-the-memory-institution)
7. [Knowing what it knows: sources, conflicts, standards, self](#7-knowing-what-it-knows)
8. [Creating agents: the five lanes, eight roles, twenty templates](#8-creating-agents)
9. [The work systems](#9-the-work-systems)
10. [Governance and improvement](#10-governance-and-improvement)
11. [The control plane](#11-the-control-plane)
12. [Interop: MCP, A2A, federation](#12-interop)
13. [Where commands run](#13-where-commands-run)
14. [Data layout on disk](#14-data-layout-on-disk)
15. [settings.toml, every key](#15-settingstoml-every-key)
16. [Every command](#16-every-command)
17. [Every HTTP endpoint](#17-every-http-endpoint)
18. [Every event name](#18-every-event-name)
19. [The test suite as the specification](#19-the-test-suite-as-the-specification)
19a. [The UX release gate](#19a-the-ux-release-gate--spec-17)
20. [Honest limits](#20-honest-limits)
21. [Running it in production](#21-running-it-in-production)
22. [Definition of Done, release gates, and where this build stands](#22-definition-of-done-release-gates-and-where-this-build-actually-stands)

---

## 1. The shape of the thing

A **fleet home** holds many **experts**. Each expert is a directory: its own
identity, settings, task queue, courses, skills, memory and logs. Nothing is
shared implicitly — an expert reads another's knowledge only through the
commons or an explicit peer question.

The platform is **file-backed**. There is no database and no server process
that owns the truth: the truth is files on disk, written atomically, and any
process (the loop, the panel, your text editor, `grep`) can read them. That
is a deliberate trade — you give up query speed at scale and gain the ability
to inspect, diff, back up and repair everything with ordinary tools.

Six systems, and the modules that implement each:

| # | System | Modules |
|---|---|---|
| 1 | **Harness & loop** | `loop.py` `harness.py` `policy.py` `effects.py` `locks.py` `checkpoint.py` `sandbox.py` `context.py` |
| 2 | **Fleet & creation lanes** | `fleet.py` `quick.py` `templates.py` `team.py` |
| 3 | **Work systems** | `goal.py` `workflows.py` `consult.py` `prospective.py` `routines.py` `research.py` |
| 4 | **Memory institution** | `memory.py` `skills.py` `commons.py` `recall.py` `gotchas.py` `premise.py` `memrouter.py` `sources.py` `conflicts.py` `standards.py` `selfmodel.py` `curriculum.py` `cases.py` |
| 5 | **Improvement & governance** | `variants.py` `approvals.py` `replay.py` `benchmark.py` `verify.py` `citecheck.py` `memcheck.py` `designcheck.py` `candidates.py` `evidence.py` `confidence.py` |
| 6 | **Control plane & interop** | `ui.py` `ui.html` `chief.py` `doctor.py` `bootstrap.py` `preflight.py` `backup.py` `providers.py` `toolbox.py` `mcp.py` `federation.py` `trace.py` `uicards.py` `modelrouter.py` |

Support: `ingest.py` (all input formats), `demo.py` (keyless tour),
`package.py` (ship a zip).

### The one idea

The model is rented and replaceable. Everything that makes the output
trustworthy lives **outside** the model, in code: what goes into its context,
what it is allowed to do, and what must be true before its work is accepted.
When a claim in this document sounds like a promise about behaviour, look for
the gate — the promise is the gate, not the prompt.

---

## 2. The harness

`harness.py` exists so the harness is an **object you can inspect**, not a
folk belief about what the code does.

### `manifest(root)`

A machine-readable description of the whole apparatus:

- **tools** — the five tools, and which roles may call each
- **gates** — every mechanical check and its threshold (`done_check`,
  `max_done_rejects`, citecheck, memcheck, verify, skill promotion at 3
  distinct wins, variant promotion minimums, the goal judge's overrule)
- **policies** — the built-in deny rules with their reasons, owner deny/allow,
  protected roles, and every MCP server's approval and allowlist settings
- **memory_tiers** — every ledger and directory the platform writes
- **budgets** — every ceiling in `[agent]`, plus the sandbox backend
- **loop_events** — scraped from the source of every module that logs events
- **versions** — MCP protocol eras, A2A version, and a `sha256[:12]` of each
  prompt and core module, so you can tell whether the thing running is the
  thing you reviewed

### `check_contracts(root)`

Verifies the harness against itself: every declared tool has an execution
branch; every event the panel renders is an event the code actually emits;
every prompt the doctor requires exists; every role's provider is configured.
It is how a rename gets caught the day it happens instead of in production.

### `integrity(root)`

A sub-300ms readiness check: settings parse, prompts present, ledgers parse,
no stale locks (>60s), logs and contexts writable, disk free, sandbox
available.

### The health ritual

`Agent.run()` calls `_health_ritual()` before its first task, every session.
It writes `logs/health.json` and `logs/harness.json`, logs `health_ritual`
and a heartbeat note. It never raises — a broken health check must not stop
an agent from working, only inform it.

```bash
python harness.py                # the manifest, human-readable
python harness.py --json         # the same, machine-readable
python harness.py --check        # exit 0 when every contract holds
```

**Tests:** `test_harness.py` (the manifest is real, a fake tool is caught),
`test_faults.py` (break each contract on purpose; the validator must catch it).

---

## 3. The loop, step by step

`loop.py` is the engine — 1,998 lines, one class, `Agent`.

### Four kinds of loop

Anthropic's 2026 taxonomy, all four present:

| Kind | Here |
|---|---|
| turn-based | a task: run until the tools say finished |
| goal-based | `goal.py`: pursue until an independent judge agrees |
| time-based | `prospective.py` `every_days` / `at` intentions |
| proactive | intentions on watches and events, plus the chief's ranking |

**Every loop is defined by its stop condition.** A task may declare one:

```bash
python loop.py add --role practitioner --goal "..." \
  --stop-criteria "tests pass" --max-attempts 2 --max-steps 40 \
  --deadline 2026-09-01T09:00:00
```

Stored on the task as `stop`, enforced in `run_task_step` **before** the model
is called (deadline, max_steps), honoured by the retry path (max_attempts),
written into the first user message, and repeated in the compaction facts so
it survives a context squeeze.

### The outer loop — `Agent.run(drain=False)`

```
agent_start → health ritual → heartbeat
repeat:
    daily budget exceeded?  → sleep (or stop, in drain mode)
    next task?
        no  → heartbeat "idle", then ONE idle tick in this order:
                 prospective → inbox → gaps → exams → re-exams
              (any tick that did work restarts the cycle immediately)
              drain mode with nothing to do → drain_complete, exit
        yes → claim it atomically, take the course lock, log task_start
              step until the task leaves "running"
              then: file memory → chain → reflection → retry
```

Two loops on the same expert are safe: `claim_task` flips
queued→running under a cross-process mutex, and only the claimer proceeds.

### The inner cycle — `run_task_step()`

One tick, in this exact order:

1. **Load context**, then **compact** it if it exceeds the token threshold
2. **Stop conditions** — deadline passed or max_steps reached → fail now, with
   the reason named (`stop_condition`)
3. **Route the model** (`modelrouter`, when the role is on `route = "auto"`)
4. **Call the model** — 5 exponential-backoff attempts on the primary
   provider, then the fallback; escalated calls try the stronger model first
5. **Meter** tokens and cost; add to the task and the daily spend file
6. **Collect UI cards** from the message (closed catalogue, `uicards.py`)
7. **Parse the tool call** — native function-calling, or the grounding
   header's inline-JSON fallback for models without it
8. **No valid tool call?** count it; `max_malformed_tool_calls` (default 3)
   consecutive failures fail the task
9. **Execute the tool** (§4)
10. **`finish_task` → the gate**: run `done_check`; on failure the finish is
    **REFUSED** with the command, its exit code and its output, and the task
    keeps working. After `max_done_rejects` (default 6) the task fails
11. **Escalation** — after `escalate_after_errors` consecutive tool errors, or
    when the model writes `[[ESCALATE]]`, the next call uses the stronger model
12. **Repetition breaker** — an identical tool call repeated is a stuck agent
13. **Persist** — context, task, heartbeat

Every tool returns **text**, including its failures: an agent can recover from
`exit=1, file not found`; it cannot recover from an exception that kills its task.

### Brakes and budgets

| Brake | Default | What it does |
|---|---|---|
| `max_steps` | 150 | ceiling on steps per task |
| `max_task_usd` | 2.00 | per-task dollar ceiling |
| `daily_budget_usd` | 0 (off) | fleet-wide daily breaker |
| `max_done_rejects` | 6 | refusals before a gated task fails |
| `max_task_retries` | 2 | fresh-context retries after failure |
| `max_malformed_tool_calls` | 3 | consecutive unusable model replies |
| `command_timeout_seconds` | 300 | hard kill for `run_command` |
| `model_timeout_seconds` | 180 | hard kill for a model call |

### Retry with fresh eyes

`_maybe_retry` re-queues a failed task with a **new context**, carrying the
previous attempt's error into the goal — not the previous transcript. Attempt
counts are on the task, the base goal is never stacked twice, and
`stop.max_attempts` overrides the default budget. (`test_retry.py`)

### Compaction as a contract

Past `context_token_threshold` (default 50k), `compact_context`:

1. archives the middle turns **verbatim** to `contexts/<id>.archive.jsonl`
   (nothing is ever lost — `recall.py` searches these)
2. **clears tool results** over 1,500 chars, replacing each with a pointer to
   the exact archive line, *before* summarizing — the summarizer never re-reads
   a 30KB grep dump
3. asks the model for a summary under seven required headings
4. appends **HARNESS FACTS** the code knows mechanically: the goal, the
   definition of done, the stop condition, the files written
5. if a heading is missing, says so and logs `compaction_incomplete`

(`test_compaction.py`, `test_context.py`, `test_governance.py`)

### Checkpoints — recover, don't restart

`checkpoint.py`. A twenty-minute transcription that dies at chunk 17 resumes
at chunk 18. Keyed by task lineage + operation + inputs, stored under
`checkpoints/`. Wired into `ingest.transcribe` (per chunk), `ingest_folder`
(per file) and `add_url` crawls (per sub-page). (`test_checkpoint.py`)

### Wake on an event

```bash
curl -X POST http://127.0.0.1:7777/api/experts/<slug>/wake \
  -H "Content-Type: application/json" \
  -d '{"event":"price.drop","payload":{"sku":"A1"}}'
```

Writes `events/<ts>-<event>.json`, fires any armed `event` intention at once,
and starts the loop if idle. The payload reaches the model **fenced as a
file**, never as instructions. (`test_wake.py`)

---

## 4. The five tools, and what guards them

The model gets exactly five. Not fewer, because it must be able to read,
write, run, finish and escalate. Not more, because every extra tool is
another way to be wrong.

| Tool | Arguments | Notes |
|---|---|---|
| `read_file` | `path` | inside the agent root only |
| `write_file` | `path`, `content` | creates parent directories |
| `run_command` | `cmd` | hard timeout; policy + sandbox (below) |
| `finish_task` | `summary` | **gated** by `done_check` |
| `ask_human` | `question` | appends to `blocked.md`, task → blocked |

### Per-role allowlists (the Rule of Two)

`[roles.<r>] tools = [...]` restricts a role. A role that reads untrusted
material should not also hold `run_command`. `finish_task` and `ask_human` are
always allowed — a role must always be able to end or escalate.

### Path containment

`_safe_path` resolves every file path and refuses anything outside the agent
root, symlinks included. (`test_paths.py`)

### Command policy — `policy.py`

A deterministic guard between the model and the shell, checked **before** any
backend is consulted. Built-in denials, each with a reason:

recursive delete of a filesystem root · recursive delete of a drive · disk
formatting · power control · pipe-to-shell download execution · privilege
escalation (`sudo`/`doas`/`runas`) · credential file access (`/etc/shadow`,
`.ssh/id_*`, `.aws/credentials`, `agent.env`) · raw device write · fork bomb ·
world-writable permissions · firewall modification · force push

Owner rules extend it:

```toml
[agent.command_policy]
deny = ["\\bterraform\\s+destroy\\b"]
[agent.command_policy.ripper]
allow = ["^python3? ingest\\.py "]     # this role may run ONLY these
```

### Untrusted content is fenced

Any file content injected into context is wrapped in
`<<<FILE-CONTENT path>>> … <<<END-FILE-CONTENT path>>>`, and the grounding
prompt forbids obeying instructions found inside a fence. That is how a
poisoned PDF stays data. (`test_guardrails.py`)

### Effects ledger — exactly once

`effects.py`, `logs/effects.jsonl`. A side effect is keyed by lineage; a retry
of the same task replays the record instead of repeating the effect. A corrupt
line is skipped, not fatal. (`test_effects.py`)

### Approvals — the human in the loop

`approvals.py`. A destructive MCP tool (by its own `destructiveHint`
annotation) pauses and writes a pending record keyed by
`lineage|server|tool|argument-hash`. Change one byte of the arguments and it
is a **new** approval. A decision cannot be flipped afterwards. The panel
shows what was done / what this step does / what comes next, from
`trace.brief`. (`test_approvals.py`)

---

## 5. The context compiler

`context.py`. What the model sees is a **compiled view**, never a pile.

Ten named sources, each with a token budget:

| Source | Default | What it carries |
|---|---|---|
| `self` | 600 | the agent's factual self-model (§7) |
| `commons` | 1500 | fleet lessons (curated) + owner pins |
| `course` | 2500 | the course's mission and index |
| `standards` | 700 | the bar this work must clear (§7) |
| `authority` | 400 | which sources outrank which (§7) |
| `conflicts` | 700 | rulings on contradictions relevant to this goal |
| `gotchas` | 800 | failures this expert already paid for |
| `premise` | 400 | contradictions between the goal and verified memory |
| `skills` | 3000 | activated playbooks + a name-only index of the rest |
| `memory_files` | 12000 | the files this task was handed |

Order matters: `self` first (an agent that knows what it has verified reads
everything after it differently), then the shared, then the specific.

**Trimming is explicit.** An over-budget file is cut at its budget and marked
`[...trimmed: N chars over budget; read_file <path> for the rest]`. Content is
never silently dropped; a file that could not be loaded at all is listed.

**Progressive disclosure.** Skills that did not activate still appear as a
`SKILL INDEX` — name and one line each — so the agent knows the playbook
exists at a fraction of the tokens.

**Every compile leaves a manifest** at `contexts/<task>.compile.json`: which
sources ran, what each was allowed, what it used, which files were included,
trimmed or dropped, the router's decision and why. The panel renders it as
budget bars; the CLI prints it:

```bash
python context.py --root experts/<slug> --task <id>
```

### The memory router

`memrouter.py` decides which kinds a task may see, per role:

| Role | Sees |
|---|---|
| `student` | self, course, memory_files — **closed book** |
| `examiner`, `consultant` | self, course, memory_files, premise, gotchas, authority, conflicts |
| `reflector` | self, memory_files, skills, gotchas |
| `ripper` | self, memory_files, gotchas, course, authority |
| everyone else | everything |

Two rules protect the guarantees above it: a goal beginning `PLAN cycle`,
`TEAM` or `JUDGE` always gets the commons; and the student rule may only
**remove** sources — an owner override cannot hand an examinee the notes it is
being tested on. (`test_memory_kinds.py`, `test_exam.py`)

---

## 6. The memory institution

Nine kinds, each with a different job. This is the part most agent platforms
reduce to "a vector store", and the reason this one does not is that the kinds
have different rules for being written, trusted and forgotten.

### 6.1 Courses and atoms — what it studied

`courses/<name>/` holds `source/` (originals), `lessons/NN/` (extracted text
and notes), `index.md`, `spec.md`, `notes.md`, `gaps.md`,
`lessons-learned.md`, `retractions.md`, `exam/`, `artifacts/`.

Every claim in `notes.md` is an **atom** with an id and a citation:

```
- C-0101 Body text contrast is at least 4.5:1 [src: https://www.w3.org/TR/WCAG22/]
```

`citecheck.py` is the gate: an answer may only cite atoms that are **defined**,
or write `NOT IN MY TRAINING`. A citation to nothing fails the gate, so an
ungrounded answer cannot ship. `memcheck.py` makes the same rule checkable
over notes themselves. (`test_memcheck.py`, `test_consult.py`)

### 6.2 Skills — procedural memory with a promotion gate

`skills.py`. A playbook is written by the Reflector after real work, and has a
lifecycle enforced by outcomes, never by opinion:

- **candidate** — injected with a hypothesis banner: use, but verify
- **proven** — a matched held-out ablation showed a positive effect: the
  same cases run with and without the skill, arms shuffled per case, scored
  by a grader that never sees which arm it is grading. Co-occurrence —
  however many wins — promotes nothing
- **quarantined** — an ablation showed HARM; never auto-injected
  again, still on disk. One verified win redeems it to candidate

Skills compose: `USES: a, b` or `[[name]]` pulls sub-skills one hop.

Two shapes, one graph key: the flat `skills/x.md` the Reflector writes, and
the Agent Skills standard folder `skills/x/SKILL.md` with YAML frontmatter.
Import and export in the open format:

```bash
python skills.py list --root experts/<slug>
python skills.py import ./pdf-forms --root experts/<slug>   # arrives "community"
python skills.py promote pdf-forms --root experts/<slug>    # owner trust
python skills.py export restore-a-backup --to ./out --root experts/<slug>
```

**Provenance tiers** gate authority: `own` (written here), `owner` (imported
and vouched for), `community` (third party). A community skill is injected
with a warning banner and **its bundled scripts will not run** until promoted
— the loop refuses them. (26.1% of community skills in the 2026 study carried
a vulnerability.) (`test_skillgraph.py`, `test_skillmd.py`)

### 6.3 The commons — what the fleet knows together

`commons.py`. `lessons.md` (mistakes, append-only), `knowledge/<topic>.md`
(facts), `quarantine.md` (withdrawn claims, struck through, never deleted),
`directory.md` (who knows what), `pins.md` (owner pins, injected first).

A fact from one expert is a **candidate**; it is promoted to shared knowledge
only when a second, different expert reports the same thing, or it arrives
with a citation. One agent's bad episode cannot poison the fleet.

**ACE-style curation.** `curate()` derives `lessons.curated.md` from the
append-only ledger: near-duplicates merged, every contributor kept, hit counts
visible. The ledger is never rewritten (that is how a memory drifts into bland
advice — "context collapse"), and every merge is journalled to `edits.jsonl`.
Delete the view and it rebuilds identically.

### 6.4 Failures — sixteen categories

`memory.py`. Every failed task files a structured record under
`commons/failures/<category>.jsonl`, categorised **by the harness's own error
string**, never by asking a model why it failed:

`false_success` `hallucination` `bad_retrieval` `context_loss` `planning`
`tool_misuse` `missing_evidence` `wrong_assumption` `coordination` `budget`
`security` `infrastructure` `model_limitation` `premature_stop` `eval_gaming`
`unknown`

Identical failures increment a recurrence count instead of duplicating, so a
recurring problem becomes visibly recurring.

### 6.5 Gotchas — the failures that will bite again

`gotchas.py`. Each failure also becomes a one-line gotcha, scoped to where it
recurs: `courses/<c>/gotchas.md`, `gotchas/mcp-<server>.md`, or
`gotchas/general.md`.

```
- [2026-08-21] (F-8619957975) TRIGGER: debug, kafka, broker, lag | WHEN tool_misuse: ...
  | DO read the tool's error text and fix the arguments | src: task c669ef00 | x3 hit again ...
```

Matching is phrase-aware and conservative (two trigger words, or one plus a
repeat). A matching later task carries them as a **binding** block. An
unrelated task does not. (`test_memory_kinds.py`)

### 6.6 Premise awareness

`premise.py`. Before work starts, the goal is checked against what memory has
already settled: a cited atom that was **retracted**, an atom that **no note
defines**, a goal whose subject matches a retraction, or a claim the fleet
**quarantined**. Warnings appear as a `PREMISE CHECK` block and a
`premise_warning` event. Being helpful about a false premise is a
hallucination with better manners.

### 6.7 Competence — measured, never claimed

`memory.competence()` scores every (expert, domain) from gated outcomes, with
verified results weighted double. Small samples are *reported as small*: under
3 attempts is "insufficient evidence", and the confidence label
(none/low/moderate/high) is part of the answer.

### 6.8 Recall — the third tier

`recall.py` searches the entire mind, including turns that compaction paged
out of the window (the `*.archive.jsonl` files), plus notes, skills, lessons
and retractions. Associative expansion (RippleMem/CABLE) pulls in
neighbouring material a literal search would miss. (`test_recall.py`,
`test_associative.py`)

### 6.9 Retention and retirement

The hot queue stays small forever (`retain_finished_tasks`, default 150);
everything beyond it moves to `archive/tasks.jsonl` with its transcript and
compile manifest. Nothing is deleted. An expert can be **retired**
(`memory.retire`) — its record is preserved and restorable.
(`test_retention.py`, `test_memory.py`)

---

## 7. Knowing what it knows

The newest layer, and the one that answers "what happens when forty PDFs
disagree".

### 7.1 The source ledger — `sources.py`

Every ingested source is recorded with an **authority tier**, inferred from
its origin and always explained:

| Tier | Name | Examples |
|---|---|---|
| 1 | normative | W3C, WHATWG, IETF/RFC, ISO, DOI, arXiv, ACM, IEEE, Nature, python.org |
| 2 | professional | MDN, web.dev, Apple/Google/Microsoft developer docs, NN/g, Material, WebAIM, Smashing |
| 3 | instructional | YouTube, Udemy, Coursera, Medium, dev.to, freeCodeCamp, Stack Overflow |
| 4 | anecdotal | Reddit, Hacker News, Quora, X, unknown origins |

`.gov`/`.edu` fall to tier 2. Everything unrecognised is rated by kind and
says so. The owner overrules with a reason, recorded:

```bash
python sources.py --root experts/<slug> --classify https://example.com/x
python sources.py --root experts/<slug> --course design --set S-3 --tier 1 --why "the published spec"
```

Or in settings: `[agent.source_tier]` maps a domain to a tier.

### 7.2 Contradiction control — `conflicts.py`

Detection is deterministic and conservative: polarity flips (always/never,
use/avoid, a negation on one side only) and numeric disagreements on the same
unit, **between atoms demonstrably about the same subject** (shared content
words, Jaccard ≥ 0.30 — a shared adjective is not a shared subject). It would
rather miss a subtle conflict than invent one.

Each conflict gets one of four verdicts:

| Verdict | Rule | The ruling says |
|---|---|---|
| **superseded** | newer source, at least equal authority | use the newer, say the older is out of date |
| **authority** | lower tier number wins | follow the higher tier, name the source you did not follow |
| **context** | both carry different stated conditions | both hold — state the condition with the rule |
| **contested** | equals, same era, no condition | **no winner** — present both, never assert either |

Written to `courses/<c>/conflicts.md` (readable) and `conflicts.json`
(machine). Rescanned only when the notes actually change.

**The contested rule is enforced**, not advisory:

```bash
python conflicts.py --root experts/<slug> --check answers/reply.md --course design
```

An answer that states a contested point as settled fails (exit 1). One that
presents both sides, or names the disagreement, passes. Wire it as a
`done_check` and an agent cannot ship a false certainty.

### 7.3 Standards — `standards.py`

Normative atoms (must/never/at least/required) become a per-course bar in
`courses/<c>/standards.md`, each carrying the tier of its source and, where a
number exists, a machine check:

```
- R-02 [tier 1] Body text contrast must be at least 4.5:1 [atom: C-0202]
  [src: https://www.w3.org/TR/WCAG22/] [check: min_contrast=4.5]
```

Two refusals keep the list honest: a **contested** point never becomes a
standard, and neither does a **defeated** one — the blog post beaten by the
spec does not come back as a rule. Thresholds resolve to the **stricter**
value regardless of file order, so no source can loosen a stricter one.

The file is append-only and yours to edit; extraction never rewrites a line
you wrote, and `--add` writes rules the material never stated.

### 7.4 The self-model — `selfmodel.py`

Compiled fresh into every context window:

- **who** it is (name, charter)
- **studied** — each course, its verified atom count, its exam result or
  `NEVER EXAMINED`, the source tiers it rests on, contested points
- **proven** — measured competence per domain, proven skills
- **quarantined** — playbooks it must not use
- **scars** — its own failure record by category, recurring gotchas
- **blind** — known gaps, in its own words
- **now** — role, allowed tools, stop condition, sandbox backend, pending
  approvals; and a warning when the role has no provider configured
- **the edge rule** — if the task needs something it has not studied, say
  exactly that and stop

Nothing is generated. One lucky success reads as "insufficient evidence"; a
course never examined is labelled unproven. This is self-knowledge in the
operational sense — an accurate model of its own capabilities and limits,
which is what makes calibrated refusal possible. **It is not a claim about
consciousness, and the platform never makes one.**

```bash
python selfmodel.py --root experts/<slug>
```

### Learning smart, not just learning (`curriculum.py`)

Material used to be studied in arrival order. Now a plan is computed first,
and every lesson carries the reason for its depth:

| Rule | Why |
|---|---|
| **authority first** | the tier-1 specification is studied before the tutorial covering the same ground, so later material is read against a baseline instead of averaged into one |
| **prerequisites forward** | a lesson that DEFINES atoms other lessons cite is a prerequisite by construction |
| **don't re-read** | near-duplicates are skimmed for *only what they add* (measured: content-word overlap sees a paraphrase at 0.38 where 5-word shingles see 0.02) |
| **know why** | relevance is *containment* of the mission's vocabulary, not Jaccard — a long lesson can never win Jaccard against a short mission whatever it covers |

```bash
python curriculum.py --root experts/<slug> --course <c>            # the plan
python curriculum.py --root experts/<slug> --course <c> --apply    # queue it
python curriculum.py --root experts/<slug> --course <c> --coverage
```

Depths are `study`, `skim` (indexed, read for the delta) and `skip`
(redundant). Nothing is deleted: a skipped lesson stays on disk with its
reason, and the whole plan is written to `curriculum.json` before a single
task is queued. Applying it is explicit — arrival-order ingestion is
unchanged until you ask for the plan.

### Agentic retrieval (`research.py`)

A question is an investigation, not a lookup. Before a consultation is
answered, the question is decomposed into the facts it rests on, each is
retrieved separately, and the consultant is handed both the evidence and the
explicit list of what could **not** be established — so a gap is declared
instead of filled.

```bash
python research.py "what contrast do we need and what is our refund policy?"     --root experts/<slug>
```

Decomposition is deterministic (question grammar plus content words, no model
call), so the same question always yields the same plan. `consult.py` runs it
automatically and falls back to the single-shot path if it fails.

### Confidence, and the compute ladder (`confidence.py`)

Compute should follow doubt. Every finished task carries a measured
confidence built from eight signals the harness already checked — grounding,
evidence coverage, contested points, premise warnings, **measured**
competence in the domain, prior experience, and how hard it fought its gate.
Nothing asks a model how sure it is.

| band | action |
|---|---|
| high (≥0.75) | ship it |
| medium | spend more attempts before accepting |
| low (<0.45) | escalate to the stronger model, or ask the human |

The band is recorded on the task and logged as `low_confidence`, so "why did
this cost more" is answerable.

```bash
python confidence.py --root experts/<slug> --task <id>
```

### Did the fix hold? (`cases.py`)

The failure record answers *what went wrong*; experience needs *what fixed
it, and did it last*. A failure opens a case; a later task that **passes its
gate** closes it, recording what it did differently; the same failure after a
fix is logged **RECURRED** — the most valuable state, because it says the
obvious fix was wrong. A returning problem carries that history into its
context.

```bash
python cases.py --root experts/<slug>            # the ledger
python cases.py --root experts/<slug> --goal "…" # what bears on this work
python cases.py --root experts/<slug> --stats
```

### Test-time compute (`candidates.py`)

Adaptive and on by default: one attempt until something fails its gate, then
3, then 5, inside the existing `max_task_usd` / `daily_budget_usd` ceilings.
Candidates are scored by the verifiers that already gate the work — the
task's own `done_check` is hard and disqualifying, then grounding
(citecheck), honesty (conflicts), interface (designcheck) and spec — each
applying only where it means something. Nothing asks a model whether an
answer is good.

```bash
python candidates.py --root experts/<slug> --task <id> --explain
```

### Evidence, not assertion (`evidence.py`)

```bash
python evidence.py            # runs every test, writes EVIDENCE.md
```

Captures the sentence each test prints about what it proved, maps them to the
six systems, and states a **blind spot** for each. An unclassified test fails
the report; a system with no tests prints UNPROVEN.

---

### 7.5 The design gate — `designcheck.py`

Taste cannot be prompted; specifics can be checked. Wired automatically as the
definition of done for any deliverable ending `.html/.htm/.css/.jsx/.tsx/
.vue/.svelte` (disable with `[agent] design_gate = false`).

**Blockers:** contrast below the floor on any colour pair declared together ·
no breakpoint at all · a fixed width that overflows a phone · missing `lang` ·
an image without `alt` · an unlabelled control · a `<button>` with no
accessible name · a `<div>` carrying `onclick` · lorem ipsum shipped.

**Warnings:** too many type sizes · spacing off any 4px rhythm · raw colour
literals beside defined tokens · no landmarks · the default indigo/violet
palette · emoji as iconography · everything centred · pill radius plus default
palette · stock marketing copy.

Every finding names the line and the fix. A course's own numeric standards
raise the bar.

```bash
python designcheck.py out/index.html --root experts/<slug> --course design
```

(`test_conflicts.py`, `test_awareness.py`, `test_design.py`)

---

## 8. Creating agents

### The five lanes

| Lane | Command | What you get |
|---|---|---|
| 🎓 **Trained expert** | `fleet.py create` + teach | studies whole courses into cited notes, proves skills, sits closed-book exams |
| ⚡ **Quick specialist** | `quick.py "goal"` | briefed from files you drop and working in seconds, still caged by every gate |
| 🧬 **From an archetype** | panel → template | one of 20 pre-built specialists |
| 📚 **Learner** | panel → learner | give it a topic; it finds and ingests its own material |
| 🤝 **Team** | `team.py run` | chosen specialists, lead decomposes, handoffs are files |

All five are in the panel under **Agents**, and all five produce the same kind
of expert — the lanes differ in how the expert is seeded, not in what governs
it. (`test_lanes.py`)

### The eight roles

Each has a prompt in `prompts/` and a distinct job:

| Role | Job |
|---|---|
| `ripper` | ingestion: turn any format into text, deterministically where possible |
| `watcher` | study a lesson into cited notes |
| `librarian` | resolve gaps, record retractions |
| `practitioner` | do the work |
| `examiner` | grade against the spec, run mechanical checks |
| `student` | sit closed-book exams |
| `reflector` | write skills from what actually happened |
| `consultant` | answer questions under the citation gate |

Above them all: `constitution.md` (overrides everything) and `_grounding.md`
(the tool contract, the fence rule, the escalation marker).

### The twenty templates

`frontend-developer` · `ui-ux-designer` · `code-reviewer` · `data-analyst` ·
`technical-writer` · `copywriter` · `seo-auditor` · `research-analyst` ·
`contract-analyst` · `devops-runner` · `ux-reviewer` · `scout` ·
`critic-sentinel` · `market-researcher` · `competitive-intel` ·
`trend-forecaster` · `treasurer-analyst` · `tradeops-landed-cost` ·
`local-radar` · `seo-orchestrator`

```bash
python templates.py                     # list them with their deliverables
```

---

## 9. The work systems

### Task

The unit. `role`, `goal`, optional `course`, `memory_files`, `done_check`,
`stop`. Queue one from the CLI or the panel.

### Goal engine — `goal.py`

State what you want; the system pursues it until an **independent judge**
agrees. Each cycle produces milestones with CHECK commands; the judge can
overrule a self-report, and the overrule is recorded. (`test_goal.py`)

### Team — `team.py`

A lead decomposes the work, specialists execute, handoffs are files with a
constraint digest that must survive. The panel renders a run as a **thread**:
brief → plan → each deliverable → synthesis. (`test_team.py`)

### Workflow — `workflows.py`

Deterministic staged pipelines: fixed stages, each a gated task, each firing
the next only when its gate passes. Use when you already know the procedure
and want no autonomy at all. (`test_workflows.py`)

### Consultation — `consult.py`

For fields an agent cannot execute: the answer must cite defined atoms or say
`NOT IN MY TRAINING`, enforced by `citecheck.py` as the done gate.

### Prospective memory — `prospective.py`

Remembering to **act**, not just remembering facts. Four kinds:

| Kind | Fires when |
|---|---|
| `every_days` | a period elapses |
| `at` | a timestamp passes |
| `watch` | a file or folder changes |
| `event` | a named event arrives at `/wake` |

Firing queues a normal gated task — a fired intention earns no shortcuts.
`repeat: true` stays armed; consumed events are capped at 200.

### Routines — `routines.py`

Show the work once, then have it done forever: a finished task becomes a
`SKILL.md` plus an armed intention plus a record under `routines/`. From the
panel: a task → *save as routine*. (`test_routines.py`)

---

## 10. Governance and improvement

### Charter evolution with a prediction — `variants.py`

A variant is an edited role prompt, tried on a fixed battery. Two gates:

1. it must beat the base on gated passes, **strictly**, over a minimum number
   of tasks
2. **decision observability** — when a variant declares a prediction
   (`{metric, expected_delta}`), promotion is **refused** if the prediction did
   not hold, naming predicted versus observed

`PROTECTED_ROLES` may not be varied at all. Nothing on disk changes until
promotion passes; a trial selects the variant through an env var only.
(`test_variants.py`, `test_decisions.py`)

### Replay — `replay.py`

Re-run a recorded decision against a different model or charter and get an
agreement number, instead of an opinion about whether the change helped.

### Benchmark — `benchmark.py`

The lift benchmark: what does the harness actually add to the rented model?
Same battery, harness on and off.

### Model routing that is earned — `modelrouter.py`

`[roles.<r>] route = "auto"` with `route_candidates`. Every finished task
appends one line to `logs/model-outcomes.jsonl`; profiles are computed per
provider/model (n, pass rate, verified pass rate, average cost, replay
agreement). `choose()` returns the **cheapest candidate clearing the bar**
(`route_min_pass`, default 0.8; `route_min_n`, default 5), or falls back to
the static setting **with the reason stated**. (`test_modelrouter.py`)

### Verification hierarchy

1. `verify.py` — mechanical spec checks
2. `citecheck.py` / `memcheck.py` — grounding
3. hidden exams — `exam/` questions the agent never sees in context
4. `designcheck.py` — interface work
5. `conflicts.py --check` — no false certainty on contested points

---

## 11. The control plane

### The panel

```bash
python ui.py            # or bootstrap.py starts it
```

Six sections, named for **jobs rather than architecture** (UI/UX spec §2).
Each states its own purpose in the sidebar:

| Section | Purpose | What is in it |
|---|---|---|
| **Home** | Start work and see what needs attention | command bar, active work, needs-you, recently completed, platform health, Today, live pulse |
| **Work** | Everything being done | missions, goals, teams as threads, workflows, routines |
| **Agents** | Create and manage intelligence | the roster, the creation wizard, one page per agent |
| **Resources** | What agents know and can use | Computers · Tools · Knowledge · Skills |
| **Proof** | Evidence and quality | Work Proof and Platform Proof |
| **Admin** | Infrastructure and policy | Health · Models & cost · People · Audit · Training lab · Backup & release |

Nothing was deleted to get here. The previous top-level views were **moved**,
and `tests/test_frontend.py` asserts that each one is still routed *and* still
reachable from a control a person can click:

| Was | Is now |
|---|---|
| Memory | Resources → Knowledge (and Proof → Work proof) |
| Models | Admin → Models & cost |
| System | Admin → Health |
| Guide | contextual help, and `Go: Guide` in the palette |

A view that is hosted inside another page suppresses its own page title, so
every page has exactly one `<h1>`; opened by name it prints its title as
before.

### Home — §3

A command bar (*"What do you want accomplished?"*) and four primary actions:
**New mission · Create specialist · Build team · Connect tool or computer**.
Typing an outcome and pressing Start opens the mission dialog with the text
carried over, and that dialog **refuses a mission with no success criteria** —
a mission without them can only be abandoned, never finished.

Below it: **Active work** (objective, owner, progress against criteria,
current action, cost, next blocker), **Needs you**, **Recently completed**
with its proof, and a one-line **platform health** verdict — `Ready`,
`1 blocker`, `Ready · 2 risks` — linking to Admin and Proof.

A **first-10-minutes checklist** (§13) sits at the top until it is finished.
Its seven steps read *real state*, not clicks: creating an agent from the
terminal ticks the box exactly as well as doing it in the panel. Dismissible
and resumable.

### Creating an agent — §4

**Five intent questions**, none of which names a lane:

| The question a person answers | What the platform builds |
|---|---|
| working immediately from files or instructions? | Quick specialist |
| formally trained and tested on your material? | Trained expert |
| learn a subject on its own? | Learner |
| start from a proven job template? | Archetype |
| does the work need several specialists? | Team |

Then six steps — **Job · Knowledge · Access · Quality · Cost · Review** —
ending in a plain-language summary of what the agent will be able to know, do,
spend and change. `LANE_STEPS` declares which steps each lane can honour, so a
lane can never reach a step whose answer nothing consumes. The lane name
appears once, in the review, as a footnote.

Everything the later steps collect is applied **after** creation, each through
the endpoint that owns it — the wizard has no private way to write settings.

### One agent — §5

Seven tabs, named for what a person is looking for. *Mind* is gone: it was
evocative and operationally ambiguous.

| Tab | What it holds |
|---|---|
| **Overview** | job, status, blocked questions, courses, approvals, intentions, skills, recent work |
| **Work** | every task, with its stop condition, checkpoints, context window, trace and cards |
| **Knowledge** | the **certification record** (§10), then teach-by-link, teach-by-files and templates |
| **Skills** | self-model, sources/standards/conflicts, context windows, the file tree |
| **Performance** | verified success, false success, the case ledger, cost by purpose, which model actually works here, tool error rates, which computers its work ran on |
| **Access** | the tools it may call, the computers it may use, its file and network scope, pending approvals, and the citation-gated consultation box |
| **Advanced** | Identity & prompts · Models & compute · Raw files |

### The mission page — §6

The centre of the product. Objective and contract fingerprint; the
success-criteria checklist with the evidence behind each met one; binding
constraints; explicit non-goals; **Needs you** separated from **Blocked on**
(the first cannot be solved by trying harder, the second routes somewhere);
bound-action and amendment counts; and, under Advanced, the contract exactly
as the agent sees it, recompiled every iteration.

`mission.compile_state` derives `current_action`, `plan` (every action filed
under the criterion it serves) and `cost_usd`, so a single request answers
every question §15 says a supervisor must answer in fifteen seconds.

### Computers — §7

Resources → Computers. Each card shows the trust zone and what that zone
means, what the machine can do (**declared** capabilities and the ones its
**kind implies**), cost per hour, whether it scales to zero, how long it has
been used, and which agents may access it.

The router answers in a sentence and names the machine, not the backend kind:

> Using Office Windows PC because excel + internal-network are required (no compute cost)

…with a disclosure listing why every other computer was passed over. Work is
placed **cheapest first, then most isolated, then fastest to start** —
isolation outranks speed deliberately, because an organization machine on the
internal network is often free and instant and would otherwise become the
default home for arbitrary model-authored work.

### Proof — §9

Two tabs.

**Work proof** — every mission with its criteria, the evidence behind each met
one, and which are still open.

**Platform proof** — 19 capabilities, each with its level (0 SPEC → 5
PRODUCTION PROVEN), the reason for that level, what a user can actually do
with it, the invariants it must hold, the code hash the evidence is bound to,
and the exact `python tests/…` command that reproduces it.

**No endpoint accepts a level.** The panel can re-run evidence and nothing
else; a level is computed from observations bound to the current code hash and
falls on its own when the code changes or the evidence ages.

### Training reads as certification — §10

Per course: **Sources → Coverage → Gaps → Exercises → Exams → Competence**.
Source authority by tier and unresolved conflicts; requirements with evidence
over requirements required; open gaps; lessons written up over lessons
ingested; the exam score with whether it was closed-book, how many sittings
and when the next one is due; and the competence record.

`/api/experts/<slug>/training` **returns no percentages**. It returns
numerators and denominators, so the page physically cannot print "100%
learned" — `42/42 requirements covered, exam 92%, 3 unresolved conflicts` is a
sentence somebody can check.

### Models are a policy — §11

| Policy | Bar | Tie-break | What it costs you |
|---|---|---|---|
| Cheapest | 50% verified | cheapest | more retries, so the saving is smaller than it looks |
| Balanced *(default)* | 80% verified | cheapest | nothing obvious |
| Highest quality | 90% verified | best rate | money; use it where being wrong is expensive |
| Custom | yours | yours | — |
| Pinned | — | — | nothing is chosen automatically |

A policy is a **name for two numbers the router already read** —
`route_min_pass` and the new `route_prefer`. The policy in force is *derived*
by comparing settings to the presets rather than stored, for the same reason
proof levels are derived: a stored label drifts from what it describes.

Every model card carries its sample size. A profile measured over fewer than
`MIN_PROFILE_SAMPLE` (5) tasks is shown as **unrankable**, never ranked badly.

### Who may do what — spec §2 Admin, manual §21

`org.py` says `check()` is *"the single question every mutating path asks"*.
Until this pass the panel — the main mutating path — never asked it, because
one shared token left it no way to know who was calling. Now:

- each member can hold a **personal bearer token** (`python org.py token
  <email> --as you@…`, or *give one* in Admin → People). The value is returned
  once and never stored; only its SHA-256 is kept
- `_authed` resolves the token to a member before every request, and
  `_may_write` looks the required permission up in a **declared table** — a
  route with no entry falls through to `create_agent`, so a route added
  tomorrow is refused for a viewer rather than waved through
- the audit trail records the **token's owner**, never an actor named in the
  request body
- a fleet that **belongs to an organization auto-enables a token**, for the
  same reason an exposed one does: with nothing to check, `_authed` returns
  early, every caller resolves to the owner, and the roles somebody configured
  govern nothing. The panel says so on start-up and points at
  `python org.py token`
- with **no organization**, `org.check` returns True for everything, so a solo
  install behaves exactly as it always did

`tests/test_rbac.py` enumerates it: every write route refused for a viewer,
the operator/builder boundaries, that no POST route is ungated by omission,
and that a request claiming a different author is recorded against the real
one.

### When something fails — §12

`diagnose(task)` translates one task record into three answers, in one place,
so the board, the dialog and Home cannot disagree about what went wrong:

| Which part failed | Example headline |
|---|---|
| the verifier | "The check refused the work after 6 attempts" |
| the platform | "The platform itself failed, not the agent" |
| the model provider | "The model provider refused the call" / "Rate-limited" |
| the budget breaker | "It stopped because it hit a spend limit" |
| the command it ran | "A command it ran never finished" |
| you | "It is waiting for a decision only you can make" |
| the agent | "It could not complete the task" |

Each carries **what happens next** and **what you can do**. The raw error sits
under an Advanced disclosure; the task board shows state *and* reason, because
a status nobody can act on is a status nobody reads.

On a phone it becomes a bottom-nav app: single column, full-screen dialogs,
40px targets.

### Live events

`GET /api/events` is a Server-Sent Events stream: the last 30 feed rows on
connect, then every expert's log tailed live and mapped to typed events. The
6-second poll is kept as a fallback. Token-guarded like the rest of the API.
(`test_events.py`)

### Generative UI, safely — `uicards.py`

An agent may return a structured card by emitting `<<<UI-CARD {json}>>>`.
The catalogue is **closed**: `table`, `checklist`, `diff`, `metric`. Anything
else is logged as `ui_card_invalid` and dropped. The client escapes all
content and never renders markup. (`test_uicards.py`)

### Traces — `trace.py`

One trace per task, built from what the harness already writes: model turns
with token deltas, tool spans with milliseconds, gates, approvals,
compactions, routing. Plus `tool_stats` — **per-tool error rates**, so "the
agent is flaky" becomes "this one tool is failing 40% of the time".

### Chief of staff — `chief.py`

Answers "what should I do today?" from real state, ranking nine actions:
`APPROVE` `ANSWER` `RESTART` `FUND` `REPAIR` `PREPARE` `REVIEW` `HARVEST`
`ADVANCE`.

### Doctor and bootstrap

`doctor.py` imports all 44 core modules, checks prompts, keys, tools and
health, and prints a `[readiness]` section naming ENV vars (never values).
`bootstrap.py` is the one command that gets from nothing to running, exit 0
runnable / 2 blocked with a numbered list.

---

## 12. Interop

### MCP — `mcp.py`

A client for **both** protocol eras, so old and new servers work. Servers are
declared in an `mcp.json` (§15) with `approval`, `allow_roles`, `allow_tools`,
`deny_tools`, `require_approval`, `no_approval`. Tool results are fenced like any other untrusted content;
`isError` is surfaced loudly; a wedged tool times out in seconds; an unknown
server is refused with the configured list. Destructive tools route through
approvals. (`test_mcp.py`)

### A2A and federation — `federation.py`

An agent card, a fleet identity with a fingerprint, and peers. Another owner's
agents can work with yours **without trust**: claims arrive quarantined, and
what a peer says is evidence, not fact. (`test_federation.py`)

### Providers — `providers.py`

Any OpenAI-compatible endpoint: OpenRouter, DeepSeek, Groq, NVIDIA, Hugging
Face, a local server. Per role: provider, model, fallback, escalation target,
prices. Live catalogue browsing from the panel.

---

## 13. Where commands run

`[agent] sandbox = "docker" | "host" | "e2b" | "daytona"`.

- **host** — this machine, under `policy.py`
- **docker** — a throwaway container at `/work`, `--network none` by default,
  1GB memory, 256 pids
- **e2b / daytona** — hosted microVM sandboxes behind their API keys

**`host` is refused by default.** It is not isolation — a model-authored
process reaches the whole machine, and a detached child outlives the check
that would have caught it. An owner who wants it for a trusted development
fixture must also write `allow_unsafe_host = true`; every refusal names
that key.

**Fail closed.** A configured-but-unavailable backend returns exit 127 with
the reason and runs **nothing** on the host. Policy runs first in every
backend.

**Credentials are withheld.** Every model-written command gets a scrubbed
environment: any name matching `*KEY*`, `*SECRET*`, `*TOKEN*`, `*PASSWORD*`,
`*CREDENTIAL*`, `*AUTH*`, `*COOKIE*`, `*SESSION_ID*` is removed, so `env`
cannot leak your keys into a transcript. Two narrow exceptions: the platform's
own helpers get exactly one key for exactly one command shape
(`ingest.py transcribe` → `GROQ_API_KEY`), and `[agent] command_env_allow`
passes named variables through.

**Timeouts report independently.** A killed command returns exit 124, says it
timed out, and keeps whatever it printed first.
(`test_sandbox.py`, `test_secrets.py`)

---

## 14. Data layout on disk

```
<fleet home>/
  agent.env                    your keys (never packaged, never logged)
  prompts/                     fleet-default role prompts
  commons/
    lessons.md                 append-only ledger of mistakes
    lessons.curated.md         the derived, merged view
    edits.jsonl                every curation operation
    knowledge/<topic>.md       corroborated facts
    quarantine.md              withdrawn claims, struck through
    directory.md               who knows what
    pins.md                    owner pins, injected first
    failures/<category>.jsonl  16 categories
    competence/<expert>.jsonl  measured outcomes
  experts/<slug>/
    identity.md                who it is
    settings.toml              its budgets, roles, providers, sandbox
    reputation.md
    state.json                 the hot queue (stays small forever)
    archive/tasks.jsonl        every task ever finished
    blocked.md                 questions waiting on you
    inbox/                     drop files here
    events/                    wake payloads
    checkpoints/               resumable long jobs
    approvals/                 pending and decided
    routines/                  standing arrangements
    skills/
      graph.json               status, wins, losses, provenance
      <name>.md                flat playbook
      <name>/SKILL.md          folder playbook (+ scripts/)
    gotchas/                   general and per-MCP-server
    courses/<course>/
      source/                  the originals
      lessons/NN/              extracted text, notes
      index.md  spec.md  notes.md  gaps.md
      lessons-learned.md  retractions.md
      sources.json             the authority ledger
      conflicts.json/.md       the rulings
      standards.md             the bar
      gotchas.md
      exam/  exam-results.md  artifacts/
    contexts/
      <task>.json              the live transcript
      <task>.compile.json      what went into the window and why
      <task>.archive.jsonl     verbatim turns compaction paged out
      archive/                 finished transcripts
    logs/
      agent.log                every event, JSON per line
      commands.log             every command attempted
      effects.jsonl            exactly-once side effects
      model-outcomes.jsonl     routing evidence
      health.json harness.json the last health ritual
```

---

## 15. settings.toml, every key

```toml
[agent]
max_steps = 150                     # steps per task
command_timeout_seconds = 300
model_timeout_seconds = 180
poll_interval_seconds = 10          # idle sleep
context_token_threshold = 50000     # compaction trigger
context_keep_recent_messages = 10   # kept verbatim at the tail
max_malformed_tool_calls = 3
lock_stale_minutes = 30
runner_lease_seconds = 900          # see below — a backstop, not the mechanism
reflect_after = ["practitioner"]    # roles that trigger reflection
exam_threshold = 90                 # pass mark
reexam_days = [7, 30, 90]           # spaced repetition
max_skills_loaded = 3
max_task_retries = 2
auto_scan_inbox = true
inbox_settle_seconds = 10
daily_budget_usd = 0                # 0 = off
max_task_usd = 2.0                  # 0 = off
max_done_rejects = 6
escalate_after_errors = 3
max_output_tokens = 0               # 0 = provider default
retain_finished_tasks = 150
sandbox = "docker"                  # docker | host | e2b | daytona
allow_unsafe_host = false           # `host` is REFUSED unless this is true
sandbox_network = false             # docker egress
sandbox_image = "python:3.12-slim"
command_env_allow = []              # named keys a command may see
design_gate = true                  # gate interface deliverables
chain = { practitioner = "examiner" }
```

**`runner_lease_seconds`.** A task marked `running` means either *a loop is
working on it right now* or *a loop died holding it*, and treating the first
as the second makes two loops execute one task (U15). Each loop records
itself on the task it claims — id, pid, host, timestamp — and refreshes that
timestamp on every commit. Another loop may take the task over only when the
owner is demonstrably gone.

On the **same host** liveness is the whole answer: an owner whose process is
alive is never overtaken, however old its timestamp, because a loop parked in
a twenty-minute provider call is healthy rather than stale; an owner whose
process is gone is recovered immediately, which is the crash recovery this
was always meant to provide. `runner_lease_seconds` applies only when
liveness cannot be asked — the owner recorded a **different host**, so its pid
number means nothing locally. Raise it if several machines share one expert
directory over a network filesystem and you would rather wait than risk a
double run; the default of 15 minutes is already far longer than any single
step.

```toml
[agent.context_budget]              # per-source token budgets
memory_files = 12000

[agent.memory_router.practitioner]  # override which kinds a role sees
kinds = ["self", "course", "memory_files"]

[agent.source_tier]                 # your own authority ratings
"internal.wiki" = 2

[agent.command_policy]
deny = ["\\bterraform\\s+destroy\\b"]
[agent.command_policy.ripper]
allow = ["^python3? ingest\\.py "]

[providers.openrouter]
type = "openai"                     # or "mock" for scripted offline testing
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
native_tools = true                 # false → the inline-JSON tool format
input_per_mtok = 0.15               # USD per 1M input tokens (cost metering)
output_per_mtok = 0.60              # USD per 1M output tokens

[roles.practitioner]
provider = "openrouter"
model = "..."
fallback_provider = "..."
escalate_provider = "..."           # used on hard steps
escalate_model = "..."
tools = ["read_file", "write_file"] # the Rule of Two
route = "auto"                      # earn the model choice
route_candidates = ["openrouter:cheap", "openrouter:strong"]
route_min_pass = 0.8
route_min_n = 5

```

**MCP servers are configured separately**, in an `mcp.json` searched for
beside the expert, then at the fleet home, then beside the code:

```json
{"servers": {
  "db": {
    "cmd": "python", "args": ["path/to/server.py"], "env": {},
    "approval": "destructive",
    "allow_roles": ["practitioner"],
    "allow_tools": ["query"], "deny_tools": ["drop_table"],
    "require_approval": ["delete_record"], "no_approval": ["ping"]
  }
}}
```

---

## 16. Every command

| Command | What it does |
|---|---|
| `python bootstrap.py` | set up and start everything; exit 2 = blocked with a numbered list |
| `python doctor.py` | health + readiness verdict |
| `python harness.py [--json\|--check]` | the harness manifest / contract check |
| `python demo.py` | the whole platform, keyless |
| `python loop.py run [--drain] --root <e>` | run an agent's loop (also `status`, `course`, `answer`) |
| `python loop.py add --role R --goal G [--done-check C] [--stop-*]` | queue a task |
| `python loop.py check --root <e>` | probe every role's provider |
| `python fleet.py create "Name" --identity "..."` | new expert (also `list`, `delete`) |
| `python quick.py spin "Name" --goal "..." [--template T] [--file F] [--deliverable P]` | ⚡ lane (`quick.py templates` lists archetypes) |
| `python team.py run "goal" --experts a,b,c` | 🤝 lane (also `list`, `result`) |
| `python templates.py` | the 20 archetypes |
| `python goal.py pursue "goal" --expert <slug>` | pursue until a judge agrees (also `list`, `show`) |
| `python workflows.py run <spec.json> --root <e>` | staged pipeline (also `list`) |
| `python consult.py ask "question" --root <e>` | citation-gated answer (also `list`) |
| `python ingest.py url\|add-folder\|scan-inbox\|pdf-text\|transcribe\|vision\|... ` | teach it anything |
| `python memory.py map\|failures\|competence\|search\|retire\|restore` | the memory institution |
| `python skills.py status\|list\|import\|export\|promote` | procedural memory |
| `python sources.py [--classify U] [--course C] [--set S --tier N --why W]` | the authority ledger |
| `python conflicts.py --course C [--write\|--check FILE\|--goal G]` | contradiction rulings |
| `python standards.py --course C [--extract\|--add TEXT]` | the bar |
| `python selfmodel.py --root <e> [--role R]` | the self-model |
| `python designcheck.py <file\|dir> [--course C] [--strict]` | the design gate |
| `python gotchas.py [--goal G]` | what it already burned itself on |
| `python premise.py "goal" --root <e>` | does memory contradict this task? |
| `python memrouter.py --role R --goal G` | which memory kinds a task may see |
| `python context.py [--task ID]` | the exact window a task was given |
| `python trace.py --task ID \| --tools` | spans / per-tool error rates |
| `python modelrouter.py [--role R]` | measured profiles and the routing decision |
| `python routines.py save <task-id> --every-days 1` | standing arrangement (also `list`, `cancel`) |
| `python checkpoint.py --root <e>` | resumable jobs |
| `python sandbox.py [--run CMD]` | the execution backend |
| `python variants.py spawn\|trial\|list` | charter evolution (promote/rollback are panel actions) |
| `python approvals.py list\|grant\|deny` | the human-in-the-loop ledger |
| `python replay.py --root <e> [--task ID] [--role R] [--last N]` | re-run decisions against the record |
| `python benchmark.py run --expert <slug>` / `suite` | the lift benchmark / show the battery |
| `python recall.py "query"` | search everything |
| `python mcp.py list\|tools\|call\|catalog\|enable` | MCP client |
| `python federation.py card\|peers\|serve\|trust\|ask` | A2A identity and peers |
| `python commons.py show\|learn\|note\|ask` | shared memory + peer questions |
| `python chief.py` | what should I do today |
| `python toolbox.py` | what this machine can actually do |
| `python verify.py <course>` / `citecheck.py <file>` / `memcheck.py` | the verification layers |
| `python package.py` | ship a clean zip |
| `python ui.py [--port N] [--token T]` | the control panel |

---

## 17. Every HTTP endpoint

Derived from `ui.py`, not from memory — 51 read routes, 18 write routes and
23 per-expert actions.

**Read (GET) — the fleet**

`/api/system` `/api/systems` `/api/experts` `/api/feed` `/api/events` (SSE)
`/api/memory` `/api/retired` `/api/commons` `/api/commons/pins` `/api/goals`
`/api/team` `/api/templates` `/api/toolbox` `/api/briefing` `/api/doctor`
`/api/harness` `/api/readiness` `/api/federation` `/api/gates`
`/api/missions` `/api/org` `/api/audit` `/api/training` `/api/workers`
`/api/proof` `/api/proof/<capability>`

**Read (GET) — one expert**

`/api/experts/<s>` and, under it: `tasks` `tree` `file` `settings` `skills`
`variants` `approvals` `prospective` `workflows` `models` `context` `trace`
`harness` `identity` `routines` `self` `knowledge` `acquisitions` `spend`
`missions` `missions/<id>` `performance` `policy` `training`

**Create (POST)**

`/api/experts` (trained lane) · `/api/quick` (⚡ lane) · `/api/learner`
(📚 lane) · `/api/team` · `/api/missions` · `/api/workers` ·
`/api/workers/<id>/state` · `/api/workers/choose` · `/api/org` ·
`/api/org/users` · `/api/curriculum` · `/api/proof/refresh` ·
`/api/preflight` · `/api/backup` · `/api/federation` ·
`/api/retired/<s>/restore` · `/api/shutdown`

**Act (POST `/api/experts/<slug>/<action>`)**

`task` `goal` `consult` `answer` `start` `stop` `launch` `template` `url`
`scan` `intention` `wake` `workflow` `variant` `approval` `skill` `routine`
`provider` `role` `policy` `verify` `memcheck` `probe`

**Edit (PUT):** `/api/experts/<s>/identity` · `/api/experts/<s>/file` ·
`/api/commons/pins`

**Delete:** `/api/experts/<slug>` (retire; `?purge=1` to remove)

### What the API deliberately will not do

- **Set a proof level.** `/api/proof/refresh` re-runs the evidence; nothing
  accepts a level. A status somebody can click green is a status nobody can
  trust.
- **Take a raw shell command as a definition of done.** `/api/experts/<s>/task`
  accepts a gate *specification* from the closed catalogue in `gates.py`; a
  free-form string is refused.
- **Reveal a credential.** Keys are reported present or absent. There is no
  route that returns one, and `/api/toolbox` reports only the environment
  variable names.
- **Accept a cross-origin write.** Every mutating verb requires a same-origin
  request whether or not a token is set (`test_csrf.py`).

All of it is guarded by the same token when you start the panel with
`--token`, as an `Authorization: Bearer` header. The stream is read with `fetch` rather than `EventSource`
cannot send headers.

---

## 18. Every event name

Written as JSON lines to `logs/agent.log`, streamed to the panel:

`agent_start` `task_start` `task_end` `task_unblocked` `done_refused`
`stop_condition` `retry_queued` `retries_exhausted` `escalated` `tool_error`
`command_refused` `approval_required` `step_crash` `provider_failure`
`budget_exceeded` `task_cost_ceiling` `drain_complete` `drain_budget_stop`
`prospective_check_failed` `chain_queued` `reflection_queued` `skill_status`
`skill_record_failed` `failure_recurred` `memory_file_failed` `gotcha_filed`
`gotcha_failed` `premise_warning` `model_routed` `route_record_failed`
`compaction_incomplete` `tool_results_cleared` `health_ritual`
`trajectory_opened` `trajectory_closed` `trajectory_refused`
`trajectory_close_failed` `procedure_compiled` `procedure_compile_refused`
`procedure_evaluated` `procedure_evaluation_refused` `procedure_route`
`procedure_route_rejected` `procedure_route_skipped`
`scheduler_record_failed`
`health_ritual_failed` `harness_manifest_failed` `state_corrupt`
`state_trimmed` `archive_failed` `lock_break` `inbox_scanned`
`exam_dispatched` `reexam_queued` `reexam_scheduled` `gaps_queued`
`ui_card` `ui_card_invalid`

---

## 19. The test suite as the specification

```bash
python tests/run_all.py          # 93 tests, ~5 minutes
```

The tests are not unit tests of functions; each is an acceptance test of a
claim, and each prints `[section]` lines saying what it proved in English.
When this document and the tests disagree, **the tests are right**.

Highlights: `test_e2e_crash` kills the process mid-lifecycle and proves it
resumes · `test_faults` breaks every contract on purpose and proves the
validator catches it · `test_exam` proves closed-book by context *and* by
tools · `test_secrets` proves no key value reaches a transcript, log or state
file · `test_ecosystem` runs every subsystem as one organism ·
`test_invariants` enumerates every reachable path instead of exercising one
example of one · `test_ux` executes the UI spec's own acceptance table.

### Mutation testing — `python mutate_check.py`

The question that decides whether a test is worth anything is not *does it
pass*, it is **would it fail if the feature were removed**. A test that would
pass either way measures nothing, and there is no way to tell from reading it.

`mutate_check.py` answers that mechanically. For each load-bearing behaviour
it edits the module to break it, runs the single test that claims to cover
it, requires that test to FAIL, and reverts:

```
CAUGHT  docker: egress allowed by default          test_docker_live.py
CAUGHT  docker: timeout leaves the container       test_docker_live.py
CAUGHT  docker: credentials passed through         test_docker_live.py
CAUGHT  provider: no Authorization header          test_live_provider.py
CAUGHT  provider: malformed body kills the task    test_live_provider.py
CAUGHT  provider: 4xx retried like weather         test_live_provider.py
CAUGHT  package: ship the credential file          test_package.py
CAUGHT  endurance: never archive finished work     test_endurance.py
CAUGHT  rbac: every write allowed                  test_rbac.py
CAUGHT  fleet: creation stops seeding the home     test_invariants.py

10 mutations: 10 caught, 0 missed
```

A **MISSED** row is a defect in the test, not in the platform, and is treated
as one. A test whose prerequisite is absent (docker on a machine without a
daemon) reports **SKIP** rather than MISSED, because calling a skipped test a
missed mutation would raise a false alarm on every machine without docker.

It runs in CI on Linux/3.12. It is declared in `execution.ALLOWED_RAW` with
its reason rather than exempted silently — an audit with an undeclared
exception is an audit with a hole, and this file was in fact caught by that
audit before being declared.

**What it does not do.** It mutates ten behaviours, not every line. It is a
spot check on the tests that carry the heaviest claims, not a coverage
metric, and a green mutation run says nothing about the tests it did not
mutate.

### The two files that enumerate rather than exemplify

`test_invariants.py` is the answer to the audit's central finding — *a control
defends the path its author was thinking about*. It does not test behaviour
through an example; it walks the tree:

| Check | What it enumerates |
|---|---|
| execution paths | every subprocess call site in 69 modules |
| execution catalogue | every declared operation, against what it declares |
| filesystem zones | every declared control file and directory |
| traversal spellings | 12 escape forms (posix, windows, UNC, mixed, nested) |
| credential sources | all 4, asked of every subsystem that must exclude them |
| metering purposes | all 9 call purposes |
| role capabilities | all 9 roles against what their job needs |
| gate catalogue | every entry, and that a raw shell string never builds one |
| expert birth | every module that mints an expert |
| exam readers | every reader of `exam-results.md`, in every recorded format |
| sandbox names | all 139, across 93 test files, parsed with `ast` |
| documented CLI | all 58 subcommands `MANUAL.md` promises |

The last four came from the third pass, and each was a real defect first.

---

## 19a. The UX release gate — spec §17

The redesign spec is explicit that *"the redesigned UI is not accepted because
it looks cleaner"*. Its release conditions split cleanly into what a machine
can settle and what it cannot, and pretending otherwise would be the same
mistake as a proof level somebody can click:

| §17 condition | Status |
|---|---|
| Regression: existing UI API tests plus new task-based tests | **Met.** `test_frontend.py` + `test_ux.py` + `test_rbac.py`, 93 tests green twice consecutively |
| Safety: destructive UI actions match CLI confirmation semantics | **Met.** Retire, purge and approval all go through the same modules the CLI calls; `test_ux::check_proof_in_one_click` also asserts the API refuses to set a proof level at all |
| Builder test: the owner can explain every top-level nav item | **Met.** Each of the six states its purpose in `NAV_PURPOSE`, and the palette shows the equivalent CLI for every action |
| Accessibility: keyboard navigation and focus order | **Partly.** ⌘K palette with arrow keys and Enter, Escape closes, 40 px targets, labels on every field. Contrast and focus order have **not** been audited with a tool |
| 5-user formative test, ≥90% task completion | **Not done.** This needs five people, and nothing in this repository can substitute for them |
| ≤2 wrong-navigation events, median, on critical flows | **Not measured.** Same reason |

The first three are the ones a build can honestly claim. The last two are
stated here as *not done* rather than quietly omitted, because a release gate
with an unmeasured condition reported as met is a release gate that does
nothing.

---

## 20. Honest limits

Things this platform does **not** do, that you might reasonably assume it does:

1. **No weight training.** "Learning" here is non-parametric: memory, skills,
   charters, routing. Nothing fine-tunes a model.
2. **The design gate cannot judge beauty.** It catches mechanical failures and
   the common fingerprints of unconsidered output. A page can pass every check
   and still be dull.
3. **Conflict detection is conservative and text-based.** It finds polarity
   flips and numeric disagreements between claims about the same subject. It
   will miss contradictions expressed in ways those rules do not cover, and it
   has no semantic model of your domain.
4. **Authority tiers are heuristics.** The domain table is small and honest;
   anything unrecognised is rated by kind. Your own overrides are the fix.
5. **The self-model is a report, not introspection.** It describes ledgers. It
   has no access to the model's internal state, and it is not consciousness.
6. **`host` sandbox is not isolation.** Policy limits what may be attempted,
   not what a determined command could do. For untrusted work use `docker`, or
   a hosted microVM.
7. **File-backed means file-scale.** Ledgers are read and rewritten; this is
   fine for a fleet of experts and years of tasks, not for millions of rows.
8. **Cost control is a brake, not a guarantee.** Budgets are enforced between
   steps; a single very expensive call can still overshoot its task ceiling.
9. **No provider has been benchmarked here.** Every model call in development
   ran against the scripted mock provider by design. The first real-key run is
   yours.
10. **The UI has not been tested with users.** Spec §17 asks for a five-person
    formative test at ≥90% task completion. That has not happened, and no
    amount of green tests substitutes for it — what `test_ux.py` proves is
    that the information each flow needs is reachable, not that a stranger
    finds it.
11. **Accessibility is unaudited.** Keyboard navigation, focus order, labels
    and 40 px targets are in place and asserted; contrast ratios and screen
    reader behaviour have not been checked with a tool.
12. **Windows and OneDrive were the development environment, and the first
    Linux run found four defects.** Every write retries; sandboxes live in
    the system temp directory on purpose. The CI workflow has now executed
    on real runners across Ubuntu and Windows × Python 3.11/3.12/3.13, and
    four of the six jobs failed. Every failure was real: a running task
    could be taken from a live sibling loop and executed twice (invisible on
    an idle laptop, 3 failures in 12 runs on one contended CPU); a container
    ran as root and handed the agent back a workspace it could not write to;
    a secret was created world-readable by a path that never called chmod;
    and one test asserted isolation with a fact that is only a fact on
    Windows. All are fixed and each is held closed by a test and a
    mutation. It took **four CI runs** to stop finding defects: each run's
    failures had been masking the next one's, and runs two and three failed
    on the mutation harness and the inbox rather than on the suite. All six
    jobs are green as of the fourth, with 15 of 15 mutations caught. See U15–U18 in `GAPS_RISKS_AND_UNFINISHED.md`. The standing
    lesson: **one machine is one machine**, and a green suite on it says
    nothing about the next one.
13. **The panel's master token is still a master key.** Members hold personal
    bearer tokens and every write is checked against the role that token
    belongs to — but whoever holds the token the panel was *started* with
    resolves to the owner and can do everything. That is honest rather than
    accidental: the master token already implies control of the process. Give
    people their own tokens (`python org.py token <email> --as you@…`) and do
    not hand the master one to anybody you would not give the server to.
14. **There is no password, no session and no TLS.** Authentication is a
    bearer token over a loopback HTTP server. For anything beyond a machine
    you control, put it behind something that does have those.

---

## 21. Running it in production

### The one command that answers "is this fit to run?"

```bash
python preflight.py                    # exit 0 ready · 1 risks · 2 blocked
python preflight.py --exposed --json   # audit as if the panel is public
```

`doctor.py` says the software is healthy. `harness.py --check` says the
contracts hold. `preflight.py` answers the owner's question — *if this runs
unattended for a month, what will hurt?* — as **blockers, risks and notes,
each with the exact command that fixes it**:

| Area | What it checks |
|---|---|
| cost | every settings file has a daily breaker and a per-task ceiling |
| secrets | credential files are owner-only; how many copies exist |
| backups | one exists, it is recent, **its checksums verify**, and it covers every expert |
| capacity | disk headroom, oversized log directories |
| resilience | roles without a fallback provider; experts running commands on the host |
| verification | harness contracts hold; CI present |
| governance | approvals and questions waiting on a human |
| access | token protection when exposed, and the single-owner limitation |

A check that throws is reported as a failed check — the audit still returns a
verdict, because a preflight that crashes is worse than one that fails.

### Backups: the memory is the asset

Code can be re-downloaded; three months of an expert's study cannot.

```bash
python backup.py create --home . --out ../fleet-backups
python backup.py verify ../fleet-backups/fleet-2026-08-22-031217.zip
python backup.py restore <archive> --dest ./restored
python backup.py list ../fleet-backups
```

- **Carries** identities, settings, courses, cited notes, skills, commons,
  state, archives, transcripts, intentions, routines, approvals, gotchas.
- **Never carries** `agent.env`, `ui-token.txt` or federation identity keys —
  backups get synced, emailed and left on laptops, and one that carries
  credentials turns every copy into a breach. Restore therefore ends by
  telling you to put the keys back.
- **Excludes `logs/` by default** (regenerable, and most of the bytes);
  `--with-logs` when the audit trail matters more than the size.
- Every archive carries a manifest with a **SHA-256 per file**. `verify`
  recomputes them, so "is this backup intact?" has an answer. A damaged
  archive is refused by `restore` and reported as a **blocker** by the
  preflight — not discovered on the day you need it.
- `restore` refuses a non-empty destination unless `--force`, and refuses any
  entry whose path escapes the destination.

Schedule it with the platform's own scheduler, cron or Task Scheduler:

```bash
python routines.py save <task-id> --every-days 1      # if an agent runs it
0 3 * * *  cd /home/agent/agent && python backup.py create --out /backups
```

### Exposure and access

The panel binds `127.0.0.1` by default. Binding anything else **auto-enables
token auth**, generates a token, writes it to `ui-token.txt` (mode 0600) and
prints it. The token guards the whole API; the page itself carries no data.

The transport is still plain HTTP, so put it behind **Tailscale** (the
shipped `setup-remote.sh` does this) or an HTTPS reverse proxy. Never plain
HTTP on the open internet. `docker-compose.yml` publishes to `127.0.0.1` only
and applies resource limits so a runaway agent cannot take the host with it.

### Cost control

Caps ship on and are inherited by every expert created afterwards:
`daily_budget_usd = 10` (fleet breaker) and `max_task_usd = 2.0` (per task).
The breaker is checked between steps, so a single very expensive call can
still overshoot its task ceiling — set provider-side spend limits too, at
every provider, before first use.

### Upgrades

`harness.HARNESS_VERSION` is the platform version, and it is recorded in
every backup manifest and the harness manifest, alongside a `sha256[:12]` of
each prompt and core module — so you can tell whether the thing running is
the thing you reviewed. The upgrade procedure is: **back up, verify the
backup, replace the code, run `python doctor.py` and `python harness.py
--check`, run the suite, then start the loops.** State files are read
defensively (a corrupt one is quarantined and rebuilt), but there is no
automatic schema migration — that is what the backup is for.

### CI

`.github/workflows/tests.yml` runs on Ubuntu and Windows across Python
3.11/3.12/3.13: it asserts no dependency file has appeared, imports every
core module, checks the harness contracts, runs all 76 tests, and builds the
package asserting it carries no secrets and no expert data. It needs no
secrets because every model call in the suite goes to the scripted mock —
which is also its limit: a green run proves the harness holds, not that any
provider works. `python loop.py check` is the live probe, and it belongs in
your deploy.

### When something goes wrong

| Symptom | First move |
|---|---|
| an agent is "running" but nothing happens | `python doctor.py` — a wedged loop is caught by its heartbeat; restart it |
| spend looks wrong | `python trace.py --task <id>` for one task; `chief.py` for today's total |
| a tool keeps failing | `python trace.py --tools` — per-tool error rates separate a bad tool from a bad agent |
| an answer looks invented | open the task's **context window** (`python context.py --task <id>`): it shows exactly what the model was given |
| the fleet disagrees with itself | `python conflicts.py --root experts/<slug> --course <c>` |
| state file corrupt | it is quarantined and rebuilt automatically; the archive keeps every finished task |
| you need last week back | `python backup.py restore <archive> --dest ./restored` |

---

## 22. Definition of Done, release gates, and where this build actually stands

The engineering manual's §26 and §27 define what "finished" means and which
gate each kind of release must clear. Both are reproduced here **with this
build's real position against them**, because a gate table whose rows are all
green is a table nobody consulted.

### 22.1 Definition of Done — §26

> *A feature is not Finished because code compiles or the author says it works.
> Finished is a generated evidence state.*

| Check | Pass condition | This build |
|---|---|---|
| **Contract** | capability, criteria and invariants written before implementation | **Met** — `proof.REGISTRY` states each capability's sentence and its invariants; `mission.py` refuses a mission with no criteria |
| **Tests** | targeted tests cover alternate paths and fail before the fix | **Met** — every `U`-numbered defect had a failing test first; `test_invariants.py` enumerates paths rather than exemplifying them |
| **Security** | threat model reviewed for network, filesystem, secrets, execution, approvals, effects | **Met for those six**; the seventh — authorization — was reviewed only in this pass, and that is exactly where `U10` was hiding |
| **Observability** | trace/log/evidence explains the feature afterwards | **Met** — per-task traces, per-call metering, an append-only audit trail, and `evidence.py` |
| **Failure semantics** | timeout, restart, partial failure and retry defined | **Met** — `test_chaos.py` kills the process at every lifecycle point; stop conditions, checkpoints and retry budgets are declared per task |
| **Cost** | metered and bounded on every path | **Met** — every provider call goes through `modelgateway`, and `test_invariants` asserts all nine call purposes reach the meter |
| **Live integration** | required when the feature claims real provider/sandbox/tool support | **NOT MET, and no capability claims it.** Every model call in every test is the scripted mock. `proof.py` reflects this: nothing is above level 2 |
| **Benchmark** | required for a better/smarter/faster/cheaper claim | **N/A** — this build makes no such claim. `benchmark.py` exists and is exercised offline |
| **Full regression** | full suite + adversarial suite pass twice from a clean state | **Met** — 93 tests, twice consecutively, `test_chaos.py` among them |
| **Proof Pack** | generated with code/config hashes, commands, results, artifacts | **Met** — `proof.py` binds every observation to a code hash and prints the reproducing command |
| **UI status** | Proof Center shows the level; no manual green toggle | **Met** — no endpoint accepts a level; `test_ux.py` asserts it |
| **Rollback** | upgrade and rollback path tested for production-affecting change | **Partly** — `backup.py` create/verify/restore is tested and `training.rollback` is tested; there is no tested upgrade path between platform versions |

### 22.2 Release gates — §27

| Release | Minimum gate | Position |
|---|---|---|
| **Developer build** | offline suite + harness + no unexplained changes | **CLEARED.** 93 tests twice, `harness.py --check` exit 0, working tree explained by this changelog |
| **Local owner beta** | P0/P1 invariants fixed · real provider smoke · local Docker live test · backup/restore test | **NOT CLEARED.** P0/P1 fixed (2 P0s, 12 P1s, plus `U1`, `U2`, `U10`) and backup/restore tested — but **no real provider has ever been called** and **Docker has never been exercised**. Two of four |
| **Private cloud beta** | authentication, RBAC, TLS, secret manager, worker isolation, transactional state, live cost breakers, audit-by-user | **NOT CLEARED.** RBAC and audit-by-user now exist and are enforced on every path (`test_rbac.py`); cost breakers exist and are tested offline. **Authentication is a bearer token over plain HTTP**, there is no secret manager, state is files rather than transactions, and worker isolation is a record rather than a container |
| **Organization pilot** | tenant isolation, edge-worker policy, MCP integrations, SLO telemetry, incident rollback, 24/7 endurance | **NOT CLEARED.** None of these exist. `workers.py` models the policy; nothing enforces it on a real machine |
| **Training Lab beta** | immutable verifier boundary, hidden evals, model registry, rollback, reward-hacking suite | **PARTLY.** The verifier boundary, the held-out split, the registry and rollback are built and tested (`test_training.py`); there is **no reward-hacking suite**, and the lab performs no gradient updates at all — which it says on every export |
| **Production "autonomous specialist"** | domain benchmark beats predefined baselines on quality, false-success, safety, cost and intervention | **NOT CLEARED, and not close.** No domain benchmark has been run against a baseline. This is the gate the whole platform points at |

### 22.3 Build status against §24

The manual's §24 table listed seventeen systems. Six have moved:

| System | §24 said | Now |
|---|---|---|
| Model routing | PARTIAL | **BUILT** — per-call attribution and universal metering (`modelgateway`), exploration of unproven candidates, and a named policy with a configurable tie-break |
| Security/control plane | **DEFECTIVE** | **BUILT** — five authorities, CSRF closed, secrets centralised, and (this pass) authorization enforced on the panel |
| Backups/package | PARTIAL | **BUILT** — one canonical secret inventory (`credentials.py`) used by backup, package, health and runtime alike; restore is tested |
| Proof Center | PARTIAL primitives | **BUILT** — 15 capabilities, levels derived from hash-bound evidence, visible in the UI, unsettable by hand |
| Training Lab | MISSING | **BUILT, within a stated boundary** — trajectory store, sanitised export, deterministic split, registry, promotion gate, rollback. No gradient updates, and it says so |
| Autonomous tool acquisition | MISSING | **BUILT** — the full ladder: search → inspect → install in a disposable worker → mandatory capability test → owner promotion |

**Unmoved, and honestly so:** cloud product (MISSING — auth, tenancy, state
service, queue, TLS, billing), and the live half of everything above.

### 22.3b The blocking-remediation list — §25

The manual makes twelve items blocking *"before feature expansion or cloud"*.
Eleven are done; the twelfth is by definition what comes next.

| # | Item | State |
|---|---|---|
| 1 | version control, known-good baseline | **done** — git, with the remediation split across commits |
| 2 | no browser-origin/CSRF into mutating APIs; no free-form network-supplied shell gates | **done** — `_same_origin` on every mutating verb (`test_csrf.py`); `gates.py` is a closed catalogue and a raw string is refused |
| 3 | one canonical Execution Authority; no alternate path may exist | **done** — `execution.py`, and `--audit` scans all 69 modules for a bypass (`test_invariants.py`) |
| 4 | agent workspace separated from control state; all filesystem ops through File Authority | **done** — `fileauth.py` with four zones, enforced per zone rather than per file |
| 5 | `file://` and SSRF blocked; redirects/DNS/IP revalidated | **done** — scheme allowlist, blocked networks, and a redirect handler that re-checks (`test_url.py`) |
| 6 | one Credential Authority; backup/package/health/runtime agree | **done** — `credentials.py`; `test_invariants` asks the same four sources of every subsystem |
| 7 | lock ownership repaired; direct concurrency tests | **done** — a lock is stamped `pid:uuid` and verified before release; `locks.py` has its own test |
| 8 | every provider call through a universal cost/attribution/budget gateway | **done** — `modelgateway.py`; all nine call purposes are enumerated in a test |
| 9 | skill trust external and non-self-attestable | **done** — provenance comes from the graph, never from the file's own frontmatter |
| 10 | effect semantics: intent/uncertain/reconciliation; no exactly-once claim without remote idempotency | **done** — `effects.begin()`, `unfinished()`, and the docs no longer claim exactly-once |
| 11 | invariant tests that enumerate every reachable path | **done** — `test_invariants.py`, twelve enumerations |
| 12 | *only after these pass:* live provider, sandbox, MCP/federation and long-duration evaluation, then cloud and Training Lab | **this is the next step, and it needs a key.** Items 1–11 pass; nothing here has called a real provider |

Item 12 is the honest boundary of everything above. Eleven items of structural
repair were the price of being allowed to try the twelfth, and the twelfth has
not been tried.

### 22.3c Portability — §20

> *"Persistent expert state must be portable across modes; deployment is a
> location choice, not a different expert format."*

`backup.py` create → verify → restore is tested, and the test does not stop at
equal bytes: the **restored expert is driven through a gated task in its new
location** and must pass. A restore that produces identical files an agent
cannot be run from is a copy, not a restore. (`tests/test_backup.py`)

What a restore deliberately does **not** carry is credentials — the report
says so, and putting the keys back is the first thing it tells you to do.

### 22.4 Are the numbers moving? — §29

`python metrics.py` computes ten of the manual's twelve metrics from ledgers
that already exist, and **names the other three with the reason it will not
invent them**. Every figure carries its numerator, its denominator and the
ledger it was read from; a rate over fewer than five observations is printed
with the warning attached rather than as a confident percentage.

| Metric | Read from |
|---|---|
| Verified Success Rate | `state.json` — gated tasks a gate passed |
| False-Success Rate | `state.json` — finish-claims the gate threw back |
| Recovery Rate | task lineage — failures a retry rescued |
| Goal Fidelity | mission actions that name their criterion |
| Autonomy Ratio *(upper bound)* | tasks that never stopped to ask a person |
| Human interruptions per mission | blockers that route to the owner |
| Cost per verified task | model gateway ÷ gated passes |
| Repeat-failure rate | the case ledger — fixes that did not hold |
| Tool acquisition success | the acquisition ladder |
| Calibration | predicted confidence band vs the outcome |

**Not computed, and why:** supervision-hours (the denominator is a person's
time), 90-day retention (the structure is here; the elapsed time is not), any
safety-violation rate (every refusal recorded here is a control *working* —
counting refusals as violations would be the most flattering possible mistake),
and **§14's "100x" multiplier**.

That last one deserves its own paragraph. §14 defines the multiplier as
*verified output per dollar versus the same raw model without the fleet*. That
comparison needs the same work run twice and the baseline half has never been
run here, so no number is printed. What IS reported is the **harness
contribution**: a count of each moment the fleet changed the outcome, with what
a bare model would have done instead —

| Lever | Instead, a bare model would have… |
|---|---|
| a gate refused a finish-claim | returned it as finished work |
| a retry carried the failure back in | stopped, or repeated the same attempt |
| doubt escalated to a stronger model | spent the same on a trivial task and a hard one |
| a gotcha was filed | met the same environment failure for the first time, again |
| a repeat failure was recognised | had no record of the first |
| a command was refused by policy | run it |
| it stopped for a human decision | guessed and continued |
| a spend ceiling stopped it | had no ceiling and no idea what it had spent |
| it resumed after a crash | ended with the process |
| a case closed and the fix held | not know whether last week's fix worked |

These are counts of what happened, deliberately **not** divided by anything:
interventions over completions is a number that reads as a multiplier and is
not one. `metrics.py` carries the field `unit: "narrative"` for exactly this
row, and `test_metrics.py` asserts it never becomes a rate.

Visible in the panel under **Admin → Is it working?**, with the un-computable
three shown underneath in their own card, because naming them is the point.

### 22.5 The one sentence that governs all of it

Every row marked **Met** above was verified against the scripted mock provider.
A green suite proves the harness holds; it has never proved that a provider
works. `python loop.py check` remains the only live probe, and until somebody
runs it with a real key, the honest ceiling for every capability in this
platform is **OFFLINE VERIFIED** — which is exactly what `proof.py` reports.

---
