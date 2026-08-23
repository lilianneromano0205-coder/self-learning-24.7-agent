# Architecture Decisions

The decisions this codebase embodies, reconstructed from the source. There is
no commit history to consult (§ the repository is not under version control),
so these are inferred from code structure and the reasoning left in comments —
several of which record the live failure that prompted the decision.

Each entry states the decision, the alternative it rejected, and **the price it
pays**. A decision record without a stated cost is marketing.

---

## AD-1 — State lives in files, not a database

**Decision.** Every durable structure is a JSON or JSONL file on disk, mutated
under an `O_EXCL` lockfile: `state.json` (task queue), `effects.jsonl`,
`approvals.json`, `prospective.json`, `skills/graph.json`, `logs/*.jsonl`.

**Rejected.** SQLite, which is in the standard library and would have provided
transactions, atomic multi-file updates, and a real concurrency model for free.

**Why the choice makes sense.** Everything is inspectable with `cat`. The owner
can read, diff, hand-edit and back up any part of the system's memory without
tooling. For a platform whose central promise is that its decisions are
auditable, plain text is not a compromise — it is the feature.

**Price paid.** Concurrency is hand-rolled, and it is where the audit found its
most serious reliability defect: the lock primitive breaks stale locks by age
and releases without verifying ownership, so a holder that stalls past 8
seconds can find its lockfile deleted by a second process and then delete a
third's (P1-2). SQLite would have made that class of bug impossible. There is
also no atomicity *across* files: a crash between the `effects.jsonl` write and
the `state.json` write leaves the two disagreeing, which is precisely the
mechanism behind P2-1.

---

## AD-2 — Standard library only

**Decision.** The core and the entire 81-file test suite run on stdlib Python.
Third-party packages (`pymupdf`, `docling`, `markitdown`) and external binaries
(`ffmpeg`, `pandoc`, `yt-dlp`, `docker`, `node`) are optional, guarded by
try/except, and degrade to an install hint.

**Rejected.** `requests`, `pydantic`, `pytest`, a web framework — the normal
stack.

**Why.** No dependency resolution, no supply chain to audit, no version drift,
and it runs anywhere Python does. I verified this by import analysis across all
139 Python files rather than trusting the README, and it holds.

**Price paid.** Hand-rolled HTTP handling, hand-rolled schema validation, and a
hand-rolled test runner. `ui.py` is 1,572 lines largely because it implements
what a framework supplies. The test runner's block-buffering bug (which once
made `evidence.py` report 0/77 observations) is exactly the kind of thing
`pytest` would never have had.

---

## AD-3 — Verification is deterministic code, never a model judging itself

**Decision.** The verifier stack — `citecheck`, `designcheck`, `memcheck`,
`conflicts`, `verify`, and the done-gate — is six separate deterministic
modules. `candidates.py` scores competing attempts by *reusing* them rather
than asking a model which attempt is better.

**Rejected.** LLM-as-judge, the industry default.

**Why this is the strongest decision in the build.** A system that scores its
own output with the same model that produced it cannot learn anything the model
does not already believe. Grounding these scores in deterministic checks is
what makes the test-time-compute mechanism (best-of-N) worth running at all.

**Price paid.** The verifiers measure *shape*, not *truth*. `citecheck`
confirms a citation is present and well-formed; it cannot confirm the citation
supports the claim. `designcheck` enforces specifics because, as its own test
says, taste is not enforceable. The build is honest about this, and it means a
confidently wrong artefact with tidy citations scores well.

---

## AD-4 — The harness is an inspectable object

**Decision.** `harness.py` exposes `manifest()`, `check_contracts()` and an
integrity check; `context.compile` writes a manifest naming every source
included, every source trimmed, and why; routing decisions carry a `why` string;
`trace.py` produces one trace per task with tool errors counted apart from
model errors.

**Rejected.** Logging as the observability story.

**Why.** This is what made the present audit possible at the depth it reached.
The compile manifest in particular means the exact window an agent saw is a
durable artefact, not a reconstruction.

**Price paid.** Real write volume on every task, and a large surface of
self-description that can drift from behaviour. The audit found exactly that
drift in the smaller case: `_state_lock`'s docstring says 30 s, the code says 8.

---

## AD-5 — Stale locks are broken by age, not by probing the holder

**Decision.** A lockfile older than 8 seconds is presumed abandoned and
removed. The code comment gives the reasoning explicitly: `os.kill(pid, 0)` on
Windows can terminate the target, and PIDs are reused.

**Rejected.** Liveness probing.

