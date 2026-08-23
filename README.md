# Expert Fleet — learning & execution agents (v5)

**Start here:** `python bootstrap.py` sets everything up, tells you exactly
what is missing, creates your first expert and opens the control panel.
[MANUAL.md](MANUAL.md) is the practical guide; [REFERENCE.md](REFERENCE.md)
is the complete end-to-end explanation of every system, its logic and its
limits. The panel's own Guide covers the same ground inside the app.

```
python bootstrap.py --key OPENROUTER_API_KEY=... --expert "Night Analyst"
python doctor.py            # health + readiness
python harness.py --check   # every harness contract holds (exit 0)
python tests/run_all.py     # 74 offline acceptance tests
```

---

## The v4 build document (still true, plus everything since)

Implementation of the master build document: the loop (Part 5), memory layout
and fetch discipline (Parts 3, 6), the roles (Part 7, plus the closed-book
Student for hidden exams), the verification hierarchy's mechanical layer and
exit criterion with spaced re-exams (Part 8), the file-scale flywheel
(Part 9), and the ingestion matrix (Part 4).
Stdlib-only Python 3.11+; ffmpeg/pandoc/pymupdf used by ingestion when present.

## Layout

```
loop.py              the agent: queue, five tools, atomic state, course locks,
                     compaction, skill auto-loading, reflection chain,
                     exit criterion + spaced re-exam scheduler
ingest.py            Part 4 ingestion: scan-inbox, pdf-text/pdf-pages, docx,
                     chunk-audio, transcribe (Groq Whisper), frames, vision
verify.py            mechanical spec checks: runs every 'CHECK:' command in
                     spec.md, writes exam-results.md — ground truth, no model
memcheck.py          memory integrity: ID uniqueness, every [src:] citation
                     resolves, spec items cite defined atoms, index coverage —
                     makes the grounding rule mechanically checkable
fleet.py             mint isolated experts (own identity, memory, courses,
                     skills, state, spend) under experts/<name>/
ui.py                mission control (local web panel, stdlib): system
                     dashboard + per-expert tabs — Overview (teach, courses,
                     blocked, log), Memory (the expert's whole filesystem,
                     read-only, secrets refused), Board (task kanban, gaps,
                     re-exam schedule), Tools (verify/memcheck runs, manual
                     task queue for any role, provider probe, routing view)
demo.py              no-keys full-lifecycle demo with scripted models
settings.toml        per-role providers; Examiner on Groq Llama (different
                     family than the DeepSeek workers)
prompts/             constitution.md + _grounding.md prefix every role prompt
skills/              procedural memory (playbooks, written by the Reflector,
                     auto-loaded when a task goal matches name/KEYWORDS)
reputation.md        role × model × prompt-version scorecard
agent.service        24/7 daemon (Restart=always, unprivileged, hardened)
agent-inbox.*        systemd timer: scan inbox/ every 5 minutes
tests/               74 offline acceptance tests — python tests/run_all.py
inbox/  courses/  logs/  contexts/

--- v5: the harness as an inspectable object -------------------------------
bootstrap.py         one command: env, readiness, first expert, panel
harness.py           the manifest — tools, gates, policies, budgets, versions;
                     --check exits 0 only if every contract holds
context.py           the context COMPILER: per-source token budgets, explicit
                     trimming, and a manifest of every window it built
checkpoint.py        fiber-style checkpoints: long tool work recovers, never
                     restarts (transcription, folder ingest, crawls)
sandbox.py           where commands run: host | docker | e2b | daytona,
                     failing closed when a backend is unavailable
gotchas.py           environment failures, scoped and triggered, from real
                     failure records
premise.py           refuses to build on a premise memory already retracted
memrouter.py         which memory kinds a task may see (student stays
                     closed-book even against an owner override)
modelrouter.py       capability routing from measured outcomes, not vibes
routines.py          a task that worked → a skill + a schedule, one gesture
trace.py             one trace per task; per-tool error rates
uicards.py           agent-authored cards from a closed catalogue (no markup)

--- awareness, evidence, and the design gate -------------------------------
sources.py           every ingested source gets an authority tier (normative
                     → anecdotal), owner-overridable with a reason
conflicts.py         where the material disagrees with itself: rulings by
                     authority, recency, condition — or CONTESTED, which no
                     answer may state as settled
standards.py         the bar, extracted from normative atoms; contested and
                     defeated claims are refused
selfmodel.py         the agent's factual self-model, compiled into every
                     window: verified atoms, exams, competence, scars, gaps
designcheck.py       the mechanical design gate: contrast, scale, tokens,
                     breakpoints, the a11y floor, and the generated-filler
                     tells — wired as done_check for interface deliverables
MANUAL.md            the practical guide
REFERENCE.md         the complete end-to-end explanation, with honest limits
```

## The pipeline end to end

1. Drop anything into `inbox/` (or run `python ingest.py scan-inbox`).
   Text/markdown becomes a lesson directly (deterministic, no model); video,
   audio, PDF, images, docx queue a Ripper task; unknown types are parked.
