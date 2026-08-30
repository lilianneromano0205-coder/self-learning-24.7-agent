# Security policy and threat model

This document states what this platform defends, against whom, with which
mechanism, and — the part most security pages omit — **where each defence
ends**. Every mechanism named here has an acceptance test in `tests/`; every
limit named here is deliberate and documented rather than discovered.

**Reporting a vulnerability.** Open a GitHub issue titled `[security]` on
this repository. If the finding is sensitive, say only that you have one and
the maintainer will provide a private channel. There is no bug bounty; there
is a commitment to respond, and the audit record
([GAPS_RISKS_AND_UNFINISHED.md](GAPS_RISKS_AND_UNFINISHED.md)) shows that
reported defects get numbered, fixed, and regression-tested rather than
quietly closed.

---

## Trust boundaries

Six kinds of untrusted input cross into this system. Each has a named
mediator, and `python execution.py --audit` fails the build if any module
bypasses one.

| Untrusted input | Enters through | Mediated by |
|---|---|---|
| **Model output** (every token) | provider HTTP responses | the tool loop: one typed tool call per step; `policy.py` screens commands; `fileauth.py` zones file writes; gates decide "done", never the model |
| **Web content** (pages, PDFs, feeds) | `ingest.py`, `discover.py` | source tiering (`sources.py`); material is data in the window, never instructions — the grounding header says so and `test_guardrails` drives hostile material |
| **MCP servers** (third-party tools) | `mcp.py` | catalog + `enable` requires owner review (`policy.py`); every `call` passes `guarded_call` risk classes, approvals, and the effects ledger |
| **Federation peers** (other fleets) | `federation.py` | signed cards, fingerprints, answers labelled untrusted |
| **The control panel's network edge** | `ui.py` HTTP | bearer token, CSRF (Origin + Sec-Fetch-Site), per-route permission table, gate catalogue instead of free-form shell from the network |
| **Packages the agent wants** | `acquire.py` | pinned versions required, typosquat distance checks, sandboxed install, capability probe before trust, owner promotion |

## The six authorities

All power flows through six gateways; scattered checks are the defect this
architecture exists to prevent. Execution (`execution.py`), File
(`fileauth.py`), Credential (`credentials.py`), Model Gateway
(`modelgateway.py`), Effect (`effects.py`), Control Plane
(`controlplane.py`). The invariant tests enumerate every subprocess call site
and every model-provider call site in the tree, and fail on any that bypasses
its authority.

### Why the sixth one exists

An external audit asked the question the first five did not answer between
them. `fileauth` refuses the `write_file` **tool** on control state;
`policy.py` screens a command **string** and says in its own docstring that
it cannot follow the program that string starts. So a role that legitimately
holds `run_command` — practitioner, examiner, ripper and the default role,
because `settings.toml` gives them no `tools` list — could do this:

```
write_file("settings.toml", ...)                        -> REFUSED
run_command('python -c "open('settings.toml','w')..."')  -> exit 0, WROTE IT
```

Measured on the shipped default through a real practitioner task:
`settings.toml`, `prompts/constitution.md` and `approvals/*.json` were all
rewritten while the file tool was being refused in the same transcript.
Switching to `sandbox = "docker"` did not fix it either — the container
bind-mounted the whole expert root **read-write** at `/work`.

`controlplane.py` brackets every model-authored execution and is honest about
the difference between its two backends:

* **docker (and the hosted backends)** — every control path is bound
  read-only inside the container. The write is **prevented**, by the kernel.
* **host, the default** — there is no filesystem boundary to prevent with, so
  the control zone is sealed before the command and verified after: a change
  is **reverted**, the command is reported failed whatever it exited with (so
  no gate can pass on a run that edited the gate), and the attempt is
  recorded in `logs/controlplane.jsonl`. That is detect-and-revert, and this
  document does not call it prevention.

`state.json` is the one declared exception: it is reported and **not**
reverted, because a sibling loop writes it constantly and reverting would
destroy that loop's committed work. The compensating control is in the loop
itself — the next `commit_task` rewrites the running task from memory, so a
task cannot mark itself done by editing the queue.

Every owner-level CLI (`approvals.py grant`, `variants.py promote`,
`training.py register|promote|rollback`, `skills.py promote`,
`acquire.py promote`, `frontier.py adopt`) additionally refuses to run from
inside an agent task. Two independent controls; neither relies on the other.

`tests/test_controlplane.py` is the regression: it crosses every control path
`fileauth` declares with every way a shell changes a file, drives them through
a real loop task as a role that really holds `run_command`, and requires the
bytes to be identical afterwards.

### The second one, which needed no shell

Fixing the first meant reading the neighbourhood, and the neighbourhood had a
worse hole. `candidates.py` — the best-of-N engine — stashes each attempt's
artifacts and restores the winner, and it reached the filesystem with
`os.path.join` rather than through the File Authority. Two consequences, both
reproduced, both reachable with `write_file` **alone**:

* the artifact list comes from the task's own `write_file` STEPS, and a
  *refused* write is still recorded as a step; `candidates/` classified as
  ZONE_ROOT, so a worker could write
  `candidates/<id>/<n>/score.json` claiming `artifacts:
  ["prompts/constitution.md"]`, drop its own constitution beside it, and let
  the loop's `_promote_best_attempt` copy it over the first block of every
  system prompt;
