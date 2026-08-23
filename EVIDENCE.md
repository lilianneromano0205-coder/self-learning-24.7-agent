# Evidence — why we believe this works

Generated 2026-08-23T19:15:58 from an actual suite run: **99/99 tests passed**, **465 observations** recorded.

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
| 6. Control plane & interop | **proven** | 19/19 | 104 |
| 7. The five authorities | **proven** | 1/1 | 12 |
| 8. Proof, missions and long-horizon work | **proven** | 3/3 | 23 |
| 9. Computers, capability and organization | **proven** | 4/4 | 29 |
| 10. Training lab | **proven** | 1/1 | 6 |
| 12. The paths that touch something real | **proven** | 5/5 | 38 |
| 11. The interface itself | **proven** | 1/1 | 10 |

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
- `test_chaos.py` **[size]** an 11 MB file, 1,000 atoms and 200 skills compiled to a 13234 token window in 1.5s, cut marked
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
- `test_retention.py` **[bounded]** 300 tasks done, hot queue holds 40 finished (62 KB); queued and blocked work untouched
- `test_retention.py` **[lossless]** all 302 tasks accounted for — 260 archived, every field intact and findable by id
- `test_retention.py` **[flat]** persist cost 12 ms -> 17 ms after 400 more tasks (was 185 ms at 1500 before retention)
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

**Verdict: proven** — 19 of 19 declared tests ran and passed, producing 104 observations.

<details><summary>What the tests observed (104)</summary>

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
- `test_frontend.py` **[page]** the six job-shaped sections each state their purpose and route to a renderer; guide/memory/models/system were MOVED, not deleted, and each is still reachable from a clickable control; every endpoint the page names exists; both themes defined
- `test_frontend.py` **[serve]** page served from ui.html (274949 bytes)
- `test_frontend.py` **[fresh]** a newly created expert answers on all six read endpoints, no 500s
- `test_frontend.py` **[live]** frontend edits appear on reload with no server restart
- `test_package.py` **[secrets]** 222 archive members checked four ways — by basename, by containing directory, by extension and by reading every text file — and none carries a credential
- `test_package.py` **[private]** none of 5 private-data shapes carries CONTENT in the archive — no expert memory, task state, logs, context windows or organization roster — while 6 empty placeholder(s) keep the working directories so a fresh unzip runs with no setup. Proof observations DO ship, deliberately: every one is bound to a code hash and none names this machine, so the recipient inherits evidence that falls the moment they change the code
- `test_package.py` **[runnable]** the archive carries 71 modules, 99 tests, the prompts and settings.toml — and unzipped into an empty directory it passes `harness.py --check` with no setup at all
- `test_package.py` **[planted]** 3 decoy credential file(s) were created in the source tree and the archive excluded every one, by file and by value — an exclusion rule is only worth what it catches
- `test_package.py` **[evidence]** all 99 registered tests are classified into 12 systems with no overlap and no drift, every system states a blind spot, and the standing 'every call is a mock' caveat is in the module and in the generated report
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
- `test_backup.py` **[portable]** the RESTORED expert was driven through a gated task in its new location and passed — deployment is a location choice, not a different expert format (manual §20)
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

## 7. The five authorities

*one mandatory gateway per kind of power — execution, file, credential, model gateway, effect — plus the invariant tests that enumerate every caller of each*

**Verdict: proven** — 1 of 1 declared tests ran and passed, producing 12 observations.

<details><summary>What the tests observed (12)</summary>

