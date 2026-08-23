#!/usr/bin/env python3
"""Fiber-style checkpoints for long tool work — recover, don't restart.

Cloudflare's 2026 long-running-agent model: a task that may outlive its
process checkpoints progress (`stash()`), and on the next activation
recovers from the last checkpoint (`onFiberRecovered`) instead of replaying
from zero. A twenty-minute transcription that dies at chunk 17 must resume
at chunk 18 — paying again for the first seventeen is waste at best and, for
effectful work, a duplicated side effect at worst.

A Checkpoint is a small JSON record keyed by the task LINEAGE (shared by all
retries) plus the operation and its inputs, kept under <base>/checkpoints/:

  ck = Checkpoint(base, key_for("transcribe", src, dst))
  for item in items:
      if ck.is_done(item):          # recovered from a previous activation
          ...use ck.get(...)...; continue
      ...do the work...
      ck.mark(item, **state)        # durable before the next item starts
  ck.finish()

Atomic writes with the OneDrive retry loop; the ledger is append-style
(done items are never removed) so a crash between mark() and the next item
loses at most one item's work, never the whole job.
"""

import hashlib
import json
import os
import time

DIR = "checkpoints"


def key_for(op, *parts):
    lineage = os.environ.get("AGENT_TASK_LINEAGE") or "manual"
    blob = "|".join(str(p) for p in parts)
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
    return f"{lineage}|{op}|{h}"


def _atomic_write(path, obj):
    # unique per writer: two processes checkpointing the same key shared one
    # ".tmp" and could publish each other's half-written scratch file
    import uuid as _uuid
    tmp = f"{path}.{os.getpid()}.{_uuid.uuid4().hex[:8]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


class Checkpoint:
    def __init__(self, base, key):
        self.base = os.path.abspath(base)
        self.key = key
        self.op = key.split("|")[1] if key.count("|") >= 2 else key
        d = os.path.join(self.base, DIR)
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(
            d, hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] + ".json")
        self.rec = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                rec = json.load(f)
            if rec.get("key") == self.key:
                return rec
        except (OSError, ValueError):
            pass
        return {"key": self.key, "op": self.op,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "updated": None, "done": [], "state": {}, "finished": False}

    def _save(self):
        self.rec["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _atomic_write(self.path, self.rec)

    def is_done(self, item):
        return str(item) in self.rec["done"]

    def mark(self, item, **state):
        if str(item) not in self.rec["done"]:
            self.rec["done"].append(str(item))
        self.rec["state"].update(state)
        self._save()

    def get(self, name, default=None):
        return self.rec["state"].get(name, default)

    def put(self, name, value):
        self.rec["state"][name] = value
        self._save()

    def finish(self):
        self.rec["finished"] = True
        self._save()

    @property
    def recovered(self):
        return len(self.rec["done"])


def list_checkpoints(base, lineage=None):
    d = os.path.join(base, DIR)
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if lineage and not str(rec.get("key", "")).startswith(lineage + "|"):
            continue
        out.append(rec)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--lineage")
    a = ap.parse_args()
    for r in list_checkpoints(os.path.abspath(a.root), a.lineage):
        print(f"{r['key'][:40]:<42} {r['op']:<14} done={len(r['done'])} "
              f"finished={r['finished']} updated={r['updated']}")
