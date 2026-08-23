# System Diagrams

Diagrams reconstructed from source during the forensic audit. Where a diagram
shows a defect, it is marked and cross-referenced to
`GAPS_RISKS_AND_UNFINISHED.md`. Nothing here is aspirational — these describe
what the code does, including where that differs from what the docs say.

---

## 1. Task lifecycle

```mermaid
flowchart TD
    Q["task queued<br/>state.json"] --> C{"claim_task<br/>under _state_lock"}
    C -->|"atomic queued->running"| CTX["context.compile"]
    C -->|"already claimed"| SKIP["skipped"]

    CTX --> M1["per-source token budgets"]
    M1 --> M2["manifest written beside transcript<br/>(what was included, what was cut, why)"]
    M2 --> CALL["call_model(role)"]

    CALL --> R{"route = auto?"}
    R -->|yes| RT["modelrouter.choose<br/>cheapest clearing the bar"]
    R -->|no| ST["static provider/model"]
    RT --> ATT
    ST --> ATT["attempts[]:<br/>escalate -> routed -> static -> fallback"]
    ATT --> BO["exponential backoff x5<br/>permanent_net_error() short-circuits"]

    BO --> TOOL{"tool call"}
    TOOL --> AT["allowed_tools(role) gate"]
    AT -->|"denied"| TERR["tool error, counted<br/>apart from model errors"]
    AT -->|"allowed"| EXEC["dispatch"]
    EXEC --> CMP{"context near limit?"}
    CMP -->|yes| COMPACT["compact_context<br/>archive middle VERBATIM first"]
    COMPACT --> TOOL
    CMP -->|no| TOOL

    TOOL -->|"finish_task"| GATE["check_done()<br/>shell=True"]
    GATE -->|pass| COMMIT["commit_task<br/>+ modelrouter.record"]
    GATE -->|fail| FM["_file_memory()"]

    FM --> F1["record failure"]
    FM --> F2["cases.open_case / RECURRED"]
    FM --> F3["gotchas.file"]
    FM --> F4["confidence.score -> band"]
    F4 --> ESC{"escalate?"}
    ESC -->|"gate failure"| CAND["candidates: n=1 -> 3 -> 5"]
    ESC -->|"budget hit"| STOP["breaker outranks policy"]
    CAND --> Q
```

**Note on the gate.** `check_done` is drawn deliberately at the end of the
trusted path. It runs with `shell=True`, executing commands the *model* wrote
into `spec.md`, and it does not pass through `policy.py` or `sandbox.py`. See
diagram 2.

---

## 2. Trust boundaries — where controls apply, and where they do not

```mermaid
flowchart LR
    subgraph UNTRUSTED["UNTRUSTED INPUT"]
        DOC["ingested documents<br/>PDFs, URLs, video"]
        MODEL["model output"]
        PEER["A2A peers / MCP servers"]
    end

    subgraph MARKED["DATA MARKING (not a security boundary)"]
        FENCE["_read_block<br/>&lt;&lt;&lt;FILE-CONTENT&gt;&gt;&gt; fences<br/>grounding prompt forbids obeying"]
    end

    subgraph MECH["MECHANICAL CONTROLS"]
        TOOLS["allowed_tools(role)<br/>capability removal"]
        PATH["_safe_path<br/>containment"]
        POL["policy.py<br/>command screening"]
        SBX["sandbox.py<br/>env scrub + isolation<br/>FAILS CLOSED"]
        APPR["approvals.py<br/>operator gate"]
    end

    subgraph HOST["HOST"]
        ENV["full environment<br/>incl. provider keys"]
        FS["filesystem"]
    end

    DOC --> FENCE
    PEER --> FENCE
    FENCE --> MODEL
    MODEL --> TOOLS
    TOOLS --> PATH
    TOOLS --> POL
    POL --> SBX
    SBX --> APPR
    APPR --> FS
    SBX -.->|"scrubbed: sees ABSENT"| ENV

    MODEL ==>|"writes CHECK: into spec.md"| GATE
    GATE["check_done / verify.py<br/>shell=True"]
    GATE ==>|"BYPASSES policy + sandbox"| ENV

    style GATE fill:#c62828,color:#fff
    style ENV fill:#4e342e,color:#fff
```

