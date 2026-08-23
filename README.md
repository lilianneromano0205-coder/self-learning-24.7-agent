# Expert Fleet

**A file-backed, stdlib-only platform for building expert AI agents that work
continuously, prove what they did, and remember what they learned.**

70 Python modules · 99 acceptance tests · one HTML control panel · no
database, no framework, no build step. Python 3.11+ and your own API keys.

```bash
python bootstrap.py
```

One idempotent command: creates `agent.env`, tells you exactly what is
missing (numbered, with the fix), creates your first expert, starts the
control panel and opens it.

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

## The five ideas you need to know

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

**3. Five authorities, not scattered checks.**
A forensic audit of this codebase found the same pattern everywhere: *a
control defends the path its author was thinking about, and does not know
about the other paths.* Six places executed shell; one was tested. The answer
is one mandatory gateway per kind of power — Execution, File, Credential,
Model Gateway, Effect — and `python execution.py --audit` fails the build if
any module bypasses one. Today: **0 violations across 70 modules.**

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

---

## Why you should believe any of it

Four kinds of evidence, weakest first.

**The suite passes.** 99 acceptance tests, green twice consecutively from
clean. Each prints a sentence describing what it observed; `EVIDENCE.md`
quotes them verbatim.

**The tests enumerate rather than exemplify.** `tests/test_invariants.py`
does not test through an example — it walks the tree: every subprocess call
site in 70 modules, every declared control file, 12 traversal spellings, all
4 credential sources against every subsystem that must exclude them, all 9
provider-call purposes, all 9 roles, every module that mints an expert, every
reader of the exam file, all 139 sandbox names across 99 test files, and all
61 CLI subcommands the manual promises.

**Mutation testing — 10 of 10 caught.** A passing test proves nothing unless
it would fail with the feature removed. `mutate_check.py` breaks each
load-bearing behaviour and requires its test to fail:

```
CAUGHT  docker: egress allowed by default
CAUGHT  docker: timeout leaves the container running
CAUGHT  docker: credentials passed into the container
CAUGHT  provider: no Authorization header
CAUGHT  provider: malformed body kills the task
CAUGHT  provider: 4xx retried like weather
CAUGHT  package: ship the credential file
CAUGHT  endurance: never archive finished work
CAUGHT  rbac: every write allowed
CAUGHT  fleet: creation stops seeding the home

10 mutations: 10 caught, 0 missed
```

**The paths that touch something real.** Docker containers actually start —
isolation is proven by reading a Debian `os-release` from inside a container
on a Windows host. The provider HTTP client is driven against a loopback
server that speaks the protocol and can be told to misbehave, so the ~90
lines that used to first run when somebody spent money now run offline. The
first day is rehearsed end to end: bootstrap → `loop.py check` → first gated
task. Endurance is measured over 120 real tasks: latency flat at 0.13 s,
context window flat at 1083 tokens, nothing lost to the archive.

---

## What is NOT proven

Stated plainly, because a README that only reports wins is marketing.

- **No real provider has ever been called.** Every model call in every test
  is a scripted mock or a loopback server. `python loop.py check` is the only
  live probe, and until somebody runs it with a real key the honest ceiling
  for every capability here is **OFFLINE VERIFIED** — which is what
  `python proof.py` reports.
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
python tests/run_all.py   # 99 acceptance tests
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

⌘K opens a palette where every action shows its equivalent CLI command, so
the panel teaches the terminal instead of hiding it.

---

## Documentation

| Document | What it is |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | **the complete technical account — start here** |
| [MANUAL.md](MANUAL.md) | the operator's guide: every command, every setting |
| [REFERENCE.md](REFERENCE.md) | every system end to end, and an honest list of limits |
| [GAPS_RISKS_AND_UNFINISHED.md](GAPS_RISKS_AND_UNFINISHED.md) | the audit record — four passes, 14 numbered defects |
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
`REMEDIATION.md` records what was done about each finding. Fourteen numbered
defects, each with reproduction and the test that holds it closed — **and
three of them are defects in code written during those same passes**, because
a report that finds faults only in other people's work is not an audit.
