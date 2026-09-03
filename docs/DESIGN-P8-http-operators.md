# Phase 8 — Safe HTTP/API operators (design, committed before code)

**Status: DESIGN** (flips to BUILT when the preregistered benchmark below is
green in the acceptance suite on all six CI jobs). **Branch:**
`phase8/http-operators`. **Order:** the owner's operator-universe order
after SQL — *"4. Safe HTTP/API operators — with read-after-write
verification and effect semantics"* — reopened by the owner on 2026-09-02
("the agents don't have the hands an agent needs"), after Phase 7.1 and
7.2 closed the correctness backlog. The Reality Phase's remaining steps
(protect `main`, provider smoke, LIFT-001A, LEARN-001, pilot) are not
displaced by this phase; they wait on the owner and a key.

## The problem, stated from evidence

Every state world so far is local: files, tables, SQLite, Git, workbooks.
The work that reaches the outside — creating a ticket, posting a record,
updating a remote row — has no deterministic leaf: a worker can only shell
out to `curl` under `run_command`, a model step no gate observes and no
trajectory compiles, carrying the two dangers the vision contract names:
text that comes back is read as if it were instruction, and a request can
reach any host the sandbox can. The Capability Ledger lists "Generic
HTTP / API" first among the worlds that do not exist.

## What Phase 8 builds — the measurable capability

**`httpstate.py`** — a stdlib-only adapter (`urllib.request`, `json`,
`tomllib`) whose every write declares how it will be read back, and whose
reads are canonical, bounded observations:

```
http_observe {endpoint, path, query?}            GET -> canonical JSON body
http_effect  {endpoint, method, path, body?,     write, then re-observe:
              readback: {path, query?, expect,   the readback must equal
                         pointer?}}              `expect` or the effect is
                                                 REFUSED AS UNVERIFIED
```

In one sentence: **a repeated API workflow becomes a proven procedure whose
replay is model-free and whose every write is verified by an independent
read-back, against endpoints the owner named — never a host the model
chose.**

### Endpoints are owner data, not model text

A worker never names a URL. It names an endpoint from the owner's table:

```toml
[agent.http_endpoints.tickets]
base = "https://api.example.com/v1"
methods = ["GET", "POST", "PUT"]     # DELETE absent = refused
auth_env = "TICKETS_TOKEN"            # the NAME of the variable; the value
                                      # never enters a capture, log or receipt
max_bytes = 1048576
```

Empty table (the default) = every HTTP tool refuses, fail closed. The URL
is the endpoint's base plus a screened relative path (`[A-Za-z0-9_.~-]`
segments, no `..`, no scheme, no `@`, no `?`) plus a screened query
object; the request can never leave the endpoint's host. Credentials are
resolved at call time through the one credential model
(`credentials.resolve`, the same as provider keys: environment, then
`agent.env`), and an endpoint that declares a variable which is unset
**refuses** rather than calling anonymously. Owner endpoints are not
screened against private networks: an owner may legitimately name an
internal service, and the benchmark's fixture is loopback. The screen
that exists for untrusted URLs (ingestion) is a different door.

### Effect semantics: write, then read back, or refuse

`http_effect` sends the write, then performs the declared readback GET and
compares its canonical body (or a JSON-pointer projection) with `expect`.
Equal → the effect stands and the receipt carries both hashes. Not equal,
or the readback fails → **REFUSED AS UNVERIFIED**: the platform cannot roll
a remote write back and says so; the receipt is `verified: false`, the
trajectory action fails, the failure is evidence.

Exactly-once across retries is not reinvented. In the worker tool every
`http_effect` runs under the existing effects ledger (`effects.py`: key =
task lineage × endpoint × tool × sha256(arguments); write-ahead `begin`,
`record` after; a recorded result is **replayed** on a retry instead of
re-sent; a started-and-unresolved effect halts for the owner). The same
key travels as an `Idempotency-Key` header so an API that honours it
cannot double-write even when the local record was lost; an API that
ignores the header may. A procedure replay (no task lineage) sends a key
derived from the canonical arguments, so identical writes are deduped by
an honouring API and the readback still decides.

### External text ≠ instructions

Bodies come back as data: canonical JSON (sorted keys, bounded size, depth
and string length, no control characters, no floats) or refused. The tool
returns the canonical body exactly as a file read would; the compiler
stores only hashes and the `expect` the worker declared. The adapter never
follows a redirect, never sends a credential to a host other than the
endpoint's, never executes anything from a response.

