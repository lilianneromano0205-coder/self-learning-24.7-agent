#!/usr/bin/env python3
"""THE TWIN'S ARITHMETIC — every number the Self Kernel reports, in one
place, with no dependency and no model.

docs/DESIGN-P10-twin.md names the research each function borrows from; the
functions themselves are deliberately small enough to be read against it:

  featurize / fit / predict     a conditional-logit (Boltzmann-rational)
                                choice model over declared features — the
                                tractable surrogate that maximum-entropy IRL
                                (Ziebart 2008) and reward-rational implicit
                                choice (Jeon, Milli & Dragan 2020) reduce to
                                when the options are enumerated
  mine_rules / validate_rules   behavioral programs (ROTE, ICLR 2026): IF–THEN
                                heuristics with support, confidence and a
                                held-out verdict — candidate or proven, the
                                same ladder skills.py uses
  brier / ece / logloss         proper scoring rules and the reliability
                                curve (the formulas calibration.py already
                                trusts, applied to a person)
  PageHinkley                   Page (1954) / Mouss et al. (2004): the
                                cumulative change detector over a loss
                                sequence; a trip is a QUESTION, never an
                                update
  style_profile / burrows_delta Burrows (2002) Delta over function-word
                                frequencies — the blind, mechanical
                                writing-fidelity test
  kendall_tau                   ranking fidelity

Everything is deterministic: fixed epochs, fixed iteration order, hashed
splits. Two runs on the same ledger produce byte-identical kernels, which is
what lets a kernel version be a hash.
"""

import hashlib
import math
import re

# the same stop list cases.py matches on, so a term means one thing across
# the platform
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "into", "that", "this", "it", "is", "are", "be",
        "task", "run", "goal", "please", "make", "get", "use", "using",
        "would", "should", "could", "will", "was", "were", "has", "have",
        "had", "not", "but", "as", "if", "then", "than", "so", "we", "you",
        "they", "he", "she", "our", "your", "their", "his", "her", "its"}

EPOCHS = 600
LEARNING_RATE = 0.3
L2 = 0.003
MIN_TERM_DF = 2          # a term must appear in two episodes to be a feature
MAX_INTERACT = 6         # numeric situation features that may form pairs
HOLDOUT_MOD = 5          # one episode in five is held out, by hash