**The thick red path is P1-1, and it is reproduced.** In an isolated test the
gate path saw a planted environment marker; the normal `run_command` path saw
`ABSENT`. Every control in the middle column applies to the work path and none
of them applies to the verification path.

**On the fence.** `_read_block` is drawn *outside* the mechanical controls on
purpose. It is a prompt instruction. It raises the cost of a naive injection
and prevents nothing.

---

## 3. Memory architecture

```mermaid
flowchart TD
    subgraph KINDS["MEMORY KINDS (routed, not piled)"]
        COM["commons<br/>shared fleet knowledge"]
        CRS["course + atoms<br/>studied material"]
        GOT["gotchas<br/>learned failures"]
        SKL["skills/<br/>procedural playbooks"]
        PRM["premise<br/>what is assumed"]
        SLF["selfmodel<br/>what this agent IS"]
        CSE["cases<br/>open / fixed / RECURRED"]
    end

    ROUTER["memrouter<br/>per-role routing rules"]
    KINDS --> ROUTER

    ROUTER -->|"student rule:<br/>REMOVE ONLY"| CB["CLOSED BOOK<br/>exam isolation"]
    ROUTER --> CC["context.compile"]

    CC --> BUD["per-source token budget"]
    BUD --> TRIM["overflow trimmed<br/>+ pointer to read the rest"]
    TRIM --> MAN["compile manifest on disk"]
    MAN --> WIN["the window the agent sees"]

    WIN --> OVER{"approaching limit?"}
    OVER -->|yes| ARCH["archive.jsonl<br/>middle appended VERBATIM"]
    ARCH --> CLR["tool results cleared"]
    CLR --> HF["HARNESS FACTS retained"]
    HF --> WIN

    SRC["sources.py<br/>authority tier 1-4"] --> CUR["curriculum.py"]
    CUR -->|"authority first"| ORD["study order"]
    CUR -->|"covers_same_ground"| DUP["near-duplicate -> skim"]
    CUR -->|"covers_mission<br/>(containment)"| GAP["gaps.md -> idle loop tasks"]
    ORD --> CRS
    SRC --> CFL["conflicts.py<br/>4 verdicts"]
    CFL --> STD["standards<br/>(defeated claims excluded)"]
```

**Closed-book has two layers of different strength.** The `memrouter` rule is
code and can only remove sources. The second layer — `[roles.student] tools`
omitting `read_file` — is *configuration*, and no test asserts it (P2-3).

---

## 4. Verification and governance stack

```mermaid
flowchart TD
    ART["artifact produced"] --> STACK

    subgraph STACK["DETERMINISTIC VERIFIERS — no model judges itself"]
        G1["check_done<br/>hard binary gate"]
        G2["citecheck<br/>cited / defined ratio"]
        G3["designcheck<br/>blockers then warnings"]
        G4["conflicts.check<br/>contested points asserted"]
        G5["verify.py<br/>CHECK commands passing"]
        G6["memcheck<br/>memory integrity"]
    end

    STACK --> SCORE["candidates.score()<br/>composite"]
    SCORE --> BEST["best_of(n) -> winner<br/>+ candidate_chosen log<br/>with score breakdown"]
    BEST --> EXAM["examiner role<br/>independent pass"]
    EXAM --> CONF["confidence.py<br/>8 weighted signals"]
    CONF --> BAND{"band"}
    BAND -->|">= 0.75 high"| SHIP["ship"]
    BAND -->|"0.45-0.75 medium"| MORE["more_compute"]
    BAND -->|"< 0.45 low"| ESCA["escalate"]

    MORE --> N["n: 1 -> 3 -> 5<br/>ESCALATION map"]
    N --> BUDGET{"max_task_usd /<br/>daily_budget_usd"}
    BUDGET -->|"exceeded"| BRK["breaker outranks policy"]
    BUDGET -->|"within"| SCORE

    style STACK fill:#1b5e20,color:#fff
```

