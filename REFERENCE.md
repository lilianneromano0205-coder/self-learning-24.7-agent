# Expert Fleet — the complete reference

Everything in this platform, explained end to end: what each part is, the
logic it runs, how you interact with it, and what it does **not** do.

`MANUAL.md` is the short practical guide. This is the deep one. It was
written by reading the code, not from memory; where a claim could rot, the
test that keeps it honest is named.

**Scale, so you know what you are reading about:** 58 Python modules,
one HTML file for the whole UI, 81 acceptance tests, zero third-party
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
20. [Honest limits](#20-honest-limits)
21. [Running it in production](#21-running-it-in-production)

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
- **proven** — ≥3 **distinct** tasks succeeded with it loaded, ≥1
  gate-verified, wins > losses
- **quarantined** — ≥3 losses and more losses than wins; never auto-injected
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

Seven sections: **Home · Guide · Agents · Work · Memory · Models · System**.

- **Home** — readiness, what needs you, Today, and the **live pulse** (SSE, not
  polling)
- **Agents** — the five lanes and the roster; opening one gives *Overview ·
  Teach · Board · Mind · Ask · Identity · Wiring* with a teammate rail
  - **Board** — every task; a row opens its stop condition, checkpoint
    progress, **context window**, **trace**, cards, and *save as routine*
  - **Mind** — the file tree, plus **Self-model**, **Knowledge** (sources by
    authority, standards, conflicts) and **Context windows**
  - **Identity** — edit `identity.md` (backups kept) and fleet-wide owner pins
- **Work** — goals with their plans, teams as threads, workflows as pipelines
- **Memory** — fleet map, failures, competence, retired agents
- **Models** — providers, catalogue, measured profiles, variants
- **System** — doctor, harness manifest, tool error rates, routines,
  federation, remote access

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

`[agent] sandbox = "host" | "docker" | "e2b" | "daytona"`.

- **host** — this machine, under `policy.py`
- **docker** — a throwaway container at `/work`, `--network none` by default,
  1GB memory, 256 pids
- **e2b / daytona** — hosted microVM sandboxes behind their API keys

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
sandbox = "host"                    # host | docker | e2b | daytona
sandbox_network = false             # docker egress
sandbox_image = "python:3.12-slim"
command_env_allow = []              # named keys a command may see
design_gate = true                  # gate interface deliverables
chain = { practitioner = "examiner" }

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

**Read (GET):** `/api/system` `/api/experts` `/api/experts/<s>`
`/api/experts/<s>/tasks` `/api/experts/<s>/tree` `/api/experts/<s>/file`
`/api/experts/<s>/settings` `/api/experts/<s>/skills`
`/api/experts/<s>/variants` `/api/experts/<s>/approvals`
`/api/experts/<s>/prospective` `/api/experts/<s>/workflows`
`/api/experts/<s>/models` `/api/experts/<s>/context` `/api/experts/<s>/trace`
`/api/experts/<s>/harness` `/api/experts/<s>/identity`
`/api/experts/<s>/routines` `/api/experts/<s>/self`
`/api/experts/<s>/knowledge` `/api/feed` `/api/events` (SSE) `/api/memory`
`/api/retired` `/api/commons` `/api/commons/pins` `/api/goals` `/api/team`
`/api/templates` `/api/toolbox` `/api/briefing` `/api/doctor` `/api/harness`
`/api/readiness` `/api/federation`

*(All 32 verified answering against a live panel.)*

**Create (POST):** `/api/quick` (⚡ lane) · `/api/learner` (📚 lane) ·
`/api/retired/<s>/restore` · `/api/shutdown`

**Act (POST `/api/experts/<slug>/<action>`):** `task` `goal` `consult`
`answer` `start` `stop` `launch` `template` `url` `scan` `intention` `wake`
`workflow` `variant` `approval` `skill` `routine` `provider` `role` `verify`
`memcheck` `probe`

**Edit (PUT):** `/api/experts/<s>/identity` · `/api/commons/pins`

All of it is guarded by the same token when you start the panel with
`--token`; the SSE stream accepts it as `?token=` because `EventSource`
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
`health_ritual_failed` `harness_manifest_failed` `state_corrupt`
`state_trimmed` `archive_failed` `lock_break` `inbox_scanned`
`exam_dispatched` `reexam_queued` `reexam_scheduled` `gaps_queued`
`ui_card` `ui_card_invalid`

---

## 19. The test suite as the specification

```bash
python tests/run_all.py          # 81 tests, ~250 seconds
```

The tests are not unit tests of functions; each is an acceptance test of a
claim, and each prints `[section]` lines saying what it proved in English.
When this document and the tests disagree, **the tests are right**.

Highlights: `test_e2e_crash` kills the process mid-lifecycle and proves it
resumes · `test_faults` breaks every contract on purpose and proves the
validator catches it · `test_exam` proves closed-book by context *and* by
tools · `test_secrets` proves no key value reaches a transcript, log or state
file · `test_ecosystem` runs every subsystem as one organism.

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
10. **Windows and OneDrive were the development environment.** Every write
    retries; sandboxes live in the system temp directory on purpose. A CI
    workflow now runs the suite on Linux and Windows across Python
    3.11–3.13, but it has never been executed on a real runner from here.
11. **Access is single-owner.** One token grants everything: queue work, read
    any file, edit any identity. There are no per-user roles and no
    audit-by-user. Do not hand the token to anyone you would not give the
    server to.

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
