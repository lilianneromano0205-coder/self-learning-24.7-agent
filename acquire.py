#!/usr/bin/env python3
"""CAPABILITY ACQUISITION — getting a new tool without getting new authority.

Manual §12. The pipeline it specifies, in order:

    1. detect a capability gap
    2. search the trusted Tool/Skill/MCP registry
    3. if missing, search approved external catalogues
    4. inspect provenance, permissions, package source, required secrets
    5. install ONLY in an isolated disposable worker
    6. run a generated capability test and a security check
    7. register the exact version/hash, permissions and evidence if it passes
    8. promotion to organization-wide trust requires policy-defined approval

Validation gate invariants: *"No host/control-plane installs; exact
version/provenance recorded; permissions least-privilege; capability test
mandatory; rollback/removal possible."*

The load-bearing idea is that acquisition is a LADDER, not a switch. A tool
moves candidate → tested → trusted, and each rung is earned by evidence that
is recorded. Nothing arrives trusted, and nothing becomes trusted because it
worked once in the moment somebody needed it to.

Two refusals are absolute and both are structural rather than advisory:

  * an install never runs on the host or on the control plane. If no
    disposable worker exists, acquisition FAILS — it does not fall back to
    "well, just this once".
  * a capability test is mandatory. A tool that installed cleanly has proven
    that it installs, which is not the same as proving it does the job.
"""

import hashlib
import json
import os
import re
import time

LEDGER = "acquisitions.json"

# The rungs. A tool is only as trusted as the evidence behind it.
STAGES = ("requested", "inspected", "installed", "tested", "trusted",
          "rejected", "removed")

# Package sources we will consider at all, and what each one costs to trust.
SOURCES = {
    "pypi": {"kind": "python package index", "pin": "version + hash"},
    "npm": {"kind": "node package registry", "pin": "version + integrity"},
    "apt": {"kind": "system package", "pin": "version"},
    "mcp": {"kind": "MCP server", "pin": "command + args"},
    "skill": {"kind": "an Agent Skill folder", "pin": "content hash"},
}

# Signals that a package is not what it appears to be. Deliberately blunt:
# this is a tripwire, not a malware scanner, and it says so.
RISK_SIGNALS = (
    (r"\bcurl\s+[^|]*\|\s*(ba)?sh", "pipes a download straight into a shell"),
    (r"\bwget\s+[^|]*\|\s*(ba)?sh", "pipes a download straight into a shell"),
    (r"setup\.py.*install_requires.*http", "installs from a raw URL"),
    # no \b around the keyword: the interesting names are API_KEY, AWS_SECRET,
    # GITHUB_TOKEN — where the preceding underscore is a word character, so a
    # word boundary would never match the thing we are looking for
    (r"os\.environ.{0,40}(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)",
     "reads credentials"),
    (r"(getenv|environ\.get)\s*\(\s*['\"][^'\"]*"
     r"(KEY|TOKEN|SECRET|PASSWORD)", "reads credentials"),
    (r"\bbase64\.b64decode\b.*\bexec\b", "executes decoded content"),
    (r"\beval\s*\(.*\brequests?\.get\b", "executes fetched content"),
    (r"\b(rm\s+-rf\s+/|del\s+/s\s+/q\s+c:)", "destructive filesystem command"),
    (r"\.ssh/|id_rsa|authorized_keys", "touches SSH material"),
    (r"/etc/(passwd|shadow)", "touches system credentials"),
)

# Typosquat bait: a name one edit away from something very common.
POPULAR = ("requests", "urllib3", "numpy", "pandas", "flask", "django",
           "pytest", "boto3", "pillow", "cryptography", "setuptools",
           "python-dateutil", "certifi", "click", "jinja2", "lxml")


class Refused(Exception):
    """Acquisition said no. The message is what the agent and owner see."""


def _path(root):
    return os.path.join(root, LEDGER)


def load(root):
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(root, rows):
    tmp = f"{_path(root)}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    os.replace(tmp, _path(root))
    return rows


def _edit_distance(a, b):
    if abs(len(a) - len(b)) > 2:
        return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# --------------------------------------------------------------- 1. search

