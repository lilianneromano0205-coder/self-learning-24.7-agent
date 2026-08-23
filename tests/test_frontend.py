#!/usr/bin/env python3
"""The frontend itself: the page is served from ui.html, wires every tab to a
real endpoint, and never 500s on a freshly created expert (the state a brand
new expert is actually in).

Run from the agent/ directory:  python tests/test_frontend.py
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from common import free_port, AGENT_DIR, make_sandbox

PY = sys.executable
PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def main():
    home = make_sandbox("frontend", providers={"m": {"script": "s.json"}},
                        roles={"watcher": "m"}, scripts={"s.json": []})
    # the page and the code live next to each other and are both required
    page = os.path.join(AGENT_DIR, "ui.html")
    assert os.path.isfile(page), "ui.html must ship beside ui.py"
    with open(page, "r", encoding="utf-8") as f:
        html = f.read()

    # every tab the page offers must map to something the backend serves
    tabs = re.findall(r"\['(\w+)','[^']+'\]", html)
    assert set(tabs) == {"home", "guide", "agents", "work", "memory",
                         "models", "system"}, tabs
    for endpoint in ("/api/system", "/api/experts", "/tasks", "/tree",
                     "/settings", "/file", "/scan", "/answer", "/task",
                     "/api/goals", "/api/commons", "/api/doctor",
                     "/api/templates", "/api/toolbox", "/api/memory",
                     "/api/retired", "/api/team", "/api/quick", "history=1",
                     "/api/feed", "/api/briefing",
                     # the five creation lanes + every framework's surface
                     "/api/learner", "/api/federation", "/prospective",
                     "/skills", "/variants", "/template", "/intention",
                     "/variant", "dlgLauncher()", "dlgArchetype()",
                     "dlgLearner()", "dlgIntention()", "dlgVariant()",
                     "dlgPublish()", "/approvals", "/approval", "/workflows",
                     "/workflow", "dlgWorkflow()", "decideApproval(",
                     "/api/harness", "loadHarness(", "/wake", "stopFromForm(",
                     'value="event"', "/context", "ctxDlg(", "loadCtxWindows(",
                     "/skill", "dlgSkillImport(", "trustSkill(",
                     "/trace", "traceDlg(", "/routine", "dlgRoutine(",
                     "loadToolStats(", "loadRoutines(",
                     "/api/events", "EventSource(", "/api/readiness",
                     "/identity", "/api/commons/pins", "renderCard(",
                     'id="teammates"', "files=1", "threadDlg(", "planDlg(",
                     "/self", "loadSelf(", "/knowledge", "loadKnowledge(",
                     "knowDlg(", "openCmd(", "renderCmd(", "/api/systems",
                     "loadSystemsMap(", "/api/preflight", "runPreflight(",
                     "/api/backup", "runBackup(", "openEvidence("):
        assert endpoint in html, f"the page never calls {endpoint}"
    # verify/memcheck are reached through runTool(), which builds the URL
    for action in ("runTool('verify')", "runTool('memcheck')", "runTool('probe')",
                   "'/api/experts/'+S.sel+'/'+tool"):
        assert action in html, f"the page never wires {action}"
    # the page's JavaScript must actually PARSE: a stray "</script>" inside a
    # template string once ended the main script early and erased every
    # function (found live; string checks cannot see it). node validates.
    import shutil
    import tempfile
    start = html.index("<script>", html.index("<body>")) + len("<script>")
    end = html.rindex("</script>")
    js = html[start:end]
    assert js.count("</script") == 0, \
        "a literal </script> inside the main script terminates it in the browser"
    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(js)
            jsp = f.name
        try:
            r = subprocess.run([node, "--check", jsp], capture_output=True,
                               text=True, timeout=60)
            assert r.returncode == 0, f"ui.html JavaScript does not parse:\n{r.stderr[-800:]}"
            print("[syntax] the page's JavaScript parses under node --check")
        finally:
            os.remove(jsp)
    # design contract: both themes defined at token level, no theme-only colors
    assert "prefers-color-scheme:dark" in html and '[data-theme="dark"]' in html
    assert "--bg:" in html and "background:var(--bg)" in html
    print("[page] ui.html serves 7 sections, calls every endpoint incl. memory/retired/history, defines both themes")

    proc = subprocess.Popen([PY, os.path.join(AGENT_DIR, "ui.py"),
                             "--home", home, "--port", str(PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "PYTHONUTF8": "1"})
    try:
        for _ in range(50):
            try:
                get("/")
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("panel did not come up")

        status, body = get("/")
        assert status == 200 and "Expert Fleet" in body and "id=\"app\"" in body
        assert len(body) > 20_000, "the served page looks truncated"
        print(f"[serve] page served from ui.html ({len(body)} bytes)")

        # a brand-new expert: EVERY read endpoint must answer, none may 500
        subprocess.run([PY, os.path.join(AGENT_DIR, "fleet.py"), "create",
                        "Fresh One", "--identity", "brand new", "--home", home],
                       check=True, capture_output=True)
        for path in ("/api/system", "/api/experts",
                     "/api/experts/fresh-one",
                     "/api/experts/fresh-one/tasks",
                     "/api/experts/fresh-one/tree",
                     "/api/experts/fresh-one/settings"):
            st, body = get(path)
            assert st == 200, f"{path} -> {st}"
            payload = json.loads(body)
            assert not (isinstance(payload, dict) and payload.get("error")), \
                f"{path} -> {payload.get('error')}"
        # the empty queue is an empty list, not an error
        assert json.loads(get("/api/experts/fresh-one/tasks")[1]) == []
        print("[fresh] a newly created expert answers on all six read endpoints, no 500s")

        # editing ui.html is picked up without restarting the server
        with open(page, "r", encoding="utf-8") as f:
            original = f.read()
        try:
            with open(page, "w", encoding="utf-8") as f:
                f.write(original.replace("<title>Expert Fleet</title>",
                                         "<title>Edited Live</title>"))
            assert "Edited Live" in get("/")[1], "page edits must not need a restart"
        finally:
            with open(page, "w", encoding="utf-8") as f:
                f.write(original)
        assert "Expert Fleet" in get("/")[1]
        print("[live] frontend edits appear on reload with no server restart")
        print("PASS test_frontend")
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
