#!/usr/bin/env python3
"""A model-written command NEVER sees the harness's credentials (M9).

DeepSeek Harness states the rule that this test enforces ("never hand
untrusted output the ambient environment"): a spawned command gets a
scrubbed environment, because anything the model can read it can also write
into a file, a summary, or an HTTP request.

1. `env` / `printenv` / os.environ from a model command: no key values, and
   the command is told why
2. the scrub is by NAME pattern, so a key the platform has never heard of is
   still withheld
3. privilege separation, not a blanket ban: the platform's OWN helper keeps
   exactly the one credential it needs, and only for that command shape
4. the owner can allow a name explicitly, and nothing else comes with it
5. no key VALUE ever reaches the logs, the step record, or the panel

Run from the agent/ directory:  python tests/test_secrets.py
"""

import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop
import sandbox

SECRET = "sk-test-DO-NOT-LEAK-8f3a91"
ENV = {"OPENROUTER_API_KEY": SECRET, "GROQ_API_KEY": SECRET,
       "MY_COMPANY_PASSWORD": SECRET, "WEIRDNAME_TOKEN": SECRET,
       "AGENT_ROOT": "x", "PATH": os.environ.get("PATH", ""), "HOME": "/h"}


def main():
    # --- 1 + 2. scrubbing by name pattern
    clean, dropped = sandbox.scrub_env(ENV, {}, "env")
    assert "OPENROUTER_API_KEY" not in clean and "GROQ_API_KEY" not in clean
    assert "MY_COMPANY_PASSWORD" not in clean, "PASSWORD is a marker"
    assert "WEIRDNAME_TOKEN" not in clean, "an unknown key is still a key"
    assert clean.get("PATH") and clean.get("AGENT_ROOT") == "x", \
        "the command still needs a working environment"
    assert set(dropped) == {"GROQ_API_KEY", "MY_COMPANY_PASSWORD",
                            "OPENROUTER_API_KEY", "WEIRDNAME_TOKEN"}, dropped
    assert SECRET not in json.dumps(dropped), "names are reported, never values"
    print("[scrub] every credential-shaped variable was withheld by name "
          "pattern, including one the platform has never heard of")

    # --- 3. scoped grant for the platform's own helpers
    assert sandbox.granted_for("python3 ingest.py transcribe audio/ out.txt") \
        == {"GROQ_API_KEY"}
    assert "OPENROUTER_API_KEY" in sandbox.granted_for("python ingest.py vision f/")
    assert sandbox.granted_for("env") == set()
    assert sandbox.granted_for('python -c "import os;print(os.environ)"') == set()
    assert sandbox.granted_for("echo ingest.py transcribe") == {"GROQ_API_KEY"}
    clean2, _ = sandbox.scrub_env(ENV, {}, "python3 ingest.py transcribe a b")
    assert clean2.get("GROQ_API_KEY") == SECRET, "transcription must still work"
    assert "OPENROUTER_API_KEY" not in clean2, "one key, not the keyring"
    print("[scoped] the transcription helper kept exactly the one credential "
          "it needs; a bare `env` got none")

    # --- 4. owner allowlist
    clean3, _ = sandbox.scrub_env(
        ENV, {"agent": {"command_env_allow": ["OPENROUTER_API_KEY"]}}, "env")
    assert clean3.get("OPENROUTER_API_KEY") == SECRET
    assert "GROQ_API_KEY" not in clean3, "an allowlist allows one name only"
    print("[owner] an explicit allowlist entry passed one named key through, "
          "and nothing rode along with it")

    # --- 5. end to end through the loop
    sb = make_sandbox("secrets", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"},
                      scripts={"s.json": [
                          {"tool": "run_command", "args": {
                              "cmd": f'"{PY}" -c "import os;'
                                     f'print(os.environ.get(\'OPENROUTER_API_KEY\',\'ABSENT\'));'
                                     f'print(os.environ.get(\'GROQ_API_KEY\',\'ABSENT\'))"'}},
                          {"tool": "finish_task", "args": {"summary": "looked"}}]})
    os.environ["OPENROUTER_API_KEY"] = SECRET
    os.environ["GROQ_API_KEY"] = SECRET
    try:
        loop.Agent(sb).add_task("tester", "print the environment")
        assert run_drain(sb) == 0
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.environ.pop("GROQ_API_KEY", None)
    t = read_state(sb)["tasks"][0]
    step = t["steps"][0]
    assert "ABSENT" in step["result"], step["result"]
    assert SECRET not in step["result"], "THE KEY LEAKED INTO THE TRANSCRIPT"
    for rel in ("logs/agent.log", "logs/commands.log", "state.json"):
        p = os.path.join(sb, rel)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                assert SECRET not in f.read(), f"THE KEY LEAKED INTO {rel}"
    for dirpath, _, names in os.walk(os.path.join(sb, "contexts")):
        for n in names:
            with open(os.path.join(dirpath, n), encoding="utf-8",
                      errors="replace") as f:
                assert SECRET not in f.read(), f"THE KEY LEAKED INTO {n}"
    print("[e2e] an agent that went looking for the keys found ABSENT, and no "
          "key value reached the transcript, the logs or the state")

    # --- timeouts report independently of exit codes
    rc, out, err = sandbox.run(
        f'"{PY}" -c "import sys,time;print(\'partial work\');'
        f'sys.stdout.flush();time.sleep(9)"',
        sb, {}, 2, {"agent": {"sandbox": "host", "allow_unsafe_host": True}})
    assert rc == sandbox.TIMEOUT_RC, rc
    assert "TIMED OUT after 2s" in err and "no exit code" in err, err
    assert "partial work" in out, \
        "output produced before the kill is evidence, not garbage"
    print("[timeout] a killed command reported the timeout AND kept the work "
          "it had already printed")
    print("PASS test_secrets")


if __name__ == "__main__":
    main()