- `test_invariants.py` **[execution]** 71 modules scanned; 0 raw subprocess sites outside the authority (16 declared platform-internal, each with a stated reason)
- `test_invariants.py` **[catalogue]** 5 execution operations: every model-authored one enforces policy+sandbox, every platform one refuses a shell string
- `test_invariants.py` **[zones]** 15 paths + every declared control file/dir (6 files, 5 dirs) classified and enforced by zone
- `test_invariants.py` **[traversal]** 12 escape spellings (posix, windows, UNC, mixed, nested) all refused or contained
- `test_invariants.py` **[credentials]** all 4 sources (env, agent.env, inline, api_key_file) resolve, count as funded, are excluded from packaging, are redacted, and are unreadable by the agent
- `test_invariants.py` **[metering]** all 9 call purposes reach the ledger, attribute per call, and count toward today's spend
- `test_invariants.py` **[roles]** 9 roles: every one can finish/escalate, the Student holds neither read_file nor a shell, and no untrusted-material role holds run_command
- `test_invariants.py` **[gates]** 5 catalogue entries build a command; a raw shell string never does
- `test_invariants.py` **[birth]** 3 modules mint experts; the gateway seeds a never-bootstrapped home itself (library AND CLI, from any working directory), is idempotent, does not clobber owner edits, and refuses with a sentence when the home is genuinely impossible
- `test_invariants.py` **[exams]** 4 recorded formats: the loop's completion check, the self-model, and the block injected into every context window all read the same score from the same file
- `test_invariants.py` **[sandboxes]** 143 sandbox names across 99 test files, every one claimed by exactly one file — a shared temp directory is the failure that only shows up under load
- `test_invariants.py` **[cli]** 61 documented subcommands across 46 modules all parse, and every module prints its own --help on a non-UTF-8 console

</details>

**Blind spot.** these tests enumerate every path in THIS tree. They cannot see a path added by a plugin, an MCP server or a future module that does not exist yet — which is why the execution audit is a source scan rather than a runtime check, and why it fails on a new raw subprocess call rather than warning.

## 8. Proof, missions and long-horizon work

*capability proof levels derived from hash-bound evidence; the mission contract that survives context resets, restarts and model swaps*

**Verdict: proven** — 3 of 3 declared tests ran and passed, producing 23 observations.

<details><summary>What the tests observed (23)</summary>

- `test_proof.py` **[derived]** the ledger stores observations only — there is no level field for anyone to set by hand
- `test_proof.py` **[ladder]** a level requires every level beneath it: live evidence alone stayed at IMPLEMENTED until the acceptance tests passed
- `test_proof.py` **[regression]** editing the code dropped OFFLINE VERIFIED -> IMPLEMENTED automatically, and restoring it brought the level back — nobody touched a status
- `test_proof.py` **[failure]** a failing run is recorded as failing — the ledger keeps both, so a regression is visible rather than overwritten
- `test_proof.py` **[expiry]** live and stress evidence older than its window expired automatically and the badge fell back to OFFLINE VERIFIED — a green light cannot rot into a lie by sitting still
- `test_proof.py` **[stability]** the code hash survives line-ending translation while still changing on real edits
- `test_proof.py` **[registry]** 15 declared capabilities each state a user capability, invariants, code and tests; nothing with unwritten code claims a level above SPEC
- `test_mission.py` **[persisted]** the mission contract is a file on disk, not a passage in a transcript that compaction can summarise away
- `test_mission.py` **[model-swap]** the contract names no model or provider, so swapping one cannot change what the mission is
- `test_mission.py` **[bound]** an action must name the criterion it serves and the evidence it will produce; unbound work and unrecognisable outcomes are both refused
- `test_mission.py` **[monotonic]** met evidence cannot silently vanish: invalidating it needed a stated reason and the original record is still there
- `test_mission.py` **[amendment]** the objective cannot be edited in place â€” the change carries a reason, an author, and both fingerprints, so drift is visible instead of silent
- `test_mission.py` **[gaps]** 4 blocker dimensions classified and routed; only the authority gap escalated to the owner
- `test_mission.py` **[every-role]** practitioner, student and consultant all receive the objective, the binding constraints and their criterion â€” the memory router cannot route the assignment away
- `test_mission.py` **[closure]** a mission closes on met criteria, never on a decision to stop; and a mission with no criteria cannot be created
- `test_metrics.py` **[sources]** 11 metrics read from 11 distinct ledgers, each naming its own â€” no metric keeps a second count of something another subsystem already knows
- `test_metrics.py` **[samples]** 3 metric(s) below the 5-observation floor are printed with the warning attached, not as a bare percentage
- `test_metrics.py` **[honesty]** 4 metric(s) this platform cannot compute are named with the reason, rather than dropped or approximated â€” including one that would have been flattering to invent
- `test_metrics.py` **[reliability]** 2/5 gated tasks passed and 18/20 finish-claims were refused â€” both derived in one pass over one ledger, so neither can exceed 100% or contradict the other
- `test_metrics.py` **[autonomy]** the figure names itself an upper bound, and it MOVES: appending one approval_required event took it from 5/5 to 4/5 â€” it reads the log, where a human being needed is actually recorded
- `test_metrics.py` **[fidelity]** 1/1 recorded actions name the criterion they serve â€” the platform refuses to record one that does not, so this metric can only ever be 100% or reveal a bug
- `test_metrics.py` **[multiplier]** 25 harness interventions across 10 levers are reported as COUNTS with what a bare model would have done instead; the multiplier itself is in the refused list, because the baseline half has never been run
- `test_metrics.py` **[empty]** a fleet with no history reports 'no data' on every rate rather than 0%, which would read as a measured failure