def search_known(root, need):
    """Step 2: look in what we already trust BEFORE reaching outside.

    The cheapest capability acquisition is the one you already made.
    """
    need = str(need or "").lower()
    hits = []
    for row in load(root):
        if row["stage"] != "trusted":
            continue
        hay = f"{row['name']} {row.get('provides','')} {row.get('why','')}".lower()
        if need and any(w in hay for w in need.split() if len(w) > 3):
            hits.append(row)
    try:
        import toolbox
        for t in toolbox.scan(root).get("tools", []):
            if t.get("ready") and need and any(
                    w in f"{t['name']} {t.get('desc','')}".lower()
                    for w in need.split() if len(w) > 3):
                hits.append({"name": t["name"], "stage": "trusted",
                             "source": "toolbox", "provides": t.get("desc", "")})
    except Exception:
        pass
    return hits


# -------------------------------------------------------------- 2. inspect

def inspect(name, source, version="", manifest_text="", requires_secrets=None):
    """Step 4: look before installing. Returns a risk report; RAISES only for
    the things no review should ever wave through."""
    if source not in SOURCES:
        raise Refused(f"unknown package source {source!r}; approved sources "
                      f"are: {', '.join(sorted(SOURCES))}")
    findings, blocking = [], []
    nm = str(name or "").strip().lower()
    if not nm or not re.fullmatch(r"[a-z0-9][a-z0-9._@/-]{0,80}", nm):
        raise Refused(f"refusing a package name that is not a plain "
                      f"identifier: {name!r}")
    if not version:
        blocking.append(
            "no version pinned. An unpinned dependency is a different "
            "dependency tomorrow, and the evidence recorded today would "
            "describe something that no longer exists.")
    for popular in POPULAR:
        if nm != popular and _edit_distance(nm, popular) == 1:
            blocking.append(
                f"{nm!r} is one character from {popular!r} — the classic "
                f"typosquat shape. If this is genuinely the package you want, "
                f"say so explicitly.")
    for pattern, why in RISK_SIGNALS:
        if re.search(pattern, manifest_text or "", re.I):
            findings.append(why)
    secrets = list(requires_secrets or [])
    if secrets:
        findings.append(f"asks for credentials: {', '.join(secrets)}")
    return {
        "name": nm, "source": source, "version": version,
        "findings": findings, "blocking": blocking,
        "requires_secrets": secrets,
        "verdict": "blocked" if blocking else ("review" if findings else "clean"),
    }


# -------------------------------------------------------------- 3. acquire

def request(root, name, source, need, version="", manifest_text="",
            requires_secrets=None, requested_by="practitioner"):
    """Steps 1–4: record the gap, check what we already have, inspect."""
    known = search_known(root, need)
    if known:
        raise Refused(
            f"we already have this capability: "
            + ", ".join(k["name"] for k in known[:3])
            + ". Use it rather than installing something new — an unnecessary "
              "dependency is permanent and a search is free.")
    report = inspect(name, source, version, manifest_text, requires_secrets)
    rows = load(root)
    rec = {
        "id": f"acq-{hashlib.sha256((name + source + version).encode()).hexdigest()[:8]}",
        "name": report["name"], "source": source, "version": version,
        "need": str(need)[:300], "provides": "", "why": str(need)[:200],
        "stage": "rejected" if report["verdict"] == "blocked" else "inspected",
        "inspection": report, "requested_by": requested_by,
        "worker": None, "install_evidence": None, "test_evidence": None,
        "content_hash": None, "permissions": [],
        "history": [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "stage": "requested", "why": str(need)[:200]}],
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    rows = [r for r in rows if r["id"] != rec["id"]] + [rec]
    _save(root, rows)
    if report["verdict"] == "blocked":
        raise Refused("inspection blocked this acquisition: "
                      + " ".join(report["blocking"]))
    return rec


def install(root, home, acq_id, worker_id=None, task_text=""):
    """Step 5: install ONLY in an isolated disposable worker.

    There is no host fallback. If there is no disposable computer, this
    fails — because "just this once, on the host" is how a governed pipeline
    stops being one.
    """
    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    if rec["stage"] not in ("inspected", "installed"):
        raise Refused(f"{acq_id} is at stage {rec['stage']}; only an inspected "
                      f"acquisition may be installed")
    import workers
    w = workers.get(home, worker_id) if worker_id else None
    if w is None:
        w, _why = workers.choose(home, task_text or "install a package")
    if w is None:
        raise Refused(
            "no computer is available to install into. Acquisition needs a "
            "DISPOSABLE worker; add one under Resources -> Computers "
            "(Local Docker is the usual answer).")
    if w["zone"] != "isolated":
        raise Refused(
            f"refusing to install on {w['name']} ({w['zone']} zone). A new "
            f"dependency is untrusted code by definition, so it goes in a "
            f"disposable computer — never on the host and never on an "
            f"organization machine.")
    rec["worker"] = w["id"]
    rec["stage"] = "installed"
    rec["install_evidence"] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "worker": w["id"],
        "zone": w["zone"],
        "command": f"(install {rec['name']}=={rec['version']} in {w['name']})",
    }
    rec["history"].append({"at": rec["install_evidence"]["at"],
                           "stage": "installed", "why": f"in {w['name']}"})
    _save(root, rows)
    return rec


