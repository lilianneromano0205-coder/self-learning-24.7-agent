# Expert Fleet — the manual

A file-backed, stdlib-only platform for building expert AI agents that work
24/7, prove what they did, and remember what they learned. No database, no
framework, no build step: Python 3.11+ and your own API keys.

Everything below is real behaviour of the code in this folder. Where a claim
could rot, the test that keeps it honest is named.

For the deep version — every system explained end to end, the loop and the
harness in detail, all the logic, and an honest list of what the platform
does **not** do — see [REFERENCE.md](REFERENCE.md).

---

## 1. Run it today

```
python bootstrap.py
```

That one command creates `agent.env`, tells you exactly what is missing
(numbered, with the fix), creates your first expert, starts the control panel
and opens it. It is idempotent: run it again any time.

| flag | what it does |
|---|---|
| `--key NAME=VALUE` | writes a provider key into `agent.env`. The value is never printed, never logged, never in the report. |
| `--expert "Name" --identity "..."` | names the first expert |
| `--teach <url-or-folder>` | hands that expert its first material immediately |
| `--offline` | skip live provider probes (no network) |
| `--start-loop` | also start the expert's 24/7 loop |
| `--no-panel` / `--port` / `--host` / `--token` | control the panel |
| `--json` | machine-readable output (also written to `bootstrap.json`) |

Exit code `0` = ready. Exit code `2` = blocked, and stdout is the numbered
list of what to do. (`tests/test_bootstrap.py`)

**Keys.** Put them in `agent.env` beside this file — one `NAME=VALUE` per
line. `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`,
`NVIDIA_API_KEY`, `HF_TOKEN`, and optionally `E2B_API_KEY` /
`DAYTONA_API_KEY` for hosted sandboxes. Set spend caps at every provider
before first use.

**Health at any time:** `python doctor.py` (ends with a verdict and a
`[readiness]` section), `python harness.py --check` (exit 0 = every contract
holds).

---

## 2. What the platform is

Six systems, each with its own module set:

| # | system | modules |
|---|---|---|
| 1 | **Harness & loop** — context, tools, gates, brakes, retries, policy, effects, compaction | `loop.py` `harness.py` `policy.py` `effects.py` `locks.py` `checkpoint.py` `sandbox.py` |
| 2 | **Fleet & creation lanes** — trained, quick, archetype, learner, team | `fleet.py` `quick.py` `templates.py` `team.py` |
| 3 | **Work systems** — task, goal engine, workflow, consultation, intentions, routines | `goal.py` `workflows.py` `consult.py` `prospective.py` `routines.py` |
| 4 | **Memory institution** — courses, skills, commons, failures, gotchas, premise, routing, recall | `memory.py` `skills.py` `commons.py` `recall.py` `gotchas.py` `premise.py` `memrouter.py` `context.py` |
| 5 | **Improvement & governance** — variants with predictions, approvals, replay, benchmark | `variants.py` `approvals.py` `replay.py` `benchmark.py` |
| 6 | **Control plane & interop** — panel, chief, doctor, providers, toolbox, MCP, A2A, traces, cards | `ui.py` `ui.html` `chief.py` `doctor.py` `providers.py` `toolbox.py` `mcp.py` `federation.py` `trace.py` `uicards.py` `modelrouter.py` |

---

## 3. The panel

`python ui.py` (or let `bootstrap.py` start it) → http://127.0.0.1:7777

Seven sections: **Home · Guide · Agents · Work · Memory · Models · System**.

- **Home** — readiness banner, what needs you, *Today* (ranked from real
  state), then the **live pulse**: a server-sent event stream, not polling.
  Events appear the moment an agent writes them.
- **Agents** — five creation lanes and the roster. Opening one gives the
  workspace: *Overview · Teach · Board · Mind · Ask · Identity · Wiring*,
  with a **teammate rail** to switch between colleagues without losing place.
  - **Board** — every task. Each row opens a dialog with its **stop
    condition**, resumable checkpoint progress, the **context window** it was
    given, its **trace**, any **cards** it returned, and *save as routine*.
  - **Identity** — edit `identity.md` (previous versions kept) and the
    fleet-wide **owner pins** injected first into every agent's context.
- **Work** — goals (with the plan and its CHECK commands visible), teams
  (readable as **threads**: brief → plan → each deliverable → synthesis) and
  workflows drawn as **pipelines** with their gates.