</details>

**Blind spot.** no mission here has run longer than a test. The contract is proven to survive a simulated reset, not a week of real drift, and no capability has ever been observed above level 2 because that needs a real provider. Three of the manual's twelve metrics cannot be computed at all — supervision hours, 90-day retention, and anything that would need a real workload — and `metrics.py` names them rather than approximating them.

## 9. Computers, capability and organization

*where work runs and why that computer was chosen; how a capability is acquired without gaining authority; who may do what, and the trail that records it*

**Verdict: proven** — 4 of 4 declared tests ran and passed, producing 29 observations.

<details><summary>What the tests observed (29)</summary>

- `test_workers.py` **[registry]** 4 computers registered with zone, capability and cost; scale-to-zero kinds start stopped, so one expert does not imply one always-on machine
- `test_workers.py` **[isolation]** free work went to the disposable container, not to the equally-free, faster-starting organization machine — blast radius outranks speed
- `test_workers.py` **[trusted]** the owner's own machine is never selected automatically; it becomes eligible only when explicitly allowed
- `test_workers.py` **[matching]** requirements are read from the task text; an impossible requirement returns no computer AND the reason each one was ineligible, instead of falling back to whatever was nearest
- `test_workers.py` **[implied]** every kind declares what it implies, a bare registration of each kind routes for what that kind is, implied capabilities are shown separately from declared ones, and implying does not paper over a capability that is genuinely absent
- `test_workers.py` **[explain]** the choice reads as a sentence: 'Using Office Windows PC because excel + internal-network are required (no compute cost)'
- `test_workers.py` **[policy]** a computer restricted to named experts is invisible to the others, and the refusal says it was policy rather than capability
- `test_workers.py` **[cost]** an idle computer accrued nothing, an hour of GPU time accrued $2.50, and stopping it stopped the meter
- `test_acquire.py` **[search-first]** a second request for a capability we already trust was refused and pointed at the existing tool â€” an unnecessary dependency is permanent
- `test_acquire.py` **[malicious]** the package's own manifest was read before install: 2 risk signal(s) surfaced (pipes a download straight into a shell; reads credentials)
- `test_acquire.py` **[typosquat]** names one character from a very common package were blocked; the genuine package passed
- `test_acquire.py` **[pinning]** an unpinned dependency was refused: evidence recorded today would otherwise describe something that no longer exists
- `test_acquire.py` **[permissions]** a tool that wants a credential declared it during inspection, before anyone decided whether to install it
- `test_acquire.py` **[no-host]** with only a trusted computer available, acquisition FAILED rather than falling back to the host â€” including when the host was named explicitly
- `test_acquire.py` **[mandatory-test]** a tool that installed cleanly could not be promoted: the capability test is required, needs evidence, and a failing one blocks trust
- `test_acquire.py` **[ladder]** requested -> installed -> tested -> trusted, each rung recorded with its evidence, the exact version pinned, the owner granting the last rung, and removal available
- `test_org.py` **[solo]** with no organization created, every capability is available — adding RBAC must not make a person ask themselves for permission
- `test_org.py` **[ladder]** each role includes every role beneath it and nothing above: builder can run and approve, cannot manage secrets; only the owner can transfer ownership
- `test_org.py` **[refusals]** a denial names the actor's role, the role required, and what to do next — a refusal nobody understands is one they route around
- `test_org.py` **[owner]** the organization cannot be left ownerless: the owner's role cannot be downgraded and a second owner cannot be invited
- `test_org.py` **[audit]** 7 mutations recorded, each naming the actor, the action, the object and the before/after — 'every mutation attributable' is a query, not an aspiration
- `test_org.py` **[escalation]** an operator could not promote itself and a builder could not invite an admin — the permission needed to change permissions is itself gated
- `test_rbac.py` **[solo]** with no organization, creating an agent and driving it still works with no token and no role — adding RBAC must not make the person who owns the machine ask themselves for permission
- `test_rbac.py` **[tokens]** 4 personal tokens minted; none appears in org.json, none is served by the API, and each resolves to exactly one member
- `test_rbac.py` **[viewer]** all 8 write routes refused with 403, each naming the actor, the permission required and the role that has it
- `test_rbac.py` **[ladder]** an operator queued work and was refused agent creation, provider wiring and budget changes; a builder created an agent and was refused secrets, invitations and backups
- `test_rbac.py` **[coverage]** 17 POST routes; 15 named in the table and 2 falling through to 'create_agent', which needs builder or above — a route added tomorrow is refused for a viewer, not waved through
- `test_rbac.py` **[audit]** a request that claimed a different author was recorded against the token's real owner (owner@example.com) — the trail is attributable because the identity comes from the credential
- `test_rbac.py` **[shared]** a fleet that belongs to an organization refuses an untokened request, generates a master token, and admits a member on their own token while still refusing what their role forbids

