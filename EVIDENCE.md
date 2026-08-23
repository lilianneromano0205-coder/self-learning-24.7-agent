# Evidence — why we believe this works

Generated 2026-08-23T00:37:21 from an actual suite run: **83/83 tests passed**, **341 observations** recorded.

Each test below prints its own sentence describing what it proved; those sentences are quoted verbatim, not summarised. Every system also carries a **blind spot** — what these tests do not cover.

> Every model call in every test is the scripted mock provider. A green suite proves the harness holds; it never proves that any real provider works. `python loop.py check` is the only live probe.

## Verdict by system

| system | verdict | tests | observations |
|---|---|---|---|
| 1. Harness & loop | **proven** | 23/23 | 81 |
| 2. Fleet & creation lanes | **proven** | 6/6 | 21 |
| 3. Work systems | **proven** | 15/15 | 59 |
| 4. Memory institution | **proven** | 13/13 | 49 |
| 5. Improvement & governance | **proven** | 8/8 | 33 |
| 6. Control plane & interop | **proven** | 18/18 | 98 |

## 1. Harness & loop

*the engine: context assembly, five tools, gates, brakes, retries, escalation, policy, effects, compaction*

**Verdict: proven** — 23 of 23 declared tests ran and passed, producing 81 observations.

<details><summary>What the tests observed (81)</summary>

