# Expert Fleet

**A file-backed, stdlib-only platform for building expert AI agents that work
continuously, prove what they did, and remember what they learned.**

[![tests](https://github.com/reda-baqechame/self-learning-24.7-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/reda-baqechame/self-learning-24.7-agent/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![dependencies](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)
![tests](https://img.shields.io/badge/tests-120%20passing%20%C2%B7%206%20platforms-brightgreen)
![mutations](https://img.shields.io/badge/mutation%20tests-56%2F56%20killed-brightgreen)
![license](https://img.shields.io/badge/license-AGPL--3.0-orange)

109 Python modules · 142 acceptance tests · one HTML control panel · no
database, no framework, no build step. Python 3.11+ and your own API keys.

```bash
python bootstrap.py
```

One idempotent command: creates `agent.env`, tells you exactly what is
missing (numbered, with the fix), creates your first expert, starts the
control panel and opens it. **[QUICKSTART.md](QUICKSTART.md) is the
15-minute path from zero to your first VERIFIED goal** — including the
provider table: the platform is provider-universal (OpenRouter, official
Anthropic/OpenAI/Gemini/xAI/DeepSeek APIs, Groq, NVIDIA, Hugging Face,
Cloudflare Workers AI, or a local Ollama model with no key at all).

## Install

Three ways to run it, all from this repository, all with your own keys.
Nothing phones home; the panel binds localhost; keys live in `agent.env`,
read by the platform and printed by nothing.

**Desktop (Windows)** — one line in PowerShell installs to
`%USERPROFILE%\ExpertFleet` and puts an "Expert Fleet" shortcut on the
Desktop and Start Menu:

```bash
irm https://raw.githubusercontent.com/reda-baqechame/self-learning-24.7-agent/main/install.ps1 | iex
```

**Desktop (Linux / macOS)** — one line installs to `~/ExpertFleet` and a
`fleet` command that proves the wiring before starting anything:

```bash
curl -fsSL https://raw.githubusercontent.com/reda-baqechame/self-learning-24.7-agent/main/install.sh | bash
```

**Cloud (24/7, no hardware of yours)** — one line on a fresh Ubuntu server
runs the full audited bootstrap: unprivileged user, systemd units installed
but *not* enabled, and the complete test suite passing on the server before
anything is allowed to start:

```bash
curl -fsSL https://raw.githubusercontent.com/reda-baqechame/self-learning-24.7-agent/main/get-fleet.sh | sudo bash
```

Then follow [deploy/VPS.md](deploy/VPS.md): keys in, `loop.py check`
green, services enabled, and the panel reached **privately** — over
Tailscale or a Cloudflare Tunnel with `UI_TOKEN` set, never a raw open
port. Work continues while you are away; the ⏸ button in every goal's
cockpit is the only thing that stops it. Prefer containers?
`docker compose up -d` gives the same fleet sandboxed and
resource-braked, and the image refuses to build unless the whole test
suite passes inside it.

---

## See it

| The fleet, at a glance | A goal's cockpit |
|---|---|
| ![Home: blockers with exact fixes, an onboarding checklist that reads real state, and the systems map](docs/panel/home.png) | ![The cockpit: frozen graders with live PASS/FAIL, budget bars, milestones, owner steering, and the replayable ledger](docs/panel/cockpit.png) |

| Competence, measured | The knowledge graph |
|---|---|
| ![Mastery: sealed capability packs with pretest → exam lift and retention, against frozen bars](docs/panel/mastery.png) | ![Graph: entities sized by evidence and colored by source tier, load-bearing source concentration, and flagged directive-shaped claims](docs/panel/graph.png) |

*Screenshots of the shipped control panel on a local demo fleet — every
number in them is computed from files on disk, none is staged.*

---

## The systems at a glance

Three families at the door — named by **what you walk away with** — and one
law under all of them: **"done" is always a mechanical check the worker
cannot edit.** Behind the door, each family has proven lanes; you never have
to pick one yourself, because the router reads your goal's shape and picks
the lane (override freely).

**WORK — you walk away with an outcome**

| Lane | What it is | "Done" means |
|---|---|---|
| **Task** | one gated job for one role | its done-check command exits 0 |
| **Goal** | pursued across cycles until frozen graders pass; machine path first, judge overruled if the graders disagree | VERIFIED: every sealed acceptance test passes, run by the harness |
| **Mission** | a standing objective with success criteria, held on disk across weeks | every criterion met by recorded evidence |
| **Workflow** | fixed stages with a gate between each | each stage's gate passed, in order |
| **Team** | 2–4 specialists + a lead; file handoffs; constraint digests | the members' gates + the lead's synthesis |

**COMPETENCE — you walk away with a capability, provable on unseen work**

| Lane | What it is | "Done" means |
|---|---|---|
| **Learning** | courses → cited notes → spec → closed-book exam | spec 100% · exam ≥ threshold · zero gaps |
| **Mastery** | sealed capability packs; pretest → study → exam → retention | harness-run validators clear the pack's frozen bars |
| **Runbooks** | machine-executed procedures, zero model calls, earned trust | every step's verify exits 0 |

**ANSWERS — you walk away with a cited answer**

| Lane | What it is | "Done" means |
|---|---|---|
| **Consult** | answers where every claim carries a citation | cites resolve, or NOT IN MY TRAINING |

Why three families and not three systems? The lanes resemble each other in
pairs — a task is a goal with one grader, a runbook is a workflow that earned
zero-model trust, mastery is learning with a sealed proof — but each
difference is a **tested law, not a naming accident**: who executes (a model
behind a gate vs a machine under earned trust), who grades (frozen graders vs
one check), whether the student can read its own exam. All nine already share
one engine — every lane enqueues into the same task loop, one authority
stack, one memory — so merging code would buy no power and risk proven
behaviour. The fold happens at the door, where the confusion was.

Start simple: one **Task** with a done-check, then one **Goal** with
graders. Everything else is these two, scaled.

Not sure which system a goal needs? Ask the router — it reads the goal's
shape (a question, a schedule, a pipeline, a standing responsibility …)
with a deterministic rule, names the system, and says why:

```bash
python universal.py route --goal "every day at 9 summarize new arxiv papers"
```

The panel runs the same rule under "Can it do this?", and it is a floor,
not a ceiling: override it freely, steer any run mid-flight, pause it with
one button, or promote a task to a goal by adding graders — the systems
share one memory and one authority stack, so switching costs nothing.

---

## Why this, in a world of agent frameworks

2026's agent landscape is crowded and genuinely impressive — OpenClaw's
five-component runtime and enormous ecosystem, Hermes Agent's
self-improving loop, Grokbot's named no-code agents with connectors,
schedules and demonstration recording, NemoClaw wrapping agents in
sandboxing, privacy routing and audit. This platform covers that ground —
and differs from all of it on one structural axis: **here, the guarantees
are laws with tests that would fail, not features with descriptions.**

| Property | The well-known harnesses | Expert Fleet |
|---|---|---|
| Who says "done"? | the model or its framework judges its own run | frozen, caller-authored graders sealed before planning, run only by the harness; even the judge is overruled when they disagree — **56/56 mutation-tested laws** |
| Self-improvement | trust the loop to compound | validation-gated: a procedure is PROVEN only after 3 wins in which its own steps verified **and the caller's independent acceptance test passed afterwards**; oscillation stops the lane; drafts refuse to run — matching what the 2026 fragility literature demands |
| Learn by demonstration | recorded, then trusted | `runbook.py record`: recorded → **CANDIDATE**; a rehearsal replays the demo through the full authority stack, which proves the recording RUNS and earns no trust — a procedure grading its own replay is still the procedure grading itself; a demo you watched is a claim, a demo the *caller's* graders accepted is evidence |
| Security | wrapper products exist *because* the frameworks need wrapping (see the published security analyses of the popular ones) | six mandatory authorities inside the platform — Execution, File, Credential, Model Gateway, Effect, Control Plane — `--audit` at 0 bypasses **in CI**, a worker that cannot change its own authority even through a shell, plus directive-shaped memory flagged at the source |
| Competence claims | self-reported benchmarks | sealed capability packs the student can neither read nor edit; pretest → exam lift measured by harness-run validators; the author never sits its own exam |
| Memory over years | vectors and summaries | file-backed cited atoms with expiry, supersession, and a **retraction feed** — plus the compaction-cliff law: safety rules are never summarized, ever |
| Long context | a bigger window | **recursive sub-calls** (the RLM result, MIT 2025): the material never enters the window — slices go to disposable sub-calls on the cheapest rail, only distilled answers return, metered and contained like every call |
| New tools | a fixed integration catalogue, or an agent that installs what it likes | **the capability frontier**: an agent may PROPOSE a tool it lacks, never author the test — it declares an import or a binary, the *platform* generates the probe, and the probe must FAIL before anything is installed. Readiness is decided by a seal outside the agent's reach, and a human adopts it from a terminal |
| Knowing what a goal needs | a prompt asking the model to list its tools | two measured corpora, 50 goals across 40+ trades, pinned as tests. The broad set went **24% → 100%** honest coverage; the adversarial set found that **5 goals carrying irreversible physical or financial effects did not stop for the owner** — cutting power to a heater, changing a CNC feed rate, filing a claim in your name — because every authority rule was about a digital permission and none about a machine that moves. Now 0 |
| Dependencies | large stacks | Python stdlib. Zero. 120 tests on 6 CI platforms |
| Your state | often hosted, often theirs | files you own, provider-universal (any key, or a zero-key local model) — the model is a swappable part; the memory, graders, runbooks and ledgers are the asset |

Four shipped archetypes cover the famous products' ground on this
machinery — **Chief of Staff** (Grokbot-class personal automation),
**Deep Researcher** (Hermes-class compounding research), **Nightwatch
Optimizer** (AVO-class long-horizon improvement), **Privacy Warden**
(NemoClaw-class zero-egress operation) — each inheriting the graders,
earned trust and control-zoned ledgers those products do not have.

And the honest counterweight, because a lab states it: those platforms
have vast integration ecosystems, hosted polish and mobile apps this
local-first platform does not chase — and this platform's measured
model-lift experiment still awaits an API key. What is claimed here is
what is tested here.

---

## The idea in one paragraph

An LLM with a shell is not an employee. It forgets everything between
sessions, drifts away from the objective inside a long task, cannot be held
to a specification nobody wrote down, and — most expensively — will tell you
a job is finished when it is not. None of that is fixable inside the model,
because the model is the thing being asked. **Capability comes from the
system around the model.** So this platform surrounds a cheap model with the
things that make its output verifiable: a *gate* that must exit zero before
"done" is accepted, a *mission contract* held outside the transcript, ledgers
that make yesterday's failure cheap, and a *proof system* in which no status
can be set by hand.

**→ [ARCHITECTURE.md](ARCHITECTURE.md) is the complete technical account** —
the problem, the thesis, the eleven concepts, how a task actually runs, why I
claim it works, and what is not proven.

---

## The eleven ideas you need to know

**1. "Done" is a command, not an opinion.**
A task can carry a definition of done. When the model calls `finish_task`,
the platform runs that command. Non-zero exit means the finish is **refused**
and the failure text goes back to the model. The count of refusals is kept,
because *how often did it claim completion and get caught* is the most honest
reliability number this platform has.

**2. The objective lives outside the conversation.**
A mission is an objective plus success criteria, on disk. The objective is
immutable — amending it is recorded and fingerprinted. Every criterion is met
by evidence, never assertion. Every action must name the criterion it serves.
The contract is recompiled into every context window, so a compaction, a
restart or a model swap cannot erase the goal.

**3. Six authorities, not scattered checks.**
A forensic audit of this codebase found the same pattern everywhere: *a
control defends the path its author was thinking about, and does not know
about the other paths.* Six places executed shell; one was tested. The answer
is one mandatory gateway per kind of power — Execution, File, Credential,
Model Gateway, Effect, Control Plane — and `python execution.py --audit`
fails the build if any module bypasses one. Today: **0 violations across 87
modules**, 16 declared platform-internal.

The sixth arrived the same way the pattern predicts. A later audit asked what
the first five answered *between* them, and found nothing there: the File
Authority correctly refuses the `write_file` **tool** on control state, and
`policy.py` correctly screens a command **string** while saying in its own
docstring that it cannot follow the program that string starts. So a role
holding `run_command` rewrote `settings.toml` and `prompts/` by running a
program — measured, on the shipped default, in the same transcript where the
file tool was being refused. `controlplane.py` owns that invariant now:
read-only binds on docker (prevented by the kernel), seal-and-revert on
`host` (there is no boundary there to prevent with, and the module says so).
`tests/test_controlplane.py` crosses every control path with every way a
shell changes a file — **100 attacks, 0 durable changes**.

Closing that one meant reading the neighbourhood, and the neighbourhood held
a worse hole: the best-of-N engine restored an attempt's artifacts by
`os.path.join`, and the artifact list came from the task's own steps — so a
role with **no shell at all** could have the loop copy its own file over
`prompts/constitution.md`, or write outside the expert root entirely. Both
reproduced; both now cross the File Authority. Seven more paths that are read
into a prompt or a decision turned out to be agent-writable and are control
state now. The lesson the codebase keeps re-learning, in its own words: *a
control that lives at a call site protects that call site and nothing else.*

**4. Proof is derived, never claimed.**
Six levels from SPEC to PRODUCTION PROVEN, computed from evidence bound to a
code hash. Change a file a capability covers and its badge drops on its own.
Live evidence expires. **No endpoint accepts a level** — the panel can re-run
the evidence and nothing else.

**5. Memory is an institution, not a vector store.**
Courses with cited atoms · skills promoted on outcomes · failures in sixteen
categories · gotchas this expert already paid for · cases that record whether
the fix *held* · competence measured from gated results. A memory router
decides which kinds each role may see — the Student sees the course and
nothing else, because a closed-book exam is not closed-book if the answers
are in the window.

**6. It finds its own sources — from catalogues, never a search engine.**
An expert that can only read what a human pasted has not learned anything by
itself. `discover.py` queries the registries the real material lives in —
OpenAlex, Crossref, DOAJ, PubMed, Zenodo, Software Heritage, GitHub, the EU
open-data portal, the Library of Congress — all keyless, all public, all
curated. **Deliberately not a web search**: a general index is ranked for
engagement, personalised, and changes hourly, so citing it cites nothing, and
its top results for a technical question are content farms and reposts of the
real document. Every search-engine host is pinned to tier 4 and can never
clear the learn bar at any setting. "Only reputable sources" is therefore a
property of *where candidates can come from*, not an instruction a model may
ignore.

Two things make it usable rather than merely principled. The goal is reduced
to its subject before being sent — the raw goal `understand b-tree index
concurrency control` had PubMed returning *Vascular Compliance and
Cardiovascular Disease*, matching `compliance`/`control`. And any result
sharing no substantive term with the query is dropped **and counted**,
because an off-topic paper reached by a trusted route becomes a cited atom:
a wrong belief carrying a real citation, which is worse than no belief. The
same query now returns Bayer & Schkolnick 1977, ARIES/IM, and Graefe's
*Modern B-tree techniques*.

```bash
python discover.py "b-tree index concurrency" --limit 5
python discover.py "CRISPR off-target" --rails pubmed --min-tier 1
python discover.py "raft consensus" --commands --root experts/dbexpert
```

**7. A goal's graders are frozen before the work begins.**
An external audit found the hole in every "the agent checks its own work"
design, including this one's: *the planner writes its own graders* — the
milestone checks are authored by the same model family that then satisfies
them. The goal contract (`contract.py`) closes it structurally. Acceptance
tests come from the caller, are hashed and **sealed outside the expert's
working root**, and the harness runs them itself. The worker's file tools
cannot write contract files; a worker that shells around that and edits them
anyway gets a **TAMPER** verdict — nothing runs, nothing passes. Completion
is a state transition (`verified` only when every frozen test passed in a
harness-run), budgets end pursuits **blocked by name**, and a pursuit that
fails the same wall twice in a row is stopped with the wall named instead of
burning its remaining cycles on it. A goal with no mechanical acceptance
tests can end *achieved* (the judge's checked opinion) but never *verified*
— that ceiling is printed, not hidden. Every transition is an event in an
append-only ledger that replays; a snapshot forged to "verified" with no
event behind it is detected as divergence.

```bash
python goal.py pursue "migrate the reports module" --expert builder --drive \
    --accept "tests pass::python -m pytest tests/reports -q" \
    --max-usd 2.50 --max-minutes 180
python contract.py verify experts/builder <goal-id>   # re-run the graders
```

**8. The machine runs what is proven; the model is spent on the frontier.**
The pre-AI agents that did regulated, hard work reliably — crawlers,
spacecraft autonomy, workflow engines, cluster controllers — were not
intelligent. The work was *written down as executable procedure* and the
machine replayed it, verifying as it went. `runbook.py` brings that here: a
runbook is typed steps, each `do` + `verify`, run through the Execution
Authority with **zero model calls** — a step that cannot prove itself stops
the run, a hostile command is refused by policy, and trust is *earned* (three
all-verified wins promote candidate → proven; the trust ledger is
CONTROL-zoned, so a runbook cannot promote itself and a self-declared
`"status": "proven"` is ignored). `runbook.py reconcile` is the model-free
goal loop — observe the frozen acceptance tests, apply the matching proven
runbook, re-verify, repeat. Applicability is **typed**, not just keyword
triggers: a
runbook can carry `when.not` (negative triggers — words that mean this is
the wrong tool however well the positive words fired) and `when.requires`
(observe-probes that must exit 0 *here and now* — the tool is installed, the
input exists); reconcile takes the best match that can actually run and
names the unmet precondition when none can. And runbooks **compose**: a
step may be `{"run": "sub-runbook"}` — the sub keeps its own earned-trust
gate (a proven parent cannot smuggle a quarantined child), records its own
wins, and a cycle or over-deep chain stops the run with the chain named.
`goal.pursue` tries all of this **before** spending a
single model cycle. Proven end to end: a pursuit completed VERIFIED with zero
tasks created, against a mock provider rigged to fail any task instantly. The
division of labour is the economics: the model plans and recovers at the
frontier, then writes the procedure down; the machine replays it forever for
pennies, and the library — unlike a model — is auditable line by line. Where
no runbook matches, the result is *blocked with the frontier named*, never
improvisation: brittleness at the frontier is what killed the old
deterministic agents, and the frontier is exactly where the model belongs.

When a pursuit ends BLOCKED, `repair.py` closes the loop the research
record actually supports (Huang et al. ICLR 2024; Voyager; Darwin Gödel
Machine): every repair is grounded in the failing check's recorded error —
never in the model re-reading its own work — revisions keep lineage beside
their parent, budget and tamper blocks route to the owner alone, and repair
itself can move a goal back to `running` but can never grade it: VERIFIED
still only comes from the frozen acceptance tests, and the event ledger
proves the graders spoke first.

```bash
python runbook.py list      experts/builder
python runbook.py reconcile experts/builder <goal-id>   # zero-token goal loop
python runbook.py draft     experts/builder <goal-id>   # skeleton from a win
python repair.py  apply     experts/builder <goal-id> --resume
```

**9. Competence is proven on sealed unseen work, never self-declared.**
Learning information (sources → cited notes → closed-book exam) is not the
same as being able to *build*. A **Capability Pack** (`capability.py`) is a
sealed exam for a domain: competencies, practice exercises, transfer tasks
the student meets for the first time at exam-time, and stdlib validator
scripts — stored **outside every expert's root** (the worker's file tools
can neither read nor edit its own exam) and content-hashed like a contract;
an edited validator is a TAMPER verdict that grades nothing. The mastery
loop (`mastery.py`) runs pretest (baseline *before* study) → study →
practice → sealed exam → diagnose (failing checks as evidence) → bounded
targeted re-study → verdict → distill (wins become runbook drafts) →
retest (retention under fresh ids). The MASTERED verdict is computed only
from harness-run grader results against the pack's frozen thresholds, and
it is recorded with its honest ceiling: a mechanical floor, not taste.

```bash
python mastery.py run    <home> <expert> responsive-pricing --drive
python mastery.py retest <home> <expert> responsive-pricing   # retention
python capability.py draft <home> new-domain --domain "what it is" \
    --competency reading="study query"     # a pack skeleton for a NEW domain
```

A pack records its **author**, and mastery refuses to examine the author on
its own pack — the student never sits an exam it wrote, enforced by
provenance on top of the file zones. A drafted pack is all TODOs and
refuses to freeze until a person or a *different* expert writes the exam in.

**10. You can steer a running pursuit — and steering is never a grader.**
Between "let it finish wrong" and "kill it" there is now a third option:
`steer.py` (and the panel's cockpit) records a note that lands verbatim in
the planner's context at the top of its **next cycle**. The laws: advice
never touches the acceptance tests or the verdict (a note saying "mark it
verified" is a note the graders never read); the worker cannot write its
own guidance channel (CONTROL-zoned — a worker that could forge "the owner
says ship it" would have promoted itself to owner); and every note lands on
the contract ledger as a `steered` event, because influence on a pursuit
must never be invisible.

```bash
python steer.py add experts/builder <goal-id> "mobile first — most visits are phones"
```

**11. Learned claims age — and the platform shows the decay.**
A cited atom, once earned, used to be true forever. `freshness.py` adds
expiry (`[expires: 2026-01-01]`), supersession (`[supersedes: C-01]` — the
old atom is flagged, its successor named, lineage kept), and a
**retraction ledger**: retract a source ref once and every atom citing it
is flagged fleet-wide. Flags, never deletions — the owner decides. It also
flags **directive-shaped memory** — the authority-collapse attack from the
2026 memory-poisoning literature, where "always invest $5,000 when X" gets
studied off a webpage into a cited atom and later recalls as knowledge:
atoms that command money, claim the owner's voice, or carry injection
idioms are flagged with the matched shape and source named (narrow by
design — a how-to's "run npm install" is not an attack, and the blind spot
is stated). Memory is evidence here, never instruction: the zones already
keep any atom from grading or steering anything, and policy still screens
every command.
The ledger is CONTROL-zoned, so an agent cannot retract the source of a
claim it would rather not defend. `freshness.py doi <doi>` live-probes
Crossref for retraction notices, keyless.

```bash
python freshness.py scan    experts/builder
python freshness.py retract experts/builder "10.1234/withdrawn" --why "publisher notice"
```

**[GOAL_SPECIALIST.md](GOAL_SPECIALIST.md)** is the deep account: the
architecture, the evidence (46/46 mutations killed across the contract,
runbook, repair, swarm, mastery, steering, freshness, provider-hub and
memory-law layers), and
the audit's complete 115-gap register with an honest status for every
row.

---

## Why you should believe any of it

Five kinds of evidence, weakest first — and the last is the only one produced
on a computer this project does not own.

**The suite passes — on three platform/version pairs now, not one.** 112
acceptance tests, green on Windows under Python 3.14 and on Linux under
Python 3.11 and 3.13. Each test prints a sentence describing what it
observed; `EVIDENCE.md` quotes them verbatim. CI runs the same suite on
Ubuntu and Windows × 3.11/3.12/3.13 and **all six jobs are green** — but
check the badge on the repository rather than this sentence, because the
first three times this paragraph and the CI result disagreed, the paragraph
was wrong.

**The tests enumerate rather than exemplify.** `tests/test_invariants.py`
does not test through an example — it walks the tree: every subprocess call
site in 77 modules, every declared control file, 12 traversal spellings, all
4 credential sources against every subsystem that must exclude them, all 9
provider-call purposes, all 9 roles, every module that mints an expert, every
reader of the exam file, the sandbox names across all test files, all
64 CLI subcommands the manual promises, and — parsing every module — every
comparison that puts a file timestamp on both sides, which is how two
silent staleness bugs were found at once rather than one at a time.

**Mutation testing — 0 missed.** A passing test proves nothing unless it
would fail with the feature removed. `mutate_check.py` breaks each
load-bearing behaviour and requires its test to fail:

```
CAUGHT  docker: egress allowed by default
CAUGHT  docker: timeout leaves the container
SKIP    docker: every host variable forwarded into the container
CAUGHT  inbox: a zero settle window can still hold a file back
CAUGHT  credentials: the environment scrub removed from every backend
CAUGHT  provider: no Authorization header
CAUGHT  provider: malformed body kills the task
CAUGHT  provider: 4xx retried like weather
CAUGHT  package: ship the credential file
CAUGHT  endurance: never archive finished work
CAUGHT  rbac: every write allowed
CAUGHT  fleet: creation stops seeding the home
CAUGHT  loop: a running task is stolen from a live sibling
SKIP    credentials: a secret written under the umask
SKIP    docker: the container runs as root in the mount

15 mutations: 12 caught, 0 missed, 3 skipped     [on Windows]
```

**A `SKIP` here is a refusal to score, and each states its own reason.** Two
are POSIX-only because file modes are not the mechanism on Windows. The
third — `every host variable forwarded into the container` — is POSIX-only
for a completely different reason, and it is the one worth reading:
forwarding a Windows `PATH` into a Linux container means `sh` cannot be
found, so the container never boots and no assertion is ever reached. A
CAUGHT there would be counting a crash, not a test noticing anything.

That is not hypothetical. That row **did** report CAUGHT on Windows for four
releases, certifying a test that had never actually run; the first time the
mutation step reached Linux it reported MISSED, which was the truth. See
[U21](GAPS_RISKS_AND_UNFINISHED.md) — a mutation harness reports two things
and only one was being checked: whether the test failed, and whether it
failed **for the reason claimed**. A shared skip reason was the same mistake
one level up, so each row now carries its own.

Three scores, because where a mutation ran changes what it means:

| Where | Result |
|---|---|
| Windows | 15 mutations: **12 caught, 0 missed**, 3 refused (POSIX-only) |
| Linux container, no docker daemon | **11 caught, 0 missed**, 4 refused (the docker rows skip themselves rather than pass) |
| CI on ubuntu, with a daemon | **15 caught, 0 missed, 0 skipped** — nothing is refused there, because nothing needs to be |

That last row is the one that counts, and it is the only one no machine here
could produce: the docker mutations need a real daemon, and a container
without one refuses to score rather than passing. Splitting that hair is the
point — "15 caught on Linux" was written into this paragraph *before* any
runner had said so, and had to be taken back out. It is exactly the reflex
[U21](GAPS_RISKS_AND_UNFINISHED.md) is about, and writing the entry does not
make you immune to it.

**The paths that touch something real.** Docker containers actually start —
isolation is proven by the container answering under its own hostname and a
Debian `os-release` from the image, and by the agent being able to rewrite
what the container wrote. The provider HTTP client is driven against a loopback
server that speaks the protocol and can be told to misbehave, so the ~90
lines that used to first run when somebody spent money now run offline. The
first day is rehearsed end to end: bootstrap → `loop.py check` → first gated
task. Endurance is measured over 120 real tasks: latency flat at 0.13 s,
context window flat at 1083 tokens, nothing lost to the archive.

**Computers we do not own — and what they found.** Everything above was
produced on one Windows laptop, which is the flaw in all of it. The first CI
run on Ubuntu and Windows × Python 3.11/3.12/3.13 **failed four of six jobs**,
and every failure was a real defect that four audit passes had not found —
the worst being two loops executing the same task at once (six queued,
fourteen completions logged). Six defects later the suite is green on both
platforms. The point is not that they were fixed; it is that **no amount of
care on one machine would have found them**, and this project had been
disclosing that limit in writing without being able to act on it.

---

## What is NOT proven

Stated plainly, because a README that only reports wins is marketing.

- **No real provider has ever been called.** Every model call in every test
  is a scripted mock or a loopback server. `python loop.py check` is the only
  live probe, and until somebody runs it with a real key the honest ceiling
  for every capability here is **OFFLINE VERIFIED** — which is what
  `python proof.py` reports.
- **One machine is one machine, and it took three CI runs to stop finding
  defects.** Everything above was developed and proven on a single Windows
  laptop, green twice consecutively, after four audit passes. Then the suite
  ran on computers this code had never touched — Ubuntu and Windows × Python
  3.11/3.12/3.13. Each run found what the one before it had masked:

  | Run | Result | Found |
  |---|---|---|
  | 1 | 4 of 6 jobs failed | a task taken from a **live** sibling loop and executed twice; a container running as root, handing back a workspace the agent could not write to; a secret created world-readable; an evidence sentence claiming "on a Windows host" wherever it ran (U15–U18) — and reproducing them locally found two more, where "has this changed?" was decided by comparing two files' timestamps, unsound on the filesystem every container uses (U19, U20) |
  | 2 | 1 of 6 failed | the suite was green everywhere; the **mutation harness** was not. A row had reported CAUGHT for four releases while the test it certified had never actually run (U21) |
  | 3 | 1 of 6 failed | a settle window of zero behaving as a window of forever, because a file's mtime can land *ahead* of the wall clock (U22) |

  Eight defects, all fixed and held closed by tests and mutations
  ([U15–U22](GAPS_RISKS_AND_UNFINISHED.md)). U22 is the one to notice:
  3000 files written and stat'd on the development machine produced **zero**
  negative ages. It is not that the defect is rare here — it is invisible
  here. A green suite on one machine is evidence about that machine.
- **The UI has been used by nobody but its author.** The spec asks for a
  five-person test at ≥90 % task completion; that has not happened.
- **No gradient updates.** The Training Lab governs promotion and exports
  data. It does not train weights, and says so on every export.
- **Authentication is a bearer token over plain HTTP.** RBAC is real and
  enforced on every write; TLS, sessions and expiry are not there.
- **The "100×" claim is refused, not made.** It is defined as verified output
  per dollar *versus the same raw model without the fleet*. That needs the
  same work run twice and the baseline half has never been run, so
  `metrics.py` reports the harness's observable contribution as counts and
  refuses to divide them into a multiplier.

Of the six release gates the engineering manual defines, **only the developer
build is cleared.** The full table is in
[ARCHITECTURE.md §11](ARCHITECTURE.md#11-what-is-not-proven).

---

## Try it without a key

```bash
python demo.py            # the whole platform, keyless, in one run
python tests/run_all.py   # 142 acceptance tests
python proof.py           # what is proven, and to what level
python evidence.py        # why we believe it, and where belief runs out
python metrics.py         # is it working — and the numbers it refuses to invent
python preflight.py       # is this installation fit to run unattended
python mutate_check.py    # break each feature, confirm its test notices
```

## With a key

```bash
python bootstrap.py --key DEEPSEEK_API_KEY=sk-...   # the value is never printed
python loop.py check --root experts/<slug>          # the only live probe
python loop.py run --drain --root experts/<slug>    # work the queue
python ui.py                                        # the control panel
```

Keys live in `agent.env` beside the code, one `NAME=VALUE` per line. They are
reported present or absent and **never printed** — there is no route, log
line or backup that returns one. Set spend caps at every provider before
first use; the platform's own daily breaker is a second line of defence, not
the first.

---

## The control panel

Six sections named for jobs rather than architecture: **Home · Work · Agents
· Resources · Proof · Admin**. A command bar that asks *"what do you want
accomplished?"*, an agent-creation wizard that asks five intent questions
instead of exposing a taxonomy, a mission page that answers objective /
current action / blocker / remaining criteria / cost in one screen, a Proof
Center where clicking a badge shows the evidence and the command that
reproduces it, and a failure view that names *which part* failed — the
verifier, the platform, the provider, the budget, the command, the agent, or
you.

The panel goes as deep as the system does. Per agent:

- **Goal cockpit** — every pursuit opened whole: the frozen contract with
  each grader's live PASS/FAIL, budget bars, the cycle's milestones, the
  append-only ledger replayed event by event (with per-task traces), a
  **re-run-the-graders** button, and a **steering box** whose notes reach
  the planner's next cycle — advice on the record, never a grader.
- **Graph** — the knowledge graph drawn live on a canvas (no libraries):
  entities sized by evidence and colored by best source tier, drag to
  untangle, click a node for its cited atoms; beside it, the
  **load-bearing sources** (concentration risk — one retraction here takes
  an area of knowledge with it) and the claims resting below the learn bar.
- **Mastery** — every capability pack with its seal state (SEALED / TAMPER
  / draft-with-TODOs), author, competencies, and the honest score line:
  pretest → exam (**the measured lift**) → retention, against the pack's
  frozen bars.
- **Knowledge → Freshness** — expired, superseded and retracted claims
  flagged with reasons, and a retraction can be recorded from the panel.
- **Trace** — any task's whole life: every tool call, cost, token count,
  gate refusal and error, in order.

⌘K opens a palette where every action shows its equivalent CLI command, so
the panel teaches the terminal instead of hiding it.

---

## Documentation

**New here?** [QUICKSTART.md](QUICKSTART.md) → the systems table above →
[ARCHITECTURE.md](ARCHITECTURE.md) → [GOAL_SYSTEM_COMPLETE.md](GOAL_SYSTEM_COMPLETE.md).
**Auditing the claims?** [EVIDENCE.md](EVIDENCE.md) →
[GAPS_RISKS_AND_UNFINISHED.md](GAPS_RISKS_AND_UNFINISHED.md) →
[TRACEABILITY_MATRIX.md](TRACEABILITY_MATRIX.md) — the platform documents
its own holes as carefully as its features.

| Document | What it is |
|---|---|
| **[QUICKSTART.md](QUICKSTART.md)** | **zero to your first VERIFIED goal in ~15 minutes** |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | **the complete technical account — start here** |
| [MANUAL.md](MANUAL.md) | the operator's guide: every command, every setting |
| **[GOAL_SYSTEM_COMPLETE.md](GOAL_SYSTEM_COMPLETE.md)** | **the goal system end to end** — every module, loop, file format, the reasoning, and what is missing |
| **[GOAL_SPECIALIST.md](GOAL_SPECIALIST.md)** | the goal contract: graders the worker cannot write, and the audit's 115-gap register with honest statuses |
| [SECURITY.md](SECURITY.md) | trust boundaries, the six authorities, and the seven things deliberately NOT defended |
| **[CLOUDFLARE.md](CLOUDFLARE.md)** | can this run on Cloudflare? what fits, what cannot, and what it costs |
| **[deploy/VPS.md](deploy/VPS.md)** | **hosting it 24/7 on a $5 VPS, reachable from anywhere** — systemd, secure access, off-site snapshots |
| [deploy/README.md](deploy/README.md) | running it in a container: the R2 restore/snapshot lifecycle an ephemeral disk makes mandatory |
| [deploy/worker/README.md](deploy/worker/README.md) | the Cloudflare Worker: a Durable Object alarm that wakes the fleet, and a REST sandbox |
| [REFERENCE.md](REFERENCE.md) | every system end to end, and an honest list of limits |
| [GAPS_RISKS_AND_UNFINISHED.md](GAPS_RISKS_AND_UNFINISHED.md) | the audit record — five passes, 21 numbered defects |
| [REMEDIATION.md](REMEDIATION.md) | what was done about each, and the residual risk |
| [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) | each decision, the alternative rejected, the price paid |
| [SYSTEM_DIAGRAMS.md](SYSTEM_DIAGRAMS.md) | execution, memory, trust boundaries, and where the defects lived |
| [TRACEABILITY_MATRIX.md](TRACEABILITY_MATRIX.md) | capability → test → **what it does not establish** |
| [EVIDENCE.md](EVIDENCE.md) | generated from an actual suite run, quoting each test |
| [FULL_BUILD_FORENSIC_REPORT.md](FULL_BUILD_FORENSIC_REPORT.md) | the forensic audit, evidence-labelled |
| [CHANGELOG.md](CHANGELOG.md) | what shipped, and the defects each release found |

---

## Requirements

Python 3.11 or newer, and nothing else. Optional and detected at runtime:
`ffmpeg` and `yt-dlp` for audio/video ingestion, `pandoc` or `pymupdf` for
documents, `docker` for the isolated sandbox. `python toolbox.py` reports
what this machine actually has, and a missing capability is reported as
missing — an agent that cannot read a PDF says so instead of inventing its
contents.

## A note on the audit record

`GAPS_RISKS_AND_UNFINISHED.md` is kept in the audit's own present tense, and
`REMEDIATION.md` records what was done about each finding. Twenty-one
numbered defects, each with reproduction and the test that holds it closed
— **and five of them are defects in this project's own verification
machinery** (U8, U13, U17, U18, U21), because a report that finds faults
only in other people's work is not an audit.

The fifth pass is the one worth reading: it is what happened when the suite
ran on computers this project does not own.

---

## License

**GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).

Copyright © 2026 the Expert Fleet authors.

AGPL was chosen deliberately rather than MIT or Apache. The clause that
matters is **§13, Remote Network Interaction**: this platform ships a web
control panel (`ui.py`), so anyone who modifies it and offers it to others
over a network — a hosted "agent platform" built on this code — must make
their modified source available to those users. A permissive licence would
allow a closed hosted fork; this one does not.

What that means in practice:

- **Use it, privately, however you like.** Running it for yourself or inside
  your company, modified or not, triggers nothing. AGPL obligations attach to
  *distribution* and to *offering it over a network to others*.
- **Modify and self-host for your own use** — still nothing to publish.
- **Offer a modified version as a service to other people** — you must offer
  those users the corresponding source of your modified version.
- **Redistribute it** — under the same licence, with the source.

> This is a plain-language summary for orientation, not legal advice. The
> [LICENSE](LICENSE) file is the operative text, and if the distinction
> matters to your situation you should read §13 yourself or ask a lawyer.

If the copyright line should carry a legal name or entity rather than
"the Expert Fleet authors", edit it here and in any file headers you add —
it is the one thing in this repository that a tool should not have guessed.
