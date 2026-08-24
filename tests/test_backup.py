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

import calendar
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

    # --- 4b. and the restored expert actually WORKS
    #
    # Manual §20: "persistent expert state must be portable across modes;
    # deployment is a location choice, not a different expert format." Equal
    # bytes are necessary and not sufficient — a restore that produces
    # identical files an agent cannot be driven from is not a restore, it is
    # a copy. So the test drives one.
    import loop
    from common import run_drain
    restored_root = os.path.join(dest, "experts", "archivist")
    # the mock provider's script travels with the fleet home, not the expert,
    # so a restored expert needs it beside it — exactly what a real restore
    # needs its keys put back for, and the report says so
    with open(os.path.join(restored_root, "s.json"), "w",
              encoding="utf-8") as f:
        json.dump([{"tool": "write_file",
                    "args": {"path": "out/restored.md",
                             "content": "written after a restore"}},
                   {"tool": "finish_task",
                    "args": {"summary": "the restored expert worked"}}], f)
    agent = loop.Agent(restored_root)
    tid = agent.add_task("tester", "prove the restored expert can work",
                         done_check='python -c "import os,sys;'
                                    'sys.exit(0 if os.path.exists('
                                    "'out/restored.md') else 1)\"")
    run_drain(restored_root, timeout=180)
    with open(os.path.join(restored_root, "state.json"), encoding="utf-8") as f:
        done = [t for t in json.load(f)["tasks"]
                if t["id"] == tid and t["status"] == "done"]
    assert done, (
        "the restored expert could not complete a gated task — equal bytes "
        "are not the same thing as a working expert, and §20 asks for the "
        "second one")
    # it also kept everything it knew
    assert os.path.isfile(os.path.join(restored_root, "identity.md"))
    assert os.path.isfile(os.path.join(restored_root, "courses", "history",
                                       "notes.md"))
    print("[portable] the RESTORED expert was driven through a gated task in "
          "its new location and passed — deployment is a location choice, not "
          "a different expert format (manual §20)")

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

    # --- 7. the remote path: signed correctly, and credentials never travel
    # A backup that only exists on the machine being backed up is not a
    # backup, so archives can be pushed to any S3-compatible store. That
    # signing is AWS Signature V4 written here in stdlib, and the only honest
    # way to know it is right without an account is AWS's OWN published
    # example vectors. The first draft passed the raw query string through
    # instead of canonicalising it, and these caught it -- which would have
    # broken every remote-list call, since that one carries ?list-type=2.
    EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    KID = "AKIAIOSFODNN7EXAMPLE"
    SEC = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    ts = calendar.timegm((2013, 5, 24, 0, 0, 0, 0, 0, 0))
    vectors = [
        ("GET", "https://examplebucket.s3.amazonaws.com/?lifecycle",
         "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543"),
        ("GET", "https://examplebucket.s3.amazonaws.com/?max-keys=2&prefix=J",
         "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"),
    ]
    for method, url, expect in vectors:
        h = backup._sigv4(method, url, EMPTY, KID, SEC, region="us-east-1",
                          now=ts)
        got = h["Authorization"].split("Signature=")[-1]
        assert got == expect, (url, got, expect)
        assert "AWS4-HMAC-SHA256" in h["Authorization"]
        # the SECRET must never appear in a header, only a derived signature
        assert SEC not in h["Authorization"], "the secret key leaked into the header"
        assert SEC not in json.dumps(h), "the secret key leaked into the headers"
    print(f"[sigv4] {len(vectors)} of AWS's own published example signatures "
          f"reproduced byte for byte, and the secret appears in no header -- "
          f"the request is signed with a derivation of it, never the key")

    # a push with no credentials refuses, names the variable, and uploads
    # nothing: the same fail-closed rule the sandbox backends follow
    for var in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        os.environ.pop(var, None)
    arch = backup.latest(out_dir)["path"]
    try:
        backup.push(arch, "https://example.invalid", "b", root=home)
        raise AssertionError("a push with no credentials must refuse")
    except SystemExit as e:
        assert "R2_ACCESS_KEY_ID" in str(e), str(e)
    print("[fail-closed] a push with no credentials refuses by name and sends "
          "nothing -- it does not reach the network to find out")
    # --- a backup must not archive its own backups (U-compounding)
    # The default output is <home>/backups, which is INSIDE the tree being
    # archived and is not in SKIP_DIRS, so every snapshot swallowed all of
    # its predecessors: 28,451 -> 43,088 -> 72,321 bytes on a fresh fleet,
    # with one then two nested archives. Exponential, on the very disk the
    # fleet needs to save itself — so the failure mode of the backup system
    # was to make backups impossible. preflight.py recommends exactly that
    # path, which made the RECOMMENDED configuration the broken one.
    import zipfile as _zip
    nested_out = os.path.join(home, "backups")
    sizes = []
    for _ in range(4):
        rec = backup.create(home, nested_out)
        ap = rec["path"] if isinstance(rec, dict) else str(rec)
        sizes.append(os.path.getsize(ap))
        with _zip.ZipFile(ap) as z:
            # only FLEET archives count: this test deliberately plants
            # evil.zip and tampered.zip earlier to exercise traversal and
            # damage detection, and those are legitimate content
            inner = [n for n in z.namelist()
                     if os.path.basename(n).startswith("fleet-")
                     and n.lower().endswith(".zip")]
        assert not inner, (
            f"a backup archived {len(inner)} earlier archive(s): {inner[:3]}")
    assert max(sizes) <= min(sizes) * 1.15, (
        f"archive size grew {max(sizes)/min(sizes):.2f}x across four "
        f"snapshots into the default directory: {sizes}")
    print(f"[compounding] four snapshots into the DEFAULT output directory "
          f"stayed flat at {sizes[-1]:,} bytes with zero nested archives — a "
          f"backup no longer archives its own backups, which on a 24/7 fleet "
          f"filled the disk the fleet needs in order to save itself")

    # --- pull must VERIFY, and be able to say no
    # `pull` shipped claiming "a pull re-verifies every manifest checksum
    # before returning" with NO test behind it, and the claim was false twice
    # over: verify() returns (ok, report) and the code called .get() on the
    # tuple, so every pull raised AttributeError; and "problems" was never a
    # key of that report, so unpacking correctly would have returned None and
    # trusted a DAMAGED archive in silence. push and remote-list had pinned
    # AWS vectors; pull — the half a container needs to get its memory back
    # at boot — had nothing.
    good = backup.create(home, os.path.join(home, "pulltest"))
    good_path = good["path"] if isinstance(good, dict) else str(good)
    stored = {}
    with open(good_path, "rb") as f:
        stored["fleet-good.zip"] = f.read()
    damaged = bytearray(stored["fleet-good.zip"])
    damaged[len(damaged) // 2] ^= 0xFF          # one byte, deep inside
    stored["fleet-bad.zip"] = bytes(damaged)

    saved_env = {k: os.environ.get(k) for k in
                 ('R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY')}
    os.environ['R2_ACCESS_KEY_ID'] = 'AKIAIOSFODNN7EXAMPLE'
    os.environ['R2_SECRET_ACCESS_KEY'] = 'not-a-real-secret'
    real_s3 = backup._s3
    def fake_s3(method, url, kid, secret, body=None, region="auto", **kw):
        name = url.rsplit("/", 1)[-1].split("?")[0]
        return 200, stored[name]
    backup._s3 = fake_s3
    try:
        dest = os.path.join(home, "pulled")
        got = backup.pull("fleet-good.zip", dest, "https://x.example", "b")
        assert os.path.isfile(got), "a good archive did not land on disk"
        ok, _rep = backup.verify(got)
        assert ok, "the pulled archive should verify"
        try:
            backup.pull("fleet-bad.zip", dest, "https://x.example", "b")
            raise AssertionError(
                "a corrupted archive was accepted — restoring from it would "
                "put a damaged memory back into the fleet")
        except RuntimeError as e:
            assert "DAMAGED" in str(e), f"refused for the wrong reason: {e}"
    finally:
        backup._s3 = real_s3
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("[pull] a good archive downloads and verifies; one flipped byte "
          "deep inside is caught and REFUSED with the reason — the check the "
          "feature advertised now actually runs, having previously crashed "
          "on every archive and, once unpacked, trusted a damaged one")

    print("PASS test_backup")


if __name__ == "__main__":
    main()