- **Memory** — the fleet map, failures by category, competence, retired
  agents, and every compiled **context window**.
- **Models** — providers, live catalogue, per-model measured profiles,
  charter **variants with predictions**.
- **System** — doctor, harness manifest, pulses, **tool error rates**,
  **routines**, federation, remote access.

On a phone the same panel becomes a bottom-nav app: single column, full-screen
dialogs, 40 px targets.

---

## 4. Every module from the command line

| command | what it does |
|---|---|
| `python bootstrap.py` | set up and start everything (§1) |
| `python doctor.py` | health + readiness verdict |
| `python harness.py [--json] [--check]` | the harness manifest: tools, gates, policies, budgets, versions |
| `python loop.py run [--drain] --root <expert>` | run an agent's loop (drain = until the queue is empty) |
| `python loop.py add --role R --goal G [--done-check CMD] [--stop-criteria ...]` | queue a task |
| `python fleet.py create "Name" --identity "..."` | new expert |
| `python quick.py spin "Name" --goal "..."` | ⚡ lane: an agent, briefed and working in one step (`quick.py templates` lists archetypes) |
| `python team.py run "goal" --experts a,b,c` | 🤝 lane: specialists with handoffs as files |
| `python goal.py pursue "goal" --expert <slug>` | pursue a goal until an independent judge agrees |
| `python workflows.py run <spec.json> --root <expert>` | deterministic staged pipeline |
| `python consult.py ask "question" --root <expert>` | citation-gated answer |
| `python ingest.py url/folder/inbox ...` | teach: videos, PDFs, books, folders, sites |
| `python memory.py map\|failures\|competence\|search\|retire\|restore` | the memory institution |
| `python skills.py list\|status\|import\|export\|promote` | procedural memory + the SKILL.md supply chain |
| `python gotchas.py --goal "..."` | what this expert already burned itself on |
| `python premise.py "goal" --root <expert>` | does memory contradict this task? |
| `python memrouter.py --role student --goal "..."` | which memory kinds a task may see |
| `python context.py --task <id> --root <expert>` | the exact window a task was given |
| `python trace.py --task <id>` / `--tools` | spans for one task / per-tool error rates |
| `python modelrouter.py [--role R]` | measured model profiles and the routing decision |
| `python routines.py save <task-id> --every-days 1` | turn a finished task into a standing arrangement |
| `python checkpoint.py --root <expert>` | resumable long jobs and their progress |
| `python sandbox.py [--run CMD]` | which execution backend is active, and try it |
| `python variants.py spawn\|trial\|list` | charter evolution, gated by evidence (promote/rollback from the panel) |
| `python approvals.py list\|grant\|deny` | the human-in-the-loop ledger |
| `python replay.py --root <expert> [--task ID]` | re-run a decision against the record |
| `python benchmark.py run --expert <slug>` | the gated battery used by trials |
| `python recall.py "query"` | search everything: notes, skills, archived turns |
| `python mcp.py list\|call <server> <tool>` | MCP client (both protocol eras) |
| `python federation.py card\|peers` | A2A identity and peers |
| `python package.py` | ship a clean zip (no keys, no logs, no contexts) |
| `python demo.py` | the whole platform, keyless, in one run |
| `python preflight.py` | is this installation fit to run unattended? (§17) |
| `python backup.py create\|verify\|restore\|list` | the memory is the asset — back it up and prove the restore |

---

## 5. What one expert owns

```
experts/<slug>/
  identity.md            who it is (editable in the panel; backups kept)
  settings.toml          its own budgets, roles, providers, sandbox
  state.json             the hot task queue (small forever)
  archive/tasks.jsonl    every task ever finished
  courses/<c>/           material, notes.md (cited atoms), spec, exams,
                         gaps.md, retractions.md, gotchas.md
  skills/<name>.md       flat playbooks (the Reflector writes these)
  skills/<name>/SKILL.md folder skills, Agent Skills standard, may bundle scripts/
  skills/graph.json      earned status + provenance per skill
  gotchas/*.md           environment failures, scoped (mcp-<server>.md, general.md)
  contexts/<id>.json     the transcript · <id>.compile.json the window manifest
  contexts/<id>.archive.jsonl   verbatim turns, never deleted
  checkpoints/*.json     resumable progress of long tool work
  events/*.json          payloads delivered by wake-on-event
  approvals/*.json       every guarded call and its decision
  effects.jsonl          the exactly-once ledger of external effects
  routines/*.json        saved routines (skill + schedule)
  variants/              charter experiments, their trials and predictions
  logs/agent.log         one JSON line per step and event
  logs/model-outcomes.jsonl   the evidence capability routing uses
  logs/health.json       the harness health ritual at loop start
```

