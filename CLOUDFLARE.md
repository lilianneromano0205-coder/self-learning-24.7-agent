# Expert Fleet on Cloudflare — a compatibility study

**Question asked:** can this platform run on Cloudflare, which of their products
fit, and what does it cost?

**Short answer:** one part of Cloudflare is a drop-in win *today* and is
already wired up and tested in this repository. One part can host the agent
loop, with a caveat that would silently reintroduce the worst defect this
project has ever had. And one part — the one most people mean when they say
"run it on Cloudflare" — **cannot run this platform at all**, for reasons that
are structural rather than fixable.

---

## 0. How this research was done, and why you should trust it

You asked for real research and for the method to be stated. Here it is.

**Primary sources only, fetched live.** Every number and quote below comes
from `developers.cloudflare.com` fetched during this session, not from
memory. Cloudflare publishes an `llms.txt` index and a `/index.md` markdown
form of every documentation page; those are what was read, so the text quoted
is the text Cloudflare publishes rather than a summary of it. The raw files
are in `.firecrawl/` (git-ignored) and can be re-fetched:

```bash
curl -sS https://developers.cloudflare.com/llms.txt
curl -sS https://developers.cloudflare.com/containers/pricing/index.md
curl -sS https://developers.cloudflare.com/workers/languages/python/stdlib/index.md
```

**The product list is theirs, not mine.** The catalog in §2 is
`developers.cloudflare.com/llms.txt` — Cloudflare's own index, **106 products
across 9 categories** — rather than a list I recalled. That matters because
the interesting fits (Sandbox SDK, Artifacts, Agent Memory) are products I
would not have thought to look for.

**Claims about *our* side were derived from the code, not remembered.** The
subprocess count, the lock primitives, the credential list and the capability
inventory below were produced by running the platform's own tools
(`toolbox.py`, `doctor.py`, `execution.py --audit`) and by grepping the
source. Where this document says "20 modules use subprocess", that number
came from a command, and the command is shown.

**The central compatibility claim was tested, not asserted.** §4.1 claims
Workers AI works with this platform unmodified. That was verified by pointing
the *real, unmodified* provider client at a loopback server on Cloudflare's
documented URL shape and inspecting the request it produced. The result is
below, and the harness that produced it (`tests/fake_provider.py`) is the same
one the acceptance suite uses.

**What this method cannot tell you.** No Cloudflare account was used. Nothing
below was executed against Cloudflare's actual infrastructure — no container
was started, no Neuron was spent, no token exists. Everything marked
**VERIFIED** was tested locally against their documented contract; everything
marked **DOCUMENTED** is their claim, read carefully, and not independently
confirmed. That distinction is kept on every row that matters.

---

## 1. What this platform needs to run end to end

Before asking where it can run, here is what it needs *anywhere*. Produced by
`python doctor.py` and `python toolbox.py` on a clean install.

### Tier 0 — nothing at all

`python demo.py` and `python tests/run_all.py` run with **zero** keys, zero
installs, zero network. Python 3.11+ and the standard library. This is not a
degraded mode; it is the whole platform with scripted models instead of real
ones.

### Tier 1 — one API key, and the agents think

| Need | Why | Without it |
|---|---|---|
| **One provider key** in `agent.env` | every model call | agents cannot think; everything else still runs |

One key is genuinely enough — `settings.toml` ships with five providers
configured and any single one runs all nine roles. Options, cheapest first:

| Provider | Env var | Note |
|---|---|---|
| **Cloudflare Workers AI** | `CLOUDFLARE_API_TOKEN` | **10,000 Neurons/day free, forever** — see §4.1 |
| NVIDIA NIM | `NVIDIA_API_KEY` | free tier |
| Hugging Face | `HF_TOKEN` | free tier |
| Groq | `GROQ_API_KEY` | free tier, very fast |
| DeepSeek | `DEEPSEEK_API_KEY` | paid, cheap, the shipped default |
| OpenRouter | `OPENROUTER_API_KEY` | paid, one key for many models |

### Tier 2 — optional capabilities, each detected at runtime

The platform reports what this machine can do and **an agent that cannot read
a PDF says so instead of inventing its contents**. Nothing here is required.