The green block is the build's strongest design decision: competing attempts
are scored by deterministic modules that already existed, not by asking a model
which attempt it prefers. The limitation is that these verifiers measure
**shape** (is a citation present and well-formed) rather than **truth** (does
the citation support the claim).

---

## 5. Concurrency — and the ownership hole

```mermaid
sequenceDiagram
    participant A as Process A
    participant L as lockfile
    participant B as Process B
    participant C as Process C

    A->>L: O_EXCL create, write getpid()
    Note over A: enters critical section
    Note over A,L: stall > 8s<br/>(OneDrive sync / AV / suspend)
    B->>L: FileExistsError
    B->>L: mtime age > stale(8s) -> os.remove
    B->>L: O_EXCL create, write getpid()
    Note over A,B: BOTH inside the critical section
    A->>L: finally: os.remove(lock)
    Note over A,L: deletes B's lockfile,<br/>never checked ownership
    C->>L: O_EXCL create -> succeeds
    Note over B,C: BOTH inside the critical section
```

**P1-2.** Both `locks.holding()` and `loop._state_lock()` write `os.getpid()`
into the lockfile and **never read it back**. The data needed to detect this is
on disk and unused. These locks protect `effects.jsonl`, `approvals.json`,
`prospective.json`, `skills/graph.json` and `state.json`.

`locks.py` has **no test at all** — `tests/test_lock.py` tests a different
mechanism, the course lock inside `loop.py` (P1-3).

---

## 6. Module topology — the hub

```
                          ┌──────────────────────────┐
                          │        loop.py           │
                          │  2,080 lines             │
                          │  imported by 22 modules  │
                          │                          │
                          │  task schema             │
                          │  claim protocol          │
                          │  _state_lock             │
                          │  _safe_path              │
                          │  check_done   ◄── P1-1   │
                          │  call_model              │
                          │  compact_context         │
                          │  tool dispatch           │
                          │  _file_memory            │
                          └────────────┬─────────────┘
                                       │
      ┌──────────────┬─────────────────┼─────────────────┬──────────────┐
      │              │                 │                 │              │
 harness-loop     memory          governance        control-plane   work-systems
   9 modules     12 modules       11 modules         13 modules      6 modules
      │              │                 │                 │              │
 harness        memory/skills     variants           ui/chief        goal
 policy         commons/recall    approvals          doctor          workflows
 effects        gotchas/premise   replay             bootstrap       consult
 locks   ◄─P1-2 sources           benchmark          preflight       prospective
 checkpoint     conflicts         verify   ◄── P1-1  backup          routines
 sandbox ◄─P1-1 standards         citecheck          providers       research
 context        selfmodel         memcheck           toolbox
 memrouter      curriculum        designcheck        mcp    ◄── P2-1
                cases             candidates         federation
                                  evidence           trace/uicards
                                  confidence         modelrouter ◄── P1-4
```

Everything except `loop.py` is small and single-purpose. That concentration is
the build's principal maintainability risk: it is the file most likely to
produce an unanticipated effect when changed, and the file with the most
reasons to change.

---

## 7. Control plane

```mermaid
flowchart LR
    OWNER["owner"] --> UI["ui.py + ui.html<br/>2,698-line SPA"]
    OWNER --> CLI["CLI: chief, fleet, loop,<br/>doctor, preflight, backup,<br/>curriculum, evidence, ..."]

    UI --> API["/api/systems<br/>/api/preflight<br/>/api/backup<br/>/api/curriculum<br/>PUT /api/experts/&lt;s&gt;/file"]
    API --> SAN["component sanitisation<br/>9 traversal vectors tested,<br/>none escaped"]
    UI --> SSE["SSE event stream<br/>panel watches, never polls"]
    UI --> PAL["Ctrl/Cmd-K palette<br/>each entry shows the CLI equivalent"]

    API --> FLEET["experts/&lt;slug&gt;/"]
    CLI --> FLEET
    SSE -.-> FLEET

    FLEET --> E1["identity.md, prompts/, settings"]
    FLEET --> E2["state.json, logs/, memory"]
    FLEET --> E3["courses, atoms, skills/"]

    REMOTE["remote access"] --> TOK["token auth"]
    TOK --> UI

    style SAN fill:#1b5e20,color:#fff
```