- `test_harness.py` **[manifest]** 5 tools with role allowlists, 9+ gates, policies, 14 memory tiers, budgets, events, file hashes - all read from what runs
- `test_harness.py` **[contracts]** the real harness agrees with itself; a tool declared without an execution branch is named
- `test_harness.py` **[ritual]** every run starts with a sub-second health check written to logs/health.json; a corrupt ledger is named and the loop still drains
- `test_harness.py` **[panel]** /api/harness, /api/experts/<s>/harness, /api/readiness answer; readiness names the ENV var to set, never a value
- `test_faults.py` **[faults]** every broken contract was caught by the validator with the reason named, instead of reaching a model as garbage
- `test_stop.py` **[deadline]** a task past its deadline fails with the stop condition named, filed as a budget failure
- `test_stop.py` **[attempts]** max_attempts=1 stopped the retry the default budget would have made; the refusal names the stop condition
- `test_stop.py` **[steps]** max_steps=2 ended the task at step 2 with the reason
- `test_stop.py` **[context]** the stop condition is in the first message and in the compaction's HARNESS FACTS
- `test_stop.py` **[surface]** stop conditions declared from the CLI and the panel, echoed back on the board
- `test_checkpoint.py` **[primitive]** done items and state survive re-activation; finish is recorded; keys are scoped by lineage + inputs
- `test_checkpoint.py` **[transcribe]** a failure at chunk 2 resumed at chunk 2 on rerun: chunk 1 transcribed once, offsets continuous, transcript complete
- `test_checkpoint.py` **[folder]** ingesting the same folder twice queued each file exactly once
- `test_retry.py` **[retry]** the failed task was retried with the error in hand and a FRESH context, exactly the configured number of times
- `test_compaction.py` **[compaction]** the oldest turns were summarised while the head and the recent tail stayed verbatim, and the archive kept what left the window
- `test_lock.py` **[unit]** live lock blocks; dead/unknown/stale owner locks are broken
- `test_lock.py` **[integration]** two same-course tasks serialized, both done, lock released
- `test_paths.py` **[paths]** every escape spelling was refused with a clear ERROR the agent could recover from, and in-root writes were unaffected
- `test_reliability.py` **[quarantine]** a corrupt state file was quarantined with its evidence kept and the queue rebuilt - the loop kept running
- `test_e2e_crash.py` **[crash]** kill -9 in the MIDDLE of the lifecycle changed nothing about the end state: same tasks, course complete, memcheck certified
- `test_layers.py` **[L6]** finish_task refused twice with evidence, accepted only once the check passed — verification is a constraint, not a suggestion
- `test_layers.py` **[L6]** a task that can never satisfy its check fails after 3 refusals, instead of looping forever
- `test_layers.py` **[L1]** per-run cost ceiling killed the task at $3.0 after 3 steps — the third brake works
- `test_layers.py` **[L2]** every tool failure comes back as recoverable text, never an exception
- `test_layers.py` **[L5]** 3 consecutive tool errors handed the task to the stronger model, which finished it
- `test_layers.py` **[L5]** the model asked for a stronger model with [[ESCALATE]] and got it
- `test_layers.py` **[layers]** all seven contract layers held as CONSTRAINTS, not as prompt requests: tools, paths, budget, steps, gate, escalation, chain
- `test_json_toolcall.py` **[json-tools]** a model that cannot emit native tool calls is still usable: inline JSON in the content parses and executes
- `test_guardrails.py` **[budget]** $4 spent against a $3 ceiling: loop paused, next task untouched, human notified exactly once
- `test_guardrails.py` **[repetition]** identical call warned at 3, failed at 5 with the loop named
- `test_guardrails.py` **[rule-of-two]** run_command denied for the limited role: no execution, clear error, task continued
- `test_guardrails.py` **[marking]** injected directive fenced as untrusted data, rule present in grounding
- `test_guardrails.py` **[secrets]** agent.env/ui-token.txt refused for read AND write (incl. traversal spellings); normal files unaffected
- `test_effects.py` **[exactly-once]** 3 attempts of an emailing task, 1 real send; the retry received the recorded result, labelled REPLAYED; the ledger holds one effect for the lineage
- `test_effects.py` **[fresh]** an explicit --fresh call hits the world again — the ledger is a default, not a cage
- `test_effects.py` **[policy]** destructive/escalating commands refused INSIDE the loop with the rule named; normal work passed; owner deny rules and per-role allowlists enforced
- `test_effects.py` **[governance]** role allowlists and tool deny lists enforced before the server is touched; 50k-char result capped at 20k; a vetted catalog of 8 open-source servers ships
- `test_sandbox.py` **[host]** the default backend runs in the expert's own root with the AGENT_* environment the harness promises
- `test_sandbox.py` **[closed]** an unknown backend and unconfigured hosted backends refuse the command instead of quietly running it on this machine
- `test_sandbox.py` **[loop]** with a hosted backend configured but no key, the agent was told exactly what is missing -- and nothing ran locally
- `test_sandbox.py` **[order]** policy.py still decides what may be attempted at all, before any backend is asked to run it
- `test_sandbox.py` **[docker]** ran inside a throwaway container at /work with no network, and the AGENT_* environment intact
- `test_secrets.py` **[scrub]** every credential-shaped variable was withheld by name pattern, including one the platform has never heard of
- `test_secrets.py` **[scoped]** the transcription helper kept exactly the one credential it needs; a bare `env` got none
- `test_secrets.py` **[owner]** an explicit allowlist entry passed one named key through, and nothing rode along with it
- `test_secrets.py` **[e2e]** an agent that went looking for the keys found ABSENT, and no key value reached the transcript, the logs or the state
- `test_secrets.py` **[timeout]** a killed command reported the timeout AND kept the work it had already printed
- `test_chaos.py` **[kill]** killed mid-task with no cleanup: state parsed, the task resumed and finished, every artifact landed
- `test_chaos.py` **[ledgers]** 6 corrupted ledgers, zero crashes; the queue was quarantined rather than discarded
- `test_chaos.py` **[provider]** the primary provider refused every connection; the fallback finished the task and the record names which one ran
- `test_chaos.py` **[race]** two loops drained one expert at the same time: four tasks, four completions, no task claimed twice
- `test_chaos.py` **[disk]** a write that failed with ENOSPC left the previous state byte-identical and the loop recovered
- `test_chaos.py` **[size]** an 11 MB file, 1,000 atoms and 200 skills compiled to a 13234 token window in 1.2s, cut marked
- `test_chaos.py` **[clock]** a far-future deadline ran to completion and a long-past one refused to start, both naming the reason
- `test_blocked.py` **[blocked]** question recorded in blocked.md, task blocked, loop moved on
- `test_hardening.py` **[locks]** release verifies ownership: a stalled holder cannot free the lock that replaced it, and tokens are per-acquisition
- `test_hardening.py` **[gates]** the catalogue builds the command; traversal, shell syntax, unknown gates and raw strings are all refused
- `test_hardening.py` **[secrets]** api_key_file and inline api_key are secrets to every subsystem; ordinary files and settings.toml are unaffected
- `test_hardening.py` **[writes]** settings, charters, approvals and ledgers are unwritable by the agent; its own work and skills still are
- `test_hardening.py` **[scheme]** file://, ftp:// and bare paths refused by ingestion
- `test_hardening.py` **[course]** a traversing course name is slugified; the gotcha lands inside the expert, not above it
- `test_hardening.py` **[skills]** a third-party SKILL.md cannot self-declare 'own'; only the owner's recorded decision grants trust
- `test_hardening.py` **[effects]** the ledger is write-ahead: an unresolved effect is visible, and one effect reads as one entry
- `test_candidates.py` **[artifacts]** the scorer reads what the task actually wrote from its own step record, not from a guess
- `test_candidates.py` **[gate]** two identical artifacts, one gate failure: the failure cannot win at any score
- `test_candidates.py` **[interface]** the considered page scored 1.0 and the generated filler 0.0, both passing the same gate
- `test_candidates.py` **[applies]** a citation to a nonexistent atom sank its candidate; the same check stayed silent about an interface
- `test_candidates.py` **[isolation]** an attempt's changes were undone byte-for-byte, including deleting the file it invented
- `test_candidates.py` **[promote]** the winning attempt's bytes were put back and every attempt kept its own score on disk
- `test_candidates.py` **[adaptive]** one attempt until something fails, then 3, then 5 — capped by the owner's setting and switchable off
- `test_candidates.py` **[explain]** the winner is reported with the reason every loser lost
- `test_retention.py` **[bounded]** 300 tasks done, hot queue holds 40 finished (60 KB); queued and blocked work untouched
- `test_retention.py` **[lossless]** all 302 tasks accounted for — 260 archived, every field intact and findable by id
- `test_retention.py` **[flat]** persist cost 12 ms -> 16 ms after 400 more tasks (was 185 ms at 1500 before retention)
- `test_retention.py` **[context]** finished transcripts tidied into contexts/archive/, the verbatim never-lose tier left in place and still recallable
- `test_retention.py` **[heartbeat]** the loop pulses with its current task; a stale pulse is what separates 'wedged' from 'idle'
- `test_context.py` **[manifest]** the compiled window names every source it used and the files inside it; the transcript matches the manifest
- `test_context.py` **[disclosure]** a skill that did not activate is offered by name and one line, not by loading its body
- `test_context.py` **[budget]** a 45 KB handed file was cut to its 500-token budget and the cut is marked with how to read the rest
- `test_context.py` **[clearing]** big tool outputs were archived verbatim and replaced by a pointer before summarizing -- the summarizer never saw them
- `test_context.py` **[panel]** the control panel serves the exact window each task was given, per source

