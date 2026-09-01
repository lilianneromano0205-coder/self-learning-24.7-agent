"""Owner-created immutable learning records, outside fleet experts.

This is a tamper-detecting custody boundary, not host-process containment.
Standalone roots use org/learning and MUST hide that directory from workers.
Deleting/replacing both the records and ledger requires defeating the owner's
filesystem authority; these hashes do not make an unrestricted host safe.
"""
import hashlib
import json
from pathlib import Path
import re

import controlplane
import locks


class Refused(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value):
        raise Refused("invalid learning record identifier")
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def directory(root):
    root = Path(root).absolute()
    base = root.parent.parent if root.parent.name.lower() == "experts" else root
    path = base / "org" / "learning"
    # A junction/symlink must never relocate authority into a worker path.
    for p in (path, *path.parents):
        if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
            raise Refused("TAMPER: redirected learning authority path")
    return path


def _key(root, namespace, key):
    expert = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]
    return f"{expert}-{identifier(namespace)}-{identifier(key)}"


def load(root, namespace, key):
    name = _key(root, namespace, key)
    path = directory(root)
    try:
        rows = [json.loads(line) for line in (path / "seals.jsonl").read_text(encoding="utf-8").splitlines() if line]
        seals = [r["sha256"] for r in rows if r["key"] == name]
        record = path / (name + ".json")
        if record.is_symlink():
            raise Refused("TAMPER: redirected learning record")
        value = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refused("missing or TAMPERed sealed learning record") from exc
    if not seals or len(set(seals)) != 1 or digest(value) != seals[0]:
        raise Refused("TAMPER: conflicting or changed learning seal")
    return value


def store(root, namespace, key, value):
    controlplane.owner_only("seal learning evaluation authority")
    name = _key(root, namespace, key)
    path = directory(root)
    path.mkdir(parents=True, exist_ok=True)
    ledger = path / "seals.jsonl"
    with locks.holding(str(ledger), timeout=5):
        record = path / (name + ".json")
        # Never make a newer append authoritative, including crash remnants.
        if record.exists() or (ledger.exists() and any(
                json.loads(line).get("key") == name
                for line in ledger.read_text(encoding="utf-8").splitlines() if line)):
            raise Refused("sealed learning record already exists; use a new experiment")
        blob = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with record.open("x", encoding="utf-8") as stream:
            stream.write(blob)
        with ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"key": name, "sha256": digest(value)}) + "\n")
    return value
