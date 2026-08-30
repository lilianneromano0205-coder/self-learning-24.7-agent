#!/usr/bin/env python3
"""The three ideas worth taking from the EDEN corpus, implemented and proven.

1. FEDERATION (Agent Cards, zero implicit trust): two separate fleets, each
   with its own identity, exchange signed work. Unknown fleets, bad
   signatures, and unexposed experts are refused BEFORE any model is invoked;
   a peer's answer arrives labelled UNTRUSTED EVIDENCE and is filed fenced.
2. MEMORY PROMOTION BY SCOPE: one expert's uncited claim stays a candidate;
   a second, different expert corroborating it promotes it; a cited claim
   promotes immediately; withdrawn beliefs are struck, never deleted.
3. CONSTRAINT DIGEST: a brief's hard constraints are hashed and carried into
   every handoff, and a specialist that drops them is DETECTED rather than
   discovered later in the final deliverable.

Run from the agent/ directory:  python tests/test_federation.py
"""

import json
import os
import secrets
import sys
import threading
import time
from http.server import ThreadingHTTPServer

from common import free_port, AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import commons
import federation as F
import fleet
import team

PORT = free_port()

CONSULT_SETTINGS = """[agent]
poll_interval_seconds = 1
inbox_settle_seconds = 0
max_task_usd = 0
reflect_after = []

[providers.c]
type = "mock"
script = "scripts/c.json"

[roles.default]
provider = "c"
model = "mock"

[roles.consultant]
provider = "c"
model = "mock"
tools = ["read_file", "write_file", "finish_task", "ask_human"]
"""