| Capability | Needs | Currently | Without it |
|---|---|---|---|
| `web_fetch`, `site_crawl` | stdlib | ✅ READY | — |
| `recall_memory`, `verify_spec` | stdlib | ✅ READY | — |
| `pdf_text` | pymupdf *or* pdftotext | ✅ READY | PDFs unreadable, and said so |
| `audio_chunk` | ffmpeg | ✅ READY | — |
| `git`, `node_js` | git, node | ✅ READY | — |
| `containers` | docker | ✅ READY | falls back to policy-gated host execution |
| `docs_convert` | pandoc or markitdown | ❌ MISSING | .docx/.pptx/.epub not ingestible |
| `video_download` | yt-dlp | ❌ MISSING | no YouTube ingestion |
| `transcribe` | ffmpeg + `GROQ_API_KEY` | ❌ MISSING | no audio → text |
| `vision` | `OPENROUTER_API_KEY` etc. | ❌ MISSING | no image understanding |

```bash
pip install pymupdf yt-dlp          # closes docs_convert partly, and video
winget install pandoc               # closes docs_convert fully
```

### Tier 3 — running it unattended

`python preflight.py` is the authority here. On this install its only blocker
is *"no backups"*, which is correct for a fresh fleet.

| Need | Why |
|---|---|
| **A backup schedule** | `python backup.py create` — preflight blocks without one |
| **A panel token** | auto-generated when exposed; `0600` via the Credential Authority |
| **A reverse proxy or tunnel** | the panel is plain HTTP with no TLS — see §5.3 for Cloudflare Tunnel |
| **Spend caps at the provider** | the platform's daily breaker is a second line of defence, not the first |

---

## 2. Cloudflare's complete product surface

From their own index: **106 products, 9 categories**. The full developer
platform (38 products) is listed here because you asked for every product;
the rest of the catalog (application performance, application security,
Cloudflare One, network security, consumer) is real but has no bearing on
whether an agent platform runs, so it is summarised rather than enumerated.

**Developer platform — compute**
`Workers` · `Workers AI` · `Durable Objects` · `Containers` · `Dynamic Workers`
· `Workflows` · `Pages` · `Sandbox SDK` · `Cloudflare for Platforms`

**Developer platform — AI**
`AI` · `AI Gateway` · `AI Search` (managed RAG) · `Agents` · `Agent Memory`
· `Agent Lee` · `Vectorize` · `Browser Run` · `Cloudflare Wallets`

**Developer platform — storage & data**
`R2` · `R2 Data Catalog` · `R2 SQL` · `D1` (serverless SQLite) · `KV` ·
`Hyperdrive` · `Queues` · `Pipelines` · `Artifacts` · `Images` · `Stream`

**Developer platform — other**
`Workers VPC` · `Email Service` · `Flagship` (feature flags) · `Realtime` ·
`MoQ` · `Zaraz` · `Privacy Gateway` · `Privacy Pass` · `Privacy Proxy`

**The rest of the catalog**, one line each: *Application performance* (Argo,
Cache/CDN, China Network, …), *Application security* (WAF, Bot Management,
DDoS, Turnstile, …), *Cloudflare One* (Zero Trust, Access, Tunnel, Gateway,
Browser Isolation, …), *Network security* (Magic Transit, Magic WAN, …),
*Core platform* (DNS, SSL/TLS, Load Balancing, Logs, …), *Consumer* (1.1.1.1,
WARP). Of these, only **Cloudflare Tunnel** matters to us (§5.3).

---

## 3. The three questions that decide everything

### 3.1 Can the agent loop run on Workers? **No. Structurally.**

| Workers limit | Value | What this platform does |
|---|---|---|
| Memory | **128 MB** | the loop is comfortable, but see below |
| CPU per request | **10 ms free / 5 min max paid** | a task runs for minutes to hours |
| Runtime | V8 isolate (JS/WASM) | **20 modules call `subprocess`** |
| Filesystem | none | **an expert *is* a directory** |

Python Workers do not rescue this. Cloudflare's own stdlib page says
`threading` and `multiprocessing` "can be imported, but are not functional
due to the limitations of the WebAssembly VM", there is no `subprocess` at
all, and the filesystem is in-memory and **"lost when the Worker isolate is
destroyed"**.

Expert Fleet's entire thesis is that a gate is *a command the platform runs*.
A runtime with no process execution cannot run a gate. This is not a porting
problem; it is the removal of the platform's central mechanism.

**Verdict: the loop will never run on Workers, and should not.**

### 3.2 Can the loop run in Cloudflare Containers? **Yes — with one serious caveat.**

Containers give a real Linux container with a real filesystem, orchestrated by
a Worker. Instance types (**DOCUMENTED**):

| Type | vCPU | Memory | Disk |
|---|---|---|---|
| lite | 1/16 | 256 MiB | 2 GB |
| basic | 1/4 | 1 GiB | 4 GB |
| standard-1 | 1/2 | 4 GiB | 8 GB |
| standard-4 | 4 | 12 GiB | 20 GB |

