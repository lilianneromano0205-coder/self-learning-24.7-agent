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

from common import AGENT_DIR, make_sandbox, read_state

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
    # uses (http) instead of a file:// stand-in that ingestion must refuse
    class _Page(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    os.environ["no_proxy"] = "127.0.0.1,localhost"
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    uri = f"http://127.0.0.1:{srv.server_address[1]}/page.html"
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
    srv.shutdown()
    print("PASS test_url")


if __name__ == "__main__":
    main()