</details>

**Blind spot.** every model call in these tests is the scripted mock provider. They prove the harness holds around a model; they prove nothing about any real provider's behaviour.

## 2. Fleet & creation lanes

*trained expert, quick specialist, archetype, learner, team*

**Verdict: proven** — 6 of 6 declared tests ran and passed, producing 21 observations.

<details><summary>What the tests observed (21)</summary>

- `test_fleet.py` **[identity]** each expert carries its own identity, under the constitution
- `test_fleet.py` **[isolation]** alpha worked; beta's memory untouched
- `test_fleet.py` **[fleet]** list shows both experts with independent task counts
- `test_quick.py` **[kind]** operator/advisor/maker detected; unknown defaults to maker
- `test_quick.py` **[briefing]** 3 files converted with zero model cost, image routed to a Ripper queued ahead of the job, index built, deliverable gated
- `test_quick.py` **[operator]** job done through its gate, Examiner review chained and done
- `test_quick.py` **[advisor]** question answered by the shell-less Consultant, briefing cited, unknown marked UNVERIFIED, delivery gated
- `test_lanes.py` **[teach]** 'use as this agent's charter' now applies the template for real
- `test_lanes.py` **[intentions]** armed, listed, cancelled through the panel API
- `test_lanes.py` **[federation]** identity, publish, A2A card — all from the panel, no secret material in any payload
- `test_lanes.py` **[shapes]** settings carry key_present; detail carries consults — the panel renders what the backend actually returns
- `test_team.py` **[flow]** lead planned, both specialists delivered, lead synthesized — all gated
- `test_team.py` **[handoff]** outputs flowed forward as files; no shared mutable state
- `test_team.py` **[isolation]** beta:1 task, gamma:1 task, alpha:plan+synthesis — memories separate
- `test_team.py` **[result]** one deliverable, citations preserved, run listed
- `test_toolbox.py` **[scan]** capabilities reflect this machine; the note instructs, not hints
- `test_toolbox.py` **[gallery]** 20 specialists, all kinds covered, identities carry standards and refusals
- `test_toolbox.py` **[quick]** capability note injected first; template identity installed
- `test_local.py` **[env]** agent.env loaded automatically, comments and quotes handled
- `test_local.py` **[inbox]** daemon scanned its own inbox on idle: file -> lesson -> watcher -> done
- `test_local.py` **[demo]** python demo.py: full lifecycle, COMPLETE course, both proofs PASS, no keys

</details>

**Blind spot.** the lanes are exercised with scripted providers and small briefings; no test covers a multi-hour real ingestion or a team larger than three specialists.

## 3. Work systems

*task, goal engine, team, deterministic workflow, consultation, prospective intentions, routines*

**Verdict: proven** — 15 of 15 declared tests ran and passed, producing 59 observations.

<details><summary>What the tests observed (59)</summary>

