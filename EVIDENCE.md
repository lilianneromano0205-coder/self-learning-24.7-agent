# Evidence — why we believe this works

Generated 2026-08-31T22:59:58 from an actual suite run: **135/137 tests passed**, **641 observations** recorded.

Each test below prints its own sentence describing what it proved; those sentences are quoted verbatim, not summarised. Every system also carries a **blind spot** — what these tests do not cover.

> Every model call in every test is the scripted mock provider. A green suite proves the harness holds; it never proves that any real provider works. `python loop.py check` is the only live probe.

## Verdict by system

| system | verdict | tests | observations |
|---|---|---|---|
| 1. Harness & loop | **proven except skipped** | 26/27 | 93 |
| 2. Fleet & creation lanes | **proven** | 6/6 | 21 |
| 3. Work systems | **proven** | 23/23 | 115 |
| 4. Memory institution | **proven** | 22/22 | 76 |
| 5. Improvement & governance | **proven** | 11/11 | 35 |
| 6. Control plane & interop | **proven** | 21/21 | 120 |
| 7. The six authorities | **proven** | 3/3 | 33 |
| 8. Proof, missions and long-horizon work | **proven** | 5/5 | 27 |
| 9. Computers, capability and organization | **proven except skipped** | 7/8 | 41 |
| 10. Training lab | **proven** | 1/1 | 6 |
| 12. The paths that touch something real | **proven** | 6/6 | 42 |
| 11. The interface itself | **proven** | 1/1 | 10 |
| 13. The universal agent | **proven** | 3/3 | 20 |

## 1. Harness & loop

*the engine: context assembly, six tools, gates, brakes, retries, escalation, policy, effects, compaction*

**Verdict: proven except skipped** — 26 of 27 declared tests ran and passed, producing 93 observations.
**NOT RUN HERE — test_shutdown.py:** Popen.terminate() on Windows is TerminateProcess, which no handler can intercept — there is no SIGTERM here to catch, so this asserts nothing rather than asserting something false. The container CI runs it.

<details><summary>What the tests observed (93)</summary>

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
- `test_compaction.py` **[cliff]** five compaction rounds and the safety rule survived each one byte-identical (never entering the summarized region), and a rule appended to the constitution on disk reached the very next window verbatim — typed compaction by construction: rules are files, only conversation is summarized
- `test_lock.py` **[unit]** live lock blocks; dead/unknown/stale owner locks are broken
- `test_lock.py` **[integration]** two same-course tasks serialized, both done, lock released
- `test_lock.py` **[hammer]** 12 threads x 40 acquisitions: every writer survived and all 480 rows landed — EACCES during lockfile creation is retried as the contention it is
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
- `test_subquery.py` **[subquery]** a 2000-line corpus was map-reduced through a disposable sub-call on its own cheap rail: the distilled answer reached the task while the corpus text reached NEITHER the task record nor any persisted context window; the sub-call was metered as purpose=subquery; an oversized slice was refused naming the cap; a path escape was refused — recursion under the same laws as everything else
- `test_json_toolcall.py` **[json-tools]** a model that cannot emit native tool calls is still usable: inline JSON in the content parses and executes
- `test_json_toolcall.py` **[parallel-tools]** a single message carrying 3 tool calls left 0 orphaned ids of 4: the first ran, the other 2 were answered with NOT RUN and asked for again, so the transcript stays valid and no work disappears
- `test_guardrails.py` **[budget]** $4 spent against a $3 ceiling: loop paused, next task untouched, human notified exactly once
- `test_guardrails.py` **[repetition]** identical call warned at 3, failed at 5 with the loop named
- `test_guardrails.py` **[rule-of-two]** run_command denied for the limited role: no execution, clear error, task continued
- `test_guardrails.py` **[marking]** injected directive fenced as untrusted data, rule present in grounding
- `test_guardrails.py` **[secrets]** agent.env/ui-token.txt refused for read AND write (incl. traversal spellings); normal files unaffected
- `test_effects.py` **[exactly-once]** 3 attempts of an emailing task, 1 real send; the retry received the recorded result, labelled REPLAYED; the ledger holds one effect for the lineage
- `test_effects.py` **[fresh]** an explicit --fresh call hits the world again — the ledger is a default, not a cage
- `test_effects.py` **[policy]** destructive/escalating commands refused INSIDE the loop with the rule named; normal work passed; owner deny rules and per-role allowlists enforced
- `test_effects.py` **[exemption]** the review exemption is per-SUBCOMMAND, not per-file: `mcp.py call` stays exempt because guarded_call gates it, while `mcp.py enable` — which grants a whole toolkit and is gated by nothing — now requires the owner. Checked across 7 shapes including chaining and a lookalike script.
- `test_effects.py` **[governance]** role allowlists and tool deny lists enforced before the server is touched; 50k-char result capped at 20k; a vetted catalog of 8 open-source servers ships
- `test_effects.py` **[claim]** two threads raced one effect key through the real lookup/unfinished/begin sequence and exactly one claimed it; the ledger holds 1 started row(s)
- `test_sandbox.py` **[host]** explicit developer-only host mode runs in the expert's own root with the AGENT_* environment the harness promises
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
- `test_chaos.py` **[size]** an 11 MB file, 1,000 atoms and 200 skills compiled to a 13292 token window in 1.8s, cut marked
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
- `test_candidates.py` **[interface]** the considered page scored 1.0 and the generated filler 0.2963, both passing the same gate
- `test_candidates.py` **[applies]** a citation to a nonexistent atom sank its candidate; the same check stayed silent about an interface
- `test_candidates.py` **[isolation]** an attempt's changes were undone byte-for-byte, including deleting the file it invented
- `test_candidates.py` **[promote]** the winning attempt's bytes were put back and every attempt kept its own score on disk
- `test_candidates.py` **[adaptive]** one attempt until something fails, then 3, then 5 — capped by the owner's setting and switchable off
- `test_candidates.py` **[explain]** the winner is reported with the reason every loser lost
- `test_candidates.py` **[wired]** the loop stashes every refused attempt (15 of them here) and promotes one only when it strictly beats the last — on a task where the verifier cannot discriminate it reports a tie and changes nothing, which is the honest answer rather than a shuffle
- `test_candidates.py` **[discriminates]** a real answer scores 1.0, a one-character one 0.75, an unfinished one carrying TODO 0.75, and a .json that does not parse 0.6 — the composite can now tell attempts apart on ordinary work, where every other component declines to answer and six attempts previously tied at 0.0
- `test_candidates.py` **[contained]** a planted stash could not overwrite prompts/constitution.md nor write outside the expert root, a traversal artifact was refused and RECORDED, and the score that decides which attempt wins is control state while the attempt's own files stay the agent's
- `test_retention.py` **[bounded]** 300 tasks done, hot queue holds 40 finished (67 KB); queued and blocked work untouched
- `test_retention.py` **[lossless]** all 302 tasks accounted for — 260 archived, every field intact and findable by id
- `test_retention.py` **[flat]** the hot state is capped at 50 finished task(s) after 400 more were run (limit 65), so persist is bounded work forever — measured 13 ms -> 15 ms here, but the COUNT is the guarantee and the clock is only a smoke check
- `test_retention.py` **[context]** finished transcripts tidied into contexts/archive/, the verbatim never-lose tier left in place and still recallable
- `test_retention.py` **[heartbeat]** the loop pulses with its current task; a stale pulse is what separates 'wedged' from 'idle'
- `test_context.py` **[manifest]** the compiled window names every source it used and the files inside it; the transcript matches the manifest
- `test_context.py` **[disclosure]** a skill that did not activate is offered by name and one line, not by loading its body
- `test_context.py` **[budget]** a 45 KB handed file was cut to its 500-token budget and the cut is marked with how to read the rest
- `test_context.py` **[clearing]** big tool outputs were archived verbatim and replaced by a pointer before summarizing -- the summarizer never saw them
- `test_context.py` **[panel]** the control panel serves the exact window each task was given, per source
- `test_use_cases.py` **[recon]** two verified weeks against a truth-recomputing gate became an unprompted candidate procedure with its parameters invented — and it is NOT trusted until an owner seals fresh cases
- `test_use_cases.py` **[sentinel]** a healthy drain queued nothing; the ERROR line fired exactly one gated investigation, which passed its own mechanical gate — no model watched anything
- `test_use_cases.py` **[memory]** the gate-diagnosed failure was filed by the harness and injected into the NEXT task's compiled context before it ran — nobody had to remember

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
- `test_toolbox.py` **[gallery]** 24 specialists, all kinds covered, identities carry standards and refusals
- `test_toolbox.py` **[quick]** capability note injected first; template identity installed
- `test_local.py` **[env]** agent.env loaded automatically, comments and quotes handled
- `test_local.py` **[inbox]** daemon scanned its own inbox on idle: file -> lesson -> watcher -> done
- `test_local.py` **[demo]** python demo.py: full lifecycle, COMPLETE course, both proofs PASS, no keys

</details>

**Blind spot.** the lanes are exercised with scripted providers and small briefings; no test covers a multi-hour real ingestion or a team larger than three specialists.

## 3. Work systems

*task, goal engine, team, deterministic workflow, consultation, prospective intentions, routines, procedural mastery (sealed capability packs)*

**Verdict: proven** — 23 of 23 declared tests ran and passed, producing 115 observations.

<details><summary>What the tests observed (115)</summary>