**Why the reasoning is sound.** Both stated objections are true. Age is a
defensible proxy on a platform where liveness probes are unsafe.

**Price paid, and the part that does not follow.** The argument rules out
probing a *foreign* PID. It does not rule out reading back *your own* token
before deleting a lockfile you believe is yours. Both implementations write
`os.getpid()` into the lock and never read it, which converts a sound
"don't probe" decision into an unsound "don't check" implementation. The
8-second threshold is also aggressive for a tree stored inside a OneDrive
folder, where sync and antivirus stalls of several seconds are ordinary.

---

## AD-6 — Untrusted content is fenced, and the fence is not called a security boundary

**Decision.** `_read_block` wraps file content in `<<<FILE-CONTENT>>>` markers;
the grounding prompt forbids obeying directives found inside the fence.

**Rejected.** Treating ingested documents as trusted input.

**Why it is right to include.** It raises the cost of a naive injection carried
in an ingested PDF or web page.

**Price paid, honestly stated by the build itself.** The code calls this
"spotlighting", which is the correct and modest term. **A prompt instruction is
not a security boundary.** Nothing mechanically prevents a model from following
an instruction inside the fence. The real containment is elsewhere — the tool
allow-list, path containment, environment scrubbing, the approval gate — and
that is where it belongs.

---

## AD-7 — Closed-book exams are enforced by removing the tool, not by asking

**Decision.** Two mechanisms, both mechanical: `memrouter`'s student rule can
only *remove* context sources, and `[roles.student] tools` omits `read_file`
entirely, so the Student has no capability to open a note.

**Rejected.** Instructing the model not to consult its notes.

**Why.** This is the correct pattern — capability removal beats instruction
every time, and it is the same reasoning as AD-6 applied where it actually can
be mechanised.

**Price paid.** The two layers are not equally strong. The context layer is
code; the tool layer is a settings value with **no test asserting `read_file`
is absent**. A one-word edit to `settings.toml` voids the guarantee and the
suite still passes green (P2-3).

---

## AD-8 — Failure is a first-class object

**Decision.** A gate failure runs `_file_memory`: record the failure, open a
case in `cases.py`, file a gotcha, score confidence, commit the task. Repeat
failures are detected as `RECURRED` rather than filed again. `cases.py` tracks
open → fixed → recurred, which is the half of a failure log that is normally
missing — *did the fix actually work?*

**Rejected.** Logging the error and retrying.

**Why.** Most systems discard this. Recurrence detection in particular is what
separates a failure log from a learning mechanism.

**Price paid.** Ledger growth over long operation is unbounded and unmeasured —
no test runs long enough to observe it (`test_retention` addresses durability
by construction, not by duration).

---

## AD-9 — Trials change nothing on disk until they pass a gate

**Decision.** A charter variant is selected by the `AGENT_PROMPT_VARIANT`
environment variable and read from `variants/<id>/<role>.md`. The live prompt
files are untouched until `variants.promote()` passes its gate, and a variant
must state a *prediction* about its effect before it can be promoted.

**Rejected.** Editing prompts in place and observing what happens.

**Why.** Rollback is free, and requiring a prediction converts prompt-tuning
from taste into a falsifiable claim.

**Price paid.** Prediction accuracy is scored against mocked model outcomes in
every test, so the mechanism is proven to *work* and never proven to *help*.

---

## AD-10 — Routing is earned from this expert's own measured outcomes

**Decision.** `modelrouter` picks the cheapest model clearing a pass-rate bar
on this expert's own gated work, keyed per expert rather than per fleet —
because, as the code comment says, a model that suits one expert's work may be
wrong for another's. The configured pair is always retained as fallback so
routing can never strand a role.

**Rejected.** A global leaderboard or a static per-role assignment.

**Why.** The measurement is local, gated and honest — outcomes come from real
verdicts, not benchmarks.

**Price paid — and it is severe.** The design has no exploration policy, so a
candidate can never accrue the runs it needs to become eligible (P1-4). The
decision is sound and the implementation is structurally inert. This is the
clearest case in the build of a good idea that was never closed out.

---

## AD-11 — Sandboxing fails closed

**Decision.** `sandbox.py` defines a backend interface (host / docker / e2b /
daytona). An unavailable backend refuses to run rather than silently falling
back to the host. Environment scrubbing is default-deny with narrow scoped
grants (`ingest.py` transcription receives `GROQ_API_KEY` and nothing else). A
timeout returns exit 124 and keeps partial output rather than discarding it.

**Rejected.** Best-effort isolation with host fallback.

