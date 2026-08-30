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
    check_the_ssrf_guard_reads_addresses_not_strings()
    check_a_video_host_is_a_HOST()
    print("PASS test_url")



def check_the_ssrf_guard_reads_addresses_not_strings():
    """An IPv4 address has more than one spelling, and the guard knew one.

    `_blocked_ip` judged IPv6 by string prefix — `::1`, `fe80`, `fc`, `fd` —
    so `::ffff:169.254.169.254` and `0:0:0:0:0:ffff:a9fe:a9fe`, which are both
    the cloud metadata endpoint, passed: they contain a colon so the IPv4
    table was never consulted, and they start with none of those prefixes.
    Numeric hosts were worse: `http://2130706433/` is 127.0.0.1 as a 32-bit
    integer, and the check only ever looked at what getaddrinfo returned — on
    a stack that refuses that name the code took its "unresolvable, the fetch
    will fail anyway" exit while urllib went on to connect.

    Ingestion is the LOWEST-privilege input here: a .url file dropped in
    inbox/ is auto-scanned and every line reaches fetch_url. One line of text
    is the whole attack.
    """
    import ingest
    BLOCKED = [
        ("http://169.254.169.254/latest/meta-data/", "cloud metadata, v4"),
        ("http://[::ffff:169.254.169.254]/", "the same, IPv4-mapped IPv6"),
        ("http://[0:0:0:0:0:ffff:a9fe:a9fe]/", "the same, written long"),
        ("http://2130706433/", "127.0.0.1 as a decimal integer"),
        ("http://0x7f000001/", "127.0.0.1 in hex"),
        ("http://[::1]/", "IPv6 loopback"),
        ("http://127.0.0.1/", "IPv4 loopback"),
        ("http://10.0.0.1/", "a private network"),
        ("http://[fd00::1]/", "unique-local IPv6"),
    ]
    # this file's own fixtures serve on 127.0.0.1 and therefore set
    # ALLOW_PRIVATE_INGEST — the operator's deliberate override. Clear it, or
    # the guard is being asked a question it has been told not to answer.
    saved = os.environ.pop("ALLOW_PRIVATE_INGEST", None)
    try:
        allowed = []
        for url, why in BLOCKED:
            try:
                ingest._check_host(url)
                allowed.append(f"{url} ({why})")
            except ValueError:
                pass
        assert not allowed, (
            "these resolve inside the network and were not refused:\n  "
            + "\n  ".join(allowed))
        ingest._check_host("http://example.com/")  # a public host still works
        # ...and the override still overrides, or an operator who needs an
        # intranet page has no way in
        os.environ["ALLOW_PRIVATE_INGEST"] = "1"
        ingest._check_host("http://127.0.0.1/")
    finally:
        os.environ.pop("ALLOW_PRIVATE_INGEST", None)
        if saved is not None:
            os.environ["ALLOW_PRIVATE_INGEST"] = saved
    print(f"[ssrf] all {len(BLOCKED)} internal-address spellings refused — "
          f"IPv4-mapped and long-form IPv6, decimal and hex integer hosts "
          f"included — and an ordinary public host still fetches")


def check_a_video_host_is_a_HOST():
    """VIDEO_HOSTS was matched against netloc+PATH, so an ordinary article
    whose slug named a video site was routed to the downloader and never
    fetched as a page."""
    import ingest
    for u in ("https://blog.example.com/why-tiktok.com-is-dying",
              "https://en.wikipedia.org/wiki/YouTube",
              "https://youtube.com.evil.example/watch"):
        assert not ingest.is_video_url(u), u
    for u in ("https://www.youtube.com/watch?v=a", "https://youtu.be/a",
              "https://m.youtube.com/watch?v=a",
              "https://www.linkedin.com/learning/course"):
        assert ingest.is_video_url(u), u
    print("[video-host] a host is matched exactly or as a parent domain: an "
          "article about YouTube is fetched as a page, a lookalike domain "
          "buys nothing, and real video hosts still route to the downloader")

if __name__ == "__main__":
    main()
