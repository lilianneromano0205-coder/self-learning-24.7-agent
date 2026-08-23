#!/usr/bin/env python3
"""Inbox scanner + real extraction (Part 4 ingestion, offline parts).

- A dropped .md file becomes a lesson (deterministic copy) with a queued
  Watcher task whose context includes the lesson text.
- A dropped .pdf queues a Ripper task; the pdf-text helper extracts a real
  text layer (pymupdf generates and reads the fixture locally).
- Audio chunking produces chunk files via ffmpeg (skipped if ffmpeg missing).
- Unknown extensions are parked with no task.

Run from the agent/ directory:  python tests/test_inbox.py
"""

import json
import os
import shutil
import subprocess
import sys

from common import AGENT_DIR, make_sandbox, read_state

INGEST = os.path.join(AGENT_DIR, "ingest.py")
PY = sys.executable


def scan(sb, course=None):
    cmd = [PY, INGEST, "scan-inbox", "--root", sb]
    if course:
        cmd += ["--course", course]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def main():
    sb = make_sandbox("inbox", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    inbox = os.path.join(sb, "inbox")
    os.makedirs(inbox)

    # --- text file -> lesson + watcher task
    with open(os.path.join(inbox, "intro to backoff.md"), "w", encoding="utf-8") as f:
        f.write("# Lesson\nExponential backoff doubles the wait per retry.\n")
    out = scan(sb)
    assert "queued watcher task" in out, out
    lesson = os.path.join(sb, "courses", "intro-to-backoff", "lessons", "01", "lesson.md")
    assert os.path.exists(lesson), "lesson.md must exist"
    assert os.path.exists(os.path.join(sb, "courses", "intro-to-backoff",
                                       "source", "intro to backoff.md")), \
        "original must be preserved in source/"
    tasks = read_state(sb)["tasks"]
    assert len(tasks) == 1 and tasks[0]["role"] == "watcher" \
        and tasks[0]["course"] == "intro-to-backoff", tasks
    # the queued task's memory must reference the lesson file
    assert any("lesson.md" in m for m in tasks[0]["memory_files"]), tasks[0]
    print("[text] lesson created, original kept, watcher queued with the lesson as memory")

    # --- pdf -> ripper task, and pdf-text extracts a real text layer
    try:
        import fitz
    except ImportError:
        fitz = None
    if fitz:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Backoff base is 2 and max attempts is 5.")
        pdf_path = os.path.join(inbox, "chapter2.pdf")
        doc.save(pdf_path)
        out = scan(sb, course="intro-to-backoff")
        assert "queued ripper task" in out, out
        tasks = read_state(sb)["tasks"]
        assert tasks[-1]["role"] == "ripper", tasks[-1]
        stored = os.path.join(sb, "courses", "intro-to-backoff", "source", "chapter2.pdf")
        txt = os.path.join(sb, "courses", "intro-to-backoff", "lessons", "02", "transcript.txt")
        r = subprocess.run([PY, INGEST, "pdf-text", stored, txt],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        with open(txt, "r", encoding="utf-8") as f:
            assert "max attempts is 5" in f.read()
        print("[pdf] ripper queued; pdf-text extracted the real text layer")
    else:
        print("[pdf] SKIPPED (pymupdf not installed)")

    # --- audio chunking via ffmpeg
    if shutil.which("ffmpeg"):
        wav = os.path.join(sb, "tone.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=2", wav],
                       check=True, timeout=60)
        chunks_dir = os.path.join(sb, "chunks")
        r = subprocess.run([PY, INGEST, "chunk-audio", wav, chunks_dir],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        chunks = [f for f in os.listdir(chunks_dir) if f.startswith("chunk-")]
        assert chunks, "chunk-audio must produce at least one chunk"
        assert all(os.path.getsize(os.path.join(chunks_dir, c)) < 25_000_000
                   for c in chunks)
        print(f"[audio] ffmpeg chunking produced {len(chunks)} chunk(s) under the 25MB limit")
    else:
        print("[audio] SKIPPED (ffmpeg not installed)")

    # --- unknown extension is parked, no task
    with open(os.path.join(inbox, "mystery.xyz"), "w", encoding="utf-8") as f:
        f.write("?")
    before = len(read_state(sb)["tasks"])
    out = scan(sb)
    assert "UNKNOWN" in out, out
    assert len(read_state(sb)["tasks"]) == before, "unknown type must queue nothing"
    print("[unknown] parked in source/, no task queued")
    print("PASS test_inbox")


if __name__ == "__main__":
    main()