The green node is a **negative** finding worth recording: I hypothesised a path
traversal in the upload endpoint and attacked it with nine vectors including
Windows drive letters, `../`, `..\`, absolute POSIX paths and dot-collapse.
Every one resolved inside the expert root. The control holds.

---

## Diagram legend

| Marking | Meaning |
|---|---|
| Red node / thick edge | Confirmed defect, cross-referenced to a P-number |
| Green node | Control verified to hold under attack |
| `◄── P1-x` | Module carries the referenced finding |
| Dotted edge | Scrubbed, filtered, or read-only relationship |

---

## 8. The CSRF → RCE chain (reproduced end-to-end)

The audit's most severe finding. Every edge below was executed against an
isolated sandbox panel with synthetic values.

```mermaid
flowchart TD
    OP["operator has the panel open<br/>127.0.0.1:7777 · default settings"]
    EVIL["operator visits ANY other web page<br/>in the same browser"]

    EVIL --> POST["cross-origin POST<br/>Content-Type: text/plain<br/>(CORS simple request - NO preflight)"]

    POST --> AUTH{"ui.py _authed()"}
    AUTH -->|"token is None by default<br/>-> return True"| ROUTE["route dispatched"]
    AUTH -.->|"no Origin check"| X1["no Referer check"]
    AUTH -.-> X2["no Sec-Fetch check"]
    AUTH -.-> X3["no Content-Type check"]

    ROUTE --> T1["POST /api/experts<br/>-> created"]
    ROUTE --> T2["POST /api/experts/x/task<br/>done_check taken FROM THE BODY"]
    ROUTE --> T3["POST /api/experts/x/start<br/>-> loop process spawned"]

    T2 --> ADD["loop.add_task(done_check=...)"]
    ADD --> QUEUE["state.json"]
    T3 --> LOOP["loop runs the task"]
    QUEUE --> LOOP
    LOOP --> FIN["model calls finish_task"]
    FIN --> GATE["check_done()<br/>subprocess.run(cmd, shell=True)"]

    GATE --> RCE["ARBITRARY COMMAND EXECUTED<br/>on the operator's machine"]
    GATE -.->|"never consulted"| POL["policy.py"]
    GATE -.->|"never consulted"| SBX["sandbox.py"]
    GATE -.->|"never consulted"| SG["skills.script_guard"]
    GATE --> ENV["full parent environment<br/>incl. agent.env keys"]

    OP -.-> EVIL

    style AUTH fill:#c62828,color:#fff
    style GATE fill:#c62828,color:#fff
    style RCE fill:#7f0000,color:#fff
    style ENV fill:#4e342e,color:#fff
