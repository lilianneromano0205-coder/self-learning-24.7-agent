#!/usr/bin/env python3
"""Phase 4 exit benchmark — Capability Signatures, in shadow, held green.

docs/DESIGN-P4-capability-signatures.md preregistered six properties; this
file is that benchmark. The one that matters most is the pair in the
middle: a task whose WORDS share nothing with a proven procedure is found
by STRUCTURE — and routing still does not change, because the shadow has
no authority and may never gain any without the preregistered SIG-001
comparison.

Run from the agent/ directory:  python tests/test_capability_signatures.py
"""
import copy
import io
import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import loop                     # noqa: E402
import procedure                # noqa: E402
import runbook                  # noqa: E402
import signatures               # noqa: E402


def _settings(root, providers):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0', '']
    for name in providers:
        s += [f'[providers.{name}]', 'type = "mock"',
              f'script = "scripts/{name}.json"', '']
    s += ['[roles.default]', f'provider = "{providers[0]}"', 'model = "mock"', '']
    for name in providers:
        s += [f'[roles.r_{name}]', f'provider = "{name}"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)


def _script(root, name, steps):
    json.dump(steps, io.open(os.path.join(root, "scripts", f"{name}.json"),
                             "w", encoding="utf-8"))


def _events(root):
    out = []
    for line in io.open(os.path.join(root, "logs", "agent.log"),
                        encoding="utf-8", errors="replace"):
        if "{" in line and line.rstrip().endswith("}"):
            try:
                out.append(json.loads(line[line.index("{"):]))
            except ValueError:
                pass
    return out


def _tasks(root):
    return json.load(io.open(os.path.join(root, "state.json"),
                             encoding="utf-8"))["tasks"]


def _digestion_rb():
    return {"name": "proc-digestion", "triggers": ["digestion"],
            "procedure_version": 2,
            "steps": [{"kind": "deterministic",
                       "action": {"tool": "write_file",
                                  "args": {"path": {"input": "path"},
                                           "content": "digest\n"}},
                       "preconditions": [],
                       "effects": [{"predicate": "file_equals",
                                    "path": {"input": "path"},
                                    "value": "digest\n"}]}],
            "operator": {"inputs": {"path": "path"}, "preconditions": [],
                         "effects": [], "invariants": [], "cost_usd": 0.0,
                         "latency_seconds": 0.0,
                         "reversibility": "conditional",
                         "authority": ["workspace-write"]},
            "provenance": {"compiled": False, "family": "digestion",
                           "acceptance_basis": "authored",
                           "input_hashes": [], "trajectory_ids": []}}


def check_signature_is_structure_not_words():
    rb = _digestion_rb()
    sig = signatures.of_runbook(rb)
    assert sig["input_kinds"] == ["path"]
    assert sig["operators"] == ["write_file"]
    assert sig["effect_kinds"] == ["file_equals"]
    reworded = copy.deepcopy(rb)
    reworded["name"] = "proc-something-else"
    reworded["triggers"] = ["totally", "different", "words"]
    assert signatures.of_runbook(reworded)["signature_hash"] == \
        sig["signature_hash"], "words must never enter the identity"
    widened = copy.deepcopy(rb)
    widened["operator"]["inputs"]["extra"] = "string"
    assert signatures.of_runbook(widened)["signature_hash"] != \
        sig["signature_hash"], "schema changes must change the identity"
    retooled = copy.deepcopy(rb)
    retooled["steps"][0]["action"]["tool"] = "copy_file"
    retooled["steps"][0]["action"]["args"] = {"source": {"input": "path"},
                                              "path": {"input": "path"}}
    assert signatures.of_runbook(retooled)["signature_hash"] != \
        sig["signature_hash"]
    print("[identity] the signature is computed from schema, operators, "
          "effects and control — rewording changes nothing, restructuring "
          "changes everything")


def _prove_digestion(root):
    rb = _digestion_rb()
    os.makedirs(os.path.dirname(runbook.path(root, rb["name"])), exist_ok=True)
    io.open(runbook.path(root, rb["name"]), "w",
            encoding="utf-8").write(json.dumps(rb))
    procedure.seal_suite(root, "digestion-suite", {
        "family": "digestion",
        "cases": [{"id": f"c{i}", "edge": i == 2,
                   "inputs": {"path": f"out/d{i}.md"}} for i in range(3)],
        "checks": [{"predicate": "file_equals", "path": {"input": "path"},
                    "value": "digest\n"}]})
    verdict = procedure.evaluate(root, "proc-digestion", "digestion-suite")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict


GATE = (f'"{PY}" -c "import os,sys;'
        'sys.exit(0 if os.path.isfile(sys.argv[1]) else 1)"')


def check_structure_finds_what_words_miss(root):
    _prove_digestion(root)
    assert runbook.match(root, "assemble the weekly summary of notes") == [], \
        "the paraphrase must be lexically invisible for this check to mean anything"
    _script(root, "worker", [
        {"tool": "write_file", "args": {"path": "out/w1.md",
                                        "content": "digest\n"}},
        {"tool": "finish_task", "args": {"summary": "assembled"}}])
    agent = loop.Agent(root)
    agent.add_task("r_worker", "assemble the weekly summary of notes",
                   done_check=GATE + " out/w1.md",
                   inputs={"path": "out/w1.md"})
    assert run_drain(root, timeout=120) == 0
    task = _tasks(root)[-1]
    assert task["status"] == "done" and not task.get("procedure_routed"), \
        "shadow must change NOTHING: the words missed, so the model worked"
    shadows = [e for e in _events(root) if e.get("event") == "signature_shadow"
               and e.get("task") == task["id"]]
    assert shadows and shadows[-1]["agreement"] == "structural_only", shadows
    assert shadows[-1]["structural"] == ["proc-digestion"]
    assert shadows[-1]["lexical"] == []
    print("[paraphrase] a task sharing no words with the proven procedure "
          "was found by STRUCTURE and logged structural_only — while the "
          "task still ran through the model, because shadow has no authority")


def check_lexical_routing_is_untouched(root):
    _script(root, "silent", [])
    agent = loop.Agent(root)
    agent.add_task("r_silent", "run the digestion of notes",
                   done_check=GATE + " out/w2.md",
                   inputs={"path": "out/w2.md"})
    assert run_drain(root, timeout=120) == 0
    task = _tasks(root)[-1]
    assert task["status"] == "done" and \
        task.get("procedure_routed") == "proc-digestion", task
    routed = [e for e in _events(root) if e.get("event") == "procedure_route"
              and e.get("task") == task["id"]]
    assert routed and routed[0]["model_calls"] == 0
    shadows = [e for e in _events(root) if e.get("event") == "signature_shadow"
               and e.get("task") == task["id"]]
    assert shadows and shadows[-1]["agreement"] == "same", shadows
    print("[authority] the lexically-matched task routed zero-model exactly "
          "as before the shadow existed, and the ledger recorded agreement")


def check_no_false_structural_match(root):
    _script(root, "worker", [
        {"tool": "write_file", "args": {"path": "out/w3.md",
                                        "content": "notes\n"}},
        {"tool": "finish_task", "args": {"summary": "assembled"}}])
    agent = loop.Agent(root)
    agent.add_task("r_worker", "assemble the other weekly summary of notes",
                   done_check=GATE + " out/w3.md",
                   inputs={"path": "out/w3.md", "bogus": "extra"})
    assert run_drain(root, timeout=120) == 0
    task = _tasks(root)[-1]
    assert task["status"] == "done" and not task.get("procedure_routed")
    shadows = [e for e in _events(root) if e.get("event") == "signature_shadow"
               and e.get("task") == task["id"]]
    assert shadows and shadows[-1]["agreement"] == "both_empty", shadows
    assert shadows[-1]["structural"] == []
    print("[strict] wrong typed inputs proposed nothing — the structural "
          "lens does not guess either")


def check_the_report_aggregates_the_ledger(root):
    rep = signatures.report(root)
    assert rep["agreement"]["structural_only"] == 1, rep
    assert rep["agreement"]["same"] == 1, rep
    assert rep["agreement"]["both_empty"] == 1, rep
    assert rep["structural_only_procedures"] == {"proc-digestion": 1}
    assert "lexical" in rep["authority"]
    import subprocess
    r = subprocess.run([PY, os.path.join(AGENT_DIR, "signatures.py"),
                        "report", "--root", root], capture_output=True,
                       text=True, errors="replace", timeout=120,
                       env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0 and '"structural_only": 1' in r.stdout, r.stdout
    print("[ledger] the report counted one structural-only find, one "
          "agreement and one strict refusal — and says in as many words "
          "that authority stayed lexical")


def _purge_rb():
    """Same typed schema, same operator and effect kinds as digestion —
    different semantics (it writes a purge marker, not a digest)."""
    rb = copy.deepcopy(_digestion_rb())
    rb["name"], rb["triggers"] = "proc-purge", ["purge"]
    rb["steps"][0]["action"]["args"]["content"] = "purged\n"
    rb["steps"][0]["effects"][0]["value"] = "purged\n"
    rb["provenance"]["family"] = "purge"
    return rb


def check_same_schema_different_semantics_collide(root):
    """Finding 7 of docs/DESIGN-P6.1, stated as a test rather than hidden:
    structural compatibility is a typed-schema fit, so two proven procedures
    with one schema and one operator/effect shape but different semantics
    share a signature and are BOTH proposed. That is exactly why the shadow
    has no authority; the two-sided requirement/capability signature is the
    next SIG design, not this one."""
    rb = _purge_rb()
    io.open(runbook.path(root, rb["name"]), "w",
            encoding="utf-8").write(json.dumps(rb))
    procedure.seal_suite(root, "purge-suite", {
        "family": "purge",
        "cases": [{"id": f"p{i}", "edge": i == 2,
                   "inputs": {"path": f"out/p{i}.md"}} for i in range(3)],
        "checks": [{"predicate": "file_equals", "path": {"input": "path"},
                    "value": "purged\n"}]})
    verdict = procedure.evaluate(root, "proc-purge", "purge-suite")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    assert signatures.of_runbook(rb)["signature_hash"] == \
        signatures.of_runbook(_digestion_rb())["signature_hash"], \
        "one schema, one operator, one effect kind: one signature for two semantics"
    _script(root, "worker", [
        {"tool": "write_file", "args": {"path": "out/w4.md",
                                        "content": "digest\n"}},
        {"tool": "finish_task", "args": {"summary": "assembled"}}])
    agent = loop.Agent(root)
    agent.add_task("r_worker", "assemble the monthly summary of notes",
                   done_check=GATE + " out/w4.md", inputs={"path": "out/w4.md"})
    assert run_drain(root, timeout=120) == 0
    task = _tasks(root)[-1]
    assert task["status"] == "done" and not task.get("procedure_routed"), task
    shadows = [e for e in _events(root) if e.get("event") == "signature_shadow"
               and e.get("task") == task["id"]]
    assert shadows and shadows[-1]["structural"] == ["proc-digestion", "proc-purge"], \
        shadows
    assert shadows[-1]["agreement"] == "structural_only"
    print("[collision] two proven procedures with one typed schema and one "
          "operator/effect shape — write a digest, write a purge — share a "
          "signature and were BOTH proposed for a paraphrase: schema "
          "compatibility is not semantic identity, which is why the shadow "
          "holds no authority")


def check_shadow_failures_are_logged(root):
    """Finding 8 of docs/DESIGN-P6.1: a shadow observation the guard had to
    drop is logged with its error class, so SIG-001 knows its data is
    incomplete instead of being biased toward the tasks the shadow handled.
    A declared input the file authority refuses makes the structural check
    itself fail — the live route is untouched, the miss is recorded."""
    _script(root, "worker", [
        {"tool": "write_file", "args": {"path": "out/w5.md",
                                        "content": "digest\n"}},
        {"tool": "finish_task", "args": {"summary": "assembled"}}])
    agent = loop.Agent(root)
    agent.add_task("r_worker", "assemble the quarterly summary of notes",
                   done_check=GATE + " out/w5.md",
                   inputs={"path": "settings.toml"})
    assert run_drain(root, timeout=120) == 0
    task = _tasks(root)[-1]
    assert task["status"] == "done" and not task.get("procedure_routed"), task
    failures = [e for e in _events(root)
                if e.get("event") == "signature_shadow_failure"
                and e.get("task") == task["id"]]
    assert failures and failures[-1]["error"] == "Denied" and \
        failures[-1]["runbook"] is None, failures
    shadows = [e for e in _events(root) if e.get("event") == "signature_shadow"
               and e.get("task") == task["id"]]
    assert shadows == [], "a failed observation must not also count as one"
    print("[shadow-failure] a structural check the guard had to drop was "
          "logged as signature_shadow_failure with its error class — the "
          "miss is data, not silence — while the live route completed the "
          "task untouched")


def main():
    home = make_sandbox("capability-signatures",
                        providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Digest Desk", "finds structure behind words")
    _settings(root, ["worker", "silent"])
    check_signature_is_structure_not_words()
    check_structure_finds_what_words_miss(root)
    check_lexical_routing_is_untouched(root)
    check_no_false_structural_match(root)
    check_the_report_aggregates_the_ledger(root)
    check_same_schema_different_semantics_collide(root)
    check_shadow_failures_are_logged(root)
    print("PASS test_capability_signatures")


if __name__ == "__main__":
    main()