Fleet-wide: `commons/lessons.md` (append-only ledger),
`commons/lessons.curated.md` (grow-and-refine view), `commons/edits.jsonl`,
`commons/pins.md`, `commons/knowledge/`, `commons/quarantine.md`,
`teamwork/<run>/`, `experts/`, `retired/`.

---

## 6. settings.toml

```toml
[agent]
max_steps = 150                 # hard ceiling per task
max_task_retries = 2            # retries with the error in hand
max_done_rejects = 6            # gate refusals before giving up
daily_budget_usd = 0            # 0 = off
max_task_usd = 2.0              # per-task ceiling
poll_interval_seconds = 10
context_token_threshold = 50000 # compaction trigger
context_keep_recent_messages = 10
max_skills_loaded = 3
reflect_after = ["practitioner"]
exam_threshold = 90
reexam_days = [7, 30, 90]
retain_finished_tasks = 150
sandbox = "host"                # host | docker | e2b | daytona
sandbox_network = false         # docker: default-deny egress
sandbox_image = "python:3.12-slim"

[agent.context_budget]          # tokens per source in every window
commons = 1500
course = 2500
gotchas = 800
premise = 400
skills = 3000
memory_files = 12000

[agent.memory_router.practitioner]
kinds = ["commons", "course", "memory_files", "skills"]   # owner override

[roles.practitioner]
provider = "openrouter"
model = "meta-llama/llama-3.3-70b-instruct"
route = "auto"                                  # capability routing on
route_candidates = ["openrouter:qwen/qwen-2.5-7b-instruct",
                    "openrouter:meta-llama/llama-3.3-70b-instruct"]
route_min_pass = 0.8            # gated pass rate to qualify
route_min_n = 5                 # runs of evidence required
escalate_provider = "deepseek"  # used on [[ESCALATE]] or repeated tool errors
escalate_model = "deepseek-reasoner"

[providers.openrouter]
type = "openai"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
prices = { "meta-llama/llama-3.3-70b-instruct" = 0.60 }
```

The **student** role is closed-book by construction: the memory router may
only ever remove sources for it, never add — an owner override cannot hand an
examinee its own notes (`tests/test_memory_kinds.py`).

---

## 7. Stop conditions

Every loop is defined by when it stops. Declare it per task:

```
python loop.py add --role practitioner --goal "reconcile the ledger" \
  --stop-criteria "reconciled.csv exists and balances" \
  --max-attempts 2 --max-steps 40 --deadline 2026-09-01T08:00:00
```

The criteria text reaches the model in its first message and survives
compaction inside HARNESS FACTS; deadline/max_steps/max_attempts are enforced
by the harness, and a stop is filed as a `budget` failure with the reason
named (`tests/test_stop.py`).

---

## 8. Wake on an event

```
curl -X POST http://127.0.0.1:7777/api/experts/<slug>/wake \
  -H "Content-Type: application/json" \
  -d '{"event": "price.drop", "payload": {"sku": "A1", "drop": 0.15}}'
```

The payload is written to `events/` and handed to the task as a fenced file —
never as instructions. Arm what should happen with an `event` intention in
the panel (or `prospective.py`), optionally repeating. A wake can also queue
its own gated task directly (`tests/test_wake.py`).

---

## 9. HTTP API

| method | path | purpose |
|---|---|---|
| GET | `/api/events` | **live SSE stream** (`?token=` for EventSource) |
| GET | `/api/system` `/api/feed` `/api/briefing` `/api/doctor` | fleet state, feed, chief briefing, doctor |
| GET | `/api/harness` `/api/readiness` | manifest + contracts, readiness list |
| GET | `/api/experts` · POST | list / create |
| GET | `/api/experts/<s>/tasks` `/tree` `/file` `/settings` `/skills` `/prospective` `/workflows` `/variants` `/approvals` `/models[?profiles=1]` `/harness` `/context[?task=]` `/trace[?task=]` `/routines` `/identity` | everything about one agent |
| POST | `/api/experts/<s>/task` `/goal` `/wake` `/intention` `/workflow` `/variant` `/approval` `/skill` `/routine` `/answer` `/start` `/stop` `/url` `/scan` `/launch` | act |
| PUT | `/api/experts/<s>/identity` · `/api/commons/pins` · `/api/experts/<s>/file` | owner-authored text and uploads |
| GET | `/api/team[?run=<id>&files=1]` · POST | team runs, and one run as a thread |
| POST | `/api/shutdown` | stop the panel and its children |

