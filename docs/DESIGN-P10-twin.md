# Phase 10 — The Twin: a Self Kernel of the OWNER, beneath every agent (design, committed before code)

**Status: BUILT** (this document was committed first; the build commit
follows it and cites this file; the preregistered benchmark below is green
in the acceptance suite — `tests/test_twin.py`, 13 checks — and the four
mutation checks in `mutate_check.py` go red when a law is removed).
**Branch:** `phase10/self-kernel`. **Series:** docs/DESIGN-P9a maps the
pre-AI lineages the platform builds beneath the model; this phase opens a
new lineage — the *person* the platform works for.

## The order

The owner's brief of 2026-09-03, kept in its own words: *a system that
produces an agent that is literally a clone of the person using it. You show
it how you think, how you work, what to do; it becomes your digital self.
Not a chatbot that remembers you — a system that IS the person, at an
extremely high level, from real research, added end to end without breaking
or changing what is already built.*

The correction the brief itself makes, and this design keeps as its first
law: an *exact copy of your current judgement* and *a hundred times your
capability* are two different objects. So the phase builds two layers and
never lets one leak into the other:

1. **The Clone** — `π_you(a | situation, history, goals, constraints)`: a
   calibrated predictor of what the owner would do, learned from what the
   owner actually did, measured against held-out decisions the owner made
   later, and honest about where it does not know.
2. **The Super-Self** — the same identity, objectives, standards and
   decision authority, handed the platform's whole augmentation stack
   (models, research, procedures, parallel work, perfect memory). It never
   replaces the Clone; it shows the owner where a better-informed version
   of them *diverges*, and asks whether the policy should change.

Everything else in this document is the machinery that makes those two
layers measurable rather than a persona.

## What exists already (nothing is replaced)

| Piece of the brief | What the platform already holds | What this phase adds |
|---|---|---|
| "self model" | `selfmodel.py` — the **agent's** factual self-model, compiled into every window | `twin.py` — the **owner's** self-kernel; a new `owner` context source beside `self` |
| episodic memory | `contexts/`, `archive/tasks.jsonl`, `logs/agent.log`, `cases.jsonl` | `twin/episodes.jsonl` — the owner's decision episodes, attributed by source |
| semantic memory | courses, atoms, `knowledge.py`, `commons` | the owner's **belief state** is read from what the platform showed them (approval briefs, goal events), never assumed |
| procedural memory | `skills.py`, `runbook.py`, `procedure.py` (candidate → proven) | **behavioral programs** mined from the owner's episodes, with the same candidate → proven ladder |
| active elicitation | `ask_human`, `steer.py`, approvals with a note | **questions** the kernel asks *only at high-information points*, bounded to one open at a time |
| calibration | `calibration.py` (Brier, ECE, reliability curve on mechanical outcomes) | the same formulas applied to the kernel's shadow predictions |
| drift | `freshness.py` (stale knowledge), `watchdog.py` (limits) | **Page-Hinkley** over prediction loss + refit deltas; a drift is a *question to the owner*, never a silent update |
| custody | `learning_authority.py` (owner-created immutable records, first-seal-wins) | **consent** and **revocation** as sealed records, checked before every twin output |
| test-time compute, research | `candidates.py`, `research.py`, `consult.py`, the model gateway | the **Super-Self** call, metered under a new gateway purpose `twin` |

## The research this rests on

The ideation the owner supplied cites ten works; this design verified them
and adds the mechanisms it borrows from each (the full dossiers with URLs,
about eighty citations, are in `docs/research/P10-twin-research-A.md` and
`-B.md`; corrections found while verifying are folded in below):

* **Park et al., arXiv 2411.10109** (v1 2024 *Generative Agent Simulations
  of 1,000 People*; retitled in v3, June 2026, *LLM Agents Grounded in
  Self-Reports Enable General-Purpose Simulation of Individuals*). Agents
  built from two-hour interviews reproduced General Social Survey answers
  at **83–86 % of each participant's own two-week test-retest
  consistency** (74 % for demographics-only agents); incentivized
  economic-game behavior was the hardest stratum (~0.66 normalized). Two
  lessons are taken verbatim: (a) a clone is scored
  *normalized by the person's self-consistency*, never against a fictitious
  deterministic ground truth — so the kernel measures the owner's own
  retest agreement and reports fidelity as a fraction of it; (b) the
  richest signal is the person's *stated reasoning*, so the kernel asks
  "why" and stores the answer as first-class evidence.
