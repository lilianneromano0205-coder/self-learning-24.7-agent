#!/usr/bin/env python3
"""Any-link learning.

- HTML is stripped to clean lesson text (scripts/styles gone, title kept).
- add_url fetches a page deterministically, writes the lesson, and queues the
  Watcher (proven offline against a loopback HTTP server — the real https
  code path, not a file:// stand-in).
- file:// and every other scheme are REFUSED: ingestion reads the web, never
  the disk. A .url file dropped in inbox/ is auto-scanned, so one line saying
  file:///.../agent.env would otherwise pull the provider key into a lesson.
- A YouTube link queues a Ripper task with the yt-dlp instructions.
- A dropped .urls file routes every link through the same machinery.

Run from the agent/ directory:  python tests/test_url.py
"""

import http.server
import os
import pathlib
import sys
import threading
import time

from common import AGENT_DIR, agent_setting, make_sandbox, read_state, serve_dir

sys.path.insert(0, AGENT_DIR)
import ingest

HTML = """<html><head><title>Backoff 101</title><style>p{color:red}</style>
<script>alert('never in the lesson')</script></head>
<body><h1>Retries</h1><p>Backoff doubles the wait.</p>
<p>Give up after five attempts.</p></body></html>"""


def main():
    # --- extractor unit
    text = ingest.html_to_text(HTML)
    assert text.startswith("# Backoff 101"), text[:40]
    assert "doubles the wait" in text and "five attempts" in text
    assert "alert(" not in text and "color:red" not in text, \
        "script/style must never reach the lesson"
    print("[extract] HTML -> clean titled lesson text, scripts and styles stripped")

    # --- add_url on a real (file://) page -> fetched lesson + watcher queued
    sb = make_sandbox("url", providers={"m": {"script": "s.json"}},
                      roles={"watcher": "m", "ripper": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    page = os.path.join(sb, "page.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(HTML)

    # a loopback server, so the test exercises the SAME code path production
    # uses (http) instead of a file:// stand-in that ingestion must refuse.
    # serve_dir opts in to ALLOW_PRIVATE_INGEST: a fixture is a deliberate
    # loopback target, which the SSRF policy requires you to say out loud.
    base, stop_site = serve_dir(sb)
    uri = f"{base}/page.html"
    ingest.add_url(sb, uri, course="webcourse")
    lesson = os.path.join(sb, "courses", "webcourse", "lessons", "01", "lesson.md")
    with open(lesson, "r", encoding="utf-8") as f:
        body = f.read()
    assert body.startswith(f"SOURCE-URL: {uri}"), "provenance must be recorded"
    assert "doubles the wait" in body
    tasks = read_state(sb)["tasks"]
    assert tasks[-1]["role"] == "watcher" and tasks[-1]["course"] == "webcourse"

    # --- ingestion reads the WEB, never the disk (audit P1-7)
    secret = os.path.join(sb, "agent.env")
    with open(secret, "w", encoding="utf-8") as f:
        f.write("DEEPSEEK_API_KEY=sk-must-never-be-ingested" + chr(10))
    for bad in (pathlib.Path(secret).as_uri(), "file://localhost/etc/passwd",
                "ftp://example.com/x", "/etc/passwd"):
        try:
            ingest.fetch_url(bad, os.path.join(sb, "leak.md"))
            raise AssertionError(f"must refuse a non-web scheme: {bad}")
        except ValueError as e:
            assert "accepts http and https" in str(e), str(e)
    assert not os.path.exists(os.path.join(sb, "leak.md")), (
        "a refused fetch must write nothing")
    print("[scheme] file://, ftp:// and bare paths are refused — a .url file "
          "in the inbox cannot read agent.env into a lesson")
    with open(os.path.join(sb, "courses", "webcourse", "sources.md"),
              "r", encoding="utf-8") as f:
        assert uri in f.read()
    print("[page] URL fetched deterministically, lesson written with provenance, watcher queued")

    # --- YouTube link -> ripper task with yt-dlp instructions, no network
    ingest.add_url(sb, "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                   course="webcourse")
    t = read_state(sb)["tasks"][-1]
    assert t["role"] == "ripper" and "youtube" in t["goal"] and "cookies" in t["goal"], t["goal"]
    print("[youtube] link queued to the ripper with the yt-dlp + cookies playbook")

    # --- a dropped .urls file routes every link
    os.makedirs(os.path.join(sb, "inbox"), exist_ok=True)
    with open(os.path.join(sb, "inbox", "reading list.urls"), "w", encoding="utf-8") as f:
        f.write(f"# my course links\n{uri}\n")
    n = ingest.scan_inbox(sb)
    assert n == 1
    tasks = read_state(sb)["tasks"]
    assert tasks[-1]["role"] == "watcher" and tasks[-1]["course"] == "reading-list"
    print("[.urls] dropped link file became a course with its own lessons")

    # --- the settle window must not be able to invert (U22)
    # A file whose mtime lands AHEAD of time.time() gave a negative age, and
    # `age < settle` was then true even at settle = 0 — "no settling
    # required" behaving as "never ingest". It happened on a CI runner and
    # not once in 3000 attempts here, so the skew is forced rather than
    # waited for: nothing about this defect was reproducible by patience.
    second = os.path.join(sb, "inbox", "second list.urls")
    with open(second, "w", encoding="utf-8") as f:
        f.write(f"# more links\n{uri}\n")
    future = time.time() + 5           # the filesystem clock, running ahead
    os.utime(second, (future, future))
    assert os.path.getmtime(second) - time.time() > 0, "the skew was not applied"
    n2 = ingest.scan_inbox(sb)
    assert n2 == 1, (
        f"a file dated in the future was skipped at settle = 0: scan_inbox "
        f"returned {n2}. Zero settling must mean zero, or a clock a few "
        f"milliseconds ahead strands the file until something touches it")
    # and a real settle window still holds that same file back
    agent_setting(sb, "inbox_settle_seconds = 30")
    third = os.path.join(sb, "inbox", "third list.urls")
    with open(third, "w", encoding="utf-8") as f:
        f.write(f"# still copying\n{uri}\n")
    assert ingest.scan_inbox(sb) == 0, (
        "a file written moments ago was ingested despite a 30s settle "
        "window — the fix for the zero case must not disable the feature")
    os.utime(third, (time.time() - 60, time.time() - 60))
    assert ingest.scan_inbox(sb) == 1, "a settled file was never picked up"
    agent_setting(sb, "inbox_settle_seconds = 0")
    print("[settle] zero settling means zero even when the filesystem clock "
          "runs ahead of the wall clock, and a real window still holds a "
          "file back until it stops changing")
    stop_site()
    print("PASS test_url")


if __name__ == "__main__":
    main()
