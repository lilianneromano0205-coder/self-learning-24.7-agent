#!/usr/bin/env python3
"""Fiber-style checkpoints (M2-L2): long tool work recovers, never restarts.

1. Checkpoint primitive: done items persist across instances; state is
   durable; finish() is recorded; a foreign key never reads another job's
   record; records are listed by lineage.
2. transcribe(): the chunk loop is checkpointed — when chunk 2 of 3 fails
   once, the rerun transcribes ONLY the remaining chunks (chunk 1 is never
   transcribed twice), the offsets stay continuous, and the output is
   complete.
3. ingest_folder(): running it twice queues every file exactly once.

Run from the agent/ directory:  python tests/test_checkpoint.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state

sys.path.insert(0, AGENT_DIR)
import checkpoint as ck
import ingest


def main():
    sb = make_sandbox("checkpoint", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})

    # --- 1. the primitive
    os.environ["AGENT_TASK_LINEAGE"] = "lin-A"
    key = ck.key_for("demo", "input.bin")
    c = ck.Checkpoint(sb, key)
    assert not c.is_done("a") and c.recovered == 0
    c.mark("a", total=1)
    c.mark("b", total=2)
    c2 = ck.Checkpoint(sb, key)                 # a new activation
    assert c2.is_done("a") and c2.is_done("b") and c2.get("total") == 2
    assert c2.recovered == 2 and not c2.rec["finished"]
    c2.finish()
    assert ck.Checkpoint(sb, key).rec["finished"]
    other = ck.Checkpoint(sb, ck.key_for("demo", "other.bin"))
    assert not other.is_done("a"), "a different input is a different job"
    other.mark("a")
    assert not ck.Checkpoint(sb, key).is_done("z"), "records never bleed"
    recs = ck.list_checkpoints(sb, "lin-A")
    assert len(recs) == 2 and all(r["key"].startswith("lin-A|") for r in recs)
    os.environ["AGENT_TASK_LINEAGE"] = "lin-B"
    assert ck.list_checkpoints(sb, "lin-B") == []
    os.environ.pop("AGENT_TASK_LINEAGE", None)
    print("[primitive] done items and state survive re-activation; finish is "
          "recorded; keys are scoped by lineage + inputs")

    # --- 2. transcribe recovers instead of restarting
    audio = os.path.join(sb, "audio")
    os.makedirs(audio, exist_ok=True)
    for n in (1, 2, 3):
        with open(os.path.join(audio, f"part{n}.mp3"), "wb") as f:
            f.write(b"\x00" * 10)
    calls = []
    boom = {"armed": True}

    def fake_chunk(path, api_key):
        name = os.path.basename(path)
        calls.append(name)
        if name == "part2.mp3" and boom["armed"]:
            boom["armed"] = False
            raise RuntimeError("provider hiccup")
        return {"segments": [{"start": 0.0, "end": 10.0, "text": f"words of {name}"}]}

    ingest.transcribe_chunk = fake_chunk
    os.environ["GROQ_API_KEY"] = "test-not-a-real-key"
    os.environ["AGENT_ROOT"] = sb
    os.environ["AGENT_TASK_LINEAGE"] = "lin-T"
    dst = os.path.join(sb, "courses", "c", "lessons", "01", "transcript.txt")
    try:
        try:
            ingest.transcribe(audio, dst)
            raise AssertionError("the first run must fail at chunk 2")
        except RuntimeError:
            pass
        assert calls == ["part1.mp3", "part2.mp3"], calls
        ingest.transcribe(audio, dst)          # the rerun: recovers
        assert calls == ["part1.mp3", "part2.mp3", "part2.mp3", "part3.mp3"], \
            f"chunk 1 must never be transcribed twice: {calls}"
        with open(dst, encoding="utf-8") as f:
            lines = f.read().splitlines()
        assert [l.split("] ")[1] for l in lines] == \
            ["words of part1.mp3", "words of part2.mp3", "words of part3.mp3"]
        assert lines[1].startswith("[00:00:10") and lines[2].startswith("[00:00:20"), \
            f"offsets must stay continuous across the recovery: {lines}"
        recs = ck.list_checkpoints(sb, "lin-T")
        assert recs and recs[0]["finished"] and len(recs[0]["done"]) == 3
    finally:
        for k in ("GROQ_API_KEY", "AGENT_ROOT", "AGENT_TASK_LINEAGE"):
            os.environ.pop(k, None)
    print("[transcribe] a failure at chunk 2 resumed at chunk 2 on rerun: "
          "chunk 1 transcribed once, offsets continuous, transcript complete")

    # --- 3. ingest_folder is idempotent
    folder = os.path.join(sb, "material")
    os.makedirs(folder, exist_ok=True)
    for n in (1, 2, 3):
        with open(os.path.join(folder, f"lesson{n}.md"), "w", encoding="utf-8") as f:
            f.write(f"# Lesson {n}\ncontent\n")
    os.environ["AGENT_TASK_LINEAGE"] = "lin-F"
    try:
        q1 = ingest.ingest_folder(sb, folder, course="mat")
        q2 = ingest.ingest_folder(sb, folder, course="mat")
    finally:
        os.environ.pop("AGENT_TASK_LINEAGE", None)
    assert q1 == 3 and q2 == 0, (q1, q2)
    n_tasks = len(read_state(sb)["tasks"])
    assert n_tasks == 3, f"3 lessons must queue exactly 3 tasks, got {n_tasks}"
    print("[folder] ingesting the same folder twice queued each file exactly "
          "once")
    print("PASS test_checkpoint")


if __name__ == "__main__":
    main()