**The caveat, in Cloudflare's words:** *"All disk is ephemeral. When a
Container instance goes to sleep, the next time it is started, it will have a
fresh disk as defined by its container image."* Default `sleepAfter` is **10
minutes** of inactivity.

For a platform whose architecture is "an expert is a directory" — identity,
courses, skills, failures, missions, state.json, logs — ephemeral disk means
**the agent forgets everything** on every sleep. That is the one thing this
platform exists to prevent.

Cloudflare documents an escape hatch: **mount R2 as a filesystem with FUSE**,
and explicitly names "persisting user state" and "bootstrapping agents or
sandboxes" as use cases. But they also warn: *"Object storage is not a
POSIX-compatible filesystem... you should not expect native SSD-like
performance."*

**That warning is disqualifying for our state directory, and here is exactly
why.** This platform's correctness rests on two POSIX guarantees:

```
loop.py:366   fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)   # the mutex
locks.py:47   fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
loop.py:150   tmp + fsync + os.replace                                    # every ledger write
```

Neither is atomic on an S3-backed FUSE mount: `O_EXCL` is typically
check-then-create, and `rename` is copy-then-delete. Putting `state.json` on
R2-FUSE would silently reintroduce **U15** — two loops running one task, six
queued and fourteen completions logged — the worst defect this project has
had, which took a loaded CI runner to find and would be even harder to see
across a network filesystem.

**The correct architecture is not FUSE.** It is:

- **container local disk** = working state. Fast, POSIX-correct, the mutex and
  atomic writes behave exactly as tested.
- **R2** = durable memory. `backup.py create` on a schedule and before sleep;
  `backup.py restore` on container start.

That path uses machinery this repository already has and already tests:
`test_package.py` proves an archive round-trips byte-for-byte, refuses a
damaged archive, and — the part that matters — **drives a restored expert
through a gated task in its new location**, because "deployment is a location
choice, not a different expert format."

**Verdict: viable, using backup/restore rather than a network filesystem.**

### 3.3 Is Cloudflare a good *model provider*? **Yes, and it already works.**

See §4.1. This is the immediate, no-caveat win.

---

## 4. What works today

### 4.1 Workers AI as a provider — **VERIFIED**

Workers AI exposes an OpenAI-compatible endpoint:

```
https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions
Authorization: Bearer {api_token}
```

That is precisely the contract `loop.py`'s provider client already speaks. To
prove it rather than claim it, the **unmodified** client was pointed at a
loopback server on Cloudflare's URL shape:

```
REQUEST THE UNMODIFIED CLIENT SENT
  path  : /client/v4/accounts/abc123def/ai/v1/chat/completions
  auth  : Bearer cf-to...   (never printed in full)
  model : @cf/meta/llama-3.3-70b-instruct-fp8-fast

MATCHES CLOUDFLARE'S DOCUMENTED ENDPOINT EXACTLY: True
```

**Zero code changes.** `settings.toml` now ships the provider block, commented
out pending an account id:

```toml
[providers.cloudflare]
base_url = "https://api.cloudflare.com/client/v4/accounts/ACCOUNT_ID/ai/v1"
api_key_env = "CLOUDFLARE_API_TOKEN"
```

**The free allocation is real and it is standing**, not a trial: *"Our free
allocation allows anyone to use a total of 10,000 Neurons per day at no
charge."* Beyond that, $0.011 per 1,000 Neurons.

What 10,000 Neurons/day buys, using this platform's own **measured** context
window (1083 tokens, from the 120-task endurance soak) and a 500-token reply:

| Model | Neurons/step | **Free steps/day** |
|---|---|---|
| `@cf/meta/llama-3.2-1b-instruct` | 11.8 | **848** |
| `@cf/meta/llama-3.2-3b-instruct` | 20.3 | **493** |
| `@cf/meta/llama-3.1-8b-instruct-fp8-fast` | 21.9 | **456** |

A gated task in this platform runs 2–9 steps. **~450 free steps/day is roughly
50–200 completed tasks per day, indefinitely, for nothing.**

Available models include `@cf/meta/llama-3.3-70b-instruct-fp8-fast`,
`@cf/meta/llama-4-scout-17b-16e-instruct`, `@cf/deepseek-ai/deepseek-v4-pro`,
`@cf/moonshotai/kimi-k2.6`, `@cf/mistralai/mistral-small-3.1-24b-instruct` —
62 models in the pricing table.