Everything under `/api` honours `--token` (header or `?token=`).

---

## 10. Event names in the log and the stream

`task_start` `tool_call` `task_end` `done_refused` `retry_queued`
`retries_exhausted` `escalated` `stop_condition` `approval_required`
`command_refused` `prospective_fired` `chain_queued` `exam_dispatched`
`reexam_queued` `gaps_queued` `skill_status` `failure_recurred`
`gotcha_filed` `premise_warning` `model_routed` `ui_card` `ui_card_invalid`
`tool_results_cleared` `compaction_incomplete` `health_ritual`
`budget_exceeded` `task_cost_ceiling` `provider_failure` `state_corrupt`
`task_unblocked` `agent_start`.

---

## 11. Skills: the open format and its trust tiers

A skill is either `skills/<name>.md` (what the Reflector writes) or a folder
`skills/<name>/SKILL.md` with YAML frontmatter — the Agent Skills standard,
so skills from the wider ecosystem import directly:

```
python skills.py import ./downloaded/pdf-forms --root experts/<slug>
python skills.py list --root experts/<slug>
python skills.py promote pdf-forms --root experts/<slug>
python skills.py export my-skill --to ./share --root experts/<slug>
```

Three provenance tiers gate what a skill may do:

| tier | how it got here | what it may do |
|---|---|---|
| `own` | written by this expert's Reflector from its own runs | full |
| `owner` | imported and explicitly trusted by you | full, incl. bundled scripts |
| `community` | imported from a third party | injected with a warning banner; **bundled scripts refused** until you promote it |

Independently, the skill **graph** grades every playbook on evidence:
candidate → proven (3 distinct wins, ≥1 gate-verified) → quarantined (3
losses and more losses than wins). Provenance is where it came from; status
is what it has earned (`tests/test_skillmd.py`).

---

## 12. Where commands run

`[agent] sandbox = "host" | "docker" | "e2b" | "daytona"`.

`docker` runs each command in a throwaway container at `/work` with
`--network none` by default. If a configured backend is unavailable the
command is **refused** (exit 127) with the reason — it never silently falls
back to your machine. Policy still runs first in every backend
(`tests/test_sandbox.py`).

Commands never receive the harness's credentials. Any environment variable
whose name looks like a secret (`*KEY*`, `*SECRET*`, `*TOKEN*`, `*PASSWORD*`,
`*CREDENTIAL*`, `*AUTH*`, `*COOKIE*`) is withheld from every model-written
command, so `env` cannot leak your keys into a transcript, a file or an HTTP
request. Two escape hatches, both narrow:

* the platform's own helpers get exactly the one key they need, and only for
  that command shape — `ingest.py transcribe` sees `GROQ_API_KEY`, a bare
  `env` sees nothing;
* `[agent] command_env_allow = ["NAME"]` passes one named variable through.

A command killed by the timeout reports the timeout **and** keeps whatever it
printed first (exit 124), because "it hung after writing 900 rows" and
"nothing happened" are different facts (`tests/test_secrets.py`).

---

## 13. Knowing what it knows: sources, conflicts, standards, self

Feed an expert forty PDFs, ten videos and a pile of posts and they will
contradict each other. Four files per course keep that from turning into
confident nonsense.

| file | what it is | written by |
|---|---|---|
| `courses/<c>/sources.json` | every source with an **authority tier** (1 normative → 4 anecdotal) and why it got it | `sources.py`, automatically at ingestion |
| `courses/<c>/conflicts.md` | every contradiction found, classified and ruled on | `conflicts.py` |
| `courses/<c>/standards.md` | the bar the material demands, append-only and owner-editable | `standards.py --extract` |
| — | the agent's factual self-model, compiled fresh into every window | `selfmodel.py` |

The four verdicts a contradiction can get:

* **authority** — a tier-1 spec outranks a tier-3 blog post; the ruling names
  the source that lost
* **superseded** — 2026 guidance beats 2018 guidance at equal authority
* **context** — both rules hold, under different stated conditions; both are
  kept with their condition