def terms(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def is_holdout(episode_id):
    """Deterministic split by hash of the id — a fit can never see a
    held-out row and a held-out row can never be chosen by hand."""
    h = hashlib.sha256(str(episode_id).encode("utf-8")).hexdigest()
    return int(h[-2:], 16) % HOLDOUT_MOD == 0


# ------------------------------------------------------------ features

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def active_keys(situation, counterpart=None):
    """The situation-level feature keys a prediction turns on — the set the
    novelty score compares against what the fit had seen."""
    keys = set()
    for k, v in (situation.get("features") or {}).items():
        if _num(v) is not None:
            keys.add(f"sit:{k}")
    for t in terms(situation.get("text")):
        keys.add(f"sterm:{t}")
    if counterpart:
        keys.add(f"cp:{str(counterpart).lower()}")
    return keys


def featurize(situation, option, counterpart, stats, vocab):
    """One option's feature vector, as {key: value}.

    stats : {key: (mean, std)} for numeric keys, fixed at fit time
    vocab : the term keys admitted at fit time (df >= MIN_TERM_DF)

    Option identity interacts with situation numerics and terms, so an
    approve/deny decision can depend on the situation; option-level numerics
    and terms are shared, so "pick the best offer" can depend on the offer.
    """
    oid = str(option.get("id"))
    x = {f"opt:{oid}": 1.0}
    sit = []
    for k, v in sorted((situation.get("features") or {}).items()):
        f = _num(v)
        if f is None:
            continue
        z = standardize(f"sit:{k}", f, stats)
        x[f"opt:{oid}|sit:{k}"] = z
        sit.append((k, z))
    # pairwise products of the situation's numerics: a person's rule is
    # rarely one threshold — "risk high AND margin thin" is a conjunction,
    # and a product term is the smallest thing that lets a linear model
    # bend around one (bounded: MAX_INTERACT numerics -> at most 15 pairs)
    for i, (ka, za) in enumerate(sit[:MAX_INTERACT]):
        for kb, zb in sit[i + 1:MAX_INTERACT]:
            x[f"opt:{oid}|sit:{ka}*{kb}"] = za * zb
    for k, v in (option.get("features") or {}).items():
        f = _num(v)
        if f is None:
            continue
        x[f"feat:{k}"] = standardize(f"feat:{k}", f, stats)
    for t in terms(option.get("text")):
        key = f"term:{t}"
        if key in vocab:
            x[key] = 1.0
    for t in terms(situation.get("text")):
        key = f"sterm:{t}"
        if key in vocab:
            x[f"opt:{oid}|{key}"] = 1.0
    if counterpart:
        x[f"opt:{oid}|cp:{str(counterpart).lower()}"] = 1.0
    return x


def standardize(key, value, stats):
    mean, std = stats.get(key, (0.0, 1.0))
    return (value - mean) / std if std > 1e-9 else 0.0


def numeric_stats(episodes):
    """{key: (mean, std)} over every numeric situation/option feature."""
    acc = {}
    for ep in episodes:
        for k, v in (ep.get("situation", {}).get("features") or {}).items():
            f = _num(v)
            if f is not None:
                acc.setdefault(f"sit:{k}", []).append(f)
        for o in ep.get("options") or []:
            for k, v in (o.get("features") or {}).items():
                f = _num(v)
                if f is not None:
                    acc.setdefault(f"feat:{k}", []).append(f)
    out = {}
    for k, vals in acc.items():
        n = len(vals)
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        out[k] = (mean, math.sqrt(var))
    return out


def build_vocab(episodes):
    df = {}
    for ep in episodes:
        seen = set()
        for t in terms(ep.get("situation", {}).get("text")):
            seen.add(f"sterm:{t}")
        for o in ep.get("options") or []:
            for t in terms(o.get("text")):
                seen.add(f"term:{t}")
        for k in seen:
            df[k] = df.get(k, 0) + 1
    # a term in (nearly) every episode carries no information about the
    # choice; it would only soak up weight the real features deserve
    ceiling = max(MIN_TERM_DF, int(0.9 * len(episodes)))
    return {k for k, n in df.items() if MIN_TERM_DF <= n <= ceiling}


def seen_keys(episodes):
    """How many episodes turned on each situation-level key — novelty's
    reference."""
    out = {}
    for ep in episodes:
        for k in active_keys(ep.get("situation") or {}, ep.get("counterpart")):
            out[k] = out.get(k, 0) + 1
    return out


def novelty(situation, counterpart, seen):
    """1 - share of the situation's active keys the fit saw at least twice.
    A situation with no declared features is entirely novel."""
    keys = active_keys(situation, counterpart)
    if not keys:
        return 1.0
    known = sum(1 for k in keys if seen.get(k, 0) >= 2)
    return round(1.0 - known / len(keys), 4)


# -------------------------------------------------------------- the fit

def _rows(episodes, stats, vocab):
    rows = []
    for ep in episodes:
        opts = ep.get("options") or []
        ids = [str(o.get("id")) for o in opts]
        if len(opts) < 2 or str(ep.get("choice")) not in ids:
            continue
        xs = [featurize(ep.get("situation") or {}, o, ep.get("counterpart"),
                        stats, vocab) for o in opts]
        rows.append((xs, ids.index(str(ep["choice"]))))
    return rows


def _softmax(us):
    m = max(us)
    ex = [math.exp(u - m) for u in us]
    z = sum(ex)
    return [e / z for e in ex]


def _dot(w, x):
    return sum(w.get(k, 0.0) * v for k, v in x.items())


def fit(episodes, epochs=EPOCHS, lr=LEARNING_RATE, l2=L2):
    """Conditional logit by full-batch gradient ascent — deterministic.

    Returns the fitted parameters and everything a later predict() needs to
    reproduce the feature space: {weights, stats, vocab, seen, n, loglik}.
    """
    stats = numeric_stats(episodes)
    vocab = sorted(build_vocab(episodes))
    vocab_set = set(vocab)
    rows = _rows(episodes, stats, vocab_set)
    w = {}
    ll = 0.0
    for _ in range(epochs):
        grad = {}
        ll = 0.0
        for xs, chosen in rows:
            ps = _softmax([_dot(w, x) for x in xs])
            ll += math.log(max(ps[chosen], 1e-12))
            for i, x in enumerate(xs):
                coef = (1.0 if i == chosen else 0.0) - ps[i]
                for k, v in x.items():
                    grad[k] = grad.get(k, 0.0) + coef * v
        if not rows:
            break
        n = len(rows)
        for k in sorted(set(grad) | set(w)):
            g = grad.get(k, 0.0) / n - l2 * w.get(k, 0.0)
            w[k] = w.get(k, 0.0) + lr * g
    return {"weights": {k: round(v, 6) for k, v in sorted(w.items())},
            "stats": {k: [round(m, 6), round(s, 6)] for k, (m, s) in
                      sorted(stats.items())},
            "vocab": vocab, "seen": seen_keys(episodes), "n": len(rows),
            "loglik": round(ll, 4)}


def _stats_of(model):
    return {k: (m, s) for k, (m, s) in (model.get("stats") or {}).items()}


def predict(model, situation, options, counterpart=None):
    """-> {probs: {id: p}, utilities, contributions: {id: [(key, w*x)]}}
    from the logit arm alone. Rules and neighbors are layered on by
    twin.predict, which also owns the abstention mass."""
    stats, vocab = _stats_of(model), set(model.get("vocab") or [])
    w = model.get("weights") or {}
    xs = [featurize(situation or {}, o, counterpart, stats, vocab)
          for o in options]
    us = [_dot(w, x) for x in xs]
    ps = _softmax(us) if us else []
    out = {"probs": {}, "utilities": {}, "contributions": {}}
    for o, x, u, p in zip(options, xs, us, ps):
        oid = str(o.get("id"))
        out["probs"][oid] = p
        out["utilities"][oid] = u
        contrib = sorted(((k, w.get(k, 0.0) * v) for k, v in x.items()
                          if abs(w.get(k, 0.0) * v) > 1e-6),
                         key=lambda kv: -abs(kv[1]))[:6]
        out["contributions"][oid] = [(k, round(c, 4)) for k, c in contrib]
    return out


def attention(model, top=8):
    """What this person looks at: the features with the largest fitted
    weight, option identity removed, normalized to sum 1."""
    w = model.get("weights") or {}
    agg = {}
    for k, v in w.items():
        base = k.split("|", 1)[1] if "|" in k else k
        if base.startswith("opt:"):
            continue
        if "*" in base:
            # an interaction is attention paid to BOTH of its features
            head, pair = base.split(":", 1)
            for part in pair.split("*"):
                key = f"{head}:{part}"
                agg[key] = agg.get(key, 0.0) + abs(v) / 2
            continue
        agg[base] = agg.get(base, 0.0) + abs(v)
    total = sum(agg.values()) or 1.0
    ranked = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return [{"feature": k, "share": round(v / total, 4)} for k, v in ranked]


def signed_weights(model, top=8):
    """Per option identity, the situation features that push toward it —
    the 'trade-offs' line of the owner block reads from this."""
    w = model.get("weights") or {}
    out = {}
    for k, v in w.items():
        if "|" not in k:
            continue
        head, base = k.split("|", 1)
        out.setdefault(head[4:], []).append((base, round(v, 4)))
    for oid in out:
        out[oid] = sorted(out[oid], key=lambda kv: -abs(kv[1]))[:top]
    return out


# ------------------------------------------------------------ the rules

def _quantiles(vals, cuts=10):
    """Candidate thresholds at the deciles of what the owner has seen —
    fine enough to land near a real habit's threshold, coarse enough that
    a rule cannot be fitted to one episode."""
    s = sorted(vals)
    n = len(s)
    if n < 4:
        return []
    return sorted({s[(i * n) // cuts] for i in range(1, cuts)})


def predicates(episodes):
    """The atomic predicates a rule may use: numeric thresholds at the fit
    quartiles, counterparts, and situation terms with df >= 3."""
    nums, cps, tdf = {}, {}, {}
    for ep in episodes:
        for k, v in (ep.get("situation", {}).get("features") or {}).items():
            f = _num(v)
            if f is not None:
                nums.setdefault(k, []).append(f)
        if ep.get("counterpart"):
            c = str(ep["counterpart"]).lower()
            cps[c] = cps.get(c, 0) + 1
        for t in terms(ep.get("situation", {}).get("text")):
            tdf[t] = tdf.get(t, 0) + 1
    preds = []
    for k, vals in sorted(nums.items()):
        for t in _quantiles(vals):
            preds.append(("num_gt", k, t))
            preds.append(("num_le", k, t))
    for c, n in sorted(cps.items()):
        if n >= 3:
            preds.append(("cp", c, None))
    for t, n in sorted(tdf.items()):
        if n >= 3:
            preds.append(("term", t, None))
    return preds


def holds(pred, ep):
    kind, a, b = pred
    sit = ep.get("situation") or {}
    if kind in ("num_gt", "num_le"):
        f = _num((sit.get("features") or {}).get(a))
        if f is None:
            return False
        return f > b if kind == "num_gt" else f <= b
    if kind == "cp":
        return str(ep.get("counterpart") or "").lower() == a
    if kind == "term":
        return a in terms(sit.get("text"))
    return False


def describe(pred):
    kind, a, b = pred
    if kind == "num_gt":
        return f"{a} > {b:g}"
    if kind == "num_le":
        return f"{a} <= {b:g}"
    if kind == "cp":
        return f"counterpart is {a}"
    return f"situation mentions '{a}'"


def mine_rules(episodes, min_support=3, min_confidence=0.85, max_rules=40):
    """IF (one or two predicates) THEN choice — over recurring choice ids
    only (an option id that appears once cannot be a habit)."""
    eps = [ep for ep in episodes if ep.get("options") and ep.get("choice")
           is not None]
    choice_count = {}
    for ep in eps:
        c = str(ep["choice"])
        choice_count[c] = choice_count.get(c, 0) + 1
    targets = {c for c, n in choice_count.items() if n >= min_support}
    if not targets or not eps:
        return []
    base_rate = {c: choice_count[c] / len(eps) for c in targets}
    preds = predicates(eps)
    truth = [[holds(p, ep) for ep in eps] for p in preds]
    found = []

    def consider(idx_tuple):
        match = [i for i in range(len(eps))
                 if all(truth[j][i] for j in idx_tuple)]
        if len(match) < min_support:
            return
        for c in targets:
            k = sum(1 for i in match if str(eps[i]["choice"]) == c)
            conf = k / len(match)
            if conf >= min_confidence and conf > base_rate[c] * 1.1:
                found.append({
                    "if": [list(preds[j]) for j in idx_tuple],
                    "text": " AND ".join(describe(preds[j]) for j in idx_tuple),
                    "then": c, "support": len(match), "confidence": round(conf, 4),
                    "base_rate": round(base_rate[c], 4),
                    "lift": round(conf / base_rate[c], 3) if base_rate[c] else None,
                    "status": "candidate"})

    for j in range(len(preds)):
        consider((j,))
    for j in range(len(preds)):
        for k in range(j + 1, len(preds)):
            if preds[j][1] == preds[k][1] and preds[j][0] != preds[k][0]:
                continue        # x > t AND x <= t' is a band; keep it simple
            consider((j, k))
    # a two-predicate rule that adds no confidence over one of its parts is
    # noise; keep the simplest statement of each habit
    singles = {(tuple(map(tuple, r["if"]))[0], r["then"]): r["confidence"]
               for r in found if len(r["if"]) == 1}
    kept = []
    for r in found:
        if len(r["if"]) == 2:
            parts = [tuple(p) for p in r["if"]]
            if any(singles.get((p, r["then"]), 0) >= r["confidence"]
                   for p in parts):
                continue
        kept.append(r)
    kept.sort(key=lambda r: (-r["confidence"], -r["support"], r["text"]))
    return kept[:max_rules]


def validate_rules(rules, holdout, min_support=2, min_confidence=0.8):
    """A rule is PROVEN when it holds on episodes the miner never saw;
    otherwise it stays a candidate, with its held-out numbers attached."""
    out = []
    for r in rules:
        preds = [tuple(p) for p in r["if"]]
        match = [ep for ep in holdout if ep.get("options") and
                 all(holds(p, ep) for p in preds)]
        k = sum(1 for ep in match if str(ep.get("choice")) == r["then"])
        rec = dict(r)
        rec["holdout_support"] = len(match)
        rec["holdout_confidence"] = round(k / len(match), 4) if match else None
        rec["status"] = ("proven" if len(match) >= min_support and
                         k / len(match) >= min_confidence else "candidate")
        out.append(rec)
    return out


def rules_firing(rules, situation, counterpart):
    ep = {"situation": situation or {}, "counterpart": counterpart}
    return [r for r in rules if all(holds(tuple(p), ep) for p in r["if"])]


# --------------------------------------------------------------- scores

def logloss(p_chosen):
    return -math.log(max(min(p_chosen, 1.0), 1e-6))


def brier(probs, chosen):
    """Multi-class Brier: sum over options of (p - y)^2."""
    return sum((p - (1.0 if oid == chosen else 0.0)) ** 2
               for oid, p in probs.items())


def entropy_ratio(probs):
    ps = [p for p in probs.values() if p > 0]
    if len(ps) < 2:
        return 0.0
    h = -sum(p * math.log(p) for p in ps)
    return h / math.log(len(ps))


def ece(rows, bins=10):
    """rows: [(p_max, hit)] -> expected calibration error and the curve."""
    groups = [[] for _ in range(bins)]
    for p, hit in rows:
        groups[min(bins - 1, int(p * bins))].append((p, hit))
    curve, total = [], 0.0
    for i, g in enumerate(groups):
        n = len(g)
        if n:
            conf = sum(p for p, _ in g) / n
            acc = sum(1 for _, h in g if h) / n
            total += n * abs(conf - acc)
        curve.append({"lower": i / bins, "upper": (i + 1) / bins, "n": n,
                      "confidence": round(conf, 4) if n else None,
                      "accuracy": round(acc, 4) if n else None})
    return (round(total / len(rows), 4) if rows else None), curve


def kendall_tau(a, b):
    """Rank correlation between two orderings of the same ids."""
    ids = [x for x in a if x in set(b)]
    if len(ids) < 2:
        return None
    pa = {x: i for i, x in enumerate(a)}
    pb = {x: i for i, x in enumerate(b)}
    conc = disc = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            s = (pa[ids[i]] - pa[ids[j]]) * (pb[ids[i]] - pb[ids[j]])
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
    n = len(ids)
    return round((conc - disc) / (n * (n - 1) / 2), 4)


# ---------------------------------------------------------------- drift

class PageHinkley:
    """The cumulative change detector over a loss sequence.

    m_T = sum_t (x_t - mean_T - delta); PH_T = m_T - min_t m_t; trip when
    PH_T > lambda. State is a plain dict so it lives in drift.json.
    """

    def __init__(self, delta=0.005, lam=1.5, state=None):
        s = state or {}
        self.delta = s.get("delta", delta)
        self.lam = s.get("lambda", lam)
        self.n = s.get("n", 0)
        self.mean = s.get("mean", 0.0)
        self.m = s.get("m", 0.0)
        self.m_min = s.get("m_min", 0.0)

    def update(self, x):
        self.n += 1
        self.mean += (x - self.mean) / self.n
        self.m += x - self.mean - self.delta
        self.m_min = min(self.m_min, self.m)
        return (self.m - self.m_min) > self.lam

    def reset(self):
        self.n, self.mean, self.m, self.m_min = 0, 0.0, 0.0, 0.0

    def state(self):
        return {"delta": self.delta, "lambda": self.lam, "n": self.n,
                "mean": round(self.mean, 6), "m": round(self.m, 6),
                "m_min": round(self.m_min, 6),
                "ph": round(self.m - self.m_min, 6)}


# ------------------------------------------------------------- the style

FUNCTION_WORDS = [
    "the", "of", "and", "a", "to", "in", "that", "is", "was", "it", "for",
    "with", "as", "on", "be", "at", "by", "this", "not", "but", "from",
    "or", "an", "are", "which", "if", "we", "you", "i", "they", "he", "she",
    "so", "then", "than", "there", "would", "should", "could", "will",
    "just", "very", "really", "also", "only", "when", "what", "how",
    "because", "however", "therefore", "maybe", "perhaps", "actually",
    "basically", "ok", "okay", "yes", "no", "please", "thanks", "let",
    "us", "our", "my", "your", "their", "its", "into", "about", "over",
]
STYLE_DIMS = FUNCTION_WORDS + ["_sent_len", "_comma_rate", "_excl_rate",
                               "_question_rate", "_word_len"]


def style_vector(text):
    """Frequencies per 1000 words of each function word, plus five
    shape features — one row of the profile matrix."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    n = max(len(words), 1)
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    vec = {w: 1000.0 * counts.get(w, 0) / n for w in FUNCTION_WORDS}
    sents = [s for s in re.split(r"[.!?]+", text or "") if s.strip()]
    vec["_sent_len"] = n / max(len(sents), 1)
    vec["_comma_rate"] = 1000.0 * (text or "").count(",") / n
    vec["_excl_rate"] = 1000.0 * (text or "").count("!") / n
    vec["_question_rate"] = 1000.0 * (text or "").count("?") / n
    vec["_word_len"] = sum(len(w) for w in words) / n
    return vec


def style_profile(texts):
    """Mean and std per dimension over the owner's own documents."""
    rows = [style_vector(t) for t in texts if t and len(t.split()) >= 5]
    if not rows:
        return None
    prof = {}
    for d in STYLE_DIMS:
        vals = [r[d] for r in rows]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        prof[d] = [round(mean, 4), round(math.sqrt(var), 4)]
    return {"dims": prof, "docs": len(rows),
            "words": sum(len(t.split()) for t in texts)}


def burrows_delta(profile, text):
    """Mean absolute z-score distance from the profile. Smaller is closer.
    A dimension the owner never varies on (std 0) is compared at a floor,
    so one habit cannot dominate."""
    if not profile:
        return None
    v = style_vector(text)
    total, n = 0.0, 0
    for d, (mean, std) in profile["dims"].items():
        floor = max(std, 0.5 if d.startswith("_") else 1.0)
        total += abs(v[d] - mean) / floor
        n += 1
    return round(total / n, 4) if n else None
