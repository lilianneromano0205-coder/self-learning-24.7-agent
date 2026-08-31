"""Experimental constrained memory choices; never a production authority.

No filesystem mutation. External institutional records are immutable here.
Only policy-created tier-4 working notes may be revised or hidden, never erased.
"""
import copy
import hashlib
import json
import math
import time

import retrieval

ACTIONS = ("store", "retrieve", "update", "summarize", "discard")


class MemoryPolicy:
    def __init__(self, records, *, enabled=False):
        records = copy.deepcopy(list(records))
        if any(not r.get("id") for r in records) or len({r["id"] for r in records}) != len(records):
            raise ValueError("unique memory ids required")
        self._records = {r["id"]: r for r in records}
        self._owned = set()                 # never read ownership from supplied metadata
        self.enabled = enabled is True
        self.receipts = []
        self._feedback = {}

    def snapshot(self):
        return copy.deepcopy(list(self._records.values()))

    def _mutable(self, key):
        record = self._records[key]
        if (key not in self._owned or record.get("protected") or record.get("retracted")
                or record.get("superseded_by") or record.get("source_tier") != 4):
            raise PermissionError("institutional evidence, authority and retractions are immutable")
        return record

    def apply(self, action, **args):
        if not self.enabled:
            raise PermissionError("experimental memory policy is disabled")
        allowed = {"store": {"id", "text"}, "retrieve": {"query", "limit"},
                   "update": {"id", "text"}, "summarize": {"id", "ids"}, "discard": {"id"}}
        if action not in allowed or set(args) - allowed[action]:
            raise ValueError("unknown action or protected metadata mutation")
        before = hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True).encode()).hexdigest()
        key = args.get("id")
        if action in ("store", "summarize"):
            if not isinstance(key, str) or not key or key in self._records:
                raise ValueError("new unique memory id required")
            if action == "summarize":
                ids = args.get("ids", [])
                if not ids:
                    raise ValueError("summary needs source notes")
                # Extractive and append-only: it cannot turn a retraction into a
                # positive claim, elevate tier, or erase the original material.
                inputs = [self._mutable(i) for i in ids]
                if any(not r.get("valid", True) for r in inputs):
                    raise PermissionError("discarded notes cannot be summarized back into validity")
                text = "\n".join(r["text"] for r in inputs)
            else:
                text = args.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("non-empty note text required")
            result = dict(id=key, text=text, source_tier=4, provenance=f"experimental-policy:{key}",
                          observed_at=time.time(), valid=True, retracted=False, superseded_by=None,
                          protected=False, kind="memory_files", versions=[])
            if action == "summarize":
                result["derived_from"] = list(ids)
                result["source_provenance"] = [r["provenance"] for r in inputs]
            self._records[key] = result
            self._owned.add(key)
        elif action == "retrieve":
            result = retrieval.rank(self.snapshot(), args.get("query", ""), args.get("limit", 12))
        else:
            result = self._mutable(key)
            if action == "update":
                if not isinstance(args.get("text"), str) or not args["text"].strip():
                    raise ValueError("non-empty update required")
                result["versions"].append(dict(text=result["text"], observed_at=result["observed_at"]))
                result["text"] = args["text"]
                result["observed_at"] = time.time()
            else:
                result["valid"] = False
                result["discarded_at"] = time.time()
        after = hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True).encode()).hexdigest()
        receipt = dict(id=f"memory-action-{len(self.receipts)}", action=action,
                       before_sha256=before, after_sha256=after, experimental=True)
        self.receipts.append(receipt)
        return copy.deepcopy(result)

    def observe(self, receipt_id, verified_utility):
        """Trusted experiment runner submits measured utility, never model advice."""
        if receipt_id in self._feedback or not any(r["id"] == receipt_id for r in self.receipts):
            raise ValueError("feedback requires a fresh execution receipt")
        if (type(verified_utility) not in (int, float) or not math.isfinite(verified_utility)
                or not -1 <= verified_utility <= 1):
            raise ValueError("utility must be finite and between -1 and 1")
        self._feedback[receipt_id] = verified_utility

    def choose(self, allowed_actions):
        """Empirical utility policy; caller constraints and apply guards still win."""
        allowed = list(allowed_actions)
        if not self.enabled or not allowed or not set(allowed) <= set(ACTIONS):
            raise ValueError("explicit allowed experimental actions required")
        def mean(action):
            values = [self._feedback[r["id"]] for r in self.receipts
                      if r["action"] == action and r["id"] in self._feedback]
            return sum(values) / len(values) if values else 0
        return sorted(allowed, key=lambda a: (-mean(a), ACTIONS.index(a)))[0]