* **contested** — equals, same era, no condition: **no winner**, and
  `conflicts.py --check` refuses any answer that states it as settled

```bash
python sources.py --root experts/<slug> --course design
python conflicts.py --root experts/<slug> --course design --write
python standards.py --root experts/<slug> --course design --extract
python selfmodel.py --root experts/<slug>
```

The panel shows all of it under an agent → **Mind**: *Self-model* (what it has
verified, per course, with exam results and source tiers) and *Knowledge*
(sources by authority, standards, disagreements). A contested point is a red
pill, and clicking a course opens the rulings.

Owner overrides: `python sources.py --course design --set S-3 --tier 1 --why
"this is the published spec"`, or `[agent.source_tier]` in `settings.toml`.
`standards.py --add` writes a rule the material never stated. Extraction never
rewrites a line you wrote, and a contested point can never become a standard.

---

## 14. The design gate

`designcheck.py` is what makes "professional, not generic AI output" a
refusal rather than a wish. It is wired automatically as the definition of
done for any launched deliverable ending in `.html/.htm/.css/.jsx/.tsx/.vue/
.svelte`.

```bash
python designcheck.py out/index.html
python designcheck.py out/ --root experts/<slug> --course design --json
```

It checks contrast against WCAG on every colour pair declared together, one
type and spacing scale, tokens over literals, a real breakpoint, no fixed
width that overflows a phone, the accessibility floor (lang, alt, labels,
focusable controls, landmarks) — and the fingerprints of unconsidered output:
the default indigo/violet palette, emoji as icons, lorem ipsum, everything
centred, stock marketing copy. Blockers fail the gate; warnings are reported.

A course's own numeric standards raise the bar: `R-01 … contrast … 7:1
[check: min_contrast=7.0]` makes the gate demand 7:1 for that course.

The **UI/UX Designer** template (`templates.py`) is the lane: feed it the
references first, then give it screens.

---

## 15. Troubleshooting

| symptom | what it means / what to do |
|---|---|
| `bootstrap.py` exits 2 | read the numbered list; each line names the ENV var and the fix |
| `VERDICT: 1 PROBLEM(S)` — keys | no provider key yet; `demo.py` still runs keyless |
| tasks queue but nothing happens | the loop is not running: panel → agent → *start loop*, or `python loop.py run --root experts/<slug>` |
| `finish_task REFUSED` | the definition of done did not pass — that is the gate working; read the evidence in the task |
| `sandbox '<b>' unavailable` | the backend named in `settings.toml` is not installed/keyed; fix it or set `sandbox = "host"` |
| a community skill's script is refused | read it, then `python skills.py promote <name>` |
| `APPROVAL REQUIRED (ap-…)` | a destructive MCP tool paused for you: panel → the agent → the approval card |
| pulse says *polling* not *live* | the SSE stream could not stay open (proxy?); the panel falls back to a 6 s poll automatically |
| Windows + OneDrive write errors | every write retries; sandboxes and tests use the system temp dir on purpose |

---

## 16. The test suite is the specification

```
python tests/run_all.py
```

Every claim in this manual is covered by a named acceptance test that runs a
real loop against a scripted provider — no mocking of the harness itself.
`tests/run_all.py` prints each test's own sentence describing what it proved.

---

## 17. Before you run it on real work

```
python preflight.py          # exit 0 ready · 1 risks · 2 blocked
```

`doctor.py` says the software is healthy; `harness.py --check` says the
contracts hold; **`preflight.py` says whether this installation is fit to run
unattended**. It audits spend caps, credential permissions, backups (present,
recent, checksums verified, covering every expert), disk headroom, provider
fallbacks, sandbox choice, harness contracts, CI, and anything waiting on a
human. Every finding names the command that fixes it.

```
python backup.py create --home . --out ../fleet-backups
python backup.py verify <archive>
python backup.py restore <archive> --dest ./restored
```

Backups carry the memory that cannot be re-downloaded — identities, courses,
cited notes, skills, the commons, state, archives — and **never** carry your
keys, so a restore ends by telling you to put them back. Every file is
checksummed; a damaged archive is refused by `restore` and reported as a
blocker by the preflight.

Full operational detail — exposure and access, cost control, the upgrade
procedure, CI, and an incident table — is in
[REFERENCE.md §21](REFERENCE.md#21-running-it-in-production).