- `test_goal.py` **[judge]** a judge claiming ACHIEVED while a check failed was OVERRULED; the pursuit continued and finished the work for real
- `test_goal.py` **[replan]** cycle 2 planned WITH the previous assessment in hand
- `test_goal.py` **[shape]** learning goals detected; build goals keep a build-shaped plan
- `test_goal.py` **[commons]** the overruled-judge failure became a binding fleet lesson; duplicates collapse into repeat markers; the directory lists who knows what
- `test_goal.py` **[share]** every task now opens with what the agent has verified about itself, then the fleet's shared memory
- `test_goal.py` **[peer]** one expert asked another; the answer runs through the peer's own citation gate, attributed to the asker
- `test_workflows.py` **[chain]** draft -> review -> revise ran on one idle drain in order, each stage gated on its own deliverable, variables substituted
- `test_workflows.py` **[halt]** a failed gate in stage 2 stopped the pipeline — stage 3 never queued; status reports exactly where evidence stopped
- `test_workflows.py` **[guard]** single-stage specs refused; workflows listable with status
- `test_consult.py` **[gate]** real citation passes; ghost named and failed; uncited essay failed; honest blank passes
- `test_consult.py` **[flow]** hallucinated citation blocked at the gate (C-7777 named), corrected answer shipped with real citations + honest blank
- `test_prospective.py` **[deadline]** fired exactly once, queued a normal task carrying the trigger and the reason; the record survives as history
- `test_prospective.py` **[watch]** file_contains held silent until the phrase appeared, then fired
- `test_prospective.py` **[chain]** task_done waited for the task, then queued the follow-on
- `test_prospective.py` **[recur]** every_days fired and re-armed itself
- `test_prospective.py` **[safety]** path escapes refused; cancellation is a recorded status
- `test_prospective.py` **[loop]** an idle drain noticed the due intention, queued it, executed it to done, and logged the firing
- `test_routines.py` **[save]** one finished task became a skill written from its own trajectory plus an armed schedule, carrying the same gate
- `test_routines.py` **[refuse]** only work that actually finished may become a promise, and it must say when to run
- `test_routines.py` **[fire]** when the schedule came due it queued a gated task carrying the exact procedure that worked
- `test_routines.py` **[panel]** routines are saved, listed and cancelled from the panel; one with no schedule is refused with 400
- `test_wake.py` **[wake]** an external event fired the armed intention once; the payload travels fenced as a memory file, never as instructions
- `test_wake.py` **[repeat]** a repeating intention fires on every arrival
- `test_wake.py` **[direct]** a wake can queue its own gated task; bad names are refused with 400
- `test_wake.py` **[run]** every woken task drained to done with its payload fenced in context
- `test_research.py` **[decompose]** one compound question became 3 facts to establish, and a named atom became its own
- `test_research.py` **[retrieve]** the two design questions found their atoms (C-0101, C-0102); the refund question found nothing and is listed as unestablished — coverage 67%
- `test_research.py` **[brief]** the brief names the gap and instructs an honest refusal for it rather than an improvisation
- `test_research.py` **[handoff]** the consultation carries the brief as a memory file and its goal points at it
- `test_research.py` **[deterministic]** the same question produced the identical plan and the identical evidence, with no model call anywhere
- `test_course.py` **[re-exam]** scheduled on completion, queued once, ran, never re-queued
- `test_exam.py` **[closed-book]** notes absent from every message; the Student's read-the-notes cheat was mechanically refused; mission+index+questions present
- `test_exam.py` **[dispatch]** identical question file never re-dispatched (tracked by content hash)
- `test_exam.py` **[re-dispatch]** replaced question file -> exactly one fresh sitting + grading
- `test_verify.py` **[verify]** spec CHECK commands ran mechanically: a failing item failed the gate, and a re-run replaced the results section in place
- `test_inbox.py` **[text]** lesson created, original kept, watcher queued with the lesson as memory
- `test_inbox.py` **[pdf]** ripper queued; pdf-text extracted the real text layer
- `test_inbox.py` **[audio]** ffmpeg chunking produced 1 chunk(s) under the 25MB limit
- `test_inbox.py` **[unknown]** parked in source/, no task queued
- `test_material.py` **[hosts]** Vimeo/Coursera/Udemy/YouTube recognized as video; playlists detected
- `test_material.py` **[subs]** VTT parsed to timestamped text, repeats collapsed, tags stripped
- `test_material.py` **[folder]** a dropped course folder became 3 ordered lessons, originals preserved
- `test_material.py` **[zip]** packaged course extracted into lessons; traversal and sibling-prefix entries contained, nothing written outside the course
- `test_material.py` **[formats]** saved HTML cleaned to a lesson; ebook routed to the converter
- `test_material.py` **[crawl]** manual index + 2 same-site pages ingested; off-site links ignored
- `test_url.py` **[extract]** HTML -> clean titled lesson text, scripts and styles stripped
- `test_url.py` **[scheme]** file://, ftp:// and bare paths are refused — a .url file in the inbox cannot read agent.env into a lesson
- `test_url.py` **[page]** URL fetched deterministically, lesson written with provenance, watcher queued
- `test_url.py` **[youtube]** link queued to the ripper with the yt-dlp + cookies playbook
- `test_curriculum.py` **[authority]** arrival order was 01,02,03,04; the plan studies the tier-1 specification first: 03, 01, 04, 02
- `test_curriculum.py` **[duplicate]** the blog covering the same ground as the spec was marked 'skim': 36% overlap with lesson 03: read it only for what it adds
- `test_curriculum.py` **[relevance]** payroll tax law scored 0.0 against a contrast mission and was not studied in full
- `test_curriculum.py` **[why]** each lesson states why it earned its depth, and the whole plan is written to curriculum.json before anything is queued
- `test_curriculum.py` **[prerequisite]** the lesson defining the atoms the other one cites was pulled to the front (2 atoms cited elsewhere)
- `test_curriculum.py` **[apply]** 4 lessons queued in curriculum order; the skims are told to record only what they add
- `test_curriculum.py` **[coverage]** 2 mission topics checked against what the notes actually support
- `test_e2e.py` **[pipeline]** 7 tasks, all done, zero human interventions: ['ripper', 'watcher', 'practitioner', 'examiner', 'reflector', 'librarian', 'examiner']
- `test_e2e.py` **[verification]** mechanical PASS from verify.py, course COMPLETE, re-exam ran
- `test_e2e.py` **[memory]** memcheck certifies: IDs unique, citations resolve, spec grounded, index complete

</details>

**Blind spot.** schedules are tested with tiny intervals inside one run. Nothing here proves a month of unattended drift, clock changes across daylight saving, or a real cron environment.

## 4. Memory institution

*courses and atoms, skills graph, commons, failures, gotchas, premise, competence, recall, sources, conflicts, standards, self-model*

**Verdict: proven** — 13 of 13 declared tests ran and passed, producing 49 observations.

<details><summary>What the tests observed (49)</summary>

