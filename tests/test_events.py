#!/usr/bin/env python3
"""The panel WATCHES instead of asking (M7): a live SSE event stream.

1. /api/events opens a text/event-stream, replays the recent feed, then
   streams what happens as it happens: task_start, tool_call, task_end for a
   drain running concurrently
2. garbage log lines never break the stream
3. the stream is token-guarded exactly like the rest of the API
4. the REST feed and the stream tell the identical story (same rows)

The reader below uses http.client with a hard socket timeout, so this test
can never hang the suite.

Run from the agent/ directory:  python tests/test_events.py
"""

import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error

from common import AGENT_DIR, LOOP, PY, api, make_sandbox, start_panel, \
    stop_panel

sys.path.insert(0, AGENT_DIR)
import fleet
import loop

SCRIPT = [{"tool": "write_file", "args": {"path": "out/a.md", "content": "x"}},
          {"tool": "finish_task", "args": {"summary": "ok"}}]


def read_events(base, path, seconds=25, want=3, token=None, until=None):
    """Read SSE frames until `want` events, `until(event)` is true, or the
    deadline. Never blocks longer than `seconds`.

    `until` exists so a reader can wait for the event it actually cares about
    instead of a wall-clock guess: under a loaded suite a drain can take many
    seconds to start, and a fixed window turned that into a flake.
    """
    host = base.split("//", 1)[1]
    conn = http.client.HTTPConnection(host, timeout=seconds)
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    if resp.status != 200:
        conn.close()
        raise AssertionError(f"stream refused: HTTP {resp.status}")
    ctype = resp.headers.get("Content-Type", "")
    assert "text/event-stream" in ctype, ctype
    assert resp.headers.get("Content-Length") is None, \
        "an event stream must never declare a length"
    out, buf, deadline = [], b"", time.time() + seconds
    try:
        while time.time() < deadline and len(out) < want:
            chunk = resp.read(1)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                text = frame.decode("utf-8", errors="replace")
                if text.startswith(":"):
                    out.append({"event": "__ping__"})
                    continue
                kind = data = None
                for line in text.splitlines():
                    if line.startswith("event: "):
                        kind = line[7:].strip()
                    elif line.startswith("data: "):
                        data = line[6:]
                if kind and data:
                    try:
                        ev = {"event": kind, **json.loads(data)}
                    except json.JSONDecodeError:
                        continue
                    out.append(ev)
                    if until and until(ev):
                        return out
    except (OSError, http.client.HTTPException):
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def main():
    home = make_sandbox("events", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": SCRIPT})
    root = fleet.create(home, "Streamer", "works out loud")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\n\n[providers.m]\ntype = "mock"\n'
                'script = "script.json"\n\n[roles.default]\nprovider = "m"\n'
                'model = "mock"\n')
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump(SCRIPT, f)
    # one finished task BEFORE the stream opens: it must be replayed on connect
    loop.Agent(root).add_task("practitioner", "the earlier task")
    subprocess.run([PY, LOOP, "run", "--drain", "--root", root],
                   capture_output=True, timeout=300)

    proc, base = start_panel(home)
    try:
        # --- 1. replay on connect
        # read until the finished task shows up, rather than assuming it is
        # among the first N replayed rows: the feed carries other kinds too
        # (agent_start, health_ritual...), and their number is not this
        # test's business.
        first = read_events(base, "/api/events", seconds=25, want=60,
                            until=lambda e: e["event"] == "task_end")
        assert any(e["event"] == "task_end" for e in first), \
            [e["event"] for e in first]
        row = next(e for e in first if e["event"] == "task_end")
        assert row["expert"] == "streamer" and row["severity"] == "ok"
        assert "finished a task" in row["text"]
        print("[replay] a new connection is handed the recent history first, "
              "so a freshly opened panel is never blank")

        # --- 2. live: a drain running WHILE we watch
        tid = loop.Agent(root).add_task("practitioner", "the live task")
        got = []

        def watch():
            # stop on the live task's own end event, not on a wall-clock
            # guess: the replay rows come first, and under a loaded suite the
            # drain can take a while to even start
            got.extend(read_events(
                base, "/api/events", seconds=90, want=400,
                until=lambda e: e.get("task") == tid and
                e["event"] == "task_end"))

        th = threading.Thread(target=watch, daemon=True)
        th.start()
        time.sleep(2.0)                      # let the stream reach the live end
        subprocess.run([PY, LOOP, "run", "--drain", "--root", root],
                       capture_output=True, timeout=300)
        th.join(120)
        live = [e for e in got if e.get("task") == tid]
        kinds = [e["event"] for e in live]
        assert "task_start" in kinds, kinds
        assert "tool_call" in kinds, kinds
        assert "task_end" in kinds, kinds
        tool = next(e for e in live if e["event"] == "tool_call")
        assert tool["detail"]["tool"] in ("write_file", "finish_task"), tool
        assert tool["expert"] == "streamer"
        print("[live] the tasks the agent ran while we watched arrived as they "
              "happened: start, each tool call, end")

        # --- 3. garbage and rotation do not break it
        with open(os.path.join(root, "logs", "agent.log"), "a",
                  encoding="utf-8") as f:
            f.write("not json\n{\"event\": \"nope\"}\n")
        tid2 = loop.Agent(root).add_task("practitioner", "after the garbage")
        got2 = []

        def watch2():
            got2.extend(read_events(
                base, "/api/events", seconds=90, want=400,
                until=lambda e: e.get("task") == tid2 and
                e["event"] == "task_end"))

        th2 = threading.Thread(target=watch2, daemon=True)
        th2.start()
        time.sleep(2.0)
        subprocess.run([PY, LOOP, "run", "--drain", "--root", root],
                       capture_output=True, timeout=300)
        th2.join(120)
        assert any(e["event"] == "task_end" and "after the garbage" not in
                   str(e.get("text")) for e in got2), \
            [e["event"] for e in got2]
        print("[robust] unparseable lines in the log were skipped and the "
              "stream kept delivering")

        # --- 4. the stream says what the REST feed says
        feed = api(base, "GET", "/api/feed?limit=40")
        assert isinstance(feed, list) and feed
        assert set(feed[0]) >= {"at", "expert", "event", "severity", "text"}
        assert any(f["event"] == "task_end" for f in feed)
    finally:
        stop_panel(proc, base)

    # --- 5. token-guarded like everything else
    proc2, base2 = start_panel(home, token="s3cr3t")
    try:
        try:
            read_events(base2, "/api/events", seconds=5, want=1)
            raise AssertionError("an unauthenticated stream must be refused")
        except AssertionError as e:
            assert "HTTP 401" in str(e), str(e)
        ok = read_events(base2, "/api/events?token=s3cr3t", seconds=15, want=1)
        assert ok, "the right token opens the stream"
    finally:
        stop_panel(proc2, base2, token="s3cr3t")
    print("[auth] the live stream is guarded by the same token as the API: "
          "both as a header and as ?token= for EventSource")
    print("PASS test_events")


if __name__ == "__main__":
    main()