**Caveat, stated plainly:** this is verified against the *documented contract*,
not against Cloudflare's servers. No token exists yet. `python loop.py check`
remains the only live probe, and until it runs with a real token this is
"provably correctly shaped", not "provably working".

### 4.2 AI Gateway — one URL, and the platform gets observability

AI Gateway sits in front of any provider and adds caching, rate limiting,
retries, model fallback, per-request cost analytics and full prompt logging —
*"it only takes one line of code to get started."* For this platform it is a
`base_url` change and nothing else, and `settings.toml` ships that block too.

Worth noting what it duplicates: Expert Fleet already has its own retry
ladder, provider failover, cost metering and daily breaker. AI Gateway would
be **a second, independent view** of the same facts — which is genuinely
useful for the same reason the proof system is: an independent mechanism
producing the evidence.

### 4.3 R2 as the fleet's durable memory

10 GB storage free per month, 1 M Class A operations free, and **egress is
free** — which matters for a backup target you will restore from often. R2 is
S3-compatible, so `backup.py`'s archives can be pushed with any S3 client.

**Gap to build:** `backup.py` writes local archives and has no S3 target. This
is a small, well-scoped addition (§6).

---

## 5. Everything else, ranked by whether it earns its place

| Product | Fit | Assessment |
|---|---|---|
| **Workers AI** | ★★★★★ | Works today, free tier, verified. Do this first |
| **R2** | ★★★★★ | Backup target. Free egress. Needs a small writer |
| **AI Gateway** | ★★★★☆ | One URL. Independent cost/latency evidence |
| **Containers** | ★★★★☆ | Can host the loop. No free tier. ~$12/mo (§5.1) |
| **Cloudflare Tunnel** | ★★★★☆ | The honest fix for "the panel has no TLS" |
| **Sandbox SDK** | ★★★☆☆ | A real 5th `sandbox.py` backend — but TS-from-Workers, not REST-from-Python. Needs a shim |
| **Durable Objects** | ★★★☆☆ | Alarms give *"guaranteed at-least-once execution"* — a good scheduler for waking a sleeping container |
| **Workflows** | ★★☆☆☆ | Durable multi-step execution. Overlaps our mission engine; adopting it means rewriting the loop in TS |
| **D1 / KV / Vectorize** | ★★☆☆☆ | We are deliberately file-backed and stdlib-only. Vectorize would be useful *if* we ever wanted embedding search, which `recall.py` currently does without |
| **Agents / Agent Memory** | ★☆☆☆☆ | **This is a competing product, not a component.** See §5.2 |
| **Browser Run** | ★★☆☆☆ | Would upgrade `ingest.py` from HTTP fetch to real rendering |
| **Artifacts** | ★★☆☆☆ | "filesystem artifacts, git-compatible" — worth watching for our expert directories |
| Everything else | — | Fine products; irrelevant to an agent platform |

### 5.1 What running 24/7 on Cloudflare costs

Computed from their published rates (`$0.0000025/GiB-s` memory,
`$0.000020/vCPU-s`, `$0.00000007/GB-s` disk, with 25 GiB-hours / 375
vCPU-minutes / 200 GB-hours included on Workers Paid), for 730 hours/month and
a 5% CPU duty cycle — an agent loop spends most of its life waiting on a
provider:

| Instance | Memory | Disk | CPU | **Total (incl. $5 plan)** |
|---|---|---|---|---|
| lite (256 MiB) | $1.42 | $0.32 | $0.00 | **$6.74/mo** |
| basic (1 GiB) | $6.35 | $0.69 | $0.21 | **$12.24/mo** |
| standard-1 (4 GiB) | $26.06 | $1.42 | $0.86 | **$33.34/mo** |

**There is no free tier for Containers** — Cloudflare's pricing table says
"Free: N/A". Workers Paid at $5/month is the floor.

So: **~$12/month for a 24/7 agent fleet with ~450 free model steps a day.**
That is a real number and it is small. Note it excludes model spend above the
free allocation.

### 5.2 Cloudflare Agents is a competitor, and that is worth being clear about

Cloudflare's `Agents` product offers "durable identity, local SQL storage,
real-time connections, scheduled work, and recoverable execution", and
`Agent Memory` offers "persistent AI-powered memory... automatically extract,
classify, and recall knowledge".

Those overlap our Expert model and our memory institution. The differences are
real and worth stating without spin:

- **Theirs runs on their network and scales to millions of instances.** Ours
  runs anywhere Python runs, including a laptop with no network.
