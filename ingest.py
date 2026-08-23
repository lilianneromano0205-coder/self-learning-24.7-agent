#!/usr/bin/env python3
"""Ingestion pipeline (Part 4): every input type, exact path. Stdlib-only;
external tools (ffmpeg, pandoc, pymupdf) are used when present and fail with
actionable errors when not.

Subcommands (all take --root, default "."):

  scan-inbox [--course NAME]        classify inbox/ items, create the course
                                    structure, queue Ripper/Watcher tasks
  pdf-text IN OUT                   extract PDF text layer (pymupdf)
  pdf-pages IN OUTDIR               render PDF pages to PNG (for vision)
  docx IN OUT                       docx/odt/rtf -> markdown (pandoc)
  chunk-audio IN OUTDIR             extract audio + split into <25MB chunks (ffmpeg)
  transcribe IN_FILE_OR_DIR OUT     Groq Whisper -> timestamped transcript
                                    (needs GROQ_API_KEY)
  frames VIDEO OUTDIR [--scene S]   scene-change keyframes (ffmpeg) + crude dedupe
  vision IMAGE OUT [--prompt P]     vision model reads an image (OpenRouter,
                                    needs OPENROUTER_API_KEY)

The Ripper role calls these via run_command; scan-inbox is also what you (or
a cron/systemd timer) run to make "drop anything in inbox/" work.
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser

TYPE_BY_EXT = {
    ".mp4": "video", ".mkv": "video", ".mov": "video", ".avi": "video", ".webm": "video",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio",
    ".flac": "audio", ".opus": "audio",
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image",
    ".docx": "docx", ".doc": "docx", ".odt": "docx", ".rtf": "docx",
    ".pptx": "docx", ".ppt": "docx", ".xlsx": "docx", ".epub": "docx",
    ".mobi": "docx", ".azw3": "docx",
    ".txt": "text", ".md": "text", ".markdown": "text", ".rst": "text",
    ".csv": "text", ".json": "text", ".yaml": "text", ".yml": "text",
    ".srt": "subs", ".vtt": "subs",
    ".html": "html", ".htm": "html",
    ".zip": "archive",
    ".url": "urls", ".urls": "urls",
}

# yt-dlp handles 1000+ sites; these are the ones worth routing on sight.
VIDEO_HOSTS = (
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "bilibili.com",
    "twitch.tv", "ted.com", "coursera.org", "udemy.com", "edx.org",
    "khanacademy.org", "pluralsight.com", "linkedin.com/learning",
    "skillshare.com", "loom.com", "wistia.com", "rumble.com", "odysee.com",
    "facebook.com/watch", "instagram.com/reel", "tiktok.com",
)

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"

# The vision agent rides any OpenAI-compatible VLM endpoint. Pick the rail
# with VISION_PROVIDER (openrouter | nvidia | huggingface); NVIDIA's is free
# with a build.nvidia.com developer key.
VISION_RAILS = {
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions",
                   "OPENROUTER_API_KEY", "google/gemini-flash-1.5"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions",
               "NVIDIA_API_KEY", "meta/llama-3.2-90b-vision-instruct"),
    "huggingface": ("https://router.huggingface.co/v1/chat/completions",
                    "HF_TOKEN", "Qwen/Qwen2.5-VL-72B-Instruct"),
}
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "openrouter")
OPENROUTER_URL, _VISION_KEY_ENV, _VISION_DEFAULT = \
    VISION_RAILS.get(VISION_PROVIDER, VISION_RAILS["openrouter"])
DEFAULT_VISION_MODEL = os.environ.get("VISION_MODEL") \
    or os.environ.get("OPENROUTER_VISION_MODEL") or _VISION_DEFAULT


def classify(path):
    return TYPE_BY_EXT.get(os.path.splitext(path)[1].lower(), "unknown")


def slugify(name):
    # accents transliterate instead of vanishing: Résumé -> resume
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "course"


def need(tool):
    if shutil.which(tool) is None:
        sys.exit(f"ERROR: '{tool}' is not installed or not on PATH. "
                 f"Install it (Part 4 A3) and retry.")


def fmt_ts(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ------------------------------------------------------------- extraction

def try_rich_convert(src, dst):
    """Optional upgrade path: if Docling or MarkItDown is installed, use it —
    they preserve layout, tables, and reading order far better than a raw text
    dump, and MarkItDown covers pptx/xlsx/epub too. Neither is required; the
    stdlib/pymupdf path below is always the fallback. Returns True on success.

      pip install docling      # best structure (tables, reading order)
      pip install markitdown[all]   # widest format coverage
    """
    try:
        from docling.document_converter import DocumentConverter
        text = DocumentConverter().convert(src).document.export_to_markdown()
        if text.strip():
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with open(dst, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {dst}: {len(text)} chars (docling, layout-aware)")
            return True
    except Exception:
        pass
    try:
        from markitdown import MarkItDown
        text = MarkItDown().convert(src).text_content
        if text.strip():
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with open(dst, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {dst}: {len(text)} chars (markitdown)")
            return True
    except Exception:
        pass
    return False


def pdf_text(src, dst):
    if try_rich_convert(src, dst):
        with open(dst, "r", encoding="utf-8") as f:
            return len(f.read())
    try:
        import fitz  # pymupdf
    except ImportError:
        sys.exit("ERROR: pymupdf not installed (pip install pymupdf).")
    doc = fitz.open(src)
    pages = []
    for i, page in enumerate(doc, 1):
        pages.append(f"[page {i}]\n{page.get_text().strip()}")
    text = "\n\n".join(pages)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    printable = sum(len(p) for p in pages) - 9 * len(pages)
    print(f"wrote {dst}: {len(doc)} pages, ~{printable} chars of text layer")
    return printable


def pdf_pages(src, outdir, dpi=150):
    try:
        import fitz
    except ImportError:
        sys.exit("ERROR: pymupdf not installed (pip install pymupdf).")
    os.makedirs(outdir, exist_ok=True)
    doc = fitz.open(src)
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(dpi=dpi)
        pix.save(os.path.join(outdir, f"page-{i:03d}.png"))
    print(f"rendered {len(doc)} pages to {outdir}")


def docx_convert(src, dst):
    """docx/odt/rtf/pptx/xlsx/epub -> markdown. Uses Docling or MarkItDown when
    installed (they also cover slides, sheets, and ebooks); pandoc otherwise."""
    if try_rich_convert(src, dst):
        return
    need("pandoc")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    subprocess.run(["pandoc", src, "-t", "gfm", "-o", dst], check=True, timeout=300)
    print(f"wrote {dst}")


def chunk_audio(src, outdir, segment_seconds=1200):
    """Extract 16kHz mono mp3 and split into ~20-minute segments, which stay
    comfortably under Groq's 25MB per-file limit at 32kbps."""
    need("ffmpeg")
    os.makedirs(outdir, exist_ok=True)
    pattern = os.path.join(outdir, "chunk-%03d.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vn",
         "-ar", "16000", "-ac", "1", "-b:a", "32k",
         "-f", "segment", "-segment_time", str(segment_seconds), pattern],
        check=True, timeout=3600)
    chunks = sorted(f for f in os.listdir(outdir) if f.startswith("chunk-"))
    print(f"wrote {len(chunks)} chunk(s) to {outdir}")
    return [os.path.join(outdir, c) for c in chunks]


