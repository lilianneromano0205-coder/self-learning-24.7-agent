#!/usr/bin/env python3
"""The control panel: create an expert with one click, teach it a link and a
file, read its detail — all through the local HTTP API the UI page uses.
The mission-control surface is covered too: the full task list, the memory
browser (tree + file reads with containment and secrets refusal), manual
task queueing, verify/memcheck execution, provider probing, settings view,
the system dashboard, and expert deletion.

Run from the agent/ directory:  python tests/test_ui.py
"""

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

from common import serve_dir, free_port, AGENT_DIR, make_sandbox

PY = sys.executable
PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"

FINISH = [{"tool": "finish_task", "args": {"summary": "ok"}}]


def api(method, path, body=None, raw=False):
    data = body if raw else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    home = make_sandbox("ui", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m", "watcher": "m", "ripper": "m"},
                        scripts={"s.json": FINISH})
    # the panel ingests the fixture URL in-process, so the child needs the
    # same deliberate opt-in the fixture server declares
    proc = subprocess.Popen([PY, os.path.join(AGENT_DIR, "ui.py"),
                             "--home", home, "--port", str(PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "ALLOW_PRIVATE_INGEST": "1"})
    try:
        for _ in range(50):
            try:
                assert api("GET", "/api/experts") == []
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("panel did not come up")
        print("[up] panel serving on 127.0.0.1, empty fleet listed")

        # the button: create an expert
        r = api("POST", "/api/experts", {"name": "Deep Learner",
                                         "identity": "neural nets"})
        assert r.get("created") == "deep-learner", r
        experts = api("GET", "/api/experts")
        assert len(experts) == 1 and experts[0]["identity"] == "neural nets"
        print("[create] one click -> expert with its own identity and memory")

        # teach it a link, over the real scheme ingestion accepts
        page = os.path.join(home, "p.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write("<html><title>T</title><body><p>lesson body</p></body></html>")
        base, stop_pages = serve_dir(home)
        try:
            r = api("POST", "/api/experts/deep-learner/url",
                    {"url": f"{base}/p.html", "course": "webcourse"})
            assert "task" in r, r
        finally:
            stop_pages()

        # a file:// link is refused outright: the panel teaches from the web,
        # and the inbox is how a local file gets in (audit P1-7)
        try:
            api("POST", "/api/experts/deep-learner/url",
                {"url": pathlib.Path(page).as_uri(), "course": "nope"})
            raise AssertionError("teaching a file:// link must be refused")
        except urllib.error.HTTPError as e:
            assert e.code in (400, 500), e.code

        # teach it a file (upload straight to its inbox)
        r = api("PUT", "/api/experts/deep-learner/file?name=book.md",
                b"# Book\nchapter one", raw=True)
        assert r.get("saved") == "book.md", r
        assert os.path.exists(os.path.join(home, "experts", "deep-learner",
                                           "inbox", "book.md"))

        d = api("GET", "/api/experts/deep-learner")
        assert any(t["role"] == "watcher" for t in d["recent_tasks"]),             d["recent_tasks"]
        assert any(c == "webcourse" for c in d["courses"])
        assert "blocked_md" in d and "log" in d and "running" in d
        print("[teach] URL became a queued lesson; file landed in the inbox; "
              "detail view carries tasks, courses, blocked, log")

        # unknown expert is a clean 404, not a crash
        try:
            api("GET", "/api/experts/ghost")
            raise AssertionError("unknown expert must 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        print("[safety] unknown expert -> 404")

        # --- mission control: system dashboard
        sysd = api("GET", "/api/system")
        assert sysd["n_experts"] == 1 and sysd["experts"][0]["name"] == "deep-learner"
        assert "queued" in sysd["totals"] and sysd["spend_today_usd"] >= 0
        print("[system] fleet dashboard aggregates experts, tasks, spend")

        # --- mission control: full task list (the Board's data)
        tasks = api("GET", "/api/experts/deep-learner/tasks")
        assert tasks and all(k in tasks[0] for k in
                             ("id", "role", "status", "goal", "steps", "created"))
        print("[board] full task list served with ids, steps, ages")

        # --- mission control: memory browser
        tree = api("GET", "/api/experts/deep-learner/tree")
        paths = {e["p"] for e in tree}
        assert "courses" in paths and "inbox/book.md" in paths, sorted(paths)[:8]
        f = api("GET", "/api/experts/deep-learner/file?path=inbox/book.md")
        assert f["content"].startswith("# Book") and f["size"] > 0
        for bad in ("../p.html", "settings/../..", "agent.env"):
            try:
                api("GET", f"/api/experts/deep-learner/file?path={bad}")
                raise AssertionError(f"file read must be refused: {bad}")
            except urllib.error.HTTPError as e:
                assert e.code in (400, 404), (bad, e.code)
        print("[memory] tree + file reads work; traversal and secrets refused")

        # --- mission control: queue a task by hand
        r = api("POST", "/api/experts/deep-learner/task",
                {"role": "watcher", "goal": "re-study lesson one",
                 "course": "webcourse"})
        tid = r["queued"]
        assert tid in {t["id"] for t in api("GET", "/api/experts/deep-learner/tasks")}
        print("[tools] manual task queued for any role from the panel")

        # --- mission control: ground-truth checks executed through the panel
        ex = os.path.join(home, "experts", "deep-learner", "courses", "tiny")
        os.makedirs(ex, exist_ok=True)
        with open(os.path.join(ex, "spec.md"), "w", encoding="utf-8") as f:
            f.write("R-001: trivially true CHECK: exit 0\n")
        r = api("POST", "/api/experts/deep-learner/verify", {"course": "tiny"})
        assert r["exit"] == 0 and "PASS" in r["out"], r
        r = api("POST", "/api/experts/deep-learner/memcheck", {"course": "tiny"})
        assert r["exit"] == 0 and "sound" in r["out"], r
        print("[tools] verify.py and memcheck.py run from the panel, output returned")

        # --- mission control: settings view (names only, never key material)
        st = api("GET", "/api/experts/deep-learner/settings")
        assert "m" in st["providers"] and st["providers"]["m"]["mock"] is True
        assert "tester" in st["roles"]
        assert not any("api_key" in k.lower() and v not in ("", None)
                       for prov in st["providers"].values()
                       for k, v in prov.items() if isinstance(v, str)), \
            "no key material may ever appear in the settings view"
        print("[tools] provider/role routing visible; no secrets in the payload")

        # --- mission control: provider probe (mocks answer instantly)
        r = api("POST", "/api/experts/deep-learner/probe", {})
        assert "OK" in r["out"] and r["exit"] == 0, r
        print("[tools] loop.py check probe runs through the panel")

        # --- deep views: the goal cockpit, steering, graph memory,
        #     mastery packs, runbooks, freshness — the panel surfaces the
        #     goal system's whole depth, read from files, none of it asked
        #     of a model
        sys.path.insert(0, AGENT_DIR)
        import capability
        import contract
        root = os.path.join(home, "experts", "deep-learner")
        contract.create(root, "g-ui", "cockpit-visible goal",
                        accept=[{"id": "A1", "what": "never passes",
                                 "check": f'"{PY}" -c "import sys; sys.exit(1)"'}])
        contract.freeze(root, "g-ui")
        g = api("GET", "/api/goal?expert=deep-learner&gid=g-ui")
        assert g["contract"]["state"] == "ready", g["contract"]
        assert g["contract"]["acceptance"][0]["id"] == "A1"
        r = api("POST", "/api/steer", {"expert": "deep-learner",
                                       "gid": "g-ui",
                                       "text": "prefer the CSV export"})
        assert r.get("steered"), r
        g2 = api("GET", "/api/goal?expert=deep-learner&gid=g-ui")
        assert g2["steering"][-1]["text"] == "prefer the CSV export"
        assert any(e["kind"] == "steered" for e in g2["events"]), (
            "steering must land on the ledger — influence is never invisible")
        vr = api("POST", "/api/goal/verify", {"expert": "deep-learner",
                                              "gid": "g-ui"})
        assert vr["mechanical"] and not vr["all"] and "A1" in vr["failed"], vr
        print("[cockpit] a pursuit's contract, graders, ledger and steering "
              "all readable; a steer lands on the ledger; the graders re-run "
              "on demand and report the failing check by id")

        notes_dir = os.path.join(root, "courses", "gcourse", "lessons", "01")
        os.makedirs(notes_dir, exist_ok=True)
        with open(os.path.join(notes_dir, "notes.md"), "w",
                  encoding="utf-8") as f:
            f.write("- C-01 `alpha_tool` compresses logs "
                    "[expires: 2020-01-01] [src: https://example.org/a]\n"
                    "- C-02 `alpha_tool` needs Python 3.11 "
                    "[src: https://example.org/b]\n")
        kg = api("GET", "/api/knowledge?expert=deep-learner")
        assert "alpha_tool" in kg["entities"], list(kg["entities"])[:5]
        about = api("GET", "/api/knowledge?expert=deep-learner"
                           "&term=alpha_tool")["about"]
        assert len(about["atoms"]) == 2, about
        fr = api("GET", "/api/freshness?expert=deep-learner")
        assert any(x["atom"] == "C-01" for x in fr["expired"]), fr
        r = api("POST", "/api/freshness/retract",
                {"expert": "deep-learner", "ref": "example.org/b",
                 "why": "the vendor pulled the docs"})
        assert r.get("retracted"), r
        fr2 = api("GET", "/api/freshness?expert=deep-learner")
        assert any(x["atom"] == "C-02" for x in fr2["retracted"]), fr2
        print("[graph+fresh] the entity graph serves entities and per-term "
              "atoms; freshness flags the expired atom and a panel-recorded "
              "retraction flags the citing atom")

        capability.draft(home, "ui-pack", "panel-drafted domain",
                         {"reading": "how to read"}, author="someone-else")
        mp = api("GET", "/api/mastery?expert=deep-learner")
        row = next(p for p in mp["packs"] if p["pack"] == "ui-pack")
        assert row["problems"] and row["author"] == "someone-else", row
        assert not row["seal"]["ok"], "an unfrozen draft cannot read sealed"
        rbdir = os.path.join(root, "runbooks")
        os.makedirs(rbdir, exist_ok=True)
        with open(os.path.join(rbdir, "ui-proc.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"name": "ui-proc", "triggers": ["ui"],
                       "when": {"requires": ["true"]},
                       "steps": [{"do": "true", "verify": "true"}]}, f)
        rb = api("GET", "/api/runbooks?expert=deep-learner")
        row = next(x for x in rb["runbooks"] if x["name"] == "ui-proc")
        assert row["status"] == "candidate" and not row.get("draft"), row
        assert row["when"]["requires"] == ["true"], row
        print("[mastery+runbooks] packs list with seal state, author and "
              "draft TODOs; runbooks list with earned trust and typed "
              "applicability")

        # --- mission control: deletion with the loop stopped
        api("POST", "/api/experts", {"name": "Temp Expert", "identity": "x"})
        r = api("DELETE", "/api/experts/temp-expert")
        # deletion RETIRES by default: the agent leaves the active fleet but
        # its whole world is preserved and restorable
        assert r["retired"] == "temp-expert" and r["preserved"] is True, r
        assert all(e["name"] != "temp-expert" for e in api("GET", "/api/experts"))
        assert os.path.isdir(os.path.join(home, "retired", "temp-expert")), \
            "the retired agent's world must survive"
        # an explicit purge is the only thing that destroys
        api("POST", "/api/experts", {"name": "Purge Me", "identity": "x"})
        r = api("DELETE", "/api/experts/purge-me?purge=1")
        assert r["purged"] is True
        assert not os.path.isdir(os.path.join(home, "retired", "purge-me"))
        print("[danger] deletion retires and preserves the whole world; "
              "only an explicit purge destroys it")
        # ---- one request, one response, even when the write fails ---------
        # Every route body sits in a try ending with `except Exception ->
        # 500`. That try also wraps the SUCCESSFUL _json call, so a client
        # closing the tab mid-write raised BrokenPipeError (an OSError, hence
        # Exception), the handler caught it, and answered a second time — a
        # second status line and headers on a connection that had already
        # received a 200. On keep-alive the following response is then read as
        # the previous one's body.
        #
        # Driven directly against the handler class rather than over a socket,
        # because "make the kernel drop the connection at exactly the right
        # microsecond" is not a test, it is a coin toss.
        sys.path.insert(0, AGENT_DIR)
        import ui as ui_mod

        class _Boom(ui_mod.Handler):
            def __init__(self):                      # no socket, no server
                self.home = home
                self._responded = False
                self.sent = []
                self.wfile = self
                self.headers = {}
            def write(self, _b):
                raise BrokenPipeError("the tab was closed")
            def send_response(self, code, *a):
                self.sent.append(code)
            def send_header(self, *a, **k):
                pass
            def end_headers(self):
                pass

        h = _Boom()
        try:
            h._json({"ok": True})                    # the success path...
        except BrokenPipeError:
            h._fail({"error": "boom"}, 500)          # ...as the handler does
        assert h.sent == [200], (
            f"the handler sent {h.sent} — a failed write turned one request "
            f"into two responses on the same connection")

        fresh = _Boom()                              # and a REAL error still answers
        fresh.write = lambda _b: None
        fresh._fail({"error": "genuine"}, 404)
        assert fresh.sent == [404], (
            f"the guard swallowed a legitimate error response: {fresh.sent}")
        print("[one-response] a write that fails after the headers are sent "
              "does not produce a second status line, and an error that "
              "happens before any response still reports normally")

        print("PASS test_ui")
    finally:
        # graceful: the panel terminates its own child drivers first (a bare
        # terminate() on Windows would orphan them to haunt later tests)
        try:
            urllib.request.urlopen(urllib.request.Request(
                BASE + "/api/shutdown", data=b"{}", method="POST",
                headers={"Content-Type": "application/json"}), timeout=5).read()
        except Exception:
            pass
        try:
            proc.wait(10)
        except Exception:
            proc.terminate()
            proc.wait(10)


if __name__ == "__main__":
    main()