* **Modeling Others' Minds as Code (ROTE, ICLR 2026).** Recurring behavior
  is better predicted by *synthesized behavioral programs* than by pure
  behavior cloning. The kernel mines explicit IF–THEN heuristics over the
  owner's features with support and confidence, validates them on held-out
  episodes, and lets a proven rule outrank the statistical arm.
* **PAHF (arXiv 2602.16173) and RealPref (arXiv 2603.04191).** Preferences
  must be learned continuously from pre-action clarification and
  post-action feedback, and implicit preferences degrade over long
  horizons unless they are made explicit. Hence the question ledger and the
  drift detector.
* **GUIDE (arXiv 2603.25864, CVPR 2026), ShowUI-Aloha (arXiv 2601.07181),
  LearnAct (arXiv 2504.13805).** Models are poor at inferring *intent* from
  raw action streams (the best of eight multimodal models reached 44.6 % on
  behavior-state detection); structured context (stated intent, the "why")
  changes the result; a single structured demonstration lifted one GUI
  agent from 19.3 % to 51.7 %. So the episode format is `state → options → choice →
  why → outcome`, structured, never a recording.
* **Inverse reinforcement learning (Ziebart 2008 max-entropy IRL; Jeon,
  Milli & Dragan 2020 reward-rational implicit choice; Lazzati et al. 2026
  on identifiability).** The owner's utility is *underdetermined* by
  observed choices. The kernel therefore (a) fits a Boltzmann-rational
  (multinomial-logit) choice model — the standard, tractable IRL surrogate;
  (b) reports the *ambiguity* (novelty, entropy) as an "ask for more
  information" mass instead of hiding it.
* **Calibration and abstention** (Brier 1950, ECE / reliability diagrams,
  selective prediction). A clone's most dangerous number is a confident
  wrong answer, so the benchmark carries a *high-confidence error rate*
  as a first-class metric.
* **Change detection** (Page 1954 CUSUM / Page-Hinkley; Bifet & Gavaldà
  2007 ADWIN; Adams & MacKay 2007 Bayesian online changepoint). A person
  changes; the kernel keeps *versions* and detects drift over the loss
  sequence, then asks.
* **Stylometry** (Burrows 2002 *Delta*; function-word and character
  n-gram profiles). Writing fidelity is measured by a blind, mechanical
  attribution — a draft in the owner's voice must land closer to the
  owner's profile than to a stranger's.
* **Shadow mode / champion-challenger.** The predictor is sealed *before*
  the person acts and never shown beforehand — a shown prediction
  contaminates the very signal it is measured against.
* **Authorization primitives** (capability tokens, delegation with
  revocation; EU AI Act Art. 50 transparency for synthetic content).
  "Speaking like the owner" and "acting as the owner" are different scopes,
  granted separately, revocable, and every output is labeled.

## What a twin is, concretely

Per expert, a CONTROL-zoned directory `twin/` the worker can read and can
never write (the same rule as `approvals/` and `prompts/`):

```
twin/
  kernel.json          the Self Kernel: versions[], each a frozen fitted model
  episodes.jsonl       the experience stream (append-only, hashed, attributed)
  questions.jsonl      the "why" questions the kernel asked, and the answers
  predictions.jsonl    sealed shadow predictions and their resolution + score
  shadow/<id>.json     the hidden prediction body, revealed only once resolved
  drift.json           the change-detector state and any open drift notice
  fidelity.json        the benchmark report (recomputed on demand)
  authority.json       the projection of the sealed consent chain (org/learning)
```

### The episode