# ------------------------------------------------------------- transcription

def multipart_body(fields, file_field, file_path):
    """Build a multipart/form-data body with the stdlib only."""
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
            .encode("utf-8"))
    ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        data = f.read()
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
         f"filename=\"{os.path.basename(file_path)}\"\r\n"
         f"Content-Type: {ctype}\r\n\r\n").encode("utf-8") + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe_chunk(path, api_key):
    body, ctype = multipart_body(
        {"model": GROQ_WHISPER_MODEL, "response_format": "verbose_json"},
        "file", path)
    req = urllib.request.Request(
        GROQ_TRANSCRIBE_URL, data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": ctype},
        method="POST")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    raise RuntimeError("unreachable")


def transcribe(src, dst):
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        sys.exit("ERROR: GROQ_API_KEY is not set.")
    if os.path.isdir(src):
        files = sorted(os.path.join(src, f) for f in os.listdir(src)
                       if classify(f) == "audio")
    else:
        files = [src]
    if not files:
        sys.exit(f"ERROR: no audio files found at {src}")
    # fiber-style checkpoint: a crash at chunk 17 resumes at chunk 18 — the
    # transcribed lines and running offset of every finished chunk are
    # durable before the next chunk starts
    import checkpoint as _ck
    base = os.environ.get("AGENT_ROOT") or os.path.dirname(os.path.abspath(dst))
    ck = _ck.Checkpoint(base, _ck.key_for("transcribe", src, dst))
    lines, offset = [], 0.0
    recovered = 0
    for path in files:
        item = os.path.basename(path)
        if ck.is_done(item):
            saved = ck.get(f"chunk:{item}") or {}
            lines += saved.get("lines", [])
            offset = float(saved.get("offset", offset))
            recovered += 1
            continue
        size = os.path.getsize(path)
        if size > 25_000_000:
            sys.exit(f"ERROR: {path} is {size} bytes (> Groq's 25MB limit) — "
                     f"run chunk-audio first.")
        resp = transcribe_chunk(path, api_key)
        segments = resp.get("segments") or []
        chunk_lines = []
        if segments:
            for seg in segments:
                chunk_lines.append(f"[{fmt_ts(offset + seg['start'])}] {seg['text'].strip()}")
            offset += segments[-1]["end"]
        elif resp.get("text"):
            chunk_lines.append(f"[{fmt_ts(offset)}] {resp['text'].strip()}")
        lines += chunk_lines
        ck.mark(item, **{f"chunk:{item}": {"lines": chunk_lines, "offset": offset}})
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    ck.finish()
    print(f"wrote {dst}: {len(lines)} segments from {len(files)} file(s)"
          + (f" ({recovered} recovered from checkpoint)" if recovered else ""))