- `test_memory.py` **[classify]** 8 harness errors mapped to fixed categories deterministically — no model asked to guess why it failed
- `test_memory.py` **[failures]** structured records, deduplicated by signature with recurrence counts, filterable by agent and category
- `test_memory.py` **[competence]** computed from verified outcomes (gated work counts double); small samples labelled; routing answerable from evidence
- `test_memory.py` **[retired]** retirement moves a whole world aside intact — queryable, listed, and restorable years later
- `test_memory.py` **[preserve]** delete retires by default; only an explicit purge destroys
- `test_memory.py` **[automatic]** finishing a task files its own competence outcome and, on failure, a categorized failure record — retries count as occurrences but never as extra competence attempts
- `test_memcheck.py` **[broken]** all 4 violation types detected and named
- `test_memcheck.py` **[repaired]** memory passes: IDs unique, citations resolve, spec grounded, index complete
- `test_skills.py` **[skills]** run 2 loaded the playbook run 1 wrote, and an unrelated task did not - procedural memory compounds without leaking
- `test_skillgraph.py` **[gate]** promotion required 3 DISTINCT winning tasks (1 verified); duplicates and premature wins were refused
- `test_skillgraph.py` **[quarantine]** 3 losses quarantined the skill; a verified win redeemed it; further losses re-quarantined it
- `test_skillgraph.py` **[select]** proven first, quarantined excluded, USES pulled the sub-skill in directly after its parent
- `test_skillgraph.py` **[banner]** injected skills carry their earned status — the model knows hypothesis from proven procedure
- `test_skillgraph.py` **[loop]** a drained task recorded its loaded skills, filed a verified win, stayed candidate at n=1, and its context carried the banner
- `test_skillmd.py` **[discover]** folder skills and flat skills are both first-class and share one graph key
- `test_skillmd.py` **[disclosure]** the matching folder skill loaded with its flat sub-skill; the unrelated one was offered by name only
- `test_skillmd.py` **[mediation]** a third-party playbook was injected with a warning and its bundled script was refused by the loop
- `test_skillmd.py` **[trust]** after the owner promoted it, the same script ran
- `test_skillmd.py` **[supply]** a skill exported in the open format imported cleanly into another expert, arrived untrusted, and the owner promoted it from the panel
- `test_recall.py` **[archive]** compaction removed 50 turns from the window; all 50 archived verbatim — context is never lost
- `test_recall.py` **[recall]** one query reaches notes, skills, AND archived turns; all-term lines outrank partials; French text findable
- `test_associative.py` **[chain]** the decision anchored retrieval; both cited atoms and the linked skill came back as one evidence chain; unrelated atoms in the same files stayed out
- `test_associative.py` **[empty]** no anchors, no expansion — recall stays quiet
- `test_memory_kinds.py` **[file]** a failed gated task wrote one scoped gotcha carrying its failure id, trigger words, cause and remedy
- `test_memory_kinds.py` **[recall]** the next kafka task carried the gotcha into its window; an unrelated task did not
- `test_memory_kinds.py` **[scope]** a failure inside an MCP call was filed against that server and a repeat became a count, not a second line
- `test_memory_kinds.py` **[premise]** a goal built on a retracted atom raised a warning in the window and in the feed; a clean goal raised none
- `test_memory_kinds.py` **[router]** the student stayed closed-book even against an owner override; the practitioner kept every kind; the manifest says why
- `test_memory_kinds.py` **[curation]** duplicate lessons merged into a curated view with every contributor kept, and the ledger was not rewritten
- `test_conflicts.py` **[ledger]** every source carries an authority tier with its reason, and an owner overrule is recorded, not silent
- `test_conflicts.py` **[verdicts]** the spec outranked the blog post, 2026 superseded 2018, the two conditional rules were kept as conditions, and the two equals were declared contested
- `test_conflicts.py` **[ledger]** the rulings are written to conflicts.md, rescanned only when the material changes, and a claim that merely shares an adjective is not called a contradiction
- `test_conflicts.py` **[context]** the dark-mode task carried the contested ruling into its window; an unrelated task did not
- `test_conflicts.py` **[gate]** an answer that stated a contested point as settled was refused; the one that presented both sides passed
- `test_awareness.py` **[fresh]** a new expert is told it has verified nothing yet, instead of being handed a confident persona
- `test_awareness.py` **[studied]** it reports each course by verified atoms, exam result and source tier -- and names the course it was never examined on
- `test_awareness.py` **[evidence]** one lucky success is reported as insufficient evidence, and a playbook that lost three times is named as do-not-use
- `test_awareness.py` **[now]** it knows its role, its allowed tools, its stop condition and where commands run -- and says so when a role has no provider
- `test_awareness.py` **[window]** the self-model leads every context window, survives a closed-book exam, and carries no course content with it
- `test_audit.py` **[two-loops]** 6 tasks, 2 concurrent loops: each claimed exactly once, all done
- `test_audit.py` **[lost-update]** 24 tasks queued under concurrent writes: 0 lost, 0 regressed (was 6 lost / 12 regressed before the mutex)
- `test_audit.py` **[unicode]** accented names slug cleanly; accented content preserved verbatim
- `test_cases.py` **[open]** a failed task opened case K-a0159d74 with its cause recorded, not just a log line
- `test_cases.py` **[fixed]** a later task that passed its gate closed the case, and what it did is recorded as the fix — verified by the gate, not by an opinion
- `test_cases.py` **[recurred]** the same failure after a fix was recorded as RECURRED — the ledger now says the obvious fix already failed once
- `test_cases.py` **[recall]** the returning problem carried its own history into the window, including what was tried and that it did not hold; an unrelated task carried nothing
- `test_cases.py` **[confidence]** the task that passed scored 47% (medium) and the one that failed its gate 30% (low -> escalate)
- `test_cases.py` **[ledger]** 1 case(s), 1 that came back after a 'fix' — the number a team actually needs to see
- `test_reflector.py` **[reflection]** exactly one Reflector task followed the work, it completed, and it did not chain further