def capability_test(root, acq_id, passed, evidence, command=""):
    """Step 6: MANDATORY. A tool that installed has proven it installs."""
    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    if rec["stage"] != "installed":
        raise Refused(f"{acq_id} is at stage {rec['stage']}; a capability test "
                      f"runs against an installed tool")
    if not str(evidence).strip():
        raise Refused("a capability test records what it OBSERVED; a pass "
                      "with no evidence is a claim")
    rec["test_evidence"] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "passed": bool(passed),
        "evidence": str(evidence)[:500], "command": str(command)[:300]}
    rec["stage"] = "tested" if passed else "rejected"
    rec["history"].append({"at": rec["test_evidence"]["at"],
                           "stage": rec["stage"],
                           "why": str(evidence)[:200]})
    _save(root, rows)
    return rec


def promote(root, acq_id, by="owner", permissions=None, provides=""):
    """Step 8: the OWNER grants trust. Never the agent, never the outcome."""
    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    if rec["stage"] != "tested":
        raise Refused(
            f"{acq_id} is at stage {rec['stage']}. Trust is granted to a tool "
            f"that passed a capability test — not to one that merely "
            f"installed, and never to one that was only requested.")
    if not (rec.get("test_evidence") or {}).get("passed"):
        raise Refused("this acquisition's capability test did not pass")
    rec["stage"] = "trusted"
    rec["permissions"] = sorted(set(permissions or []))
    rec["provides"] = provides or rec.get("need", "")[:200]
    rec["promoted_by"] = by
    rec["history"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "stage": "trusted", "why": f"promoted by {by}"})
    _save(root, rows)
    return rec


def remove(root, acq_id, why="", by="owner"):
    """Rollback is mandatory in the validation gate, so it is a first-class
    operation rather than an afterthought."""
    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    rec["stage"] = "removed"
    rec["history"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "stage": "removed", "why": f"{by}: {why}"[:200]})
    _save(root, rows)
    return rec


def trusted(root):
    return [r for r in load(root) if r["stage"] == "trusted"]


def summary(root):
    rows = load(root)
    by_stage = {}
    for r in rows:
        by_stage.setdefault(r["stage"], []).append(r["name"])
    return {"total": len(rows), "by_stage": by_stage,
            "trusted": [r["name"] for r in rows if r["stage"] == "trusted"]}


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("request")
    p.add_argument("name"); p.add_argument("--source", required=True,
                                           choices=sorted(SOURCES))
    p.add_argument("--version", default=""); p.add_argument("--need", required=True)
    p.add_argument("--root", default=".")
    p = sub.add_parser("list"); p.add_argument("--root", default=".")
    p = sub.add_parser("promote"); p.add_argument("id")
    p.add_argument("--root", default="."); p.add_argument("--can", action="append",
                                                          default=[])
    p = sub.add_parser("remove"); p.add_argument("id")
    p.add_argument("--why", default=""); p.add_argument("--root", default=".")
    p = sub.add_parser("stages")
    a = ap.parse_args()
    if a.cmd == "stages":
        print("requested -> inspected -> installed -> tested -> trusted")
        print("  each rung is earned by recorded evidence; nothing arrives "
              "trusted, and only the owner grants the last one")
        return
    root = os.path.abspath(a.root)
    if a.cmd == "request":
        try:
            rec = request(root, a.name, a.source, a.need, a.version)
            print(f"{rec['id']}: {rec['stage']} "
                  f"({rec['inspection']['verdict']})")
            for f in rec["inspection"]["findings"]:
                print(f"  review: {f}")
        except Refused as e:
            print(f"REFUSED: {e}")
            raise SystemExit(1)
        return
    if a.cmd == "promote":
        rec = promote(root, a.id, permissions=a.can)
        print(f"{rec['name']} is now trusted (permissions: "
              f"{', '.join(rec['permissions']) or 'none declared'})")
        return
    if a.cmd == "remove":
        print("removed", remove(root, a.id, a.why)["name"])
        return
    s = summary(root)
    print(f"{s['total']} acquisition(s)")
    for stage, names in sorted(s["by_stage"].items()):
        print(f"  {stage:<12} {', '.join(names)}")


if __name__ == "__main__":
    main()