```

**Proof obtained:** the marker file `RCE via cross-origin POST done_check` was
written by the host after three cross-origin POSTs. `intention`, `workflow`,
and `wake` accept `done_check` by the same route, so the payload can also be
stored and fired later.

---

## 9. The secondary-path map — every control and what goes around it

This is the audit's central structural finding, drawn as one picture. Solid
green = the path the control's author defended. Red dashed = a path that
reaches the same operation without passing the control.

```mermaid
flowchart LR
    subgraph EXEC["EXECUTING A COMMAND"]
        RC["run_command"] ==>|guarded| G1["policy + sandbox + script_guard"]
        CD["check_done"] -.->|BYPASS| OPX["shell=True, full env"]
        VF["verify.py:59"] -.->|BYPASS| OPX
        GL["goal.py:261"] -.->|BYPASS| OPX
        BM["benchmark.py:84"] -.->|BYPASS| OPX
        TB["toolbox.py:85"] -.->|BYPASS| OPX
        G1 --> OPX
    end

    subgraph FS["WRITING A FILE"]
        RF["read_file / write_file"] ==>|guarded| G2["_safe_path"]
        GO["gotchas (course)"] -.->|BYPASS| DISK["filesystem"]
        CN["conflicts (course)"] -.->|BYPASS| DISK
        CU["curriculum (course)"] -.->|BYPASS| DISK
        CA["candidates (course)"] -.->|BYPASS| DISK
        IN["ingest fetch_url file://"] -.->|BYPASS| DISK
        G2 --> DISK
    end

    subgraph CRED["RESOLVING A SECRET"]
        L["loop.py: env + agent.env<br/>+ inline api_key + api_key_file"] ==> KEY["the key"]
        P["providers.py"] -.->|"2 of 4 sources"| KEY
        C["chief.py"] -.->|"1 of 4"| KEY
        B["backup.py excl."] -.->|"misses 2"| KEY
        PK["package.py excl."] -.->|"misses 3"| KEY
        SP["_safe_path guard"] -.->|"misses 2"| KEY
    end

    subgraph SPEND["SPENDING MONEY"]
        S1["loop.py:1136 main step"] ==>|counted| BUD["max_task_usd / daily_budget"]
        S2["loop.py:1058 compaction"] -.->|BYPASS| CALL["call_model"]
        S3["replay.py:83"] -.->|BYPASS| CALL
        S4["benchmark.py:112"] -.->|BYPASS| CALL
        BUD --> CALL
    end

    style OPX fill:#c62828,color:#fff
    style DISK fill:#c62828,color:#fff
    style KEY fill:#4e342e,color:#fff
    style CALL fill:#c62828,color:#fff
```

**Count:** command execution — 1 guarded path, 5 unguarded. Filesystem writes —
1 guarded, 5 unguarded. Credential resolution — 6 subsystems, 4 sources, no two
agreeing. Spend — 1 counted, 3 uncounted.

**The shape of the fix.** Not seventeen patches: three gateways — one to
execute a command, one to write a file, one to resolve a secret — that every
caller must pass through. That single change retires most of this report.

---

## 10. Controls verified to hold under attack

Reported with equal weight, because an audit that draws only failures is not
measuring itself.

```mermaid
flowchart TD
    A1["zip archive with 4 traversal members<br/>../ ..\ sub/../../"] --> Z["ingest.unpack_archive<br/>realpath + startswith(dest+sep)"]
    Z --> ZR["ALL 4 REFUSED<br/>only the legitimate member extracted"]

    A2["9 upload vectors incl.<br/>Windows drive letters, ....//"] --> U["ui.py PUT /file sanitiser"]
    U --> UR["ALL 9 CONTAINED<br/>inside the expert root"]

    A3["model-authored card content<br/>+ arbitrary file content"] --> E["ui.html esc()<br/>& < > quote apostrophe"]
    E --> ER["NO XSS<br/>75 innerHTML sites all escape at insertion"]

    A4["is a key stored in settings.toml?"] --> S["providers.py:80 contract"]
    S --> SR["NO - api_key_env names only<br/>(the documented model is sound)"]

    A5["can the model poison the commons?"] --> C["commons at fleet home<br/>_safe_path confines to expert root"]
    C --> CR["NO - note() has no product caller,<br/>no UI write endpoint"]

    style ZR fill:#1b5e20,color:#fff
    style UR fill:#1b5e20,color:#fff
    style ER fill:#1b5e20,color:#fff
    style SR fill:#1b5e20,color:#fff
    style CR fill:#1b5e20,color:#fff
```

One hypothesis in this set was mine and wrong: I flagged `ui.html:1305-07` as
an unescaped interpolation and found the call site escapes it one level up
(`${esc(when(x.when))}`). Recorded as a falsified hypothesis, not a finding.