</details>

**Blind spot.** conflict detection is text-based and conservative by design: it finds polarity flips and numeric disagreements between claims about the same subject, and has no semantic model of any domain. Contradictions phrased outside those rules are missed, and no test can enumerate what is missed.

## 5. Improvement & governance

*charter variants with predictions, approvals, replay, benchmark, promotion gates, the design gate*

**Verdict: proven** — 8 of 8 declared tests ran and passed, producing 33 observations.

<details><summary>What the tests observed (33)</summary>

- `test_variants.py` **[guards]** no promotion without a trial; no trial on a single task
- `test_variants.py` **[trial]** same battery, two real drains: base 0/2 (gate refused 12x), variant 2/2; live prompts untouched
- `test_variants.py` **[promote]** strictly-better variant installed; base charter backed up
- `test_variants.py` **[tie]** equal performance refused — churn without evidence is rot
- `test_variants.py` **[rollback]** the exact pre-promotion charter restored; un-promoted variants cannot roll back
- `test_decisions.py` **[declare]** a variant can state what it should improve and by how much; a vague prediction is refused outright
- `test_decisions.py` **[refused]** the variant DID beat base, but missed the effect it predicted -- promotion refused and the live charter untouched
- `test_decisions.py` **[held]** the variant that delivered exactly what it predicted was promoted, and rollback restored the previous charter byte for byte
- `test_decisions.py` **[stale]** a prediction declared after the fact cannot be validated by the old trial -- the harness demands a fresh one
- `test_decisions.py` **[panel]** predictions are declared and displayed from the control panel, with the verdict beside them
- `test_approvals.py` **[pause]** destructive tool (MCP annotations) refused to run; approval recorded; agent asked the owner; task blocked; world untouched
- `test_approvals.py` **[chief]** the pending approval outranks everything in the briefing
- `test_approvals.py` **[grant]** after approval the exact call ran once; task finished
- `test_approvals.py` **[policy]** denial is final and untouched; read-only never pauses; 'effects' and require_approval widen the gate as the owner chooses
- `test_replay.py` **[same]** the recording model replays its own trajectory at 100%
- `test_replay.py` **[swap]** a different model measured at 33% agreement with 1 drift and 1 refusal — decisions read, never executed, state untouched
- `test_benchmark.py` **[bare]** the model's first answer failed all 3 mechanical checks — and reported success on every one of them
- `test_benchmark.py` **[harness]** same model, same tasks: 3/3 passed, 0 false 'done', gate refused 3 wrong answers before accepting correct ones
- `test_benchmark.py` **[honest]** with a zero baseline the multiplier is reported as undefined, not infinite; false-'done' eliminated +100%; the lift cost 0.018 vs 0.004 USD, and n=3 is printed
- `test_governance.py` **[boundary]** constitution, grounding, examiner and student charters cannot be evolved; worker charters can
- `test_governance.py` **[contract]** compaction carried goal, gate and every written file mechanically; the model's missing sections were named and logged; verbatim archive intact
- `test_governance.py` **[trigger]** a skill is summoned by its TRIGGER situation words, and stays out of unrelated tasks
- `test_design.py` **[catches]** the gate refused the generated-filler page on 15 distinct rules, each with a concrete fix
- `test_design.py` **[fair]** a page with real contrast, one scale, tokens, a breakpoint and labelled controls passed with no blockers
- `test_design.py` **[standards]** normative atoms became the bar, the contested point was refused, and the numeric rule carries a gate check
- `test_design.py` **[owner-bar]** raising the course's own standard to 7:1 raised the gate: the same page passes at the default and fails at the bar
- `test_design.py` **[lane]** a launched interface deliverable was gated by designcheck: the model called it shipped, the harness did not
- `test_modelrouter.py` **[unproven]** with no measured runs, routing keeps the configured model and says exactly what evidence is missing
- `test_modelrouter.py` **[earned]** both models proved themselves, so the cheap one won on price -- the expensive one is not the default, it is the fallback
- `test_modelrouter.py` **[demoted]** once the cheap model dropped below the bar, routing moved to the stronger one and recorded why
- `test_modelrouter.py` **[fallback]** an unreachable bar falls back to the configured model instead of guessing
- `test_modelrouter.py` **[loop]** the loop used the routed model, logged the decision, and filed its own outcome as the next run's evidence
- `test_modelrouter.py` **[panel]** the measured profile of every model is served to the owner

</details>

**Blind spot.** promotion and routing decisions are proven against seeded outcome ledgers, not against months of real measured performance. The design gate checks mechanics and the known fingerprints of generated filler; it cannot judge beauty.

## 6. Control plane & interop

*panel, live events, cards, chief, doctor, preflight, backup, providers, MCP, A2A federation, traces*

**Verdict: proven** — 18 of 18 declared tests ran and passed, producing 98 observations.

<details><summary>What the tests observed (98)</summary>

