#!/usr/bin/env python3
"""Build the distributable archive.

Ships the code, prompts, tests, and deployment files — never private data:
no experts' memory, no API keys, no logs, no task state. Empty working
directories are created so a fresh unzip is immediately runnable.

Usage:  python package.py [--out ../learning-agent-core.zip]
"""

import argparse
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {"experts", "demo-run", "logs", "contexts", "__pycache__",
             "tmp", ".git", "node_modules", "federation", "backups",
             "retired", "teamwork", "goals", "consults", "approvals",
             "events", "checkpoints"}
# Credential exclusion is NOT a list here any more. It used to be, and it
# disagreed with backup.py's list: this one lacked identity.json, and
# `federation/` was not skipped, so the distributable shipped the fleet's
# HMAC secret while printing "no private data included". credentials.py is
# the single answer now; SKIP_FILES only covers non-secret working state.
SKIP_FILES = {"state.json", "briefing.md", "commons-digest.md"}
SKIP_EXT = {".pyc", ".log", ".tmp", ".zip"}
EMPTY_DIRS = ["inbox", "courses", "logs", "contexts", "skills", "experts"]


def name_is_settings(rel):
    return os.path.basename(rel).lower() == "settings.toml"


def should_skip(rel, full=None):
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts):
        return True
    name = parts[-1]
    if name in SKIP_FILES or os.path.splitext(name)[1] in SKIP_EXT:
        return True
    if name.startswith("state.json.corrupt-") or name.startswith("spend-"):
        return True
    if full:
        import credentials
        if credentials.is_secret(full, HERE):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(HERE, "..",
                                                  "learning-agent-core.zip"))
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(HERE):
            dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, HERE).replace(os.sep, "/")
                if should_skip(rel, full):
                    continue
                try:
                    if name_is_settings(rel):
                        import credentials
                        with open(full, "r", encoding="utf-8-sig") as sf:
                            z.writestr(rel, credentials.redact(sf.read()))
                    else:
                        z.write(full, rel)
                    n += 1
                except OSError as e:
                    print(f"  skipped (in use): {rel} — {e}")
        existing = set(z.namelist())
        for d in EMPTY_DIRS:
            if f"{d}/.gitkeep" not in existing:
                z.writestr(f"{d}/.gitkeep", "")
    size = os.path.getsize(out)
    print(f"wrote {out}\n  {n} files, {size/1024:.0f} KB, no private data included")


if __name__ == "__main__":
    main()