# ------------------------------------------------------------- frames/vision

def frames(video, outdir, scene=0.3):
    need("ffmpeg")
    os.makedirs(outdir, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", video,
         "-vf", f"select='gt(scene,{scene})'", "-vsync", "vfr",
         os.path.join(outdir, "%04d.png")],
        check=True, timeout=3600)
    # crude dedupe: drop a frame whose size is within 2% of its predecessor's
    kept, prev = [], None
    for fn in sorted(os.listdir(outdir)):
        p = os.path.join(outdir, fn)
        size = os.path.getsize(p)
        if prev is not None and abs(size - prev) <= prev * 0.02:
            os.remove(p)
        else:
            kept.append(fn)
            prev = size
    print(f"kept {len(kept)} keyframes in {outdir}")


def vision(image, dst, prompt=None):
    api_key = os.environ.get(_VISION_KEY_ENV, "")
    if not api_key:
        sys.exit(f"ERROR: {_VISION_KEY_ENV} is not set "
                 f"(vision rail: {VISION_PROVIDER}; switch with VISION_PROVIDER="
                 f"openrouter|nvidia|huggingface — nvidia is free via "
                 f"build.nvidia.com).")
    prompt = prompt or ("Transcribe all text in this image verbatim, then "
                        "describe its structure (layout, diagrams, code, tables).")
    ctype = mimetypes.guess_type(image)[0] or "image/png"
    with open(image, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    payload = {
        "model": DEFAULT_VISION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{b64}"}},
        ]}],
    }
    req = urllib.request.Request(
        OPENROUTER_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read().decode("utf-8"))
    text = resp["choices"][0]["message"]["content"]
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {dst} ({len(text)} chars, model {DEFAULT_VISION_MODEL})")


# ------------------------------------------------------------- URLs

BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "blockquote", "pre"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html):
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    title = p.title.strip()
    return (f"# {title}\n\n{text}" if title else text)


def is_youtube(url):
    host = urllib.parse.urlsplit(url).netloc.lower()
    return "youtube.com" in host or "youtu.be" in host


def is_video_url(url):
    """True for any known video/course-video host (yt-dlp handles far more;
    the Ripper can still be pointed at anything by hand)."""
    p = urllib.parse.urlsplit(url)
    hostpath = (p.netloc + p.path).lower().replace("www.", "")
    return any(h in hostpath for h in VIDEO_HOSTS)


def is_playlist_url(url):
    p = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(p.query)
    return ("list" in q or "/playlist" in p.path.lower()
            or "/channel/" in p.path.lower() or "/@" in p.path)