- **Theirs is TypeScript on Workers.** Ours is stdlib Python with a gate that
  executes commands — which theirs cannot do without delegating to Sandbox.
- **Ours has the gate, the mission contract and the proof system.** Those are
  the parts this project claims are the point, and they have no equivalent
  there.
- **Theirs has durable global infrastructure we would take years to match.**

They are not a substitute for each other. The sane reading is that Cloudflare
is **excellent infrastructure underneath this platform** and a **competing
opinion about what an agent framework should be** — and we only need the first.

### 5.3 Cloudflare Tunnel closes a real, documented gap

`REFERENCE.md` limit 14 says: *"There is no password, no session and no TLS."*
Cloudflare Tunnel puts the panel behind Cloudflare's edge with TLS and Zero
Trust access policies, without opening a port. That converts an honest
limitation into a solved problem using a free product, and requires no code
change at all.

---

## 6. What to build, in order

Each item is scoped, and the first two need no new infrastructure.

1. **Add the Cloudflare provider** — *already done in this commit.*
   `settings.toml` ships both the direct and AI-Gateway blocks. Uncomment,
   paste an account id, put `CLOUDFLARE_API_TOKEN` in `agent.env`, run
   `python loop.py check`. **This is the whole integration.**

2. **Push backups to R2** — *also done in this commit.* `backup.py` grew
   `push`, `pull` and `remote-list` against any S3-compatible endpoint, with
   AWS Signature V4 written in `hmac` + `urllib` rather than boto3, so the
   zero-dependency promise holds.

   ```bash
   python backup.py push <archive> --endpoint https://<id>.r2.cloudflarestorage.com --bucket fleet
   python backup.py pull  fleet-2026-08-24.zip --dest ../restored --endpoint ... --bucket fleet
   python backup.py remote-list --endpoint ... --bucket fleet
   ```

   Signing correctness was the real question, since no bucket exists to test
   against. AWS publishes example signatures; two of them — chosen because
   their `SignedHeaders` set matches ours exactly — are now permanent
   assertions in `test_backup.py`, **reproduced byte for byte**. The first
   draft failed them: it signed the raw query string instead of
   canonicalising it, which would have broken every `remote-list` call
   (`?list-type=2`) and shown up against a live bucket as an opaque 403
   rather than a diff. Credentials come through `credentials.resolve()` so
   all four sources work; a `pull` re-verifies every manifest checksum before
   returning; and a push with no credentials refuses by name **without
   touching the network**.

3. **A container image and a start/stop hook (medium).** `Dockerfile` already
   exists. Add: restore from R2 at boot, snapshot to R2 before sleep, and set
   `sleepAfter` generously. State stays on local disk — never on FUSE.

4. **A Durable Object alarm to wake the fleet (small, optional).** Cheaper
   than never sleeping: the alarm pokes the container on a schedule, the
   container drains its queue and sleeps again. Costs only what it runs.

5. **`sandbox.py` Cloudflare backend (medium, only if wanted).** Sandbox SDK
   is a genuine fifth backend beside `host`/`docker`/`e2b`/`daytona`, but its
   API is TypeScript-from-Workers, so it needs a thin Worker exposing REST
   that our Python client can call — the same shape `_hosted()` already uses.

**What not to do:** do not port the loop to Workers, do not move `state.json`
onto R2-FUSE, and do not adopt Workflows or Agents unless you are willing to
rewrite the platform in TypeScript and give up the gate.

---

## 7. What this study does not establish

- **Nothing was run against Cloudflare.** No account, no token, no container,
  no Neuron spent. Every "works" above means "matches the documented contract,
  verified locally" — except §4.1, which was additionally tested against a
  loopback server speaking that contract.
- **Prices and free tiers change.** Every figure is dated to this session and
  cited to a `/index.md` you can re-fetch in one command.
- **The container cost model assumes a 5% CPU duty cycle.** That is a
  reasoned estimate from a loop that waits on network, not a measurement. A
  fleet doing heavy local gating would cost more.
- **R2-FUSE was rejected on documented behaviour, not on a test.** The
  reasoning — `O_EXCL` and `rename` are not atomic on object storage — is
  sound and matches Cloudflare's own warning, but nobody here has run this
  platform on a FUSE mount and watched it fail. If you want that certainty it
  is a day's work to build and would make a good U-numbered entry either way.
- **Sandbox SDK's REST surface was not confirmed.** It is documented as a
  TypeScript SDK; whether a direct HTTP API exists was not established, and
  the recommendation in §6.5 assumes it does not.
