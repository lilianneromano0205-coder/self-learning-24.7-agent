# Phase 9c — Change sentinels: crawler-grade change detection beneath the model (design, committed before code)

**Status: DESIGN** (flips to BUILT when the preregistered benchmark below is
green in the acceptance suite). **Branch:** `phase9c/sentinels`. **Series:**
docs/DESIGN-P9a-reconcilers.md maps the lineages; this is the third piece.

## The lineage

A crawler that ran for years did three dull things well: it remembered
what it had seen (a content hash per resource), it noticed when that
changed, and it was polite — it did not ask the same resource twice inside
its interval. Nothing intelligent happened in the crawler; the intelligence
was applied downstream, to the pages that had actually changed. The
platform's prospective memory already fires on files appearing, on needles
in files, on events and on probe commands; what it cannot do is notice
that something *changed* — a file rewritten with different content, a
remote record that moved — and hand the change, as evidence, to gated work.

## What a sentinel is

Three new intention kinds in `prospective.py`, evaluated by the same
mechanical scheduler tick as the existing seven, armed and cancelled by the
same owner surface, firing the same ordinary gated task:

| Kind | Watches | Fires when |
|---|---|---|
| `file_changed` | one contained file | its SHA-256 differs from the last one seen (a missing file is the empty hash, so removal is a change and reappearance is a change) |
| `tree_changed` | one contained directory, bounded (`max_files`, default 2000) | the manifest hash (sorted relative paths + sizes + file hashes) differs |
| `http_changed` | an owner-named endpoint path (Phase 8) | the canonical readback body's hash differs; a readback that fails is not a change (an outage is not news) |

Each carries `every_s` (politeness interval, floor 30 s), `last_hash`,
`last_seen`, and fires **at most once per change**: an identical rewrite
(same bytes, new mtime) is not a change; the first observation only
records the baseline and never fires. The fired task's goal is prefixed
with the evidence — `CHANGE DETECTED: <kind> <target> <old hash>… → <new
hash>…` — so the worker or the reconciler downstream reasons about a
change that mechanically happened, never about a suspicion.

Detection is model-free and credential-safe: `http_changed` goes through
`httpstate.observe` under the owner's endpoint table (no host the owner did
not name, no credential in the ledger, only the hash of the body is
stored). A sentinel stores hashes, never content.

## What measurable capability this adds

"Watch this and tell me when it changes" becomes a declared, deterministic
sentinel over files, directories and owner-named APIs, with politeness and
exactly-once-per-change firing — the unit cell of every monitoring desk in
the use-case catalogue, now over the outside world as well as the disk.

## Benchmark that must pass before this becomes permanent

`tests/test_sentinels.py`, preregistered:

1. **Baseline, then change.** A `file_changed` sentinel records the
   baseline on its first tick without firing; a rewrite with the same
   bytes does not fire; a rewrite with different bytes fires exactly one
   task whose goal carries both hashes; removal fires; reappearance fires.
2. **Politeness.** Inside `every_s` a changed file is not even hashed
   (the last-seen stamp proves it); after the interval it fires.
3. **Tree.** A `tree_changed` sentinel fires on an added file, on a
   modified file and on a deletion, not on a touch; a tree over
   `max_files` refuses at `add`.
4. **HTTP.** An `http_changed` sentinel against the Phase 8 fixture records
   a baseline, does not fire on an identical readback, fires when the
   record changes, does not fire on a 404 (an outage is not a change), and
   the ledger holds hashes only — never the body, never the bearer.
5. **Owner-named only.** An `http_changed` sentinel naming an endpoint
   outside the owner's table refuses at `add`.
6. **Loop integration.** A `--drain` run with an armed `file_changed`
   sentinel and a changed file queues the gated task from the idle tick;
   a second drain with no change queues nothing.
7. **Registration.** REFERENCE lists ten intention kinds; run_all,
   evidence, proof; prose counts.

## Claim envelope (per docs/DESIGN-P6.1)

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| once per change | one scheduler tick at a time (the existing prospective lock) | two changes inside one interval collapse into one firing (the second is seen as the new state, by design — crawlers do the same) | the queued task count |
| polite | `every_s` floor 30 | a change that reverts within the interval is never seen | the `last_seen` stamp |
| hashes only | sentinels store SHA-256 | a body that is itself sensitive is still fetched (into memory), only never stored | ledger bytes |

## What this phase does NOT claim

No content diffing, no semantic change judgement (that is downstream, and
a model's job when needed). No crawl frontier or link following — the
ingestion crawler already exists. No web search.