</details>

**Blind spot.** every worker is a RECORD. Nothing here has started a container, installed a package, or measured a real start-up time — the acquisition ladder is proven to refuse correctly, not to install correctly. And `test_rbac.py` proves AUTHORISATION given an identity; the identity itself is a bearer token over plain HTTP with no TLS, session or expiry.

## 10. Training lab

*sanitised trajectory export, a deterministic non-overlapping split, an immutable verifier, a promotion threshold and a mandatory rollback target*

**Verdict: proven** — 1 of 1 declared tests ran and passed, producing 6 observations.

<details><summary>What the tests observed (6)</summary>

- `test_training.py` **[sanitised]** a credential inside a captured step was redacted before it ever reached the trajectory store
- `test_training.py` **[split]** 12 train / 3 held-out, deterministic across re-exports and provably non-overlapping
- `test_training.py` **[verifier]** a candidate evaluated with a different verifier was refused — comparing those numbers would measure the verifier, not the model
- `test_training.py` **[gate]** a change below its declared threshold and a single-seed result were both refused; a +0.05 improvement over three seeds was promoted
- `test_training.py` **[rollback]** the promotion recorded what it replaced and the rollback returned to it — a promotion without a way back is a one-way door
- `test_training.py` **[boundary]** the export states plainly that this platform does not perform gradient updates, names what an external trainer must do, and refuses a corpus too small to mean anything

</details>

**Blind spot.** this module performs no gradient updates at all, and says so on every export. What is proven is the governance around a training run — nothing here has trained anything, and no reward-hacking suite exists.

## 12. The paths that touch something real

*the two code paths that had never been executed by anything — the live provider HTTP client, and the docker sandbox — each driven against a real server and a real container*

**Verdict: proven** — 5 of 5 declared tests ran and passed, producing 38 observations.

<details><summary>What the tests observed (38)</summary>