- `test_ui.py` **[up]** panel serving on 127.0.0.1, empty fleet listed
- `test_ui.py` **[create]** one click -> expert with its own identity and memory
- `test_ui.py` **[teach]** URL became a queued lesson; file landed in the inbox; detail view carries tasks, courses, blocked, log
- `test_ui.py` **[safety]** unknown expert -> 404
- `test_ui.py` **[system]** fleet dashboard aggregates experts, tasks, spend
- `test_ui.py` **[board]** full task list served with ids, steps, ages
- `test_ui.py` **[memory]** tree + file reads work; traversal and secrets refused
- `test_ui.py` **[tools]** manual task queued for any role from the panel
- `test_ui.py` **[tools]** verify.py and memcheck.py run from the panel, output returned
- `test_ui.py` **[tools]** provider/role routing visible; no secrets in the payload
- `test_ui.py` **[tools]** loop.py check probe runs through the panel
- `test_ui.py` **[danger]** deletion retires and preserves the whole world; only an explicit purge destroys it
- `test_csrf.py` **[csrf]** a cross-origin POST is refused by Origin AND by Sec-Fetch-Site; nothing was created
- `test_csrf.py` **[same-origin]** the panel's own requests are unaffected
- `test_csrf.py` **[rce]** a free-form shell done_check over HTTP is refused — defence in depth, even from a same-origin caller
- `test_csrf.py` **[gates]** a named gate becomes the command; a traversing parameter inside one is still refused
- `test_csrf.py` **[catalogue]** GET /api/gates lists what a caller may ask for
- `test_frontend.py` **[syntax]** the page's JavaScript parses under node --check
- `test_frontend.py` **[page]** ui.html serves 7 sections, calls every endpoint incl. memory/retired/history, defines both themes
- `test_frontend.py` **[serve]** page served from ui.html (168823 bytes)
- `test_frontend.py` **[fresh]** a newly created expert answers on all six read endpoints, no 500s
- `test_frontend.py` **[live]** frontend edits appear on reload with no server restart
- `test_panel_v2.py` **[identity]** the owner rewrote who this agent is; the previous version was kept and the new words were in the next window
- `test_panel_v2.py` **[pins]** the owner's binding lines are injected first, for every agent, and re-materialised the moment they are saved
- `test_panel_v2.py` **[thread]** a team run reads as a conversation: brief, plan, each specialist's file, the lead's synthesis -- all auditable
- `test_panel_v2.py` **[approval]** every pending sign-off carries what was done, what this step is and what comes next; browser tools add takeover
- `test_panel_v2.py` **[home]** readiness lists what is missing by NAME (never a value) and the fleet's tool health is one call away
- `test_events.py` **[replay]** a new connection is handed the recent history first, so a freshly opened panel is never blank
- `test_events.py` **[live]** the tasks the agent ran while we watched arrived as they happened: start, each tool call, end
- `test_events.py` **[robust]** unparseable lines in the log were skipped and the stream kept delivering
- `test_events.py` **[auth]** the live stream is guarded by the same token as the API: both as a header and as ?token= for EventSource
- `test_uicards.py` **[catalogue]** table, checklist, diff and metric parse into normalised data with every cell coerced to a bounded string
- `test_uicards.py` **[closed]** unknown types, malformed JSON, oversized and over-the-cap cards are all dropped with a stated reason
- `test_uicards.py` **[inert]** a script tag inside a card is carried as text and never becomes markup -- the client escapes, the schema has no slot for it
- `test_uicards.py` **[loop]** cards were collected from a message and from the finish summary, the bogus one was refused, both were logged
- `test_uicards.py` **[client]** the page's renderer was run against a hostile card: every branch emitted escaped text, and the unknown type emitted nothing
- `test_remote.py` **[deny]** page served; unauthenticated API call rejected with 401
- `test_remote.py` **[allow]** wrong token refused; correct token authorized
- `test_remote.py` **[writes]** anonymous create refused and created nothing; authorized create worked
- `test_chief.py` **[quiet]** an untroubled fleet gets one calm ADVANCE â€” no invented urgency
- `test_chief.py` **[ranked]** all six situations found from real instruments and ranked in the fixed order, each with the concrete detail
- `test_chief.py` **[archetypes]** 19 pluggable specialists; authority boundaries are written INTO the charters (analysis not advice, broker verification, rollback-gated changes)
- `test_doctor.py` **[healthy]** all five sections reported; a sound expert reads as sound
- `test_doctor.py` **[damage]** half-born expert and corrupted course memory both named, exit 1
- `test_doctor.py` **[rollback]** interrupted creation leaves nothing; the next one succeeds
- `test_doctor.py` **[elsewhere]** a fleet home outside the code directory reports cleanly
- `test_mcp.py` **[handshake]** legacy stdio era negotiated; 4 tools discovered with their schemas
- `test_mcp.py` **[fence]** tool output — including a live injection attempt — arrives fenced as DATA under the grounding contract
- `test_mcp.py` **[bounded]** isError fenced loud; wedged tool timed out in seconds; unknown server refused with the configured list
- `test_mcp.py` **[toolbox]** the capability note advertises the server with the exact commands
- `test_mcp.py` **[a2a]** A2A v1.0 card served at the standard well-known path: exposed experts as skills, signed transport declared, zero secret material
- `test_federation.py` **[card]** each fleet has its own identity; the card exposes only what the owner chose, signed, with a fingerprint (never the secret)
- `test_federation.py` **[trust]** unknown fleet, forged signature, and unexposed expert all refused before a single model call
- `test_federation.py` **[ask]** a signed request became a citation-gated consultation, framed as coming from outside the fleet
- `test_federation.py` **[fetch]** the reply is signed by the answering fleet and verifies
- `test_federation.py` **[evidence]** a peer's answer is filed as fenced, attributed, untrusted evidence — never as our own knowledge
- `test_federation.py` **[promotion]** uncited claims stay candidates; independent corroboration or a citation promotes; withdrawals are struck, kept, and shared
- `test_federation.py` **[digest]** hard constraints extracted, hashed, and echoed — a handoff that drops them changes the hash and is detectable
- `test_providers.py` **[add]** known rail + custom endpoint added; settings round-tripped losslessly; only key NAMES are written
- `test_providers.py` **[roles]** any role re-pointed at any provider/model incl. fallback + escalation; unknown providers refused
- `test_providers.py` **[catalog]** models listed from a live /models endpoint; free-only and text filters work
- `test_providers.py` **[custom]** your own tools appear as capabilities, honour ready_check, and reach agents with the exact command to run
- `test_providers.py` **[fleet-tools]** a tools.json at the fleet home reaches every expert in it
- `test_check.py` **[healthy]** all roles probed, exit 0
- `test_check.py` **[broken]** dead endpoint named with reason, exit 1, healthy roles unaffected
- `test_trace.py` **[spans]** the whole life of the task -- start, three tool calls with durations, end -- rebuilt from the log the harness already writes
- `test_trace.py` **[tools]** per-tool error rates separate the one failing tool from the two that worked
- `test_trace.py` **[brief]** what was done, what is happening now, what comes next -- the three sentences a human needs before signing anything
- `test_trace.py` **[robust]** unparseable log lines are skipped; the trace still builds
- `test_trace.py` **[panel]** the panel serves the per-task trace, its brief, and the fleet-wide tool error rates
- `test_bootstrap.py` **[first-run]** one command created the env file, the first expert and a machine-readable report, and said READY
- `test_bootstrap.py` **[idempotent]** a second run created nothing, changed nothing, and still exited 0
- `test_bootstrap.py` **[secrets]** the key was written into agent.env and never appeared in the output or the report -- only its name did
- `test_bootstrap.py` **[blocked]** with no provider key the bootstrap refused to claim readiness, named the variable, and said exactly how to fix it
- `test_bootstrap.py` **[teach]** the same command handed the new expert its first material and queued the work
- `test_backup.py` **[contents]** the archive carries identities, courses, notes, skills and the commons -- and not one credential
- `test_backup.py` **[opt-in]** --with-logs adds the audit trail and still excludes keys
- `test_backup.py` **[integrity]** every file is checksummed, and a single substituted byte makes the archive report itself DAMAGED
- `test_backup.py` **[restore]** round-tripped byte-for-byte, refused a non-empty destination, and refused to restore a damaged archive
- `test_backup.py` **[traversal]** an entry pointing outside the destination was refused
- `test_backup.py` **[freshness]** the age helpers the preflight depends on report a real number, and None when there is nothing to report
- `test_preflight.py` **[blocker]** a fleet with no backup is NOT READY, and the finding carries the exact command that fixes it
- `test_preflight.py` **[cleared]** taking a backup cleared the blocker -- and the audit verified its checksums rather than trusting the filename
- `test_preflight.py` **[cost]** a disabled daily breaker was named per settings file -- the expert's and the fleet default's -- and setting it cleared that one
- `test_preflight.py` **[integrity]** a corrupted archive was caught by the audit, not discovered on the day it was needed
- `test_preflight.py` **[access]** exposure is audited only when the panel is exposed; a missing token is then a blocker, and transport is still flagged
- `test_preflight.py` **[verdict]** the verdict follows the findings and the exit code follows the verdict: 2 blocked, 1 risks, 0 clean
- `test_preflight.py` **[critic]** an examiner running the author's own model was named as review theatre; pointing it at a different model cleared it
- `test_preflight.py` **[robust]** a check that threw was reported as a failed check; the audit still produced a verdict
- `test_ecosystem.py` **[organism]** one gated win + one honest failure: skill graph, fleet competence, and the failure ledger all agree
- `test_ecosystem.py` **[prospective]** the watch fired on the file change and the fired task ran to done under its own gate
- `test_ecosystem.py` **[race]** two processes evaluated the same due intention â€” it fired exactly once (the measured double-fire stays dead)
- `test_ecosystem.py` **[writers]** 2 processes x 20 outcomes: all 40 recorded â€” the graph lock loses nothing
- `test_ecosystem.py` **[recall]** the decision pulled its cited atom's definition across files â€” chain, not fragment
- `test_ecosystem.py` **[variants]** trial refused while a loop pulses â€” arms cannot be contaminated by a foreign claimer
- `test_ecosystem.py` **[chief]** the briefing surfaced the blocked question with its actual text, ranked first
- `test_ecosystem.py` **[retire]** the whole organism â€” graph, intentions, notes â€” survived retirement and came back byte-true
- `test_ecosystem.py` **[doctor]** full inspection: ledgers parse, no stale locks, the briefing compiles â€” nothing wrong but the missing key

</details>

**Blind spot.** the panel is driven through its HTTP API and its HTML is parsed, but no test renders it in a browser. Layout, contrast and touch targets are verified by eye, not by CI.
