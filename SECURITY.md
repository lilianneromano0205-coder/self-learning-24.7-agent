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

## The five authorities

All power flows through five gateways; scattered checks are the defect this
architecture exists to prevent. Execution (`execution.py`), File
(`fileauth.py`), Credential (`credentials.py`), Model Gateway
(`modelgateway.py`), Effect (`effects.py`). The invariant test enumerates
every subprocess call site in the tree and fails on any that bypasses the
Execution Authority.

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