2. Ripper converts to `lessons/NN/transcript.txt` using the ingest.py helpers.
3. Watcher writes cited notes (C-/P-/U- IDs, [src:] stamps), appends R-items
   to spec.md — mechanically checkable ones embed `CHECK: <command>`.
4. Practitioner executes spec items (skills playbooks auto-load); Examiner
   runs `verify.py` and `memcheck.py` first (ground truth), then grades the
   rest; every FAIL lands in gaps.md; Reflector updates lessons-learned.md,
   skills/, reputation.md after each execution task.
   Role hand-offs are automatic: `[agent.chain]` queues the next role when
   one finishes (ripper → watcher by default), and the idle loop turns every
   open `- G-nnn (role)` line in gaps.md into a queued task for that role —
   nothing evaporates, and an unresolved gap set is never re-queued in a loop.
5. `python loop.py course <name>` reports the exit criterion: all R-items
   PASS + SCORE ≥ threshold + gaps.md empty → COMPLETE. The idle loop then
   schedules re-exams at `reexam_days` (default 7/30/90) with NEW questions.

## Commands

```bash
python loop.py check          # probe every role's provider — run this FIRST
python loop.py add --role watcher --course myco --goal "Study lesson 03" \
    --memory courses/myco/lessons/03/transcript.txt
python loop.py run            # forever; --drain exits when the queue empties
python loop.py status
python loop.py course myco    # exit-criterion report
python loop.py answer <id> --text "..."   # unblock a task
python ingest.py scan-inbox
python verify.py myco         # mechanical spec checks
python memcheck.py myco       # memory integrity
python tests/run_all.py       # all 74 offline acceptance tests
```

## Plugging in providers (incl. OpenRouter)

Any OpenAI-compatible endpoint works. To run a role through OpenRouter:
set `provider = "openrouter"` and `model = "<id from openrouter.ai/models>"`
in that role's block; put the key in `OPENROUTER_API_KEY`. For models
without function calling, set `native_tools = false` on the provider — the
agent switches to the grounding header's inline-JSON tool format (tested).
Optional OpenRouter attribution headers go in
`[providers.openrouter.extra_headers]`. Then `python loop.py check` probes
every role's wiring with one live request each and exits nonzero on any
failure — run it before every deploy.

## Spec file conventions (parsed by verify.py and course_status)

- `spec.md`: `R-041 [from C-0701,P-0703]: <requirement> CHECK: <shell command
  that exits 0 iff the requirement holds>` — the CHECK part is optional but
  preferred; items without one are graded by the Examiner.
- `exam-results.md`: lines containing `R-nnn ... PASS|FAIL|NOT ATTEMPTED`
  (last occurrence per item wins) and a `SCORE: <n>` line for the exam.
- `gaps.md`: open gaps are lines starting with `- G-nnn`; empty file = no gaps.

## Tested guarantees (offline, mock providers, no keys)

kill-and-resume (Part 12-B) · single-writer lock incl. stale-break · native
and inline-JSON tool calls · reflection chain (exactly one, no self-chain) ·
context compaction · mechanical verification (impossible item FAILs with
evidence; re-runs replace, not stack) · inbox scan with real pymupdf/ffmpeg
extraction · skills compounding (run 2 loads run 1's playbook; unrelated
tasks don't) · exit criterion (each dimension blocks alone) + re-exam
scheduling (queued once, never re-queued) · memory integrity (all four
violation types detected; sound memory certified) · failure retries (fresh
context, error carried forward, capped, base goal un-stacked) · blocked-task
resume (`loop.py answer <task-id> --text "..."` injects the human's reply
and requeues) · hidden exams (a file in exam/pending/ dispatches a
closed-book Student whose context provably excludes the notes AND whose tool
allowlist has no read access — cheating is mechanically refused; grading is
chained; dispatched exactly once per question-file CONTENT, and a replaced
file is a fresh exam) · secrets denial (agent.env / ui-token.txt / .keys/
refused to the file tools, so injected material cannot order keys exfiltrated)
· **full lifecycle (test_e2e): one inbox
drop → ripper → watcher → practitioner → reflector → examiner+verify → gap →
librarian → COMPLETE → re-exam, 7 tasks, zero human interventions, and the
produced memory passes memcheck**.

## Deploying (Part 4)

One command as root from this directory: `sudo bash setup-vps.sh` — installs
packages, creates the unprivileged user, copies files, installs (without
enabling) the systemd units, writes the key-file template, and runs the full
test suite. Then: fill `/home/agent/agent.env` (**spend caps first**), run
`python3 loop.py check` until every role says OK, and
`systemctl enable --now agent agent-inbox.timer`.

## What still needs live models (key-gated, per Part 12)

- C: Watcher note quality on a real lesson — read notes.md yourself; expect
  2–3 prompt iterations (the document's own JUDGMENT grade).
- D: planted contradiction → Librarian rewrite + retractions.md entry.
- E: Examiner grading quality on non-mechanical items (the mechanical layer
  is already proven by test_verify).
- G: scoped tokens (T2) against a real external system, draft-mode first.