**Why.** Silent downgrade to the host is the failure mode that makes sandboxing
worthless in practice.

**Price paid.** The guarantee has a hole the design did not anticipate: the
*verification* path (`check_done`, `verify.py`) never calls into `sandbox` at
all, so model-authored gate commands run on the host with the full environment
regardless of the sandbox setting (P1-1, reproduced). Only the host backend was
ever exercised in testing.

---

## AD-12 — Generative UI drawn from a closed catalogue

**Decision.** `uicards.py` renders cards only from a fixed catalogue of card
types. The model chooses *which* card, never what a card can do.

**Rejected.** Model-authored HTML.

**Why.** Generative UI without a closed catalogue is remote code execution with
extra steps.

**Price paid.** New presentation needs code, not a prompt. Correct trade.

---

## AD-13 — Study order is decided by source authority, not arrival order

**Decision.** `curriculum.py` orders material by the source-authority tier
already recorded in `sources.py` (tier 1 normative → tier 4 anecdotal), pulls
prerequisites, and marks near-duplicates `skim` rather than studying them
twice. `covers_same_ground` combines shingle and word Jaccard (taking the max);
`covers_mission` uses containment rather than Jaccard.

**Rejected.** Studying material in the order it was ingested.

**Why.** Authority-first ordering means later material is read against an
established baseline instead of averaging into it. The containment fix was
necessary because Jaccard is structurally wrong for asymmetric relevance — a
short mission statement can never have high Jaccard with a long lesson.

**Price paid.** Every threshold in the module (`DUPLICATE_AT = 0.60`,
`OVERLAP_AT = 0.30`, `SKIM_BELOW = 0.10`, `MIN_JACCARD = 0.30` in `conflicts`)
is a tuned constant with no principled derivation. They were moved during
development in response to observed false positives, which means they are
fitted to the material seen so far.

---

## AD-14 — Each test runs as its own subprocess in `evidence.py`

**Decision.** `evidence.py` executes each test itself rather than parsing a
combined run's output.

**Rejected.** Running `run_all.py` once and scraping stdout.

**Why.** The scraping approach silently produced 0/77 observations: `run_all.py`
headers were block-buffered when writing to a pipe, so the section markers were
interleaved unusably. The fix was structural, plus `flush=True`.

**Price paid.** The evidence run costs a full serial suite execution. And the
mechanism only sees tests that print `[section]` markers — 11 of 81 print none,
including the adversarial ones, so the evidence report is quietest exactly
where the hardest claims live.

---

## AD-15 — The panel is trusted because it is "local"

**Decision.** `ui.py` binds `127.0.0.1` and treats that as the security
boundary: `_authed()` returns `True` for everything when no token is set, and a
token is auto-generated only when the bind address is non-local.

**Rejected.** Unconditional authentication; origin checking; a Unix socket.

**Why it looks reasonable.** A loopback bind does stop *other machines* from
reaching the panel, and the auto-token-on-exposure rule is a genuinely good
instinct — the dangerous configuration enables its own defence.

**Price paid — and this is the audit's most expensive line.** A loopback bind
does **not** stop *other origins in the operator's own browser*. Any web page
can issue a cross-origin `text/plain` POST — a CORS simple request, no
preflight — and the server acts on it. Combined with AD-16 this is arbitrary
code execution on the operator's machine, reproduced. "Local" is a network
boundary; the browser is a different threat model, and the code does not
distinguish them.

---

## AD-16 — The definition of done is a free-form shell command

**Decision.** `done_check` is a string executed with `shell=True`. It is
accepted from the task record, from workflow specs, from prospective
intentions, from `goal.py`'s planner, from `spec.md` `CHECK:` lines — and from
the HTTP request body.

**Rejected.** A parameterised gate catalogue.

**Why it was chosen.** Maximum expressiveness for nothing: any check anyone can
write in a shell becomes a gate, and the four gates the platform ships
(`designcheck`, `citecheck`, `verify`, file-exists) all fall out of it for
free.

