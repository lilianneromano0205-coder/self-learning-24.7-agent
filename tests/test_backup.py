#!/usr/bin/env python3
"""A platform without a tested restore has hopes, not backups (M11).

1. a backup carries the fleet's memory -- identities, courses, notes,
   skills, commons, state, archives
2. it NEVER carries credentials, whatever the caller asks for
3. every file is checksummed, and `verify` actually recomputes them: a
   tampered archive is reported as damaged, not restored
4. restore round-trips byte-for-byte into a fresh directory, refuses a
   non-empty one, and refuses an archive that fails verification
5. a zip-slip entry cannot escape the destination
6. the age helpers the preflight depends on are real

Run from the agent/ directory:  python tests/test_backup.py
"""

import json
import os
import sys
import zipfile

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import backup
import fleet


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


SECRET = "sk-live-NEVER-IN-A-BACKUP"


def main():
    home = make_sandbox("backup", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Archivist", "keeps what matters")
    write(root, "courses/history/notes.md",
          "- C-0101 the fleet remembers [src: https://example.org/a]\n")
    write(root, "skills/keep-notes.md", "KEYWORDS: notes\nWrite them down.\n")
    write(home, "commons/lessons.md", "- [2026-08-22] (archivist) verify restores\n")
    write(home, "agent.env", f"OPENROUTER_API_KEY={SECRET}\n")
    write(home, "ui-token.txt", "tok-abc-123\n")
    write(root, "agent.env", f"OPENROUTER_API_KEY={SECRET}\n")
    write(root, "logs/agent.log", '{"event": "task_end"}\n')

    out_dir = os.path.join(home, "backups")
    man = backup.create(home, out_dir)

    # --- 1 + 2. it carries the memory, never the keys
    paths = {e["path"] for e in man["entries"]}
    for expected in ("experts/archivist/identity.md",
                     "experts/archivist/courses/history/notes.md",
                     "experts/archivist/skills/keep-notes.md",
                     "experts/archivist/settings.toml",
                     "commons/lessons.md"):
        assert expected in paths, f"the backup lost {expected}"
    assert man["experts"] == ["archivist"], man["experts"]
    assert not any(p.endswith("agent.env") or p.endswith("ui-token.txt")
                   for p in paths), sorted(paths)[:8]
    assert man["secrets_excluded"] >= 3, man["secrets_excluded"]
    assert not any("logs/" in p for p in paths), "logs are excluded by default"
    with zipfile.ZipFile(man["path"]) as z:
        blob = b"".join(z.read(n) for n in z.namelist())
    assert SECRET.encode() not in blob, "A KEY REACHED THE ARCHIVE"
    print("[contents] the archive carries identities, courses, notes, skills "
          "and the commons -- and not one credential")

    with_logs = backup.create(home, out_dir, with_logs=True, label="logs")
    assert any("logs/" in e["path"] for e in with_logs["entries"])
    with zipfile.ZipFile(with_logs["path"]) as z:
        assert SECRET.encode() not in b"".join(
            z.read(n) for n in z.namelist()), "keys stay out even --with-logs"
    print("[opt-in] --with-logs adds the audit trail and still excludes keys")

    # --- 3. verification is real
    ok, rep = backup.verify(man["path"])
    assert ok and rep["files"] == man["files"] and not rep["secrets_leaked"]
    tampered = os.path.join(home, "tampered.zip")
    with zipfile.ZipFile(man["path"]) as src, \
            zipfile.ZipFile(tampered, "w") as dst:
        for n in src.namelist():
            data = src.read(n)
            if n.endswith("courses/history/notes.md"):
                data = b"- C-0101 something a thief substituted\n"
            dst.writestr(n, data)
    ok2, rep2 = backup.verify(tampered)
    assert not ok2 and rep2["corrupt"], rep2
    assert any("notes.md" in c for c in rep2["corrupt"]), rep2["corrupt"]
    print("[integrity] every file is checksummed, and a single substituted "
          "byte makes the archive report itself DAMAGED")

    # --- 4. the restore round trip
    dest = os.path.join(home, "restored")
    rep3 = backup.restore(man["path"], dest)
    assert rep3["restored_to"] == os.path.abspath(dest)
    assert "keys back" in rep3["next"]
    orig = os.path.join(root, "courses", "history", "notes.md")
    back = os.path.join(dest, "experts", "archivist", "courses", "history",
                        "notes.md")
    assert open(orig, encoding="utf-8").read() == \
        open(back, encoding="utf-8").read(), "restore must be byte-for-byte"
    assert not os.path.exists(os.path.join(dest, "agent.env"))
    try:
        backup.restore(man["path"], dest)
        raise AssertionError("a non-empty destination must be refused")
    except FileExistsError as e:
        assert "not empty" in str(e)
    backup.restore(man["path"], dest, force=True)      # explicit override works
    try:
        backup.restore(tampered, os.path.join(home, "restored2"))
        raise AssertionError("a damaged archive must never be restored")
    except ValueError as e:
        assert "damaged" in str(e)
    print("[restore] round-tripped byte-for-byte, refused a non-empty "
          "destination, and refused to restore a damaged archive")

    # --- 5. zip slip
    evil = os.path.join(home, "evil.zip")
    with zipfile.ZipFile(man["path"]) as src, zipfile.ZipFile(evil, "w") as dst:
        for n in src.namelist():
            dst.writestr(n, src.read(n))
        dst.writestr("../escaped.txt", "owned")
    try:
        backup.restore(evil, os.path.join(home, "restored3"))
        raise AssertionError("a path traversal entry must be refused")
    except ValueError as e:
        assert "escapes" in str(e) or "damaged" in str(e), str(e)
    assert not os.path.exists(os.path.join(home, "escaped.txt"))
    print("[traversal] an entry pointing outside the destination was refused")

    # --- 6. what the preflight reads
    rows = backup.backups(out_dir)
    assert len(rows) >= 2 and rows[0]["taken"], rows[:1]
    assert backup.latest(out_dir)["path"].endswith(".zip")
    age = backup.age_days(out_dir)
    assert age is not None and age < 1, age
    assert backup.age_days(os.path.join(home, "nowhere")) is None
    print("[freshness] the age helpers the preflight depends on report a real "
          "number, and None when there is nothing to report")
    print("PASS test_backup")


if __name__ == "__main__":
    main()