```json
{"id": "ep-…", "at": "…", "kind": "approval|steer|answer|goal|decision|retest|import",
 "source": "harvest:approvals|panel|cli|import",
 "situation": {"text": "…", "features": {"risk": 0.7, "cost_usd": 120}},
 "options":  [{"id": "grant", "text": "…", "features": {…}}, {"id": "deny", …}],
 "choice": "deny", "counterpart": "supplier-x", "latency_s": 41.2,
 "why": null, "outcome": null, "hash": "sha256(…)"}
```

Harvested mechanically from the ledgers the owner already writes into —
`approvals/*.json` (grant/deny + note), `goals/*/steering.jsonl` (the
owner's words), answers to `ask_human`, `identity.history.jsonl` — and
recorded explicitly with `twin.py observe` / `twin.py import` for decisions
the platform did not witness. A harvested episode is *attributed* (its
source and origin id travel with it); a worker cannot forge one (CONTROL).

### The kernel (one version = one frozen fit)

| Part | What it holds | How it is learned |
|---|---|---|
| identity | the owner's own words (identity.md is the agent's; the owner's principles are declared with `twin.py declare`) | declared, never inferred |
| objectives | active missions and goals the owner opened | read from `missions/` and `goals/` |
| preferences | a conditional-logit weight per feature: `u(o) = w · x(o)`; `P(o) = softmax(u)` | gradient ascent with L2, fixed epochs, deterministic |
| attention | the normalized |w| per feature — *what this person looks at first* | derived from the fit |
| heuristics | IF–THEN behavioral programs with support, confidence and a held-out verdict (candidate / proven) | mined over thresholded features and terms |
| beliefs | what the owner has been shown before each decision (the approval brief, goal events) | read; a prediction reconstructs only what was knowable at that moment |
| social | per-counterpart grant rate, latency, tone | counted |
| style | function-word profile, sentence length, punctuation rate, character trigrams | from the owner's own text only |
| self-consistency | agreement rate on repeated identical situations (`retest` episodes) | measured; the fidelity ceiling |

### Inference — the Clone

```
situation + options + counterpart
   → reconstruct what the owner would know (beliefs before `at`)
   → retrieve similar episodes (term overlap + numeric closeness)
   → preferences arm:    log-odds from the fitted logit
   → programs arm:       +2.0 for a PROVEN rule that fires, +1.0 candidate
   → memory arm:         +0.5 × similarity per matching neighbor's choice
   → novelty:            share of the situation's active features unseen at fit time
   → "ask for more information" mass = f(novelty, entropy)
   → probabilities, the features that drove them, confidence tier,
     the kernel version, and the LABEL
```

Output is a distribution, never a verdict:

```
grant 0.72 · deny 0.19 · ask 0.09   (kernel v3, novelty 0.12, confidence high)
because: risk 0.7 (weight −1.9), counterpart supplier-x (deny 4/5), rule H-2 PROVEN
TWIN — a computational model of the owner, not the owner
```

### Shadow mode — how the clone is scored without contaminating the signal

Every decision point the platform creates for the owner (today: a pending
approval; the surface is a table so more kinds can be added) gets a
prediction **sealed before the owner decides**: `predictions.jsonl` holds
the SHA-256 of the prediction body and the time; the body sits in
`twin/shadow/` and the panel/CLI refuse to reveal it until the decision
lands. When the owner decides, the harvester resolves the prediction:
hit/miss, Brier, log-loss, the confidence tier — and the pair
*(prediction, actual)* becomes the next fit's training row. A disagreement
at high confidence is the most valuable row and triggers a question.

### Elicitation — asking "why" only when it pays

At most **one** open question at a time. A question is queued when the
expected information gain proxy is high: a confidently wrong shadow
prediction (`p_max ≥ 0.7`, missed), or a novel situation (`novelty ≥ 0.5`)
the owner decided without a note. The question offers the candidate
reasons the kernel can act on (the features that split the decision) plus
"something else"; the answer is stored on the episode and enters the next
fit as evidence, and as a term the heuristics miner can use.

### Drift — the owner changes; the kernel must not silently follow or refuse

Page-Hinkley over the sequence of resolved log-losses (δ = 0.005,
λ = 1.5); when it trips, the kernel refits on the last window and on the
window before, and writes a **drift notice** with both parameter estimates
(the "risk tolerance 0.37 → 0.62" form), candidate causes, and the
question *confirm permanent update?* Nothing changes until the owner
answers: `confirm` freezes a new kernel version; `dismiss` keeps the old
one and records the notice. Every prediction names the kernel version that
produced it, so a scored history is never mixed across versions.

### The benchmark — what "the clone works" means

`twin.py fidelity` recomputes, from held-out episodes only (never the fit
set, split by hash):

| Dimension | Measurement |
|---|---|
| choice fidelity | argmax = the owner's choice |
| ranking fidelity | Kendall τ between predicted order and the owner's stated ranking, when given |
| calibration | Brier, ECE, reliability curve |
| high-confidence error rate | share of `p_max ≥ 0.8` predictions that missed |
| novel-situation fidelity | choice fidelity restricted to `novelty ≥ 0.5` |
| self-consistency ceiling | agreement on `retest` episodes |
| normalized fidelity | choice fidelity ÷ ceiling (Park 2024) |
| correction speed | episodes between a miss and the next hit on a matching situation |
| writing fidelity | Burrows' Delta: owner's held-out text closer to the owner's profile than a stranger's |
| social fidelity | per-counterpart choice fidelity |

A kernel with fewer than 20 held-out episodes reports **INSUFFICIENT
EVIDENCE**, in those words, and every dimension it cannot measure is
listed as such — the honesty discipline of `evidence.py` applied to a
model of a person.

### Consent, scope, labeling — architectural, not settings

`twin.py consent grant --scope predict|advise|draft|act --by <owner>` seals a
record through `learning_authority` (owner-only, first-seal-wins, hashed in
`org/learning/seals.jsonl`); `revoke` seals a superseding record. The
effective scope is the highest sequence whose digest verifies. Scopes
nest:

| scope | the twin may |
|---|---|
| (none) | nothing — every call refuses with the reason |
| predict | score decision points in shadow; answer "what would I do" to the owner |
| advise | run the Super-Self and show the divergence |
| draft | produce text in the owner's voice, labeled, never sent |
| act | queue a *gated task* on the owner's behalf — it still runs through the ordinary ladder (gates, approvals, effects ledger); the twin never executes anything itself |

Every output carries `label: "TWIN — a computational model of <owner>, not
<owner>"`; a Super-Self output carries `"SUPER-SELF — identity-preserving
recommendation; the decision authority remains the owner"`. The label is
not a string in a prompt; it is a field the test asserts on every path.

### The Super-Self

`twin.py superself --situation … --options …` produces two answers:

* **SELF** — the Clone's distribution, mechanical.
* **SUPER-SELF** — the model (a configured role under `[agent.twin]`),
  handed the rendered kernel (identity, preferences, attention, proven
  heuristics, style, standards) *as the person whose objective it must
  preserve*, plus the platform's augmentation: the citation-gated
  `research.py`/`consult.py` path when the role has tools, `candidates.py`
  for alternatives. Metered under purpose `twin`.

The divergence is detected **mechanically**: if the Super-Self's chosen
option ≠ the Clone's argmax, a *policy update* question is queued naming
the option, the Clone's confidence, and the Super-Self's stated reason.
The kernel is not modified by the Super-Self, ever; only the owner's
answer can move it.

### The owner in every window

`context.py` gains an `owner` source (budget 500 tokens, after `self`):
the rendered kernel — the owner's principles, the trade-offs they actually
make, the heuristics that are proven, the counterpart rules, and how they
write. Every expert on the fleet then works the way its owner works, with
the same honesty as the `self` block: nothing in it is generated; a kernel
with no fit renders nothing. The student role stays closed-book.

## What measurable capability this adds

"What would I do here?" becomes a mechanical, calibrated, versioned answer
with a benchmark behind it; the owner's judgement becomes a context source
every agent reads; the machine's disagreement with the owner becomes a
question with numbers instead of a silent substitution.

## Benchmark that must pass before this becomes permanent

`tests/test_twin.py`, preregistered:

1. **Control state.** `twin/` is CONTROL (agent write refused, harness
   allowed); `twin/kernel.json` is in `harness.LEDGERS`, lands in
   `ZONE_CONTROL` and is enumerated in the leakage suite; consent records
   live under `org/learning` and refuse from inside an agent task.
2. **Episodes.** `observe` writes a hashed episode; the identical
   observation is idempotent; the harvester turns a decided approval, a
   steering note and an answered question into attributed episodes exactly
   once; a worker cannot write the ledger.
3. **Learning.** A synthetic owner with a known policy (reject when risk >
   0.5 unless margin ≥ 0.3; a counterpart-specific exception) yields, from
   60 episodes, a kernel whose held-out choice fidelity is ≥ 0.90; the
   mined heuristics contain the rule; attention ranks `risk` and `margin`
   first; a random owner yields a report that says INSUFFICIENT / low
   fidelity rather than a confident one.
4. **Calibration and abstention.** Brier and ECE are computed on held-out
   rows only (a fit-set id is refused); a situation whose features were
   never seen carries novelty ≥ 0.5, a lower confidence tier and non-zero
   ask mass; the high-confidence error rate is reported.
5. **Shadow.** A pending approval gets a sealed prediction from the idle
   tick; before the decision the API and CLI expose the hash and not the
   body; after the decision the prediction is resolved, scored, and its
   body hash still matches (a tampered body is reported TAMPER).
6. **Elicitation.** A confidently wrong prediction queues exactly one
   question with the candidate reasons; a second miss does not queue a
   second while one is open; answering stores the why on the episode; hits
   queue nothing.
7. **Drift.** A policy change after episode 60 trips the detector; a drift
   notice with old/new estimates appears; the kernel version is unchanged;
   `confirm` freezes a new version and predictions name it; `dismiss`
   keeps the old one.
8. **Style.** Burrows' Delta places the owner's held-out text nearer the
   owner's profile than a stranger's text.
9. **Consent and labeling.** Without consent every output refuses; with
   `predict`, `superself` and `draft` refuse; `act` only queues a gated
   task (its record shows the ordinary `done_check`); `revoke` returns to
   refusal; every output on every path carries the label.
10. **Super-Self.** With a scripted model the call returns SELF and
    SUPER-SELF, detects the divergence mechanically, queues a policy-update
    question, and the kernel hash is unchanged afterwards; the call is
    metered under purpose `twin`.
11. **Context.** A compiled window carries the `owner` block when a kernel
    exists and none when it does not; the manifest names the source; the
    student role never receives it.
12. **Loop.** A `--drain` run with a pending approval seals a prediction
    from the idle tick; a second drain seals nothing new.
13. **Registration.** run_all, evidence, proof, doctor, harness LEDGERS,
    fileauth, the leakage enumeration, REFERENCE, MANUAL, settings.toml.

## Claim envelope (per docs/DESIGN-P6.1)

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| fidelity ≥ 0.90 | a *consistent* owner policy expressible over declared features, ≥ 60 episodes | a policy that depends on state the platform never observes (the brief's own limit: no subconscious state, no concealed emotion) | held-out argmax agreement |
| no contamination | predictions sealed before decisions | an owner who reads `twin/shadow/` on disk by hand | the hash chain and the reveal gate |
| no silent drift | the detector trips only on resolved predictions | a change the owner never lets the platform see | the version list and the notice |
| consent-gated | `learning_authority` custody | an unrestricted host that can rewrite `org/` — the same limit that module states for itself | sealed digest verification |

## What this phase does NOT claim

No gradient training of any model (the training lab boundary stands). No
screen, keystroke or application capture — the episode surface is
*declared*; a future capture lineage would feed the same ledger. No claim
that the owner's mind is copied: the target is *behaviorally
indistinguishable within measured domains, with calibrated uncertainty
outside them*, and the fidelity report says which domains those are. No
live-provider evidence — the Super-Self is proven against the scripted
mock like every other model path here.