### Predicate and evidence

`http_satisfies {endpoint, path, readback}` — the readback, performed NOW,
equals `expect`. It is the effect a compiled `http_effect` step carries and
the shape an owner suite uses to say "the remote record IS this". A
trajectory records the readback state before and after (`exists`: the GET
answered canonical JSON; `hash`: of that body), and `finish_action`
re-performs the readback rather than believing the tool.

### Wiring

- `operators.py`: `http_satisfies` in `validate_predicate` (needs
  `endpoint` and `readback`) and `observe` (before the file check, like
  `repo_satisfies`; endpoints from the observed root's settings).
- `procedure.py`: `http_effect` joins `DETERMINISTIC_TOOLS`; `_normalize`
  canonicalizes method, path, body, readback; `_snapshot` records the
  readback state; `finish_action` re-checks the readback; `_perform`
  executes; `_compile_aligned` emits `http_satisfies` with no file guard
  (the target is remote); `http-write:<endpoint>` demanded per leaf (v2)
  and per walk (v1); `evaluate` copies `settings.toml` into each arena so
  the endpoint table is the owner's wherever the step runs.
- `loop.py`: the tool pair with capture hooks and the effects ledger;
  `[agent] http_write` allowlist for writes (empty = none); the route
  grant adds `http-write:` for the owner's endpoints.
- `settings.toml`: `http_write = []` declared; an endpoint example
  commented. `harness` tool list grows to 16.

## Benchmark that must pass before this becomes permanent

`tests/test_http_operators.py`, against a local stdlib `http.server`
fixture with an in-memory store that honours `Idempotency-Key`. Nothing
touches the internet.

1. **Owner-named hosts only.** An unknown endpoint, an escaping path, a
   scheme in a path, a disallowed method and an empty endpoint table each
   refuse before any request; the fixture records nothing for them.
2. **Read-after-write.** An effect whose readback equals `expect` stands;
   one whose readback differs is REFUSED AS UNVERIFIED and the reply never
   begins with "ok"; a readback that answers 404 refuses.
3. **Idempotency.** The same effect in the same lineage is replayed from
   the effects ledger; the fixture sees one PUT; the ledger holds the key.
4. **Credentials never leak.** The bearer reaches the fixture and nothing
   else: not the tool output, not the effects ledger; the settings carry
   only the variable's name; a redirect is refused, not followed.
5. **Data, not orders.** Instruction-shaped response text comes back as a
   bounded data string; an oversized body refuses.
6. **Authority.** `http-write:<endpoint>` is demanded per leaf (v2) and per
   walk (v1) before any request; the worker tool refuses a write outside
   `[agent] http_write`; observation needs nothing more.
7. **End to end.** Two gated record syncs compile a candidate with typed
   inputs (path, body, readback) and the endpoint literal; an owner-sealed
   fresh suite (edge: empty name, unicode tags) takes it to PROVEN; a
   silent worker replays record nine with zero model calls under an
   independent gate that reads the fixture directly, with one PUT carrying
   an idempotency key.
8. **Registration.** Tools, predicate, settings keys, harness list,
   evidence, proof and prose counts.

## Claim envelope (per docs/DESIGN-P6.1)

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| owner-named hosts | endpoint table validated on every call | a host the owner named that is itself hostile | fixture request log |
| verified effect | the readback GET answers canonical JSON | a write whose readback matches by coincidence; a remote that changed after the readback (TOCTOU is the readback's window, stated) | independent GET by the gate |
| no double write | the API honours `Idempotency-Key`, or the retry is in the same lineage | an API that ignores the header on a retry with a lost local record | fixture PUT count |
| no credential leak | the credential is a bearer from a named variable | a response body that echoes the bearer (data, returned as data — the model would see it); non-bearer schemes | grep of output and ledger |
| data not orders | canonical JSON | prompt injection remains "not a boundary" (REMEDIATION); the body is bounded, not neutralised | reply shape |

## What this phase does NOT claim

No real API, no real model: the fixture is local and the workers are
mocks. No rollback of remote writes. No OAuth, cookies, sessions, forms,
streaming or non-JSON bodies. No browser: the audit's item 5 remains after
this and is not approached by recording clicks. No SSRF screen on owner
endpoints, by design and stated.