- `test_goal.py` **[judge]** a judge claiming ACHIEVED while a check failed was OVERRULED; the pursuit continued and finished the work for real
- `test_goal.py` **[replan]** cycle 2 planned WITH the previous assessment in hand
- `test_goal.py` **[shape]** learning goals detected; build goals keep a build-shaped plan
- `test_goal.py` **[commons]** the overruled-judge failure became a binding fleet lesson; duplicates collapse into repeat markers; the directory lists who knows what
- `test_goal.py` **[share]** every task now opens with what the agent has verified about itself, then the fleet's shared memory
- `test_goal.py` **[peer]** one expert asked another; the answer runs through the peer's own citation gate, attributed to the asker
- `test_contract.py` **[frozen]** acceptance was frozen before any work, sealed outside the worker's root, and verify() ran the checks itself — failing while the artifact was missing, passing once it existed
- `test_contract.py` **[no-vacuous]** zero acceptance tests means nothing can be VERIFIED — stated in the verdict, not hidden inside an empty all()
- `test_contract.py` **[tamper]** swapping a failing grader for a passing one after the freeze produced a TAMPER verdict with nothing run — and forging the snapshot's own hash lost to the seal outside the root
- `test_contract.py` **[machine]** draft cannot jump to verified, verified is terminal, and blocked is the one ending an owner may deliberately resume
- `test_contract.py` **[zones]** the agent's file tools are refused on contract.json, events.jsonl and goal.json inside goals/, while plans and evidence notes beside them stay writable
- `test_contract.py` **[budget]** spend accumulated from the ledger tripped the ceiling by name (spend $0.60 > $0.50), and a pursuit over its wall-clock budget blocked before planning anything
- `test_contract.py` **[oscillation]** the same check failing in consecutive cycles is diagnosed with the wall named; a new failure reason or a spaced repeat is not — progress and looping are told apart
- `test_contract.py` **[replay]** the event ledger rebuilt the same state the snapshot held, and a snapshot forged to 'verified' with no such event was reported as divergence
- `test_contract.py` **[outranked]** a lying judge AND a generous planner-authored check both said done while the deliverable did not exist — the frozen acceptance test refused, the pursuit was overruled into cycle 2, did the work for real, and only then ended VERIFIED, with the whole story in the event ledger
- `test_contract.py` **[converge]** the same milestone failing the same check in cycles 1 and 2 ended the pursuit BLOCKED with the wall named — two of the four budgeted cycles were spent, not all four
- `test_contract.py` **[machine]** two threads raced one contract to two mutually exclusive endings: verified was accepted, the other was refused BY THE RULE, and the ledger carries exactly one ending
- `test_runbook.py` **[valid]** 6 malformed shapes refused with the defect named — a step with no verify, a TODO left in, a 21-step monolith; a runbook that cannot be validated cannot be trusted to run
- `test_runbook.py` **[prove]** each step must pass its own verify before the next runs: a failing step 2 stopped the run at step 2 with the reason stated, after step 1 demonstrably executed
- `test_runbook.py` **[contained]** a runbook step is a model-authored command and gets the model-command stack: `rm -rf /` in a `do` was refused by policy, not executed
- `test_runbook.py` **[earned]** 3 ACCEPTED wins promoted a candidate to proven, recorded by the harness in a ledger the worker cannot write; 5 self-verified runs with no caller acceptance promoted nothing, and a procedure the caller's graders rejected stayed a candidate after 4 of its own clean runs; a self-declared 'proven' inside the file was ignored; 2 consecutive losses quarantined, and a quarantined runbook refuses to run
- `test_runbook.py` **[match]** trigger terms select the runbook; quarantined never volunteers; candidates appear only under explicit allowance; an unrelated goal matches nothing
- `test_runbook.py` **[reconcile]** a goal contract was driven to VERIFIED by observe -> apply -> verify with no model and no task queue involvement; a goal with no matching procedure ended BLOCKED naming the frontier instead of improvising
- `test_runbook.py` **[pennies]** goal.pursue completed a goal VERIFIED with ZERO tasks created and ZERO model calls — against a provider rigged to fail any task instantly, so the model path could not have produced this outcome even by accident. The model is now reserved for goals the library has never seen.
- `test_runbook.py` **[draft]** a verified pursuit yields a skeleton carrying the proven VERIFICATIONS with the HOW left as named TODOs — validation refuses to run it until they are filled, because the machine can recover what was proven but not how it was done
- `test_runbook.py` **[applicable]** a negative trigger vetoed a matching runbook; an unmet when.requires probe made a PROVEN match inapplicable and reconcile blocked NAMING the precondition; satisfying it let the identical goal reconcile to VERIFIED
- `test_runbook.py` **[compose]** a parent runbook ran its child in place with the child's own trust gate enforced and its own wins recorded (candidate child stopped an unsupervised parent; the child earned proven through composition); a mutual cycle was refused with the chain named
- `test_runbook.py` **[record]** a demonstrated procedure landed as a CANDIDATE with recorded provenance; a step without verify was refused; the rehearsal replayed the demo through the authority stack, was recorded as a run, and earned NO trust — a procedure grading its own replay is still the procedure grading itself
- `test_repair.py` **[law1]** a blocked goal's diagnosis and every grounded repair action carry the failing check and its recorded error VERBATIM from the ledger — there is no 'reflect and try again' action anywhere in the plan
- `test_repair.py` **[law3]** a budget block and a tamper block both plan exactly one action — OWNER — and a repair pass left the contract's budget bit-for-bit unchanged: the machine cannot lift its own ceiling or forgive edits to its own graders
- `test_repair.py` **[law4]** revising a failing runbook wrote publisher-v2 BESIDE its parent — parent file and earned trust untouched, child a zero-trust candidate carrying the exact failure it must answer, refused by validation until the TODO is filled
- `test_repair.py` **[law2]** a repair whose fix was real ended VERIFIED — but the ledger shows the passing verify event BEFORE the state change: the frozen graders spoke first. A repair that fixed nothing resumed and did NOT verify. Repair moves blocked->running; it never grades.
- `test_repair.py` **[bounded]** the identical repair plan was refused a second run ('not converging'), and the attempt bound turned away a repair past its limit — a goal still blocked after grounded repairs gets an owner, not a fourth attempt
- `test_repair.py` **[signal]** apply() wrote a repair.md under 2000 chars carrying the verbatim error and the warning that the harness re-checks; a resumed pursuit injects it into the planner's context
- `test_swarm.py` **[rule1]** two failing acceptance tests with NO declared groups planned NO fan-out — independence is declared by the caller who wrote the graders, never guessed by the machine, because assumed separability is where the measured -39% to -70% lives
- `test_swarm.py` **[rule2]** two groups served by one shared procedure did not fan out (two workers, one procedure buys nothing), and a group with no proven procedure was named as the frontier instead of being improvised in parallel
- `test_swarm.py` **[fanout]** two declared groups with two distinct proven procedures ran as two workers, both artifacts produced, and the state moved only after the central graders passed — with the task queue untouched: multiplication of MACHINE work, zero model calls
- `test_swarm.py` **[rule4]** a group whose lease was held by another swarm was NOT run twice — the worker reported the held lease, the other group proceeded; with the lease released, the single remaining group was correctly refused fan-out and finished on the sequential path instead
- `test_swarm.py` **[rule3]** both workers reported success; the central graders refused A1 and the swarm result was NOT verified, with the refusing test named — a worker's opinion of its own work counts for nothing, in the contract AND in the trust ledger
- `test_swarm.py` **[cap]** a cap of 2 ran exactly 2 workers and NAMED the group it could not take (['c2']) instead of silently dropping it
- `test_swarm.py` **[e2e]** goal.pursue on a grouped goal fanned out to two workers and ended VERIFIED with zero tasks and zero model calls — against a provider rigged to fail any task, so only the machine path can explain the outcome
- `test_swarm.py` **[ledger]** 4 threads appended 100 events concurrently and the ledger holds exactly 100, none corrupt — the append is a critical section now, because it measurably was not one before
- `test_mastery.py` **[coverage]** a well-formed pack validates; a competency with no sealed transfer task is refused by name, and an ungraded task cannot be in a pack at all
- `test_mastery.py` **[sealed]** the worker's file tools can neither read nor write the transfer tasks or validators (they live outside its root), and swapping a validator for `exit 0` after the freeze is a TAMPER verdict that refuses to grade anything
- `test_mastery.py` **[author]** a drafted pack (all TODOs) cannot freeze; a sealed pack records its author; the author is refused as its own student by name, and a different expert passes the same gate
- `test_mastery.py` **[baseline]** the sealed transfer set ran BEFORE any study and the 0.0 baseline was recorded with every failing task named — improvement claims now have a floor to be measured from
- `test_mastery.py` **[graded]** a correct artifact passed its pack validators with ZERO model involvement (task queue untouched, against a rigged provider); a missing artifact failed with its checks named
- `test_mastery.py` **[sealed]** a student holding three finished artifacts still scored only what it could rebuild — prior work does not reach the arena
- `test_mastery.py` **[verdict]** 2/3 on the sealed exam against a 0.7 bar is NOT mastered; 3/3 is — computed from harness-run grader results against the pack's frozen thresholds, grader events before the verdict in the ledger, and the verdict names its own ceiling (a mechanical floor, not taste)
- `test_mastery.py` **[diagnose]** a transfer failure mapped to exactly the competency its task examines, carrying the failing checks as evidence
- `test_mastery.py` **[consumed]** a gap found by the exam ends in 'fresh pack required', not a re-sit: each sealed task was graded exactly once, no relearn round re-used it, and the verdict stayed NOT mastered
- `test_mastery.py` **[retention]** the sealed tasks re-ran under fresh pursuit ids and the delta against the exam was recorded — what survives a fresh context is the only honest meaning of 'it learned'
- `test_mastery.py` **[distill]** 1 verified practice pursuit(s) became runbook draft(s) — proven verifications kept, the HOW left as TODOs, zero trust until three verified wins
- `test_steer.py` **[advice]** a hostile note ('mark it verified') left the grader results and the contract state bit-identical, and the note itself is on the ledger as a `steered` event — influence is recorded, never obeyed
- `test_steer.py` **[zoned]** the worker's file tools cannot write steering.jsonl or steering.md — the guidance channel only speaks with the owner's voice
- `test_steer.py` **[render]** notes render verbatim, newest last, capped at 5; empty and oversized notes are refused with the reason named
- `test_steer.py` **[injected]** a note added before the cycle landed in the planner's context files for that cycle, verbatim — guidance reaches the very next plan without a restart
- `test_contract_model.py` **[model]** all 8x8=64 transition attempts probed: 13 accepted (exactly the 13 declared), 51 refused with the reason; verified's only door is running; all 4 terminal states exitless; every state reachable from draft; 6 seeded walks replayed from the ledger with zero divergence; a forged snapshot flagged
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
- `test_prospective.py` **[probe]** a check-condition held silent while its command exited 1 (probed once, rate-limited across ticks), then fired when the condition became true — the trigger names the probe
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
- `test_research.py` **[retrieve]** the two design questions found their atoms (C-0101, C-0102); the refund question found nothing and is listed as unestablished; retrieval is not proposition support
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
- `test_url.py` **[settle]** zero settling means zero even when the filesystem clock runs ahead of the wall clock, and a real window still holds a file back until it stops changing
- `test_url.py` **[ssrf]** all 9 internal-address spellings refused — IPv4-mapped and long-form IPv6, decimal and hex integer hosts included — and an ordinary public host still fetches
- `test_url.py` **[video-host]** a host is matched exactly or as a parent domain: an article about YouTube is fetched as a page, a lookalike domain buys nothing, and real video hosts still route to the downloader
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