- `test_live_provider.py` **[wire]** one real HTTP call carried the model, the messages, the configured 4096-token ceiling, exactly the 5 tools this role is allowed, the bearer key and the configured extra header — and with the ceiling left at its default, max_tokens is omitted rather than sent as 0
- `test_live_provider.py` **[cost]** the provider reported 1M+1M tokens and the ledger charged $18.00 at the configured rates — spend is read from the response, never estimated by the client
- `test_live_provider.py` **[retry]** 429 then 503 then success in 3 calls with growing backoff; a 400 stopped after exactly 1 call instead of burning five
- `test_live_provider.py` **[unreachable]** a refused connection failed over to the fallback in 2.04s and was logged as unreachable, instead of costing five backoffs per step forever
- `test_live_provider.py` **[keys]** all 3 configured key sources (env, inline, file) reached the Authorization header and were accepted by a server that checks them
- `test_live_provider.py` **[malformed]** a non-JSON body and a body with no choices are each retried through the full ladder, then failed over to the configured fallback, and logged against the provider that sent them — they used to raise straight out of the loop, killing the task and never trying the fallback
- `test_live_provider.py` **[timeout]** a provider that hung for 20s was cut off by the 2s ceiling and retried, finishing in 2.0s — the timeout is a real bound, not a suggestion
- `test_live_provider.py` **[inline]** a provider with native_tools = false received NO tool schema and answered with inline JSON, which the loop parses
- `test_live_provider.py` **[end-to-end]** a gated task was completed with 2 model calls over a real socket, the artefact exists, the gate passed, and all 2 of THIS task's calls are metered against the provider that actually served them
- `test_docker_live.py` **[available]** docker ready with python:3.12-slim
- `test_docker_live.py` **[isolated]** the command ran inside a Debian container on python 3.12.14, on a Windows host — this is not the host backend wearing a different name
- `test_docker_live.py` **[mount]** the expert's root is /work inside the container: a file written there landed on the host, and a file the host wrote was readable inside — in both directions, byte for byte
- `test_docker_live.py` **[containment]** 3 probes for the host filesystem — the C: drive, the platform's own source, and the fleet home above the mount — all came back empty from inside the container
- `test_docker_live.py` **[network]** egress is refused by default (--network none is on the argv, and a real connection attempt failed inside), and only [agent] sandbox_network = true removes it
- `test_docker_live.py` **[credentials]** three credential-shaped variables were withheld from the container, by name and by value — the scrub is not a host-only behaviour
- `test_docker_live.py` **[timeout]** a 60-second command under a 6-second ceiling was cut off in 6.9s, reported as a failure, and left no container behind
- `test_docker_live.py` **[limits]** every run carries --rm, --memory 1g and --pids-limit 256; asked for 768 processes the container reached 0 and went no further — the ceiling is enforced by the daemon, not merely declared
- `test_docker_live.py` **[end-to-end]** the loop completed a gated task with sandbox = docker: the model wrote a file inside a container, and the gate command ran in a container to verify it
- `test_hosted_sandbox.py` **[no-key]** both hosted backends refuse without a key, name the key as the reason, and — the property that matters — run nothing on this machine instead
- `test_hosted_sandbox.py` **[contract]** the exec request carried the command, a working directory, a 45000ms deadline and the key in both header styles the two services use
- `test_hosted_sandbox.py` **[credentials]** four credential-shaped values, including the sandbox service's own key, were all absent from the JSON sent to a third-party machine
- `test_hosted_sandbox.py` **[spellings]** a non-zero exit is reported as a failure in both `exitCode` and `exit_code` forms — reading only one would turn every failed remote command into a success
- `test_hosted_sandbox.py` **[failures]** 4 failure shapes — a billing refusal, a server error, a non-JSON body and a host that is not listening — each became a reported non-zero result with a message, and none raised
- `test_hosted_sandbox.py` **[honesty]** with no key each hosted backend reports itself unavailable and names the variable; with a key present it reports itself configured — which is all a key can honestly establish
- `test_first_day.py` **[bootstrap]** an empty directory became a fleet with an expert ('first-day') in one command; the key reached agent.env and appears nowhere in 1534 characters of output
- `test_first_day.py` **[probe-ok]** `loop.py check` reported OK, presented exactly the key bootstrap had stored, asked for 16 output tokens, and printed the key nowhere
- `test_first_day.py` **[probe-fail]** a rejected key reports FAIL with the HTTP status and exits non-zero; a missing key reports FAIL naming the exact environment variable to set — the two failures a first day actually produces, told apart
- `test_first_day.py` **[unreachable]** a base_url nothing is listening on reported FAIL in 2.3s instead of hanging on a 20-second timeout per role
- `test_first_day.py` **[cheap]** 9 roles sharing 1 model(s) produced 1 probe request(s): the check caches by provider/model pair rather than charging once per role
- `test_first_day.py` **[first-task]** with the probe green, a gated task ran to completion over the same provider — the artefact exists, the gate passed, and the key appears nowhere in 2074 characters of log
- `test_endurance.py` **[soak]** driving 120 real tasks through a real loop (AGENT_SOAK_TASKS to change)
- `test_endurance.py` **[queue]** 120 tasks completed; the hot queue held 20 then 42 against a retention of 20, 78 moved to the append-only archive with none lost, and state.json went 25902 -> 54372 bytes (2.1x)
- `test_endurance.py` **[latency]** per-task wall time across 6 batches: 0.12s, 0.13s, 0.13s, 0.13s, 0.14s, 0.13s — median 0.13s, and the last batch is not an outlier: the loop does not get slower as its own history grows
- `test_endurance.py` **[logs]** agent.log is 114 KB and rotates at 5 MB x 5 backups — a hard ceiling of 29 MB per expert, whatever happens
- `test_endurance.py` **[locks]** no lock file survived 120+ tasks and 6 loop restarts — every one was released by its holder or reclaimed as stale
- `test_endurance.py` **[ledgers]** the whole expert directory is 1.3 MB after 120+ tasks (10.8 KB per task): the model gateway 48 KB, routing outcomes 21 KB, compiled context windows 972 KB
- `test_endurance.py` **[context]** across 42 compiled windows the median size went 1083 -> 1083 tokens: the window is bounded by its budget, not by how much the fleet remembers
- `test_endurance.py` **[soak]** 18s of continuous operation. This is minutes, not weeks: it rules out the growth that is O(total work), and it cannot rule out a leak that needs days to show.