def subs_to_text(raw):
    """SRT or WebVTT -> timestamped plain text, de-duplicated (auto-captions
    repeat each line as they scroll)."""
    lines, last = [], None
    stamp = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        m = re.match(r"(\d{2}:\d{2}:\d{2})[.,]\d+\s*-->", line)
        if m:
            stamp = m.group(1)
            continue
        if line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        text = re.sub(r"<[^>]+>", "", line).strip()
        if text and text != last:
            lines.append(f"[{stamp or '00:00:00'}] {text}")
            last = text
    return "\n".join(lines)


def youtube_subs(url, dst):
    """Captions-first: most course videos already carry subtitles. Fetching
    them costs nothing and takes a second, versus downloading audio and paying
    for transcription. Returns True when a transcript was produced."""
    need("yt-dlp")
    workdir = os.path.join(os.path.dirname(dst) or ".", "_subs")
    os.makedirs(workdir, exist_ok=True)
    cmd = ["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-langs", "en.*,en,live_chat-none", "--sub-format", "vtt/srt",
           "-o", os.path.join(workdir, "%(id)s.%(ext)s"), url]
    for d in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        ck = os.path.join(d, "cookies.txt")
        if os.path.exists(ck):
            cmd[1:1] = ["--cookies", ck]
            break
    subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    found = sorted(f for f in os.listdir(workdir) if f.endswith((".vtt", ".srt")))
    if not found:
        print("no captions available — fall back to audio + transcription")
        return False
    with open(os.path.join(workdir, found[0]), "r", encoding="utf-8",
              errors="replace") as f:
        text = subs_to_text(f.read())
    if not text.strip():
        return False
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(f"SOURCE-URL: {url}\n\n{text}\n")
    shutil.rmtree(workdir, ignore_errors=True)
    print(f"wrote {dst}: {len(text.splitlines())} caption lines (free, no transcription)")
    return True


def playlist_entries(url):
    """Expand a playlist/channel/course URL into its individual video URLs."""
    need("yt-dlp")
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-json", url],
                       capture_output=True, text=True, timeout=600)
    out = []
    for line in r.stdout.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = e.get("url") or e.get("webpage_url")
        if u and not u.startswith("http"):
            u = f"https://www.youtube.com/watch?v={u}"
        if u:
            out.append({"url": u, "title": e.get("title") or ""})
    return out


class _LinkFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)


def same_site_links(base_url, html, limit=40):
    """Links on the same site, in document order — how a manual, guide, or
    docs course is walked page by page."""
    p = _LinkFinder()
    p.feed(html)
    base = urllib.parse.urlsplit(base_url)
    seen, out = {base_url.split("#")[0]}, []
    for href in p.links:
        u = urllib.parse.urljoin(base_url, href).split("#")[0]
        s = urllib.parse.urlsplit(u)
        if s.scheme not in ALLOWED_SCHEMES or s.netloc != base.netloc:
            continue
        if os.path.splitext(s.path)[1].lower() in (
                ".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js", ".ico"):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out


MAX_FETCH_BYTES = 256 * 1024 * 1024  # a course file should never exceed this


ALLOWED_SCHEMES = ("http", "https")