**Price paid.** The gate became the single widest attack surface in the build.
It bypasses `policy.py` and `sandbox.py` (AD-11's containment), it carries the
full environment including `agent.env`, it is reachable over HTTP without
authentication (AD-15), and it can be *stored* in `prospective.json` to fire
later. Every one of the four gates actually used is parameterisable — the
free-form string buys expressiveness the platform never spends.

---

## AD-17 — Containment is enforced at the tool boundary, not the filesystem boundary

**Decision.** `_safe_path` guards the model's `read_file`/`write_file` and one
UI endpoint. Everything the *harness itself* writes — gotchas, cases,
candidates, conflicts, curriculum plans, course locks, checkpoints, ledgers —
writes directly with `os.path.join`.

**Rejected.** A single filesystem gateway every writer passes through.

**Why it is defensible.** The model is the untrusted actor; the harness is
trusted code. Guarding the boundary the untrusted actor crosses is the right
instinct, and it keeps the trusted paths simple.

**Price paid.** The harness's own writers take *model-influenced data* as path
components — most sharply `task["course"]`, which is stored verbatim and never
sanitised. Five harness writers build `courses/<course>/…` paths from it, and
one of them was shown writing outside the expert root. The trusted code is
trusted with untrusted *inputs*, which is a different thing from being trusted.

The same shape appears in the secret lists: four of them
(`loop.SECRET_BASENAMES`, `backup.SECRET_NAMES`, `package.SKIP_FILES`,
`sandbox.SECRET_MARKERS`) each guard their own boundary, none shares a
definition, and no two agree.

---

## The pattern across all seventeen

The first pass described the failure profile as *"a sound decision whose
implementation was not carried all the way to its own edges."* Reading every
module confirms that, and sharpens it into something more specific:

**Every control in this build defends the path its author was thinking about,
and no control knows about the other paths that reach the same operation.**

- `sandbox` guards `run_command`; five other `shell=True` sites exist.
- `_safe_path` guards two tools; five harness writers and the whole ingestion
  path do not use it.
- `backup` excludes five basenames; two other credential mechanisms exist.
- `variants.PROTECTED_ROLES` guards `spawn()`; `write_file` and `promote()`
  reach the same prompts.
- `script_guard` guards `run_command`; the gate path does not consult it.
- The budget guards one `call_model` site; there are four.
- `providers.py`, `chief.py`, `backup.py`, `package.py` and `_safe_path` each
  model credentials differently from `loop.py`.

This is not carelessness — each control is individually well-reasoned, and
several (the zip-slip check, the `esc()` discipline, `STRICTER` threshold
resolution, the closed-book context rule) are excellent and hold under attack.
It is a **structural** consequence of AD-1 and AD-17: with no single gateway
for command execution, filesystem writes, or credential resolution, each new
feature adds a path, and nothing forces the new path past the old guard.

The fix that would retire most of this report is not seventeen fixes. It is
three gateways — one for executing a command, one for writing a file, one for
resolving a secret — that every caller must pass through.

## The pattern across all fourteen (first pass)

The build consistently prefers **mechanism over instruction** (AD-3, AD-6,
AD-7, AD-12), **inspectability over convenience** (AD-1, AD-4), and **failing
closed over degrading quietly** (AD-11). Where it falls short, it is almost
always the same shape: a sound decision whose implementation was not carried
all the way to its own edges — the lock that checks age but not ownership, the
sandbox that guards the work path but not the verification path, the router
that scores candidates it can never obtain data for.

That is a much better failure profile than the reverse, and it is why the
findings in `GAPS_RISKS_AND_UNFINISHED.md` are mostly small, local changes
rather than redesigns.

---

# Decisions taken while implementing the UI/UX redesign (2026-08-23)

Same rule as every entry above: the decision, the alternative it rejected, and
**the price it pays**. A decision record without a stated cost is marketing.

---

## ADR-U1 — Navigation follows jobs, and nothing is deleted to achieve it

**Decision.** Six top-level sections named for what a person is trying to do —
Home, Work, Agents, Resources, Proof, Admin — with every previously-primary
view **moved** into one of them rather than removed.

**Rejected.** Deleting the views the redesign supersedes. It is the cleaner
diff and the more confident-looking product.

**Why.** A screen that exists because somebody needed it once will be needed
again, usually by the person least able to reconstruct it. Memory, Models,
System and Guide all still render, all still route, and `test_frontend.py`
asserts both — *and* that each is reachable from a control a person can click,
because a view reachable only by typing an internal name is deleted in every
sense that matters.

**Price.** The router carries ten branches where six would do, and every
moved view needed a `nested` flag so it does not print a second page title.
Two ways to reach the same screen is a real cost in comprehension; it is
smaller than the cost of losing one.

---

## ADR-U2 — The creation wizard maps intent to a lane, and names the lane once

**Decision.** Five intent questions ("do you need this working immediately from
files?") map invisibly onto the five creation lanes. The lane is named exactly
once, in the review step, as a footnote.

**Rejected.** (a) Removing the lanes and having one creation path. (b) Keeping
the lane picker as the only entry.

**Why.** The lanes are real: a trained expert and a quick specialist differ in
what they may honestly claim, and collapsing them would mean claiming the
higher bar for both. But nobody should have to learn that taxonomy to get
started. `LANE_STEPS` declares which of the six steps each lane can honour, so
a lane can never reach a step whose answer nothing consumes — the failure mode
where a wizard collects an answer and discards it.

**Price.** Two lanes (archetype, team) hand straight off to their existing
dialogs rather than walking six steps, so the wizard is not uniform. Uniformity
would have meant ceremony; §4's requirement is that nobody must know the
taxonomy, not that every path has six steps.

---

## ADR-U3 — A model policy is a name for two numbers, derived rather than stored

**Decision.** Cheapest / Balanced / Highest quality / Custom are names for
`route_min_pass` and `route_prefer`, and the policy in force is **computed** by
comparing the settings to the presets.

**Rejected.** Storing the chosen policy name in settings.

**Why.** The same argument as proof levels: a stored label and the settings it
claims to describe drift apart, and then the label is a lie that looks
authoritative. Deriving it means editing `route_min_pass` by hand shows up
immediately as "Custom", which is the truth.

**Price.** Deriving costs a comparison on every read, and a policy whose
numbers coincidentally match a preset is reported as that preset even if the
owner set them by hand. That is a small misreading; a stale stored label is a
large one.

---

## ADR-U4 — `route_prefer` exists, because "cheapest that works" is a choice

**Decision.** The router's tie-break among candidates that clear the bar is
configurable: cost, or verified pass rate.

**Rejected.** Keeping cost as the only tie-break, on the grounds that the bar
already encodes quality.

**Why.** It does not. "The cheapest model that clears 80%" and "the model with
the best rate above 80%" are different answers to the same evidence, and which
one is right depends on what being wrong costs — which the platform cannot
know and the owner can.

**Price.** One more setting, and a second sort path to keep correct. Both are
covered by `test_modelrouter.py`'s existing profile fixtures.

---

## ADR-U5 — Training data carries no percentages

**Decision.** `/api/experts/<s>/training` returns numerators and denominators.
It computes no ratios, so the page physically cannot render "100% learned".

**Rejected.** Returning a `coverage_pct` and asking the UI to caveat it.

**Why.** §10 says never show a percentage without an explicit denominator. A
style rule in a template is a rule somebody will violate in a hurry; refusing
at the source is a rule that cannot be. And 42/42 with 3 unresolved conflicts
is a sentence somebody can check, which a percentage never is.

**Price.** The panel does arithmetic the API could have done once, and a future
consumer that genuinely wants a ratio has to compute it — with the denominator
in hand, which is the point.

---

## ADR-U6 — Every write route's permission is a declared table with a strict default

**Decision.** `POST_PERMISSION` and `ACTION_PERMISSION` name the permission each
route needs. A route with no entry falls through to `create_agent`, which needs
builder or above.

**Rejected.** (a) Checking permissions inside each handler. (b) Defaulting an
unlisted route to allow.

**Why.** Checks scattered through handlers make "which routes are gated?"
unanswerable without reading all of them, which is how a route ends up ungated
by omission — the exact shape of every defect this audit has found. And a
permissive default means the failure mode of forgetting is *silence*, which is
the one failure mode a security control must not have.

**Price.** A route that genuinely should be public — `/api/workers/choose` is
a read dressed as a POST — must be listed, or a viewer cannot call it. That is
the correct direction to be wrong in.

---

## ADR-U7 — Members hold personal bearer tokens; the master token stays a master key

**Decision.** `org.issue_token` mints a per-member token, stores only its
SHA-256, returns the plaintext once, and compares in constant time. Whoever
holds the token the panel was *started* with resolves to the owner.

**Rejected.** (a) Passwords and sessions. (b) Trusting an actor named in the
request body. (c) Pretending the master token is just another credential.

**Why.** (a) is a real authentication system, which needs TLS, hashing
parameters, session invalidation and rate limiting — none of which belongs in a
stdlib-only local platform, and all of which would be done badly here. (b) is
what the code did before, and an audit trail whose author is a request field
records what the caller typed. (c) would be a lie: the master token already
implies control of the process, so treating it as a limited credential would
create a boundary that does not exist.

**Price.** No expiry, no rotation reminder, no rate limit on token guessing —
32 bytes of entropy is the whole defence. On a loopback HTTP server that is
proportionate; behind anything public it is not, and `REFERENCE.md` §20 says so
in those words.
