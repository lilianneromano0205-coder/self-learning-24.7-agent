"""Institutional hybrid ranking. Metadata gates run BEFORE any embedding call.

Embedding code is optional, local-only and never downloads models. Returned
records keep their authority/validity metadata; similarity cannot grant trust.
"""
import math
import os
import re
import time
from datetime import datetime, timezone


def tokens(text):
    return re.findall(r"[a-zà-ÿ0-9][a-zà-ÿ0-9_-]{1,}", str(text).lower())


def timestamp(value):
    if value is None or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
        except (ValueError, TypeError):
            return None


def valid_at(record, now):
    if record.get("valid", True) is not True:
        return False
    if record.get("retracted") or record.get("superseded_by"):
        return False
    if record.get("contradiction") in ("unresolved", "rejected"):
        return False
    for key, lower in (("valid_from", True), ("valid_until", False)):
        value = record.get(key)
        if value is not None:
            stamp = timestamp(value)
            if stamp is None or (lower and stamp > now) or (not lower and stamp <= now):
                return False
    return True


class LocalEmbeddings:
    """Explicit owner-supplied local SentenceTransformer directory, CPU default.

    No network fallback, model-code trust or provider credentials. Dependency or
    model absence is handled by the retrieval caller as lexical fallback.
    """
    def __init__(self, model_path):
        if not os.path.isabs(model_path) or not os.path.isdir(model_path):
            raise ValueError("embeddings require an existing absolute local model directory")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_path, device="cpu", local_files_only=True,
                                         trust_remote_code=False)

    def __call__(self, texts):
        return self.model.encode(texts, normalize_embeddings=True,
                                 show_progress_bar=False).tolist()


def _cosines(vectors):
    if not vectors or not vectors[0]:
        raise ValueError("empty vectors")
    width = len(vectors[0])
    normalized = []
    for vector in vectors:
        if len(vector) != width or not all(math.isfinite(float(x)) for x in vector):
            raise ValueError("invalid vector")
        norm = math.sqrt(sum(float(x) ** 2 for x in vector))
        if norm == 0:
            raise ValueError("zero vector")
        normalized.append([float(x) / norm for x in vector])
    return [sum(a * b for a, b in zip(normalized[0], v)) for v in normalized[1:]]


def rank(records, query, limit=12, *, mode="hybrid", embedder=None, kinds=None,
         source_tier_max=4, task_type=None, now=None, include_invalid=False,
         metadata=None):
    """Token overlap + cosine + small authority/freshness/task reranking.

    `records` and metadata are supplied by trusted collectors, not interpreted
    from an actor's arbitrary authority claims. Dense-only mode is the simple
    RAG baseline. Historical retrieval retains an explicit valid=False marker.
    """
    if mode not in ("hybrid", "lexical", "dense", "no_memory"):
        raise ValueError("unknown retrieval mode")
    if mode == "no_memory" or limit <= 0 or not tokens(query):
        return []
    now = time.time() if now is None else now
    terms = set(tokens(query))
    rows = []
    for original in records:
        row = dict(original)
        tier = row.get("source_tier", 4)
        if type(tier) is not int or tier not in (1, 2, 3, 4):
            tier = 4
        row["source_tier"] = tier
        row.setdefault("provenance", row.get("ref", "unknown"))
        row.setdefault("observed_at", None)
        row.setdefault("retracted", False)
        row.setdefault("superseded_by", None)
        row.setdefault("contradiction", None)
        row["valid"] = valid_at(row, now)
        if not row["valid"] and not include_invalid:
            continue
        if tier > source_tier_max or (kinds is not None and row.get("kind") not in kinds):
            continue
        if metadata and any(row.get(k) != v for k, v in metadata.items()):
            continue
        rows.append(row)
    semantic = [0.0] * len(rows)
    used = "lexical"
    if mode in ("hybrid", "dense") and embedder is not None and rows:
        try:
            vectors = embedder([str(query)] + [r["text"] for r in rows])
            if len(vectors) != len(rows) + 1:
                raise ValueError("embedding count mismatch")
            semantic = _cosines(vectors)
            used = mode
        except Exception:
            used = "lexical_fallback"
    if mode == "dense" and used != "dense":
        return []                 # never quietly mislabel lexical as dense RAG
    hits = []
    for row, similarity in zip(rows, semantic):
        words = tokens(row["text"])
        matched = terms.intersection(words)
        overlap = len(matched) / len(terms)
        if not matched and similarity < 0.25:
            continue
        lexical = len(matched) * 100 + (50 if len(matched) == len(terms) else 0)
        lexical += sum(words.count(t) for t in terms)
        observed = timestamp(row["observed_at"])
        freshness = 0 if observed is None else 1 / (1 + max(0, now - observed) / 2592000)
        if mode == "dense":
            score = max(0, similarity) * 300
        else:
            score = lexical + (max(0, similarity) * 200 if used == "hybrid" else 0)
            score += (5 - row["source_tier"]) * 2 + freshness
            if task_type and row.get("task_type") == task_type:
                score += 3
        row.update(score=round(score, 6), lexical_score=lexical,
                   semantic_score=round(similarity, 6), retrieval_mode=used)
        hits.append(row)
    return sorted(hits, key=lambda r: (-r["score"], str(r.get("id", r.get("ref", "")))))[:limit]