def _check_scheme(url):
    """Ingestion fetches whatever it is pointed at, and urlopen speaks file://
    as happily as https. A `.url` file dropped in inbox/ is auto-scanned, so
    one line reading file:///.../agent.env put the provider key into course
    material — bypassing _safe_path entirely, because this is a different
    code path. The inbox is the lowest-privilege input in the platform; it
    does not get to read the disk."""
    scheme = (urllib.parse.urlsplit(str(url)).scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(
            f"refusing to fetch a '{scheme or 'schemeless'}' URL: ingestion "
            f"accepts {' and '.join(ALLOWED_SCHEMES)} only. To teach a local "
            f"file, drop it in inbox/ or use `ingest.py add-folder`.")
    return url


def fetch_url(url, dst):
    """Fetch any URL to lesson text: HTML is stripped to clean text, PDFs go
    through pymupdf, plain text is saved as-is. Downloads are capped so one
    huge link cannot fill the disk."""
    _check_scheme(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; learning-agent/1.0)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = r.headers.get_content_type()
        data = r.read(MAX_FETCH_BYTES + 1)
    if len(data) > MAX_FETCH_BYTES:
        raise ValueError(f"{url} is larger than "
                         f"{MAX_FETCH_BYTES // 1024 // 1024}MB — download it "
                         f"manually and drop the file into inbox/")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if ctype == "application/pdf" or url.lower().endswith(".pdf"):
        tmp = dst + ".src.pdf"
        with open(tmp, "wb") as f:
            f.write(data)
        pdf_text(tmp, dst)
        return dst
    text = data.decode("utf-8", errors="replace")
    if ctype == "text/html" or "<html" in text[:2000].lower():
        text = html_to_text(text)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(f"SOURCE-URL: {url}\n\n{text}")
    print(f"wrote {dst}: {len(text)} chars from {url}")
    return dst


def youtube_audio(url, outdir):
    """Download a YouTube video's audio via yt-dlp (uses cookies.txt beside
    the agent if present — the designed answer to datacenter-IP blocking)."""
    need("yt-dlp")
    os.makedirs(outdir, exist_ok=True)
    cmd = ["yt-dlp", "-x", "--audio-format", "mp3",
           "-o", os.path.join(outdir, "%(title)s.%(ext)s"), url]
    for cookie_dir in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        ck = os.path.join(cookie_dir, "cookies.txt")
        if os.path.exists(ck):
            cmd[1:1] = ["--cookies", ck]
            break
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        sys.exit(f"ERROR: yt-dlp failed (bot detection? export cookies.txt or "
                 f"download locally and drop the file in inbox/):\n{r.stderr[-500:]}")
    print(f"downloaded audio to {outdir}")


def _course_for_url(root, url, course):
    parts = urllib.parse.urlsplit(url)
    cname = course or slugify(parts.netloc + "-" + (parts.path.strip("/") or "home"))[:48]
    course_dir = os.path.join(root, "courses", cname)
    os.makedirs(course_dir, exist_ok=True)
    with open(os.path.join(course_dir, "sources.md"), "a", encoding="utf-8") as f:
        f.write(f"- {url}\n")
    _rate(root, cname, url)
    return cname, course_dir


def _rate(root, course, ref, title="", kind=""):
    """Every ingested source enters the ledger with an authority tier, so a
    later contradiction between two of them can be ruled on instead of
    averaged (sources.py / conflicts.py). Never fatal: material still
    ingests if the ledger cannot be written."""
    try:
        import sources
        return sources.record(root, course, ref, title, kind)
    except Exception:
        return None


def _queue_watcher(agent, root, cname, lesson_dir, nn, source, doc_rel):
    lesson_rel = os.path.relpath(lesson_dir, root).replace(os.sep, "/")
    return agent.add_task(
        "watcher",
        f"Study lesson {nn} of course {cname} (source: {source}). The text is "
        f"in {doc_rel}. Write {lesson_rel}/notes.md in the house format, append "
        f"R-items to spec.md, append the lesson line to index.md.",
        memory_files=[doc_rel], course=cname)


def add_url(root, url, course=None, crawl=0, max_items=200):
    """Turn ANY link into learning.

    playlist / channel / course index -> expanded into one lesson per video
    any video host (yt-dlp's 1000+)   -> Ripper: captions first, audio if none
    docs / manuals / guides (crawl>0) -> the page plus its same-site pages
    web page, online book, PDF link   -> fetched, cleaned, queued to Watcher
    anything that resists             -> Ripper task with exact instructions
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loop
    agent = loop.Agent(root)

    # --- a playlist / channel / course index becomes many lessons
    if is_video_url(url) and is_playlist_url(url):
        try:
            entries = playlist_entries(url)[:max_items]
        except Exception as e:
            entries = []
            print(f"playlist expansion failed ({e}); treating as a single video")
        if entries:
            cname, _ = _course_for_url(root, url, course)
            ids = [add_url(root, e["url"], course=cname) for e in entries]
            print(f"{url}: playlist -> {len(ids)} lesson(s) queued for course {cname}")
            return ids
    cname, course_dir = _course_for_url(root, url, course)
    lesson_dir, nn = next_lesson_dir(course_dir)
    lesson_rel = os.path.relpath(lesson_dir, root).replace(os.sep, "/")

    # --- video of any host: captions first (free), audio + Whisper only if needed
    if is_video_url(url):
        tid = agent.add_task(
            "ripper",
            f"Ingest video {url} into {lesson_rel}/ for course {cname}. "
            f"STEP 1 (always try first, it is free and instant): "
            f"`python ingest.py subs \"{url}\" {lesson_rel}/transcript.txt`. "
            f"If that produces a transcript, you are done. "
            f"STEP 2 only if no captions exist: "
            f"`python ingest.py youtube \"{url}\" {lesson_rel}/audio`, then "
            f"chunk-audio and transcribe into {lesson_rel}/transcript.txt. "
            f"cookies.txt is used automatically; if the site blocks automated "
            f"access, ask_human for a local upload — never fight bot detection.",
            course=cname)
        print(f"{url}: video -> lesson {nn}, queued ripper task {tid} (captions first)")
        return tid

    # a refused scheme is a permanent answer, not a transient fetch failure:
    # queueing a Ripper to "try again with run_command" would just hand the
    # same refusal to a model and waste a task
    _check_scheme(url)

    # --- fetch the page/book/PDF itself
    try:
        dst = os.path.join(lesson_dir, "lesson.md")
        fetch_url(url, dst)
        doc_rel = os.path.relpath(dst, root).replace(os.sep, "/")
        ids = [_queue_watcher(agent, root, cname, lesson_dir, nn, url, doc_rel)]
        print(f"{url}: fetched -> lesson {nn}, queued watcher task {ids[0]}")
    except Exception as e:
        tid = agent.add_task(
            "ripper",
            f"Fetch and ingest {url} into {lesson_rel}/ for course {cname}. "
            f"The direct fetch failed with: {e}. Try "
            f"`python ingest.py fetch \"{url}\" {lesson_rel}/lesson.md` via "
            f"run_command; if the site blocks automated access, ask_human for a "
            f"manual export dropped into inbox/.",
            course=cname)
        print(f"{url}: fetch failed ({e}) -> queued ripper task {tid}")
        return tid

    # --- a manual / guide / docs course: follow its same-site pages
    if crawl > 0:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; learning-agent/1.0)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                html = r.read().decode("utf-8", errors="replace")
            # checkpointed per sub-page: a crawl that dies at page 17 resumes
            # at page 18 and never queues a page twice
            import checkpoint as _ck
            ck = _ck.Checkpoint(root, _ck.key_for("crawl", url, cname))
            for sub in same_site_links(url, html, limit=crawl):
                if ck.is_done(sub):
                    continue
                try:
                    sd, snn = next_lesson_dir(course_dir)
                    sdst = os.path.join(sd, "lesson.md")
                    fetch_url(sub, sdst)
                    ids.append(_queue_watcher(
                        agent, root, cname, sd, snn, sub,
                        os.path.relpath(sdst, root).replace(os.sep, "/")))
                    ck.mark(sub)
                except Exception as e:
                    print(f"  skipped {sub}: {e}")
            ck.finish()
            with open(os.path.join(course_dir, "sources.md"), "a", encoding="utf-8") as f:
                f.write(f"- (crawled {len(ids) - 1} linked page(s) from {url})\n")
            print(f"{url}: crawled -> {len(ids)} lesson(s) total for course {cname}")
        except Exception as e:
            print(f"crawl failed ({e}); the index page itself was still ingested")
    return ids if len(ids) > 1 else ids[0]


# ------------------------------------------------------------- folders/zips

def ingest_folder(root, folder, course=None, max_items=500):
    """A whole course in a folder: every file becomes a lesson, in sorted
    order, walked recursively. Sub-folders are kept in the lesson naming so a
    'Module 2 / lesson 3' structure survives ingestion."""
    folder = os.path.abspath(folder)
    cname = course or slugify(os.path.basename(folder.rstrip(os.sep)))
    files = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        for fn in sorted(filenames):
            if not fn.startswith("."):
                files.append(os.path.join(dirpath, fn))
    files = files[:max_items]
    if not files:
        print(f"{folder}: no files found")
        return 0
    print(f"{folder}: {len(files)} file(s) -> course {cname}")
    # checkpointed: a crash (or a second run) never routes a file twice
    import checkpoint as _ck
    ck = _ck.Checkpoint(root, _ck.key_for("ingest_folder", folder, cname))
    queued = 0
    for path in files:
        rel = os.path.relpath(path, folder)
        if ck.is_done(rel):
            continue
        queued += route_file(root, path, cname, label=rel, move=False)
        ck.mark(rel)
    ck.finish()
    return queued


def unpack_archive(root, archive, course=None):
    """A course delivered as a .zip: extract into the course's source/ and
    ingest the extracted tree as a folder."""
    import zipfile
    cname = course or slugify(os.path.splitext(os.path.basename(archive))[0])
    dest = os.path.join(root, "courses", cname, "source",
                        os.path.splitext(os.path.basename(archive))[0])
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        real_dest = os.path.realpath(dest)
        for member in z.namelist():
            # never let an archive write outside its own directory — compare
            # against dest + separator, else a sibling like "../dest-x/f"
            # passes a plain string-prefix check
            target = os.path.realpath(os.path.join(dest, member))
            if target == real_dest or target.startswith(real_dest + os.sep):
                z.extract(member, dest)
    print(f"{archive}: extracted to {os.path.relpath(dest, root)}")
    return ingest_folder(root, dest, course=cname)


# ------------------------------------------------------------- inbox scan

def next_lesson_dir(course_dir):
    lessons = os.path.join(course_dir, "lessons")
    os.makedirs(lessons, exist_ok=True)
    existing = [int(d) for d in os.listdir(lessons) if d.isdigit()]
    nn = f"{(max(existing) + 1) if existing else 1:02d}"
    d = os.path.join(lessons, nn)
    os.makedirs(d, exist_ok=True)
    return d, nn


def route_file(root, src, cname, label=None, move=True):
    """Route one file of any format into a course as a lesson. Returns 1 when
    something was queued (or handled), 0 when nothing was."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loop
    agent = loop.Agent(root)
    fn = os.path.basename(src)
    label = label or fn
    kind = classify(fn)
    course_dir = os.path.join(root, "courses", cname)
    os.makedirs(os.path.join(course_dir, "source"), exist_ok=True)
    _rate(root, cname, label, title=fn,
          kind={"video": "video", "audio": "video", "pdf": "book",
                "doc": "book", "text": ""}.get(kind, ""))

    if kind == "archive":
        stored = os.path.join(course_dir, "source", fn)
        (shutil.move if move else shutil.copy)(src, stored)
        unpack_archive(root, stored, course=cname)
        return 1

    if kind == "urls":
        stored = os.path.join(course_dir, "source", fn)
        (shutil.move if move else shutil.copy)(src, stored)
        with open(stored, "r", encoding="utf-8", errors="replace") as f:
            urls = [u.strip() for u in f
                    if u.strip() and not u.strip().startswith("#")]
        for u in urls:
            add_url(root, u, course=cname)
        print(f"{label}: {len(urls)} link(s) routed for course {cname}")
        return 1

    stored = os.path.join(course_dir, "source", fn)
    if os.path.exists(stored):  # keep same-named files from different folders
        stem, ext = os.path.splitext(fn)
        stored = os.path.join(course_dir, "source",
                              f"{stem}-{slugify(os.path.dirname(label))[:20]}{ext}")
    (shutil.move if move else shutil.copy)(src, stored)
    stored_rel = os.path.relpath(stored, root).replace(os.sep, "/")
    lesson_dir, nn = next_lesson_dir(course_dir)
    lesson_rel = os.path.relpath(lesson_dir, root).replace(os.sep, "/")

    # formats that are already text need no model to "rip"
    if kind in ("text", "subs", "html"):
        dst = os.path.join(lesson_dir, "lesson.md")
        with open(stored, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        body = (subs_to_text(raw) if kind == "subs"
                else html_to_text(raw) if kind == "html" else raw)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(f"SOURCE-FILE: {label}\n\n{body}")
        doc_rel = os.path.relpath(dst, root).replace(os.sep, "/")
        tid = _queue_watcher(agent, root, cname, lesson_dir, nn, label, doc_rel)
        print(f"{label}: {kind} -> lesson {nn}, queued watcher task {tid}")
        return 1

    if kind == "unknown":
        print(f"{label}: UNKNOWN type — kept in {stored_rel}, no task queued")
        return 1

    tid = agent.add_task(
        "ripper",
        f"Ingest {stored_rel} (type: {kind}, original name: {label}) into "
        f"{lesson_rel}/ for course {cname}. Use the ingest.py helpers via "
        f"run_command: pdf-text (then pdf-pages + vision if the text layer is "
        f"empty) for pdf, chunk-audio then transcribe for video/audio, docx for "
        f"documents and ebooks, vision for images. End state: {lesson_rel}/ "
        f"contains transcript.txt or lesson.md; finish_task when it does.",
        course=cname)
    print(f"{label}: {kind} -> lesson {nn}, queued ripper task {tid}")
    return 1


def scan_inbox(root, course=None):
    """Classify every file in inbox/, move it into its course's source/, and
    queue the right task: Watcher directly for plain text (deterministic copy,
    no model needed for ripping), Ripper for everything else. Files modified
    within the last inbox_settle_seconds are skipped (still being copied).
    Returns the number of files processed."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loop
    agent = loop.Agent(root)
    settle = agent.cfg.get("agent", {}).get("inbox_settle_seconds", 10)
    inbox = os.path.join(root, "inbox")
    items = sorted(f for f in os.listdir(inbox) if not f.startswith("."))
    if not items:
        print("inbox is empty")
        return 0
    processed = 0
    for fn in items:
        src = os.path.join(inbox, fn)
        if time.time() - os.path.getmtime(src) < settle:
            print(f"{fn}: still settling (modified <{settle}s ago), next scan")
            continue

        # a whole course dropped as a folder
        if os.path.isdir(src):
            cname = course or slugify(fn)
            n = ingest_folder(root, src, course=cname)
            if n:
                dest = os.path.join(root, "courses", cname, "source", fn)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if os.path.exists(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(src, dest)
                processed += 1
            continue
        cname = course or slugify(os.path.splitext(fn)[0])
        processed += route_file(root, src, cname)
    return processed


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan-inbox")
    p.add_argument("--course", default=None)
    p.add_argument("--root", default=".")

    for name, nargs in (("pdf-text", 2), ("pdf-pages", 2), ("docx", 2),
                        ("chunk-audio", 2), ("transcribe", 2)):
        p = sub.add_parser(name)
        p.add_argument("src")
        p.add_argument("dst")

    p = sub.add_parser("frames")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--scene", type=float, default=0.3)

    p = sub.add_parser("vision")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--prompt", default=None)

    p = sub.add_parser("add-url", help="turn any link into a queued lesson")
    p.add_argument("url")
    p.add_argument("--course", default=None)
    p.add_argument("--crawl", type=int, default=0,
                   help="also ingest N linked pages from the same site "
                        "(for manuals, guides, and docs courses)")
    p.add_argument("--root", default=".")

    p = sub.add_parser("add-folder", help="ingest a whole course folder")
    p.add_argument("folder")
    p.add_argument("--course", default=None)
    p.add_argument("--root", default=".")

    p = sub.add_parser("subs", help="fetch a video's captions (free, no Whisper)")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("fetch", help="fetch a URL to lesson text")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("youtube", help="download a YouTube video's audio (yt-dlp)")
    p.add_argument("src")
    p.add_argument("dst")

    args = ap.parse_args()
    # keys may live in agent.env next to this script or in the cwd
    for env_dir in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        try:
            with open(os.path.join(env_dir, "agent.env"), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
        except OSError:
            continue
    if args.cmd == "scan-inbox":
        scan_inbox(os.path.abspath(args.root), args.course)
    elif args.cmd == "pdf-text":
        pdf_text(args.src, args.dst)
    elif args.cmd == "pdf-pages":
        pdf_pages(args.src, args.dst)
    elif args.cmd == "docx":
        docx_convert(args.src, args.dst)
    elif args.cmd == "chunk-audio":
        chunk_audio(args.src, args.dst)
    elif args.cmd == "transcribe":
        transcribe(args.src, args.dst)
    elif args.cmd == "frames":
        frames(args.src, args.dst, args.scene)
    elif args.cmd == "vision":
        vision(args.src, args.dst, args.prompt)
    elif args.cmd == "add-url":
        add_url(os.path.abspath(args.root), args.url, args.course, args.crawl)
    elif args.cmd == "add-folder":
        ingest_folder(os.path.abspath(args.root), args.folder, args.course)
    elif args.cmd == "subs":
        sys.exit(0 if youtube_subs(args.src, args.dst) else 1)
    elif args.cmd == "fetch":
        try:
            fetch_url(args.src, args.dst)
        except ValueError as e:
            sys.exit(f"ERROR: {e}")
    elif args.cmd == "youtube":
        youtube_audio(args.src, args.dst)


if __name__ == "__main__":
    main()