</details>

**Blind spot.** the provider tests run against a LOOPBACK SERVER that implements the documented OpenAI-compatible shape. They prove this platform's HTTP client is correct against that shape; they prove nothing about how any real provider behaves, and a provider that deviates will still surprise us. `python loop.py check` remains the only live probe. The docker tests DO start real containers, but on one machine, one image and one daemon version — not on the hosted backends (E2B, Daytona), whose CLIENT is verified against the documented shape while the services themselves have never been contacted. The endurance soak drives real tasks for minutes, which rules out growth that is O(total work) and cannot rule out a leak that needs days.

## 11. The interface itself

*the UI/UX specification's own acceptance table: that each flow's information is reachable, that the migration moved views rather than deleting them, and that no proof level can be set by hand*

**Verdict: proven** — 1 of 1 declared tests ran and passed, producing 10 observations.

<details><summary>What the tests observed (10)</summary>

- `test_ux.py` **[first-mission]** the command bar, four primary actions and a 7-step checklist that reads real state are all on Home; the briefing offers 1 next action(s) without opening Guide
- `test_ux.py` **[create-expert]** 5 intent questions cover all 5 lanes and none of them names a lane; every lane declares which of the six steps it can honour
- `test_ux.py` **[supervision]** one request answers objective, current action ('read the Acme MSA' -> C1), 2 open criteria, 1 blocker(s), and cost â€” and the blocker routes to a person rather than to a retry
- `test_ux.py` **[proof]** 15 capabilities each carry level, badge, the reason, the covering tests and the code hash the evidence is bound to; the panel has no way to set a level, only to re-run the evidence
- `test_ux.py` **[worker]** a computer card shows zone, what it can do (declared and implied), cost, scale-to-zero and who may use it; the choice reads 'Using Office Windows PC because excel + internal-network are required (no compute cost)' and names why each other computer was passed over
- `test_ux.py` **[training]** ingested / covered / examined / still-open are four separate numbers: 0 source(s), 1/2 requirements evidenced, exam 88% (pass), 1 gap(s) still open â€” and no percentage is computed anywhere without its denominator
- `test_ux.py` **[errors]** 9 failure classes, each naming which part failed (7 distinct owners incl. the verifier, the platform, the provider, the budget breaker and you), what happens next and what you can do; the raw trace sits under Advanced
- `test_ux.py` **[advanced]** identity, prompts, roles, model wiring, raw files and traces are all still reachable behind one disclosure, and none of them appears in the six-item primary nav
- `test_ux.py` **[mobile]** the sidebar becomes a bottom bar with 40px targets, grid items may shrink, and every one of the 37 tables sits in a scroll container
- `test_ux.py` **[design]** no status is carried by colour alone, a hosted view never prints a second page title, and the panel shows the command that reproduces what it claims

</details>

**Blind spot.** this proves REACHABILITY, not usability. The spec asks for five people completing five flows at 90%; that has not happened and nothing in a repository can stand in for it. The mobile assertions read CSS source, not rendered layout — the two defects they cover were found in a real browser at 375 px, which no test here runs.
