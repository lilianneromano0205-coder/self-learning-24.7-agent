#!/usr/bin/env python3
"""Universal material intake: every shape a course, book, manual, or guide
can arrive in.

  folder      a whole course dropped as a directory (recursive, ordered)
  .zip        a packaged course, extracted safely, then ingested
  subtitles   .srt/.vtt files (and video captions) parsed to timestamped text
  html file   a saved web page stripped to lesson text
  ebooks      .epub/.mobi routed to the document converter
  video hosts YouTube, Vimeo, Coursera, Udemy, edX â€¦ all routed to the Ripper
  playlists   recognized so they expand into one lesson per video
  crawl       a manual's index page plus its same-site pages

Run from the agent/ directory:  python tests/test_material.py
"""

import os
import pathlib
import sys
import zipfile

from common import serve_dir, AGENT_DIR, make_sandbox, read_state

sys.path.insert(0, AGENT_DIR)
import ingest

FINISH = [{"tool": "finish_task", "args": {"summary": "ok"}}]
VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
Backoff doubles the wait

00:00:04.000 --> 00:00:07.000
Backoff doubles the wait

00:00:07.000 --> 00:00:09.500
<i>Give up</i> after five attempts
"""


def sandbox(tag):
    return make_sandbox(f"material_{tag}", providers={"m": {"script": "s.json"}},
                        roles={"watcher": "m", "ripper": "m"},
                        scripts={"s.json": FINISH})


def main():
    sb = sandbox("folder")
    os.makedirs(os.path.join(sb, "inbox"), exist_ok=True)

    # --- host and playlist recognition
    for u in ("https://vimeo.com/12345", "https://www.coursera.org/lecture/x/y",
              "https://www.udemy.com/course/x/learn/lecture/9", "https://youtu.be/abc"):
        assert ingest.is_video_url(u), u
    assert not ingest.is_video_url("https://docs.python.org/3/tutorial/")
    assert ingest.is_playlist_url("https://www.youtube.com/playlist?list=PL123")
    assert ingest.is_playlist_url("https://www.youtube.com/@channel")
    assert not ingest.is_playlist_url("https://youtu.be/abc")
    print("[hosts] Vimeo/Coursera/Udemy/YouTube recognized as video; playlists detected")

    # --- subtitles: dedup + timestamps + tag stripping
    text = ingest.subs_to_text(VTT)
    assert text.count("Backoff doubles the wait") == 1, "scrolling repeats must collapse"
    assert "[00:00:07] Give up after five attempts" in text, text
    assert "<i>" not in text
    print("[subs] VTT parsed to timestamped text, repeats collapsed, tags stripped")

    # --- a whole course as a FOLDER (the previously unhandled case)
    course = os.path.join(sb, "inbox", "Python Mastery")
    os.makedirs(os.path.join(course, "Module 1"))
    os.makedirs(os.path.join(course, "Module 2"))
    with open(os.path.join(course, "Module 1", "lesson.md"), "w", encoding="utf-8") as f:
        f.write("# M1\nretries need backoff\n")
    with open(os.path.join(course, "Module 2", "notes.txt"), "w", encoding="utf-8") as f:
        f.write("M2 content\n")
    with open(os.path.join(course, "Module 2", "captions.vtt"), "w", encoding="utf-8") as f:
        f.write(VTT)
    n = ingest.scan_inbox(sb)
    assert n == 1, n
    tasks = read_state(sb)["tasks"]
    assert len(tasks) == 3, f"3 files -> 3 lessons, got {len(tasks)}"
    assert {t["course"] for t in tasks} == {"python-mastery"}
    assert all(t["role"] == "watcher" for t in tasks), [t["role"] for t in tasks]
    # walk order is Module 1/lesson.md, Module 2/captions.vtt, Module 2/notes.txt
    subs_lesson = os.path.join(sb, "courses", "python-mastery",
                               "lessons", "02", "lesson.md")
    with open(subs_lesson, "r", encoding="utf-8") as f:
        body = f.read()
    assert "[00:00:01] Backoff doubles the wait" in body, "the .vtt lesson must be parsed"
    assert "Module 2" in body, "the lesson must record which folder it came from"
    assert not os.path.exists(course), "the folder must be moved out of the inbox"
    assert os.path.isdir(os.path.join(sb, "courses", "python-mastery",
                                      "source", "Python Mastery"))
    print("[folder] a dropped course folder became 3 ordered lessons, originals preserved")

    # --- a course as a .zip
    sb2 = sandbox("zip")
    os.makedirs(os.path.join(sb2, "inbox"), exist_ok=True)
    zpath = os.path.join(sb2, "inbox", "Guide Bundle.zip")
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("guide/01-intro.md", "# Intro\nchapter one")
        z.writestr("guide/02-advanced.md", "# Advanced\nchapter two")
        z.writestr("../../../evil.md", "must never land outside the course")
        # sibling-prefix trap: "../Guide Bundle-x/…" passes a naive
        # startswith(dest) check but is NOT inside dest
        z.writestr("../Guide Bundle-x/evil.md", "must never land beside the course")
    assert ingest.scan_inbox(sb2) == 1
    tasks = read_state(sb2)["tasks"]
    assert len(tasks) >= 2, [t["goal"][:60] for t in tasks]
    extracted = os.path.join(sb2, "courses", "guide-bundle", "source", "Guide Bundle")
    for stray in (os.path.join(sb2, "evil.md"),
                  os.path.join(sb2, "courses", "evil.md"),
                  os.path.join(os.path.dirname(sb2), "evil.md"),
                  os.path.join(sb2, "courses", "guide-bundle", "source",
                               "Guide Bundle-x")):
        assert not os.path.exists(stray), f"zip traversal escaped to {stray}"
    for dirpath, _, filenames in os.walk(extracted):
        for fn in filenames:
            real = os.path.realpath(os.path.join(dirpath, fn))
            assert real.startswith(os.path.realpath(extracted) + os.sep), \
                f"{real} was written outside the extraction root"
    print("[zip] packaged course extracted into lessons; traversal and "
          "sibling-prefix entries contained, nothing written outside the course")

    # --- a saved HTML page and an ebook, by file
    sb3 = sandbox("formats")
    os.makedirs(os.path.join(sb3, "inbox"), exist_ok=True)
    with open(os.path.join(sb3, "inbox", "manual.html"), "w", encoding="utf-8") as f:
        f.write("<html><title>Manual</title><script>x=1</script>"
                "<body><p>Step one.</p></body></html>")
    with open(os.path.join(sb3, "inbox", "book.epub"), "wb") as f:
        f.write(b"PK\x03\x04 not a real epub")
    ingest.scan_inbox(sb3)
    tasks = read_state(sb3)["tasks"]
    roles = sorted(t["role"] for t in tasks)
    assert roles == ["ripper", "watcher"], roles
    with open(os.path.join(sb3, "courses", "manual", "lessons", "01", "lesson.md"),
              "r", encoding="utf-8") as f:
        html_lesson = f.read()
    assert "# Manual" in html_lesson and "Step one." in html_lesson
    assert "x=1" not in html_lesson, "scripts must not reach the lesson"
    print("[formats] saved HTML cleaned to a lesson; ebook routed to the converter")

    # --- a manual/guide crawled: index page + its same-site pages
    sb4 = sandbox("crawl")
    pages = os.path.join(sb4, "site")
    os.makedirs(pages)
    for name, body in (("index.html", '<h1>Manual</h1><a href="ch1.html">One</a>'
                                      '<a href="ch2.html">Two</a>'
                                      '<a href="https://other.example/x">off-site</a>'),
                       ("ch1.html", "<h1>Chapter 1</h1><p>first</p>"),
                       ("ch2.html", "<h1>Chapter 2</h1><p>second</p>")):
        with open(os.path.join(pages, name), "w", encoding="utf-8") as f:
            f.write(f"<html><title>{name}</title><body>{body}</body></html>")
    base, stop_site = serve_dir(pages)
    idx = f"{base}/index.html"
    try:
        with open(os.path.join(pages, "index.html"), "r", encoding="utf-8") as f:
            links = ingest.same_site_links(idx, f.read())
        assert len(links) == 2 and all("other.example" not in u for u in links), links
        ids = ingest.add_url(sb4, idx, course="manual", crawl=10)
        assert isinstance(ids, list) and len(ids) == 3, ids
    finally:
        stop_site()
    with open(os.path.join(sb4, "courses", "manual", "lessons", "02", "lesson.md"),
              "r", encoding="utf-8") as f:
        assert "first" in f.read()
    print("[crawl] manual index + 2 same-site pages ingested; off-site links ignored")
    print("PASS test_material")


if __name__ == "__main__":
    main()