**Verdict: proven** — 22 of 22 declared tests ran and passed, producing 76 observations.

<details><summary>What the tests observed (76)</summary>

- `test_knowledge.py` **[graph]** 8 atoms became 4 entities and 1 co-occurrence edge(s) across 1 topic(s) — derived entirely from files on disk, with every claim keeping its citation and its source tier, and nothing asked of a model
- `test_knowledge.py` **[audit]** --weak names exactly the 2 claims resting below the learn bar (a content farm and a Medium post), and --load-bearing shows one RFC underpinning 37.5% of everything believed here — concentration is a real risk that a flat notes file cannot display at all
- `test_knowledge.py` **[agree]** the knowledge graph and the citation checker see the identical 4 atoms across 4 course layouts up to 4 levels deep, because they call one walker rather than two — the flat path this used to join matched nothing the platform writes, and both this test and the code were wrong the same way
- `test_memory.py` **[classify]** 8 harness errors mapped to fixed categories deterministically — no model asked to guess why it failed
- `test_memory.py` **[failures]** structured records, deduplicated by signature with recurrence counts, filterable by agent and category
- `test_memory.py` **[competence]** computed from verified outcomes (gated work counts double); small samples labelled; routing answerable from evidence
- `test_memory.py` **[retired]** retirement moves a whole world aside intact — queryable, listed, and restorable years later
- `test_memory.py` **[preserve]** delete retires by default; only an explicit purge destroys
- `test_memory.py` **[automatic]** finishing a task files its own competence outcome and, on failure, a categorized failure record — retries count as occurrences but never as extra competence attempts
- `test_memcheck.py` **[broken]** all 4 violation types detected and named
- `test_memcheck.py` **[repaired]** memory passes: IDs unique, citations resolve, spec grounded, index complete
- `test_skills.py` **[skills]** run 2 loaded the playbook run 1 wrote, and an unrelated task did not - procedural memory compounds without leaking
- `test_skillgraph.py` **[gate]** co-occurrence wins stayed candidate; only a matched held-out ablation (6 discordant pairs, sign test) earned PROVEN
- `test_skillgraph.py` **[quarantine]** a harm-showing ablation quarantined the skill; a contradictory one redeemed it; fresh harm evidence re-quarantined
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
- `test_freshness.py` **[freshness]** 8 atoms scanned: the expired one flagged with both dates, the superseded one flagged naming its successor, the retracted source flagged through the CONTROL-zoned ledger (short refs refused, worker locked out), directive-shaped memory (a $5,000 standing order, a forged owner's voice) flagged while an honest how-to imperative was not, nothing deleted, and the Crossref retraction verdict proven pure and offline
- `test_awareness.py` **[fresh]** a new expert is told it has verified nothing yet, instead of being handed a confident persona
- `test_awareness.py` **[studied]** it reports each course by verified atoms, exam result and source tier -- and names the course it was never examined on
- `test_awareness.py` **[evidence]** one lucky success is reported as insufficient evidence, and a playbook whose ablation showed measured harm is named do-not-use — losses alone no longer convict
- `test_awareness.py` **[now]** it knows its role, its allowed tools, its stop condition and where commands run -- and says so when a role has no provider
- `test_awareness.py` **[window]** the self-model leads every context window, survives a closed-book exam, and carries no course content with it
- `test_awareness.py` **[institutions]** 22 real public bodies — the EU, CERN, Max Planck, INRIA, RIKEN, CSIRO, four national governments, the UN, OECD, IEEE, ISO, MIT OpenCourseWare — all clear the learn bar, while 5 content-farm and lookalike URLs do not; before this, the European Commission rated exactly the same as an SEO blog
- `test_audit.py` **[two-loops]** 6 tasks, 2 concurrent loops: each claimed exactly once, executed exactly once (6 endings for 6 tasks), and all done
- `test_audit.py` **[ownership]** a running task records its owner: a live sibling's work is refused by the predicate, by adopt_task and by the scheduler, while a dead owner, an unstamped task and an expired foreign lease are all still recoverable -- crash recovery survived the fix
- `test_audit.py` **[lost-update]** 24 tasks queued under concurrent writes: 0 lost, 0 regressed (was 6 lost / 12 regressed before the mutex)
- `test_audit.py` **[unicode]** accented names slug cleanly; accented content preserved verbatim
- `test_cases.py` **[open]** a failed task opened case K-11b4d76c with its cause recorded, not just a log line
- `test_cases.py` **[fixed]** a later task that passed its gate closed the case, and what it did is recorded as the fix — verified by the gate, not by an opinion
- `test_cases.py` **[recurred]** the same failure after a fix was recorded as RECURRED — the ledger now says the obvious fix already failed once
- `test_cases.py` **[recall]** the returning problem carried its own history into the window, including what was tried and that it did not hold; an unrelated task carried nothing
- `test_cases.py` **[confidence]** the task that passed scored 47% (medium) and the one that failed its gate 30% (low -> escalate)
- `test_cases.py` **[ledger]** 1 case(s), 1 that came back after a 'fix' — the number a team actually needs to see
- `test_gotcha_retire.py` **[probe]** the failing step recorded `cmd:pandoc`, and a generic runner keeps its subcommand so `git push` and `git status` are not the same claim
- `test_gotcha_retire.py` **[specific]** a different command proved nothing, and pandoc failing again proved nothing — the gotcha still binds
- `test_gotcha_retire.py` **[retired]** a later step ran pandoc successfully and the gotcha was withdrawn — MARKED, not deleted: the line still carries its cause, the date, and the task that disproved it
- `test_gotcha_retire.py` **[window]** the withdrawn gotcha no longer reaches the context window, so it stops evicting live warnings and stops forbidding a step that now works
- `test_gotcha_retire.py` **[resurrection]** the same failure came back after being withdrawn — the gotcha binds again, and the line permanently records that it was disproved once and returned, which is the signature of a FLAPPING environment rather than a fixed one
- `test_gotcha_retire.py` **[conservative]** a failure with no runnable subject gets no probe and never auto-retires, and gotcha files written before probes existed still parse and still bind — under-retiring costs a context slot, over-retiring deletes a warning that was still true
- `test_gotcha_retire.py` **[wired]** a real task through the real loop ran `echo`, and the gotcha claiming echo was broken was withdrawn automatically, logged as gotcha_retired, and counted in the ledger (1 retired, 0 still binding)
- `test_discover.py` **[rank]** three catalogues returning one DOI produced ONE result, ranked tier-first; 1 below-bar candidate(s) were filtered AND counted, and raising the bar to 4 let them back in
- `test_discover.py` **[degrade]** two dead rails and one that raised KeyError left the live rail's result intact, each failure named with its reason — a catalogue outage is a partial answer, not a total one
- `test_discover.py` **[no-trash]** all 4 search-engine result pages are tier 4 by host and cannot clear the learn bar at any setting — 'only reputable sources' is a property of the catalogue, not an instruction a model may ignore
- `test_discover.py` **[read-only]** discovery emitted 2 quoted `ingest.py add-url` lines and opened no connection of its own: finding is free and auditable, fetching stays an explicit, separate act
- `test_discover.py` **[typo]** a misspelled rail is reported by name rather than silently producing a smaller result set that looks like a real answer
- `test_discover.py` **[relevance]** the goal was reduced to its subject before being sent ('b-tree index concurrency control'), and 2 confidently-irrelevant tier-1 result(s) were dropped and counted — an off-topic source reached by a trusted route becomes a cited atom, which is a wrong belief carrying a real citation
- `test_discover.py` **[live]** SKIPPED: set DISCOVER_LIVE_TEST=1 for explicit public-catalogue smoke
- `test_sources.py` **[reviewed]** DOAJ, PubMed and Europe PMC keep tier 1, with reasons that name the review/selection process actually behind them
- `test_sources.py` **[provenance]** DOI resolvers, Crossref, DataCite and arXiv rate tier 2 — real scholarly provenance, still learnable, and the reason states outright that an identifier is not a review mark
- `test_sources.py` **[honest]** none of the 12 unreviewed scholarly hosts carries a why-text claiming review — the words a human reads now match what the host actually promises
- `test_sources.py` **[fed]** all 8 scholarly discovery rails still produce results at or under the learn bar — the halo is gone, the pipeline is not
- `test_sources.py` **[spoof]** lookalike subdomains still buy nothing
- `test_sources.py` **[proof]** the module's own 29-reference proof table runs in the suite and agrees with the registry; no domain is rated twice
- `test_sources.py` **[derived]** a tier and an owner override forged in the workspace ledger are both ignored — the tier is recomputed from the URL — while a genuine set_tier still overrules, recorded in a control-zoned file the agent cannot write and the workspace ledger stays writable so ingestion keeps working
- `test_reflector.py` **[reflection]** exactly one Reflector task followed the work, it completed, and it did not chain further

</details>

**Blind spot.** conflict detection is text-based and conservative by design: it finds polarity flips and numeric disagreements between claims about the same subject, and has no semantic model of any domain. Contradictions phrased outside those rules are missed, and no test can enumerate what is missed. Gotcha retirement has its own limit, in the other direction: a probe names the COMMAND (plus its subcommand for a generic runner like git or python), not the arguments. So a failure that depends on the input — pandoc handling .docx but choking on .odt — is retired by a success on a different file, and the warning is withdrawn while still true for the case that mattered. It comes back the next time it bites, marked UNRETIRED, but it is withdrawn in between. Narrowing the probe to the full argument list would trade this for the opposite failure: almost nothing would ever match, and gotchas would accumulate forever again.

## 5. Improvement & governance

*charter variants with predictions, approvals, replay, benchmark, promotion gates, the design gate*

**Verdict: proven** — 11 of 11 declared tests ran and passed, producing 35 observations.

<details><summary>What the tests observed (35)</summary>

- `test_variants.py` **[guards]** no promotion without a trial; no trial on a single task
- `test_variants.py` **[trial]** same battery, two real drains: base 0/2 (gate refused 12x), variant 2/2; live prompts untouched
- `test_variants.py` **[promote]** strictly-better variant installed; base charter backed up
- `test_variants.py` **[tie]** equal performance refused — churn without evidence is rot
- `test_variants.py` **[rollback]** the exact pre-promotion charter restored; un-promoted variants cannot roll back
- `test_variants.py` **[isolation]** each arm ran in its own clone of the expert; two identical charters scored identically (2 = 2), and neither arm's artifacts reached the live root
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
- `test_modelrouter.py` **[attribution]** a failover failure was split 0.9/0.1 by served share: the cheap model that did nine steps carries nine tenths of the failure, the fallback that finished it carries one tenth — the router's economics are no longer polluted by whoever happened to serve last

</details>

**Blind spot.** promotion and routing decisions are proven against seeded outcome ledgers, not against months of real measured performance. The design gate checks mechanics and the known fingerprints of generated filler; it cannot judge beauty.

## 6. Control plane & interop

*panel, live events, cards, chief, doctor, preflight, backup, providers, MCP, A2A federation, traces*

**Verdict: proven** — 21 of 21 declared tests ran and passed, producing 120 observations.

<details><summary>What the tests observed (120)</summary>

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
- `test_ui.py` **[cockpit]** a pursuit's contract, graders, ledger and steering all readable; a steer lands on the ledger; the graders re-run on demand and report the failing check by id
- `test_ui.py` **[interrupt]** the owner's stop button moved a running pursuit to BLOCKED with the reason named on the ledger — resumable, never silent
- `test_ui.py` **[danger]** deletion retires and preserves the whole world; only an explicit purge destroys it
- `test_ui.py` **[one-response]** a write that fails after the headers are sent does not produce a second status line, and an error that happens before any response still reports normally
- `test_csrf.py` **[csrf]** a cross-origin POST is refused by Origin AND by Sec-Fetch-Site; nothing was created
- `test_csrf.py` **[same-origin]** the panel's own requests are unaffected
- `test_csrf.py` **[rce]** a free-form shell done_check over HTTP is refused — defence in depth, even from a same-origin caller
- `test_csrf.py` **[gates]** a named gate becomes the command; a traversing parameter inside one is still refused
- `test_csrf.py` **[catalogue]** GET /api/gates lists what a caller may ask for
- `test_frontend.py` **[syntax]** the page's JavaScript parses under node --check
- `test_frontend.py` **[page]** the six job-shaped sections each state their purpose and route to a renderer; guide/memory/models/system were MOVED, not deleted, and each is still reachable from a clickable control; every endpoint the page names exists; both themes defined
- `test_frontend.py` **[serve]** page served from ui.html (328358 bytes)
- `test_frontend.py` **[fresh]** a newly created expert answers on all six read endpoints, no 500s
- `test_frontend.py` **[live]** frontend edits appear on reload with no server restart
- `test_package.py` **[secrets]** 347 archive members checked four ways — by basename, by containing directory, by extension, and by READING every text member for assigned credential values. The content scan was calling a path-taking function on a line of text, so it had never evaluated true; now live, it finds exactly the 7 synthetic fixtures the tests are built from and nothing else, and an unlisted hit or a stale exemption both fail
- `test_package.py` **[private]** none of 5 private-data shapes carries CONTENT in the archive — no expert memory, task state, logs, context windows or organization roster — while 8 empty placeholder(s) keep the working directories so a fresh unzip runs with no setup. Proof observations DO ship, deliberately: every one is bound to a code hash and none names this machine, so the recipient inherits evidence that falls the moment they change the code
- `test_package.py` **[runnable]** the archive carries 108 modules, 137 tests, the prompts and settings.toml — and unzipped into an empty directory it passes `harness.py --check` with no setup at all
- `test_package.py` **[install]** 4 installers ship in the archive, every GitHub reference names reda-baqechame/self-learning-24.7-agent, the shell scripts are CRLF-free, and 4 parsed clean with the interpreters present here (install.sh, get-fleet.sh, setup-vps.sh, install.ps1)
- `test_package.py` **[clone-dirs]** all 10 working directories survive a git clone, so the clone route and the zip route land the same tree — a real clone of the published repo had 8 of them missing, including the inbox the installer tells the owner to use
- `test_package.py` **[harness-safety]** the mutation harness plants a decoy only where no real credential file exists, and reports None otherwise — so the cleanup that follows can never remove an owner's keys, which it did while announcing that it was skipping them
- `test_package.py` **[planted]** 3 decoy credential file(s) were created in the source tree and the archive excluded every one, by file and by value — an exclusion rule is only worth what it catches
- `test_package.py` **[evidence]** all 137 registered tests are classified into 13 systems with no overlap and no drift, every system states a blind spot, and the standing 'every call is a mock' caveat is in the module and in the generated report
- `test_package.py` **[skip]** a deliberate skip is held apart from both outcomes it resembles: it does not make a green suite publish a FAILING artifact, it contributes no observations so it is never counted as proof, the artifact names it and quotes its reason, a genuine non-pass is still FAILING, and a system where everything skipped reads UNPROVEN rather than proven
- `test_panel_v2.py` **[identity]** the owner rewrote who this agent is; the previous version was kept and the new words were in the next window
- `test_panel_v2.py` **[pins]** the owner's binding lines are injected first, for every agent, and re-materialised the moment they are saved
- `test_panel_v2.py` **[thread]** a team run reads as a conversation: brief, plan, each specialist's file, the lead's synthesis -- all auditable
- `test_panel_v2.py` **[approval]** every pending sign-off carries what was done, what this step is and what comes next; browser tools add takeover
- `test_panel_v2.py` **[home]** readiness lists what is missing by NAME (never a value) and the fleet's tool health is one call away
- `test_events.py` **[replay]** a new connection is handed the recent history first, so a freshly opened panel is never blank
- `test_events.py` **[live]** the tasks the agent ran while we watched arrived as they happened: start, each tool call, end
- `test_events.py` **[robust]** unparseable lines in the log were skipped and the stream kept delivering
- `test_events.py` **[auth]** the live stream is guarded by the same token as the API: only as a header, including the fetch-based event stream
- `test_uicards.py` **[catalogue]** table, checklist, diff and metric parse into normalised data with every cell coerced to a bounded string
- `test_uicards.py` **[closed]** unknown types, malformed JSON, oversized and over-the-cap cards are all dropped with a stated reason
- `test_uicards.py` **[inert]** a script tag inside a card is carried as text and never becomes markup -- the client escapes, the schema has no slot for it
- `test_uicards.py` **[loop]** cards were collected from a message and from the finish summary, the bogus one was refused, both were logged
- `test_uicards.py` **[client]** the page's renderer was run against a hostile card: every branch emitted escaped text, and the unknown type emitted nothing
- `test_remote.py` **[deny]** page served; unauthenticated API call rejected with 401
- `test_remote.py` **[allow]** wrong token refused; correct token authorized
- `test_remote.py` **[writes]** anonymous create refused and created nothing; authorized create worked
- `test_chief.py` **[quiet]** an untroubled fleet gets one calm ADVANCE — no invented urgency
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
- `test_mcp.py` **[a2a]** A2A-discoverable custom card served at the standard well-known path: exposed experts as skills, signed transport declared, zero secret material
- `test_mcp.py` **[url-args]** 6 tool arguments pointing at file://, loopback, private and link-local addresses are refused BEFORE the server is called — including nested ones, which is how a browser server passes its options — and 4 ordinary argument shapes still pass
- `test_mcp.py` **[sees]** an image block is written to tmp/ (mcp-1788230947-1.png) and the result names the exact `ingest.py vision` command that reads it, so a screenshot becomes something the agent can answer questions about; an undecodable blob is reported as gone, not hidden
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
- `test_providers.py` **[plug]** a key in the environment IS a provider: a role named a rail with no settings entry and it wired from the verified catalog at runtime; keyless rails refuse naming the exact env var; cloudflare's missing account id is a named error at wire time; an explicit settings entry always outranks the catalog
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
- `test_backup.py` **[sigv4]** 2 of AWS's own published example signatures reproduced byte for byte, and the secret appears in no header -- the request is signed with a derivation of it, never the key
- `test_backup.py` **[fail-closed]** a push with no credentials refuses by name and sends nothing -- it does not reach the network to find out
- `test_backup.py` **[compounding]** four snapshots into the DEFAULT output directory stayed flat at 78,748 bytes with zero nested archives — a backup no longer archives its own backups, which on a 24/7 fleet filled the disk the fleet needs in order to save itself
- `test_backup.py` **[pull]** a good archive downloads and verifies; one flipped byte deep inside is caught and REFUSED with the reason — the check the feature advertised now actually runs, having previously crashed on every archive and, once unpacked, trusted a damaged one
- `test_backup.py` **[never-raises]** verify() reports zlib.error, BadZipFile, OSError and MemoryError as a NAMED corrupt member instead of raising — the layer that notices damage differs by platform, and the narrow except list was green on 4 of 6 runners
- `test_preflight.py` **[blocker]** a fleet with no backup is NOT READY, and the finding carries the exact command that fixes it
- `test_preflight.py` **[cleared]** taking a backup cleared the blocker -- and the audit verified its checksums rather than trusting the filename
- `test_preflight.py` **[cost]** a disabled daily breaker was named per settings file -- the expert's and the fleet default's -- and setting it cleared that one
- `test_preflight.py` **[integrity]** a corrupted archive was caught by the audit, not discovered on the day it was needed
- `test_preflight.py` **[access]** exposure is audited only when the panel is exposed; a missing token is then a blocker, and transport is still flagged
- `test_preflight.py` **[verdict]** the verdict follows the findings and the exit code follows the verdict: 2 blocked, 1 risks, 0 clean
- `test_preflight.py` **[critic]** an examiner running the author's own model was named as review theatre; pointing it at a different model cleared it
- `test_preflight.py` **[robust]** a check that threw was reported as a failed check; the audit still produced a verdict
- `test_preflight.py` **[one-truth]** a keyless fleet is NOT READY on BOTH surfaces, with preflight quoting doctor's own blocking item verbatim; supplying the key cleared both at once — one computation, two renderers, no second opinion
- `test_ecosystem.py` **[organism]** one gated win + one honest failure: skill graph, fleet competence, and the failure ledger all agree
- `test_ecosystem.py` **[prospective]** the watch fired on the file change and the fired task ran to done under its own gate
- `test_ecosystem.py` **[race]** two processes evaluated the same due intention — it fired exactly once (the measured double-fire stays dead)
- `test_ecosystem.py` **[writers]** 2 processes x 20 outcomes: all 40 recorded — the graph lock loses nothing
- `test_ecosystem.py` **[recall]** the decision pulled its cited atom's definition across files — chain, not fragment
- `test_ecosystem.py` **[variants]** trial refused while a loop pulses — arms cannot be contaminated by a foreign claimer
- `test_ecosystem.py` **[chief]** the briefing surfaced the blocked question with its actual text, ranked first
- `test_ecosystem.py` **[retire]** the whole organism — graph, intentions, notes — survived retirement and came back byte-true
- `test_ecosystem.py` **[doctor]** full inspection: ledgers parse, no stale locks, the briefing compiles — nothing wrong but the missing key

</details>

**Blind spot.** the panel is driven through its HTTP API and its HTML is parsed, but no test renders it in a browser. Layout, contrast and touch targets are verified by eye, not by CI.

## 7. The six authorities

*one mandatory gateway per kind of power — execution, file, credential, model gateway, effect, control plane — plus the invariant tests that enumerate every caller of each*

**Verdict: proven** — 3 of 3 declared tests ran and passed, producing 33 observations.

<details><summary>What the tests observed (33)</summary>

- `test_invariants.py` **[execution]** 104 modules scanned; 0 raw subprocess sites outside the authority (16 declared platform-internal, each with a stated reason)
- `test_invariants.py` **[catalogue]** 5 execution operations: every model-authored one enforces policy+sandbox, every platform one refuses a shell string, and each of the 1 declaring approval actually requires one for a consequential command while still letting ordinary work through
- `test_invariants.py` **[zones]** 15 paths + every declared control file/dir/path (10 files, 9 dirs, 1 paths) classified and enforced by zone
- `test_invariants.py` **[ledgers]** all 8 ledgers harness treats as integrity invariants are CONTROL and refused to the agent — including skills/graph.json, the skill trust graph, which sat in the workspace because `skills/` is legitimately the agent's own
- `test_invariants.py` **[traversal]** 12 escape spellings (posix, windows, UNC, mixed, nested) all refused or contained
- `test_invariants.py` **[credentials]** all 4 sources (env, agent.env, inline, api_key_file) resolve, count as funded, are excluded from packaging, are redacted, and are unreadable by the agent
- `test_invariants.py` **[metering]** 104 modules scanned by AST; every function that reaches a model provider meters it (2 declared free, each with a stated reason and each still present in the source)
- `test_invariants.py` **[metering]** all 11 call purposes reach the ledger, attribute per call, and count toward today's spend
- `test_invariants.py` **[keys]** every string-keyed dict literal in the platform is collision-free, and both proof capabilities that were competing for one name exist (19 registered)
- `test_invariants.py` **[control-plane]** the seal is derived from fileauth's zone model: all 30 control shapes sealed, the workspace untouched, every path with a declared treatment
- `test_invariants.py` **[roles]** 9 roles: every one can finish/escalate, the Student holds neither read_file nor a shell, and no untrusted-material role holds run_command
- `test_invariants.py` **[gates]** 5 catalogue entries build a command; a raw shell string never does
- `test_invariants.py` **[birth]** 3 modules mint experts; the gateway seeds a never-bootstrapped home itself (library AND CLI, from any working directory), is idempotent, does not clobber owner edits, and refuses with a sentence when the home is genuinely impossible
- `test_invariants.py` **[exams]** 4 recorded formats: the loop's completion check, the self-model, and the block injected into every context window all read the same score from the same file
- `test_invariants.py` **[sandboxes]** 176 sandbox names across 137 test files, every one claimed by exactly one file — a shared temp directory is the failure that only shows up under load
- `test_invariants.py` **[settings]** 64 [agent] key(s) read across the modules, every one of them declared in settings.toml — the file an operator reads is the file the code obeys
- `test_invariants.py` **[cli]** 81 documented subcommands across 50 modules all parse, and every module prints its own --help on a non-UTF-8 console
- `test_invariants.py` **[clocks]** every .py in the platform parsed: no file timestamp is compared against another file's, which is the comparison a coarse filesystem tick corrupts (U19, U20). The 5 remaining getmtime sites sort, or measure age against the wall clock — sound, but not unconditionally: an age can come back NEGATIVE when the two clocks disagree, which is what U22 was, so this check bans the pattern it can prove and the docstring records the edge it cannot
- `test_invariants.py` **[capabilities]** every dual-installed tool resolves the same way for the report and the runtime, and each one actually executes: yt-dlp via module
- `test_invariants.py` **[org-policy]** all 3 organization policy flags are declared with an enforcer, the named module really reads each one, flipping agents_may_install actually refuses an install, and only the owner can change it — all three were inert, unreachable and shown in the panel
- `test_invariants.py` **[arch-table]** all 5 rows of ARCHITECTURE.md's control table match execution.describe() flag for flag — the doc gave capability_probe an approval the code never implemented
- `test_invariants.py` **[policy]** an uncompilable deny OR allow pattern refuses every command and names the rule, instead of being skipped in silence while the rules around it keep working; a valid policy is unaffected in both directions
- `test_invariants.py` **[health]** the sandbox health check can actually FAIL: a configured backend that does not exist is reported, and `host` is refused unless the owner explicitly declares allow_unsafe_host
- `test_invariants.py` **[grants]** 10 authority classes grantable, 1 deliberately ask-every-time, 0 undecided — the two vocabularies cannot drift apart silently
- `test_controlplane.py` **[matrix]** 100 shell commands from a role holding run_command — truncate, append, delete, create and a redirect — against all 30 control paths fileauth declares: not one durable change, every attempt reported exit=3, 100 tamper events on the record
- `test_controlplane.py` **[owner]** all 8 owner-level CLI entry points refused from inside an agent task and the seeded approval is still denied; the same call succeeds outside one
- `test_controlplane.py` **[state]** rewriting state.json is reported as tampering and NOT reverted (a sibling loop owns it), and the compensating control holds: the task could not mark itself done, because the loop's next commit rewrites its own record from memory
- `test_controlplane.py` **[approvals]** a PENDING request may appear while a command runs (execution.run creates one); a GRANTED record may not, and the one that did was removed
- `test_controlplane.py` **[docker]** 29 read-only bind(s) layered over /work cover every one of the 30 control paths; on that backend the boundary is the kernel's, not a check's
- `test_controlplane.py` **[premise]** in the SHIPPED settings.toml, 4 role(s) hold run_command (default, examiner, practitioner, ripper) and 5 do not (consultant, librarian, reflector, student, watcher) — so the matrix above attacks the real configuration; and the seal brackets all 3 model-authored operations, because a done_check is written by the model as surely as a command is
- `test_controlplane.py` **[cost]** a 1910-path control plane (1500 approvals, 200 goal ledgers) seals and verifies in 170 ms per command — 27 s before the caches — and a change to a cached path is still caught
- `test_controlplane.py` **[clock]** a directory changed inside the timestamp-uncertainty window is re-scanned rather than served from cache, so a control file cannot hide in the resolution of the clock
- `test_controlplane.py` **[bytecode]** an import's __pycache__ under capabilities/ is reverted without failing the command; a planted .pyc never survives the bracket; a source edit beside it still convicts

</details>

**Blind spot.** these tests enumerate every path in THIS tree. They cannot see a path added by a plugin, an MCP server or a future module that does not exist yet — which is why the execution audit is a source scan rather than a runtime check, and why it fails on a new raw subprocess call rather than warning. The Control Plane Authority carries a second, sharper limit, stated in its own module: on `sandbox = "host"` it DETECTS AND REVERTS rather than prevents, because there is no filesystem boundary on that backend to prevent with. Prevention needs `sandbox = "docker"`, where the control paths are bound read-only and the boundary is the kernel's.

## 8. Proof, missions and long-horizon work

*capability proof levels derived from hash-bound evidence; the mission contract that survives context resets, restarts and model swaps*

**Verdict: proven** — 5 of 5 declared tests ran and passed, producing 27 observations.

<details><summary>What the tests observed (27)</summary>

- `test_proof.py` **[derived]** the ledger stores observations only — there is no level field for anyone to set by hand
- `test_proof.py` **[ladder]** a level requires every level beneath it: live evidence alone stayed at IMPLEMENTED until the acceptance tests passed
- `test_proof.py` **[regression]** editing the code dropped OFFLINE VERIFIED -> IMPLEMENTED automatically, and restoring it brought the level back — nobody touched a status
- `test_proof.py` **[failure]** a failing run is recorded as failing — the ledger keeps both, so a regression is visible rather than overwritten
- `test_proof.py` **[expiry]** live and stress evidence older than its window expired automatically and the badge fell back to OFFLINE VERIFIED — a green light cannot rot into a lie by sitting still
- `test_proof.py` **[stability]** the code hash survives line-ending translation while still changing on real edits
- `test_proof.py` **[registry]** 19 declared capabilities each state a user capability, invariants, code and tests; nothing with unwritten code claims a level above SPEC
- `test_mission.py` **[persisted]** the mission contract is a file on disk, not a passage in a transcript that compaction can summarise away
- `test_mission.py` **[model-swap]** the contract names no model or provider, so swapping one cannot change what the mission is
- `test_mission.py` **[bound]** an action must name the criterion it serves and the evidence it will produce; unbound work and unrecognisable outcomes are both refused
- `test_mission.py` **[monotonic]** met evidence cannot silently vanish: invalidating it needed a stated reason and the original record is still there
- `test_mission.py` **[amendment]** the objective cannot be edited in place — the change carries a reason, an author, and both fingerprints, so drift is visible instead of silent
- `test_mission.py` **[gaps]** 4 blocker dimensions classified and routed; only the authority gap escalated to the owner
- `test_mission.py` **[every-role]** practitioner, student and consultant all receive the objective, the binding constraints and their criterion — the memory router cannot route the assignment away
- `test_mission.py` **[closure]** a mission closes on met criteria, never on a decision to stop; and a mission with no criteria cannot be created
- `test_mission.py` **[unblock]** a raised blocker can be resolved through the CLI with the reason recorded, and a bad index fails loudly — resolve_blocker was written but unreachable from every surface
- `test_metrics.py` **[sources]** 12 metrics read from 12 distinct ledgers, each naming its own — no metric keeps a second count of something another subsystem already knows
- `test_metrics.py` **[samples]** 3 metric(s) below the 5-observation floor are printed with the warning attached, not as a bare percentage
- `test_metrics.py` **[honesty]** 4 metric(s) this platform cannot compute are named with the reason, rather than dropped or approximated — including one that would have been flattering to invent
- `test_metrics.py` **[reliability]** 2/5 gated tasks passed and 15/17 finish-claims were refused — both derived in one pass over one ledger, so neither can exceed 100% or contradict the other
- `test_metrics.py` **[autonomy]** the figure names itself an upper bound, and it MOVES: appending one approval_required event took it from 5/5 to 4/5 — it reads the log, where a human being needed is actually recorded
- `test_metrics.py` **[fidelity]** 1/1 recorded actions name the criterion they serve — the platform refuses to record one that does not, so this metric can only ever be 100% or reveal a bug
- `test_metrics.py` **[multiplier]** 22 harness interventions across 10 levers are reported as COUNTS with what a bare model would have done instead; the multiplier itself is in the refused list, because the baseline half has never been run
- `test_metrics.py` **[empty]** a fleet with no history reports 'no data' on every rate rather than 0%, which would read as a measured failure
- `test_evalsuite.py` **[graders]** all 24 checks pass a hand-written correct answer and all 24 reject a deliberately wrong one — both directions, because a check that only ever passes is the dead check this project already found once in its own packaging test
- `test_evalsuite.py` **[honest-stats]** 9/12 reports 47%-91%, and even a perfect 12/12 reports a lower bound of 76% — a small suite is never allowed to claim certainty
- `test_evalsuite.py` **[sealed]** every holdout run is recorded against the code hash that produced it — 2 looks across 2 versions here — because a held-out set spent without anyone counting is just training data nobody labelled

</details>

**Blind spot.** no mission here has run longer than a test. The contract is proven to survive a simulated reset, not a week of real drift, and no capability has ever been observed above level 2 because that needs a real provider. Three of the manual's twelve metrics cannot be computed at all — supervision hours, 90-day retention, and anything that would need a real workload — and `metrics.py` names them rather than approximating them.

## 9. Computers, capability and organization

*where work runs and why that computer was chosen; how a capability is acquired without gaining authority; who may do what, and the trail that records it*

**Verdict: proven except skipped** — 7 of 8 declared tests ran and passed, producing 41 observations.
**NOT RUN HERE — test_acquire.py:** no isolated sandbox on this machine (docker not available), so the install rungs cannot be exercised without breaking the rule they protect. The refusals above were all checked.

<details><summary>What the tests observed (41)</summary>

- `test_workers.py` **[registry]** 4 computers registered with zone, capability and cost; scale-to-zero kinds start stopped, so one expert does not imply one always-on machine
- `test_workers.py` **[isolation]** free work went to the disposable container, not to the equally-free, faster-starting organization machine — blast radius outranks speed
- `test_workers.py` **[trusted]** the owner's own machine is never selected automatically; it becomes eligible only when explicitly allowed
- `test_workers.py` **[matching]** requirements are read from the task text; an impossible requirement returns no computer AND the reason each one was ineligible, instead of falling back to whatever was nearest
- `test_workers.py` **[implied]** every kind declares what it implies, a bare registration of each kind routes for what that kind is, implied capabilities are shown separately from declared ones, and implying does not paper over a capability that is genuinely absent
- `test_workers.py` **[explain]** the choice reads as a sentence: 'Using Office Windows PC because excel + internal-network are required (no compute cost)'
- `test_workers.py` **[policy]** a computer restricted to named experts is invisible to the others, and the refusal says it was policy rather than capability
- `test_workers.py` **[cost]** an idle computer accrued nothing, an hour of GPU time accrued $2.50, and stopping it stopped the meter
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
- `test_rbac.py` **[coverage]** 22 POST routes; 20 named in the table and 2 falling through to 'create_agent', which needs builder or above — a route added tomorrow is refused for a viewer, not waved through
- `test_rbac.py` **[audit]** a request that claimed a different author was recorded against the token's real owner (owner@example.com) — the trail is attributable because the identity comes from the credential
- `test_rbac.py` **[shared]** a fleet that belongs to an organization refuses an untokened request, generates a master token, and admits a member on their own token while still refusing what their role forbids
- `test_frontier.py` **[unfalsifiable]** a probe observed green before anything was installed is held at 'unfalsifiable' and never reported ready; any corroboration is recorded as an owner action (1 of them), never as a stage
- `test_frontier.py` **[no-self-grant]** a passing pre-install probe cannot reach 'owned', and acquiring one is refused BECAUSE its probe never failed: the only path is request -> install -> capability_test -> a human
- `test_frontier.py` **[tamper]** an edited spec AND an appended conflicting seal both return 2 with the execution ledger unchanged — first-seal-wins, so appending a seal is not a way to re-seal a probe
- `test_frontier.py` **[zone]** frontier/ is a CONTROL directory and its ledger is in harness.LEDGERS — the scope proved here is the write_file tool's classification, which is what an agent's file writes go through
- `test_frontier.py` **[outside]** a forged 'owned' row is not ready: the deciding record is the seal ledger at kind='home', outside the expert root, which no write under that root can reach
- `test_frontier.py` **[anchor]** four unanchored quotes refused — a capability must quote a real span of what was actually asked, or it is a capability somebody imagined
- `test_frontier.py` **[authored]** propose() has no parameter that could carry probe code (14 parameters, none of them a body), and both generated bodies keep the checks that tie a pass to installed bytes rather than to anything the worker could place
- `test_frontier.py` **[contained]** a RED observed on the host is recorded honestly as uncontained and is refused as the basis for installing anything — the same refusal acquire.install already makes
- `test_frontier.py` **[owner]** adoption refuses from inside an agent task, refuses without an exact echo of the command being published to every future agent, and refuses a capability nothing has proven
- `test_frontier.py` **[backoff]** a refused capability is not retried before its recorded date, the reason travels with the refusal, and asking again changes no stage and starts no acquisition
- `test_frontier.py` **[no-false-ready]** a goal the hint table never knew now names 4 capability(ies) on its SECOND encounter, each reported not-ready with the recorded reason — the first shape of the bug was a silent drop, the second a silent READY
- `test_frontier.py` **[dry]** route, a dry acquire, capabilities, summary and a dry universal.resolve left the expert tree AND the seal directory byte-identical
- `test_frontier.py` **[shadow]** a frontier capability may not take a built-in's name ('video_download') nor carry it as a substring, and the capability note still parses into its sections
- `test_frontier.py` **[shell]** the sealed command carries no shell metacharacter, three metacharacter-bearing published commands were refused, and both adopt and acquire-promote now require review
- `test_frontier.py` **[shapes]** scan(None) and recipe(cap) answer exactly as they always did, capabilities(None) is empty rather than raising, and a frontier route appears only when a root is passed
- `test_frontier_live.py` **[available]** docker runs python:3.12-slim and the registry answers
- `test_frontier_live.py` **[live]** the sealed probe for ulid-py failed before the install and passes after it, inside the container, and the pass is bound to an install digest over the bytes that landed
- `test_frontier_live.py` **[sealed]** the acquisition reached stage 'tested' through the shipped ladder, and the unsealed lookalike probe acquire writes to tmp/ was removed (1 test event(s) recorded)
- `test_frontier_live.py` **[target]** the sealed probe, acquire's naming and the directory on disk all name 'capabilities/ulid-py' — a probe that tests a different directory from the one the install writes proves nothing
- `test_frontier_live.py` **[adopt]** a PROVEN capability is not yet READY to any agent, and adoption refused without a granted approval — leaving a pending one for a human, which is the only thing that can publish it

</details>

**Blind spot.** every worker is a RECORD. Nothing here has started a container, installed a package, or measured a real start-up time — the acquisition ladder is proven to refuse correctly, not to install correctly. And `test_rbac.py` proves AUTHORISATION given an identity; the identity itself is a bearer token over plain HTTP with no TLS, session or expiry. The capability frontier is proved WITHOUT a real install: no registry was queried, no package fetched and no hosted rail called, so what is proven here is that it refuses, seals and reports correctly — not that an acquisition completes.

## 10. Training lab

*sanitised trajectory export, a deterministic non-overlapping split, an immutable verifier, a promotion threshold and a mandatory rollback target*

**Verdict: proven** — 1 of 1 declared tests ran and passed, producing 6 observations.

<details><summary>What the tests observed (6)</summary>

- `test_training.py` **[sanitised]** a credential inside a captured step was redacted before it ever reached the trajectory store
- `test_training.py` **[split]** 80 train / 20 held-out, deterministic across re-exports and provably non-overlapping
- `test_training.py` **[verifier]** a candidate evaluated with a different verifier was refused — comparing those numbers would measure the verifier, not the model
- `test_training.py` **[gate]** a change below its declared threshold, a single-seed result and a self-declared score were all refused; promotion required a policy sealed before the candidate existed, a paired three-seed run of the owner's frozen evaluator over 20 sealed held-out tasks, and an all-must-pass canary on 20 fresh ones — and the record carries checkpoint, verifier hash, holdout hash and evidence sha256, with the score marked SEALED, not DECLARED
- `test_training.py` **[rollback]** the promotion recorded what it replaced and the rollback returned to it — a promotion without a way back is a one-way door
- `test_training.py` **[boundary]** the export states plainly that this platform does not perform gradient updates, names what an external trainer must do, and refuses a corpus too small to mean anything

</details>

**Blind spot.** this module performs no gradient updates at all, and says so on every export. What is proven is the governance around a training run — nothing here has trained anything, and no reward-hacking suite exists.

## 12. The paths that touch something real

*the two code paths that had never been executed by anything — the live provider HTTP client, and the docker sandbox — each driven against a real server and a real container*

**Verdict: proven** — 6 of 6 declared tests ran and passed, producing 42 observations.

<details><summary>What the tests observed (42)</summary>

- `test_live_provider.py` **[wire]** one real HTTP call carried the model, the messages, the configured 4096-token ceiling, exactly the 6 tools this role is allowed, the bearer key and the configured extra header — and with the ceiling left at its default, max_tokens is omitted rather than sent as 0
- `test_live_provider.py` **[cost]** the provider reported 1M+1M tokens and the ledger charged $18.00 at the configured rates — spend is read from the response, never estimated by the client
- `test_live_provider.py` **[retry]** 429 then 503 then success in 3 calls with growing backoff; a 400 stopped after exactly 1 call instead of burning five
- `test_live_provider.py` **[retry-after]** a 429 asking for 45s slept 45.7s (the blind backoff would have been 2s and retried into a closed window), a 503 asking for 1s slept 1.2s instead of 2s or more, and both carry jitter so simultaneous experts do not return in lockstep
- `test_live_provider.py` **[retry-after]** the header parser pinned across 15 shapes: both legal formats, the 120s cap, negatives and past dates clamped to 0, and every unreadable value falling back to blind backoff rather than to 0
- `test_live_provider.py` **[unreachable]** a refused connection failed over to the fallback in 2.03s and was logged as unreachable, instead of costing five backoffs per step forever
- `test_live_provider.py` **[keys]** all 3 configured key sources (env, inline, file) reached the Authorization header and were accepted by a server that checks them
- `test_live_provider.py` **[malformed]** a non-JSON body and a body with no choices are each retried through the full ladder, then failed over to the configured fallback, and logged against the provider that sent them — they used to raise straight out of the loop, killing the task and never trying the fallback
- `test_live_provider.py` **[timeout]** a provider that hung for 20s was cut off by the 2s ceiling and retried, finishing in 2.1s — the timeout is a real bound, not a suggestion
- `test_live_provider.py` **[inline]** a provider with native_tools = false received NO tool schema and answered with inline JSON, which the loop parses
- `test_live_provider.py` **[end-to-end]** a gated task was completed with 2 model calls over a real socket, the artefact exists, the gate passed, and all 2 of THIS task's calls are metered against the provider that actually served them
- `test_docker_live.py` **[available]** docker ready with python:3.12-slim
- `test_docker_live.py` **[isolated]** the command ran inside a Debian container on python 3.12.14, under its own hostname '8f193cb19d43' which is not this machine's, on a Windows host running python 3.14 — this is not the host backend wearing a different name
- `test_docker_live.py` **[mount]** the expert's root is /work inside the container: a file written there landed on the host, and a file the host wrote was readable inside — in both directions, byte for byte
- `test_docker_live.py` **[containment]** 3 probes for the host filesystem — a drive root, the platform's own source directory, and the fleet home above the mount — all came back empty from inside the container
- `test_docker_live.py` **[network]** egress is refused by default (--network none is on the argv, and a real connection attempt failed inside), and only [agent] sandbox_network = true removes it
- `test_docker_live.py` **[credentials]** three credential-shaped variables were withheld from the container by name and by value, and of the 11 variables it did receive none came from this host except the image's own — both filters checked, not just the outer one
- `test_docker_live.py` **[timeout]** a 60-second command under a 6-second ceiling was cut off in 7.4s, reported as a failure, and left no container behind
- `test_docker_live.py` **[limits]** every run carries --rm, --memory 1g and --pids-limit 256; asked for 768 processes the container reached 0 and went no further — the ceiling is enforced by the daemon, not merely declared
- `test_docker_live.py` **[end-to-end]** the loop completed a gated task with sandbox = docker: the model wrote a file inside a container, and the gate command ran in a container to verify it
- `test_hosted_sandbox.py` **[no-key]** both hosted backends refuse without a key, name the key as the reason, and — the property that matters — run nothing on this machine instead
- `test_hosted_sandbox.py` **[contract]** the exec request carried the command, a working directory, a 45000ms deadline and the key in both header styles the two services use
- `test_hosted_sandbox.py` **[credentials]** four credential-shaped values, including the sandbox service's own key, were all absent from the JSON sent to a third-party machine
- `test_hosted_sandbox.py` **[spellings]** a non-zero exit is reported as a failure in both `exitCode` and `exit_code` forms — reading only one would turn every failed remote command into a success
- `test_hosted_sandbox.py` **[failures]** 4 failure shapes — a billing refusal, a server error, a non-JSON body and a host that is not listening — each became a reported non-zero result with a message, and none raised
- `test_hosted_sandbox.py` **[honesty]** with no key each hosted backend reports itself unavailable and names the variable; with a key present it reports itself configured — which is all a key can honestly establish
- `test_first_day.py` **[bootstrap]** an empty directory became a fleet with an expert ('first-day') in one command; the key reached agent.env and appears nowhere in 1802 characters of output
- `test_first_day.py` **[probe-ok]** `loop.py check` reported OK, presented exactly the key bootstrap had stored, asked for 16 output tokens, and printed the key nowhere
- `test_first_day.py` **[probe-fail]** a rejected key reports FAIL with the HTTP status and exits non-zero; a missing key reports FAIL naming the exact environment variable to set — the two failures a first day actually produces, told apart
- `test_first_day.py` **[unreachable]** a base_url nothing is listening on reported FAIL in 2.3s instead of hanging on a 20-second timeout per role
- `test_first_day.py` **[cheap]** 9 roles sharing 1 model(s) produced 1 probe request(s): the check caches by provider/model pair rather than charging once per role
- `test_first_day.py` **[metered]** all 4 probe call(s) landed in the model-call ledger with their provider and model — `loop.py check` is a real provider call and is now attributed like any other
- `test_first_day.py` **[first-task]** with the probe green, a gated task ran to completion over the same provider — the artefact exists, the gate passed, and the key appears nowhere in 3468 characters of log
- `test_first_day.py` **[activate]** one key repoints every role at the provider that key belongs to, writes its verified endpoint and leaves the file's comments intact; 11 providers are catalogued, ranked by what they actually give away; incomplete credentials are refused rather than half-applied; and running it twice changes nothing
- `test_endurance.py` **[soak]** driving 120 real tasks through a real loop (AGENT_SOAK_TASKS to change)
- `test_endurance.py` **[queue]** 120 tasks completed; the hot queue held 20 then 42 against a retention of 20, 78 moved to the append-only archive with none lost, and state.json went 93495 -> 196273 bytes (2.1x)
- `test_endurance.py` **[latency]** per-task wall time across 6 batches: 0.15s, 0.20s, 0.19s, 0.19s, 0.19s, 0.18s — median 0.19s, and the last batch is not an outlier: the loop does not get slower as its own history grows
- `test_endurance.py` **[logs]** agent.log is 116 KB and rotates at 5 MB x 5 backups — a hard ceiling of 29 MB per expert, whatever happens
- `test_endurance.py` **[locks]** no lock file survived 120+ tasks and 6 loop restarts — every one was released by its holder or reclaimed as stale
- `test_endurance.py` **[ledgers]** the whole expert directory is 1.9 MB after 120+ tasks (16.4 KB per task): the model gateway 48 KB, routing outcomes 27 KB, compiled context windows 1077 KB
- `test_endurance.py` **[context]** across 42 compiled windows the median size went 1140 -> 1140 tokens: the window is bounded by its budget, not by how much the fleet remembers
- `test_endurance.py` **[soak]** 25s of continuous operation. This is minutes, not weeks: it rules out the growth that is O(total work), and it cannot rule out a leak that needs days to show.

</details>

**Blind spot.** the provider tests run against a LOOPBACK SERVER that implements the documented OpenAI-compatible shape. They prove this platform's HTTP client is correct against that shape; they prove nothing about how any real provider behaves, and a provider that deviates will still surprise us. `python loop.py check` remains the only live probe. The docker tests DO start real containers, but on one machine, one image and one daemon version — not on the hosted backends (E2B, Daytona), whose CLIENT is verified against the documented shape while the services themselves have never been contacted. The endurance soak drives real tasks for minutes, which rules out growth that is O(total work) and cannot rule out a leak that needs days.

## 11. The interface itself

*the UI/UX specification's own acceptance table: that each flow's information is reachable, that the migration moved views rather than deleting them, and that no proof level can be set by hand*

**Verdict: proven** — 1 of 1 declared tests ran and passed, producing 10 observations.

<details><summary>What the tests observed (10)</summary>

- `test_ux.py` **[first-mission]** the command bar, four primary actions and a 7-step checklist that reads real state are all on Home; the briefing offers 1 next action(s) without opening Guide
- `test_ux.py` **[create-expert]** 5 intent questions cover all 5 lanes and none of them names a lane; every lane declares which of the six steps it can honour
- `test_ux.py` **[supervision]** one request answers objective, current action ('read the Acme MSA' -> C1), 2 open criteria, 1 blocker(s), and cost — and the blocker routes to a person rather than to a retry
- `test_ux.py` **[proof]** 19 capabilities each carry level, badge, the reason, the covering tests and the code hash the evidence is bound to; the panel has no way to set a level, only to re-run the evidence
- `test_ux.py` **[worker]** a computer card shows zone, what it can do (declared and implied), cost, scale-to-zero and who may use it; the choice reads 'Using Office Windows PC because excel + internal-network are required (no compute cost)' and names why each other computer was passed over
- `test_ux.py` **[training]** ingested / covered / examined / still-open are four separate numbers: 0 source(s), 1/2 requirements evidenced, exam 88% (pass), 1 gap(s) still open — and no percentage is computed anywhere without its denominator
- `test_ux.py` **[errors]** 9 failure classes, each naming which part failed (7 distinct owners incl. the verifier, the platform, the provider, the budget breaker and you), what happens next and what you can do; the raw trace sits under Advanced
- `test_ux.py` **[advanced]** identity, prompts, roles, model wiring, raw files and traces are all still reachable behind one disclosure, and none of them appears in the six-item primary nav
- `test_ux.py` **[mobile]** the sidebar becomes a bottom bar with 40px targets, grid items may shrink, and every one of the 43 tables sits in a scroll container
- `test_ux.py` **[design]** no status is carried by colour alone, a hosted view never prints a second page title, and the panel shows the command that reproduces what it claims

</details>

**Blind spot.** this proves REACHABILITY, not usability. The spec asks for five people completing five flows at 90%; that has not happened and nothing in a repository can stand in for it. The mobile assertions read CSS source, not rendered layout — the two defects they cover were found in a real browser at 375 px, which no test here runs.

## 13. The universal agent

*the layer that decides which of these systems a goal needs before any work starts: that the readiness verdict is EARNED from mechanical probes rather than asserted, that knowledge from a weak source does not count as knowledge, that an AUTHORITY gap stops the run before goal.pursue is ever reached, that a dry run writes nothing, and that every gap is classified by the platform's own gap router rather than by a second opinion*

**Verdict: proven** — 3 of 3 declared tests ran and passed, producing 20 observations.

<details><summary>What the tests observed (20)</summary>

- `test_universal.py` **[earned]** the verdict moved only when the facts did: a new expert reported a knowledge gap, and 2 cited atom(s) from tier-1 sources closed it
- `test_universal.py` **[sources]** the same claim was accepted at tier 1 from an RFC and refused at tier 3 from a content farm — what is believed depends on where it came from, decided by rule and never by a model
- `test_universal.py` **[authority]** three goals implying an account, a payment, a credential, a deployment and an email all stopped BEFORE any work began and routed to the owner; goal.pursue was never reached; and an ordinary goal was not falsely escalated
- `test_universal.py` **[capabilities-corpus]** singular and plural resolve identically across 8 capability families (they did not: 'these PDFs' asked for nothing), prose asks for nothing, and interactive goals now require browser_control instead of being answered by urllib
- `test_universal.py` **[authority-corpus]** 28 phrasings that must reach the owner all do — including 'log into', 'sign in to', 'authenticate' and 'credentials', which the hand-written whole-word table missed — and 10 ordinary goals are still not escalated
- `test_universal.py` **[dry-run]** describing a goal produced 1 routed action(s), each with a reason and a command you can run yourself, and wrote nothing to the expert
- `test_universal.py` **[routing]** 3 gap(s) across 2 dimension(s), every one classified by mission.GAPS itself rather than by a second opinion, and every one carrying the route the platform already declared for it
- `test_universal.py` **[route]** 15 goal shapes each landed on the declared system, every verdict carrying a why, a CLI path and a panel path — and the note still says it is a mechanical floor, not understanding
- `test_universal.py` **[corpus]** 25 goals across 25 unrelated trades: none derives nothing, each keeps the capability it is about, and the four measured direction bugs (report->git, signing->browser, spoken->transcribe, chart->vision) all stay fixed. Before: 6 OK, 5 WRONG, 14 SILENT
- `test_universal.py` **[wild]** 25 adversarial goals across manufacturing, medical, legal, finance, media and infrastructure: none derives nothing, none loses a capability it is about, and all 8 carrying an irreversible physical or financial effect stop for the owner. Before: 5 silent, 12 incomplete, 5 that would have acted
- `test_universal.py` **[unified]** POST /api/achieve is reachable, permissioned 'run' by declaration, validates its inputs, and REFUSED to start a goal needing the owner — naming 2 blocker(s) instead of beginning. The layer that orchestrates everything is no longer reachable only from a terminal.
- `test_grants.py` **[scope]** a grant covers its own scope and nothing beside it: another vendor is refused, another KIND of authority is refused, and a scopeless grant must be spelled '*' rather than left blank
- `test_grants.py` **[lifetime]** a grant stops working the day it expires and the moment it is revoked — a permission that outlives its reason is how a temporary exception becomes standing access nobody approved
- `test_grants.py` **[owner-only]** neither an admin nor a builder can grant authority; only the owner can, and the agent has no path to it at all
- `test_grants.py` **[ledger]** the cap is consumed by real use, a second spend that would breach it is refused, and every use is written to a ledger — a standing grant without a usage log is a blank cheque
- `test_grants.py` **[wired]** universal.assess honours a live grant — the credential gap clears for the granted vendor, the MONEY gap still blocks, and another vendor is still blocked; nothing self-grants, and the moment the grant expires or is revoked this reverts with no code change
- `test_grants.py` **[recorded]** acting under 2 standing grant(s) wrote 2 usage row(s) naming the expert and the work, while a read-only assessment wrote none — the difference between a permission and a blank cheque is the log of what was done with it
- `test_experience.py` **[gotchas]** a rookie doing the same work inherits a sibling's environment failure — attributed, and marked as a WARNING rather than the binding rule it is for the expert that paid for it
- `test_experience.py` **[shared]** a rookie with no history of its own inherited a sibling's FIXED case for the same work — attributed, dated, and marked as verified in that expert's environment rather than this one's; an unrelated expert's unrelated case was not injected; and no expert harvests itself
- `test_experience.py` **[ranked]** a case carrying a verified fix outranks a bare failure, and the block reached the context window the model actually reads (104 case(s) across 3 expert(s), 1 with a fix)

</details>

**Blind spot.** it reads the goal's WORDS to infer what will be needed, so a goal that requires a PDF reader without saying anything PDF-shaped is not detected — the inference is a keyword table, deliberately inspectable rather than a model's guess, and it is better at over-asking than under-asking. It also decides readiness from what is on disk NOW: an expert can be READY and still fail, because ready means 'nothing known is missing', never 'this will succeed'.