def main():
    # ================= 1. FEDERATION =================
    homeA = make_sandbox("fed_a", providers={"m": {"script": "s.json"}},
                         roles={"tester": "m"}, scripts={"s.json": []})
    homeB = make_sandbox("fed_b", providers={"m": {"script": "s.json"}},
                         roles={"tester": "m"}, scripts={"s.json": []})
    # fleet B owns an expert it will expose
    rootB = fleet.create(homeB, "Alloy Expert", "metallurgy of alloys")
    with open(os.path.join(rootB, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(CONSULT_SETTINGS)
    os.makedirs(os.path.join(rootB, "scripts"), exist_ok=True)
    ans_dir = "consults"
    with open(os.path.join(rootB, "scripts", "c.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "finish_task", "args": {"summary": "n/a"}}], f)
    fleet.create(homeB, "Private Expert", "must stay invisible to peers")

    idA, idB = F.identity(homeA), F.identity(homeB)
    assert idA["fleet_id"] != idB["fleet_id"]
    assert "secret" in idA and idA["fingerprint"] != idA["secret"], \
        "the fingerprint must never be the secret"
    cardB = F.make_card(homeB, ["alloy-expert"], name="Fleet B",
                        endpoint=f"http://127.0.0.1:{PORT}")
    # only B itself can check the card's self-signature — that is what an
    # identity secret means. A peer pins the FINGERPRINT, nothing more.
    assert F.verify(idB["secret"], {k: v for k, v in cardB.items()
                                    if k != "signature"}, cardB["signature"])
    assert [s["expert"] for s in cardB["skills"]] == ["alloy-expert"], \
        "only exposed experts appear on the card"
    assert "private-expert" not in json.dumps(cardB)
    print("[card] each fleet has its own identity; the card exposes only what "
          "the owner chose, signed, with a fingerprint (never the secret)")

    # the owners exchange the card AND a shared secret out of band. The
    # secret is INDEPENDENT of both identity secrets — this test used to set
    # shared = idB["secret"], which handed fleet B's identity to fleet A and
    # hid that answers were being signed with the wrong key: under honestly
    # separate secrets, every reply failed verification and was discarded.
    shared = secrets.token_urlsafe(32)
    assert shared != idA["secret"] and shared != idB["secret"], \
        "the pair secret must never be either fleet's identity secret"
    F.trust(homeA, {**cardB, "secret": shared})
    F.trust(homeB, {"fleet_id": idA["fleet_id"], "name": "Fleet A",
                    "key_fingerprint": idA["fingerprint"], "secret": shared,
                    "skills": []})

    F.Handler.home = homeB
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), F.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # unknown fleet -> refused
        st, out = F.handle_ask(homeB, {"from_fleet": "fleet-nobody",
                                       "expert": "alloy-expert",
                                       "question": "hi", "nonce": "1",
                                       "signature": "x"})
        assert st == 403, (st, out)
        # known fleet, WRONG signature -> refused before any model runs
        st, out = F.handle_ask(homeB, {"from_fleet": idA["fleet_id"],
                                       "expert": "alloy-expert",
                                       "question": "hi", "nonce": "1",
                                       "signature": "forged"})
        assert st == 401 and "signature" in out["error"], out
        assert not os.path.exists(os.path.join(rootB, "state.json")), \
            "a forged request must never reach the task queue"
        # correct signature but an expert that was NOT exposed -> refused
        body = {"from_fleet": idA["fleet_id"], "expert": "private-expert",
                "question": "secrets?", "nonce": "2"}
        body["signature"] = F.sign(shared, dict(body))
        st, out = F.handle_ask(homeB, body)
        assert st == 404 and "not exposed" in out["error"], out
        print("[trust] unknown fleet, forged signature, and unexposed expert "
              "all refused before a single model call")

        # a proper request is accepted and queued as a citation-gated consult
        body = {"from_fleet": idA["fleet_id"], "expert": "alloy-expert",
                "question": "What temper suits marine bronze?", "nonce": "3"}
        body["signature"] = F.sign(shared, dict(body))
        st, out = F.handle_ask(homeB, body)
        assert st == 202 and out["ticket"], out
        ticket = out["ticket"]
        with open(os.path.join(rootB, "state.json"), encoding="utf-8") as f:
            t = next(x for x in json.load(f)["tasks"] if x["id"] == ticket)
        assert t["role"] == "consultant" and "citecheck" in (t["done_check"] or "")
        qfile = [m for m in t["memory_files"] if m.endswith("question.md")][0]
        with open(os.path.join(rootB, qfile), encoding="utf-8") as f:
            q = f.read()
        assert "FEDERATED QUESTION" in q and "OUTSIDE your owner's fleet" in q
        assert "NOT IN MY TRAINING" in q
        print("[ask] a signed request became a citation-gated consultation, "
              "framed as coming from outside the fleet")

        # answer not ready -> still working; then the signed answer comes back
        fb = {"from_fleet": idA["fleet_id"], "ticket": ticket}
        fb["signature"] = F.sign(shared, dict(fb))
        st, out = F.handle_fetch(homeB, fb)
        assert st == 202 and out["status"] == "still working", out
        # the ticket register lives at the FLEET level, not inside the expert
        rec = json.load(open(os.path.join(homeB, "federation", "inbound.json"),
                             encoding="utf-8"))[ticket]
        full = os.path.join(rootB, rec["answer_rel"])
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("Half-hard temper [P-0301]. Salinity limits: NOT IN MY TRAINING.\n")
        st, out = F.handle_fetch(homeB, fb)
        assert st == 200 and out["status"] == "answered"
        sig = out.pop("signature")
        assert F.verify(shared, out, sig), "the reply must be signed by the peer"
        assert not F.verify("wrong-secret", out, sig)
        print("[fetch] the reply is signed by the answering fleet and verifies")

        # A REAL ROUND TRIP over HTTP, ending in labelled untrusted evidence.
        # The asking side blocks while polling, so the answering side is
        # driven here: wait for the NEW inbound ticket, write its answer the
        # way its consultant would, and let the poll pick it up. (This used to
        # rely on both consultations landing in the same wall-clock second --
        # a coin flip that only showed up as a failure under load.)
        out_box = {}

        def ask():
            out_box["got"] = F.ask_peer(homeA, idB["fleet_id"], "alloy-expert",
                                        "What temper suits marine bronze?",
                                        wait=30, poll=1)

        th = threading.Thread(target=ask, daemon=True)
        th.start()
        inbound_path = os.path.join(homeB, "federation", "inbound.json")
        deadline, new_ticket = time.time() + 20, None
        while time.time() < deadline and not new_ticket:
            try:
                with open(inbound_path, encoding="utf-8") as f:
                    box = json.load(f)
                new_ticket = next((k for k in box if k != ticket), None)
            except (OSError, ValueError):
                pass
            if not new_ticket:
                time.sleep(0.2)
        assert new_ticket, "the peer never queued the second consultation"
        rec2 = json.load(open(inbound_path, encoding="utf-8"))[new_ticket]
        assert rec2["answer_rel"] != rec["answer_rel"], \
            "two consultations must never share a directory"
        full2 = os.path.join(rootB, rec2["answer_rel"])
        os.makedirs(os.path.dirname(full2), exist_ok=True)
        with open(full2, "w", encoding="utf-8") as f:
            f.write("Half-hard temper [P-0301]. Salinity limits: "
                    "NOT IN MY TRAINING.\n")
        th.join(40)
        got = out_box.get("got") or {}
        assert got.get("status") == "answered" and got.get("signature_ok"), got
        assert got["trust"].startswith("UNTRUSTED EVIDENCE")
        rootA = fleet.create(homeA, "Hull Designer", "marine hulls")
        rel = F.record_evidence(homeA, rootA, "Fleet B", "alloy-expert",
                                "temper?", got["answer"])
        with open(os.path.join(rootA, rel), encoding="utf-8") as f:
            ev = f.read()
        assert "not our knowledge" in ev and "CLAIM BY A STRANGER" in ev
        assert "<<<FILE-CONTENT" in ev, "peer text must be fenced like any outside text"
        print("[evidence] a peer's answer is filed as fenced, attributed, "
              "untrusted evidence — never as our own knowledge")
    finally:
        srv.shutdown()

    # ================= 2. MEMORY PROMOTION BY SCOPE =================
    h = homeA
    st, _ = commons.note(h, "alloys", "bronze work-hardens under cold rolling",
                         from_expert="alloy-expert")
    assert st == "candidate", st
    st, _ = commons.note(h, "alloys", "bronze work-hardens under cold rolling",
                         from_expert="alloy-expert")
    assert st == "candidate", "the SAME expert repeating itself proves nothing"
    st, kp = commons.note(h, "alloys", "bronze work-hardens under cold rolling",
                          from_expert="hull-designer")
    assert st == "promoted", "a DIFFERENT expert corroborating promotes it"
    body = open(kp, encoding="utf-8").read()
    assert "corroborated independently" in body
    st, kp2 = commons.note(h, "alloys", "tin content drives brittleness",
                           from_expert="alloy-expert",
                           src="courses/metallurgy/lessons/02/notes.md")
    assert st == "promoted", "a CITED claim carries its own evidence"
    st, _ = commons.note(h, "alloys", "tin content drives brittleness",
                         from_expert="hull-designer")
    assert st == "known"
    commons.quarantine(h, "bronze work-hardens under cold rolling",
                       "contradicted by lesson 04", by="owner")
    qbody = open(os.path.join(h, "commons", "quarantine.md"), encoding="utf-8").read()
    assert "~~bronze work-hardens" in qbody and "withdrawn" in qbody
    assert "QUARANTINED" in commons.digest(h), \
        "withdrawn beliefs must travel with the commons so nobody re-cites them"
    print("[promotion] uncited claims stay candidates; independent "
          "corroboration or a citation promotes; withdrawals are struck, "
          "kept, and shared")

    # ================= 3. CONSTRAINT DIGEST =================
    goal = ("Build the launch page. It must load under 100KB. "
            "Never use a third-party font. Deadline is Friday.")
    cons = team.constraints_of(goal)
    assert len(cons) >= 3, cons
    block, dig = team.constraint_block(cons)
    assert dig and f"CONSTRAINT-DIGEST: {dig}" in block
    assert team.digest_of(cons) == dig
    assert team.digest_of(cons[:-1]) != dig, \
        "dropping a constraint must change the digest"
    kept = f"...our work...\nCONSTRAINT-DIGEST: {dig}\n"
    lost = "...our work...\n"
    assert f"CONSTRAINT-DIGEST: {dig}" in kept
    assert f"CONSTRAINT-DIGEST: {dig}" not in lost
    print("[digest] hard constraints extracted, hashed, and echoed — a handoff "
          "that drops them changes the hash and is detectable")
    print("PASS test_federation")


if __name__ == "__main__":
    main()
