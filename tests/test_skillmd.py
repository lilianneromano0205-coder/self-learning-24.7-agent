#!/usr/bin/env python3
"""Skills as folders (the Agent Skills standard) with PROVENANCE (M5).

1. discovery: a folder skill (SKILL.md + YAML frontmatter) and a flat
   skills/x.md are both found, and both keep ONE graph key -- a playbook that
   grows into a folder keeps its earned record
2. progressive disclosure: a skill that did not activate is named in the
   SKILL INDEX without its body
3. composition across shapes: USES: resolves flat -> folder and folder -> flat
4. mediation: a community skill is injected with a warning banner, and its
   bundled scripts are REFUSED by the loop until the owner promotes it
5. supply chain: export -> import round trip, through the panel too

Run from the agent/ directory:  python tests/test_skillmd.py
"""

import json
import os
import sys

from common import AGENT_DIR, PY, api, make_sandbox, read_state, run_drain, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import context
import loop
import skills

FOLDER_SKILL = """---
name: restore-a-backup
description: Restore last night's database backup safely.
keywords: [restore, backup, database]
uses: [verify-a-restore]
version: 2
---

# Restore a backup
BODY-OF-RESTORE: stop writes, restore, then verify.
"""


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return rel


def main():
    sb = make_sandbox("skillmd", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    write(sb, "skills/restore-a-backup/SKILL.md", FOLDER_SKILL)
    write(sb, "skills/verify-a-restore.md",
          "KEYWORDS: verify, restore\nBODY-OF-VERIFY: count the rows.\n")
    write(sb, "skills/rotate-tls-keys/SKILL.md",
          "---\nname: rotate-tls-keys\ndescription: Rotate the TLS keys "
          "quarterly.\nkeywords: [tls, rotate]\n---\n\nBODY-OF-ROTATE: use "
          "certbot.\n")

    # --- 1. discovery + one key per skill
    found = {s["stem"]: s for s in skills.discover(sb)}
    assert set(found) == {"restore-a-backup", "verify-a-restore",
                          "rotate-tls-keys"}, sorted(found)
    fs = found["restore-a-backup"]
    assert fs["folder"] and fs["name"] == "restore-a-backup"
    assert fs["description"].startswith("Restore last night")
    assert "backup" in fs["keywords"] and fs["version"] == "2"
    assert fs["rel"] == "skills/restore-a-backup/SKILL.md"
    assert not found["verify-a-restore"]["folder"]
    assert skills._stem("skills/x.md") == skills._stem("skills/x/SKILL.md") == "x"
    skills.record_use(sb, ["skills/restore-a-backup/SKILL.md"], "t-1",
                      success=True, verified=True)
    assert skills.load_graph(sb)["restore-a-backup"]["verified_wins"] == 1
    print("[discover] folder skills and flat skills are both first-class and "
          "share one graph key")

    # --- 2. + 3. activation, disclosure and composition across shapes
    a = loop.Agent(sb)
    rels = a.matching_skills("restore a backup of the database tonight")
    assert "skills/restore-a-backup/SKILL.md" in rels, rels
    assert "skills/verify-a-restore.md" in rels, \
        f"USES: must pull the flat sub-skill: {rels}"
    msgs, man = context.compile(a, {"id": "t-sk", "role": "tester",
                                    "goal": "restore a backup of the database "
                                            "tonight", "memory_files": []})
    user = msgs[1]["content"]
    assert "BODY-OF-RESTORE" in user and "BODY-OF-VERIFY" in user
    assert "PROVEN" in user or "CANDIDATE" in user, "status label rides along"
    assert "BODY-OF-ROTATE" not in user, "an unrelated skill must not load"
    assert "rotate-tls-keys" in user and "Rotate the TLS keys" in user, \
        "but it must still be OFFERED by name and description"
    print("[disclosure] the matching folder skill loaded with its flat "
          "sub-skill; the unrelated one was offered by name only")

    # --- 4. provenance mediation
    # A folder skill with no entry in the graph arrived from somewhere other
    # than `import_skill` — a manual copy, an unzip, a restore, a model write
    # — so it is third-party until the OWNER says otherwise. It used to be
    # trusted on the strength of its own `provenance:` line, which let a
    # third-party SKILL.md declare itself first-party and unlock its scripts.
    assert skills.provenance_of(sb, "skills/rotate-tls-keys/SKILL.md") ==         "community", "an unregistered folder skill is not trusted by default"
    skills.set_provenance(sb, "rotate-tls-keys", "own")
    assert skills.provenance_of(sb, "skills/rotate-tls-keys/SKILL.md") == "own",         "the owner's recorded decision is what grants trust"
    skills.set_provenance(sb, "rotate-tls-keys", "community")
    write(sb, "skills/rotate-tls-keys/scripts/rotate.py", "print('rotating')\n")
    msgs2, _ = context.compile(a, {"id": "t-sk2", "role": "tester",
                                   "goal": "rotate the tls keys",
                                   "memory_files": []})
    assert "COMMUNITY SKILL" in msgs2[1]["content"], msgs2[1]["content"][:300]
    assert "scripts are DISABLED" in msgs2[1]["content"]
    cmd = f'"{PY}" skills/rotate-tls-keys/scripts/rotate.py'
    guard = skills.script_guard(sb, cmd)
    assert guard and "REFUSED" in guard and "promote" in guard, guard
    assert skills.script_guard(sb, f'"{PY}" -c "print(1)"') is None
    sb2 = make_sandbox("skillmd_loop", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"},
                       scripts={"s.json": [
                           {"tool": "run_command", "args": {"cmd": cmd}},
                           {"tool": "finish_task", "args": {"summary": "ran"}}]})
    write(sb2, "skills/rotate-tls-keys/SKILL.md",
          "---\nname: rotate-tls-keys\ndescription: Rotate keys.\n---\nbody\n")
    write(sb2, "skills/rotate-tls-keys/scripts/rotate.py",
          "print('SCRIPT-RAN')\n")
    skills.set_provenance(sb2, "rotate-tls-keys", "community")
    loop.Agent(sb2).add_task("tester", "rotate the tls keys")
    assert run_drain(sb2) == 0
    step = read_state(sb2)["tasks"][0]["steps"][0]
    assert "REFUSED" in step["result"] and "SCRIPT-RAN" not in step["result"], \
        step["result"]
    with open(os.path.join(sb2, "logs", "agent.log"), encoding="utf-8") as f:
        assert "untrusted skill script" in f.read()
    print("[mediation] a third-party playbook was injected with a warning and "
          "its bundled script was refused by the loop")

    skills.set_provenance(sb2, "rotate-tls-keys", "owner")
    with open(os.path.join(sb2, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "run_command", "args": {"cmd": cmd}},
                   {"tool": "finish_task", "args": {"summary": "ran"}}], f)
    with open(os.path.join(sb2, "s.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "run_command", "args": {"cmd": cmd}},
                   {"tool": "finish_task", "args": {"summary": "ran"}}], f)
    loop.Agent(sb2).add_task("tester", "rotate the tls keys once trusted")
    assert run_drain(sb2) == 0
    step2 = [t for t in read_state(sb2)["tasks"]
             if "once trusted" in t["goal"]][0]["steps"][0]
    assert "SCRIPT-RAN" in step2["result"], step2["result"]
    print("[trust] after the owner promoted it, the same script ran")

    # --- 5. export / import round trip
    out_dir = os.path.join(sb, "exports")
    path = skills.export_skill(sb, "restore-a-backup", out_dir)
    body = open(os.path.join(path, "SKILL.md"), encoding="utf-8").read()
    assert body.startswith("---\nname: restore-a-backup")
    assert "description: Restore last night" in body
    assert "BODY-OF-RESTORE" in body and "uses: [verify-a-restore]" in body
    sb3 = make_sandbox("skillmd_import", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": []})
    rel = skills.import_skill(sb3, path)
    assert rel == "skills/restore-a-backup/SKILL.md"
    imported = skills.discover(sb3)[0]
    assert imported["provenance"] == "community", "an import is never evidence"
    assert imported["description"].startswith("Restore last night")
    assert skills.status_of(sb3, rel) == "candidate"

    home = make_sandbox("skillmd_home", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    import fleet
    root = fleet.create(home, "Importer", "collects playbooks")
    proc, base = start_panel(home)
    try:
        r = api(base, "POST", "/api/experts/importer/skill",
                {"op": "import", "path": path})
        assert r["imported"] == "skills/restore-a-backup/SKILL.md", r
        sk = api(base, "GET", "/api/experts/importer/skills")
        cand = [x for x in sk["candidate"] if x["skill"] == "restore-a-backup"]
        assert cand and cand[0]["provenance"] == "community", sk
        r2 = api(base, "POST", "/api/experts/importer/skill",
                 {"op": "promote", "name": "restore-a-backup"})
        assert r2["provenance"] == "owner"
        sk2 = api(base, "GET", "/api/experts/importer/skills")
        assert [x for x in sk2["candidate"]
                if x["skill"] == "restore-a-backup"][0]["provenance"] == "owner"
        r3 = api(base, "POST", "/api/experts/importer/skill",
                 {"op": "export", "name": "restore-a-backup"})
        assert os.path.isfile(os.path.join(r3["exported"], "SKILL.md"))
    finally:
        stop_panel(proc, base)
    print("[supply] a skill exported in the open format imported cleanly into "
          "another expert, arrived untrusted, and the owner promoted it from "
          "the panel")
    print("PASS test_skillmd")


if __name__ == "__main__":
    main()