* naming `../../../../OUT.txt` as an artifact made `promote()` write outside
  the expert root — the reproduction created a file in the user's home
  directory.

So the Rule-of-Two roles that are deliberately denied a shell had a write
primitive anyway. Every path in that module now crosses `fileauth.resolve`
with the agent's own rights, its stash destinations are contained against the
stash directory, a refused artifact is *recorded* rather than dropped in
silence, and `score.json` — which decides which attempt wins, gate-first — is
control state.

The same walk found seven more paths the agent could write that are read into
a prompt or a decision: `commons-digest.md`, `missions/*/mission.json`,
`mastery/*/events.jsonl`, `commons/quarantine.md`, `capabilities/`,
`identity.history.jsonl` and the `identity.md.bak-*` rollback copies. All
CONTROL now. `courses/*/sources.json` could not be zoned — the agent runs
`ingest.py add-url` itself, and that records sources — so its **tier is
derived rather than trusted**, recomputed from `classify()` on read, with
genuine owner overrides moved to a control-zoned file beside it.

## The goal contract (anti-reward-hacking)

Acceptance tests for a goal are frozen **before planning**, hashed, and
sealed outside the expert's working root (`contract.py`). The worker's file
tools cannot write contract files (CONTROL zone); a worker that edits them
through the shell anyway produces a **TAMPER** verdict — the seal no longer
matches and nothing is run. Completion is a state transition made by the
harness running those tests, never by the worker's or the judge's say-so.

## What is deliberately NOT defended, and why

Honesty about limits is part of the security posture. These are known,
stated, and in several cases measured:

1. **The `host` sandbox is not isolation.** `policy.py` is a fast,
   inspectable veto on the recognisable spellings of catastrophe — it reads
   a string, and a running program can go anywhere the user can. Real
   containment is `[agent] sandbox = "docker"` (or e2b / daytona /
   cloudflare), where the boundary is the kernel's. The policy module's own
   docstring says this in as many words.
2. **The panel speaks plain HTTP.** It binds to localhost by default and
   must stay there. Exposing it beyond localhost requires TLS termination
   in front (a reverse proxy or the Cloudflare Worker in `deploy/worker/`,
   which fronts the container with Cloudflare's TLS). `preflight.py` flags
   exposure as a BLOCKER when asked.
3. **Bearer token, not identity.** The panel's token is one credential with
   one scope. There is no MFA, no session expiry, no per-user audit
   identity. Multi-user deployments need an identity provider in front;
   `org.py` provides roles once requests are authenticated, not
   authentication itself.
4. **No tenant isolation.** One home is one trust domain. Two organisations
   must run two homes.
5. **Prompt-injection resistance is structural, not semantic.** Untrusted
   material cannot *directly* invoke tools (material is data; tool calls
   come only from the model's own turn), gates still decide "done", and
   commands are screened — but a model persuaded by a hostile document to
   *choose* a harmful-but-policy-legal action is not fully preventable by
   any known mechanism. The mitigations are least privilege (role
   allowlists, Rule of Two: no role holds both untrusted-material reading
   and a shell), effects approvals, and audit trails.
6. **Credential handling is exclusion, not a vault.** Keys live in
   `agent.env` / environment / files; `credentials.py` is the single
   resolver; the sandbox scrubs credential-shaped variables from
   model-visible environments; packaging and backups exclude and are tested
   against planted decoys. There is no rotation, no short-lived issuance,
   no KMS. For a deployment that needs those, put a secret manager in front
   and inject at process start.
7. **Detection over prevention inside the root.** A worker with a shell can
   edit files inside its own root (see 1). What it cannot do is make
   forged state *count*: contracts are sealed outside the root, proof
   levels are recomputed from evidence bound to code hashes, the events
   ledger is append-only, and divergence is surfaced (`contract.replay`,
   `test_contract`).

## Supply chain

The platform is stdlib-only by design — there is no `requirements.txt` to
poison. Optional tools (`ffmpeg`, `pandoc`, `pymupdf`, `yt-dlp`, `docker`)
are detected, never auto-installed. The agent's own acquisition ladder
(`acquire.py`) refuses unpinned versions, checks typosquat distance against
popular names, installs into an isolated prefix inside a sandbox, and
requires an owner-approved promotion before anything is trusted. The
Cloudflare Worker's dependencies are pinned in `deploy/worker/package.json`
with a committed lockfile.

## Incident posture

Every consequential action leaves a row somewhere greppable: task steps in
expert state, external effects in the effects ledger, grant uses in
`org/grant-uses.jsonl`, goal events in `goals/<gid>/events.jsonl`, approvals
in the approvals ledger, packet-level provider calls in the model gateway
ledger. `backup.py` produces verified, credential-free archives; restore
re-verifies every checksum before promoting anything. A wedged loop is
distinguishable from an idle one by heartbeat age.

## Review cadence

This document is updated when the architecture changes, and it carries the
same rule as the rest of the documentation: a claim without a test or a
stated limit behind it does not belong here.
