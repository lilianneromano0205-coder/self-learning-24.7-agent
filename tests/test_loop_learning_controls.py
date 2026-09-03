#!/usr/bin/env python3
"""Integration checks for the learning-control modules wired into loop.py."""
import json
import os
from pathlib import Path
import sys
import unittest

from common import AGENT_DIR, agent_setting, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import context
import loop
import procedure
import runbook


class LoopLearningControlsTests(unittest.TestCase):
    def sandbox(self, name="loop-learning", extra=""):
        return make_sandbox(
            name,
            providers={"p": {"script": "p.json"},
                       "f": {"script": "f.json"}},
            roles={"tester": "p"},
            scripts={"p.json": [{"content": "primary"}],
                     "f.json": [{"content": "fallback"}]},
            extra=extra)

    def test_every_mock_attempt_is_context_gated_before_consumption(self):
        root = self.sandbox("loop-context-gate")
        agent_setting(root, "context_limit = 10000")
        agent_setting(root, "context_completion_reserve = 1000")
        a = loop.Agent(root)
        with self.assertRaises(context.ContextBudgetError):
            a.call_model("tester", [{"role": "user", "content": "x" * 12000}],
                         use_tools=False)
        msg, _, _ = a.call_model(
            "tester", [{"role": "user", "content": "small"}],
            use_tools=False)
        self.assertEqual(msg["content"], "primary")

    def test_raw_arm_does_not_fall_back_from_configured_provider(self):
        root = self.sandbox(
            "loop-raw-provider",
            '[evaluation]\nsingle_provider_attempt = true\n'
            'disabled_modules = ["routing"]')
        settings = os.path.join(root, "settings.toml")
        text = Path(settings).read_text(encoding="utf-8")
        start = text.index("[providers.p]")
        end = text.index("[providers.f]")
        block = text[start:end].replace('type = "mock"', 'type = "openai"')
        block += 'api_key_env = "LOOP_RAW_MISSING_KEY"\n'
        Path(settings).write_text(text[:start] + block + text[end:], encoding="utf-8")
        os.environ.pop("LOOP_RAW_MISSING_KEY", None)
        with self.assertRaisesRegex(RuntimeError, "no API key"):
            loop.Agent(root).call_model(
                "tester", [{"role": "user", "content": "hello"}],
                use_tools=False)

    def test_done_check_files_an_l0_verifier_receipt(self):
        root = self.sandbox("loop-verifier-receipt")
        a = loop.Agent(root)
        task = {"id": "verify-1", "role": "tester",
                "done_check": f'"{sys.executable}" -c "raise SystemExit(0)"'}
        passed, evidence = a.check_done(task)
        self.assertTrue(passed, evidence)
        self.assertEqual(task["verification"]["decided_by"], "L0")
        ledger = os.path.join(root, "logs", "verifier-outcomes.jsonl")
        row = json.loads(Path(ledger).read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(row["mechanically_verified"])

    def test_tool_hooks_record_procedure_and_skill_reference(self):
        root = self.sandbox("loop-tool-hooks")
        os.makedirs(os.path.join(root, "skills", "demo"), exist_ok=True)
        skill_rel = "skills/demo/SKILL.md"
        Path(os.path.join(root, *skill_rel.split("/"))).write_text("demo", encoding="utf-8")
        procedure.seal_judge(
            root, "judge-1",
            [{"predicate": "file_equals", "path": "out/proc.txt", "value": "ok"}])
        procedure.begin_trajectory(root, "task-1", "judge-1", {"value": "ok"}, "demo")
        task = {"id": "task-1", "role": "tester", "steps": [],
                "skills_used": [skill_rel]}
        a = loop.Agent(root)
        self.assertIn("ok, wrote", a._exec_tool(
            task, "write_file", {"path": "out/proc.txt", "content": "ok"}))
        # what a file says enters the window as MARKED DATA (DESIGN-P11):
        # the bytes are exact, between the untrusted markers
        seen = a._exec_tool(task, "read_file", {"path": skill_rel})
        self.assertTrue(seen.startswith(
            "<<<TOOL-RESULT read_file " + skill_rel + ">>>\n"), seen)
        self.assertIn("\ndemo\n<<<END-TOOL-RESULT read_file " + skill_rel + ">>>",
                      seen)
        trajectory = procedure.finish_trajectory(root, "task-1")
        self.assertTrue(trajectory["accepted"])
        self.assertEqual(task["skill_trace"][-1]["event"], "referenced")


class VerifiedExperienceBecomesCheapCompetenceTests(unittest.TestCase):
    """The whole slice, through the REAL loop, in one run.

    novel work -> independently judged trajectories -> induction -> sealed
    evaluation on fresh instances -> earned trust -> the next matching task
    executes deterministically with no model call at all.

    The falsifiable half is the last task: the mock provider's script is
    EXHAUSTED by then, so if the deterministic route did not fire, the model
    path cannot write the artifact and the task's own gate refuses it. The
    task passing is therefore evidence that no model was consulted, not a
    claim that none was.
    """

    FAMILY = "reportfile"

    def _root(self):
        # one provider per task: a mock script replays from its first entry
        # for EVERY task, so a shared script would give the second task the
        # first one's write as well — two mutations against one, which the
        # compiler correctly refuses to align. The third role's script is
        # empty, which is what makes the last assertion falsifiable.
        return make_sandbox(
            "loop-experience-compiler",
            providers={"pa": {"script": "a.json"}, "pb": {"script": "b.json"},
                       "pc": {"script": "c.json"}},
            roles={"ta": "pa", "tb": "pb", "tc": "pc"},
            scripts={"a.json": [{"tool": "write_file",
                                 "args": {"path": "out/a.txt",
                                          "content": "alpha"}},
                                {"tool": "finish_task", "args": {"summary": "a"}}],
                     "b.json": [{"tool": "write_file",
                                 "args": {"path": "out/b.txt",
                                          "content": "beta"}},
                                {"tool": "finish_task", "args": {"summary": "b"}}],
                     "c.json": []})

    @staticmethod
    def _gate(path, text):
        return (f'"{sys.executable}" -c "import io,sys;'
                f"sys.exit(0 if io.open(r'{path}',encoding='utf-8')"
                f".read()=='{text}' else 1)\"")

    def test_verified_trajectories_compile_and_then_run_without_a_model(self):
        root = self._root()

        # --- owner authority, sealed BEFORE any work: two independent
        # judges (induction refuses a single grader's word) and one
        # evaluation suite of fresh instances the induction never saw.
        procedure.seal_judge(root, "judge-a", [
            {"predicate": "file_equals", "path": "out/a.txt", "value": "alpha"}])
        procedure.seal_judge(root, "judge-b", [
            {"predicate": "file_equals", "path": "out/b.txt", "value": "beta"}])
        procedure.seal_suite(root, "suite-1", {
            "family": self.FAMILY,
            "cases": [
                {"id": "case-1", "inputs": {"path": "out/e1.txt", "text": "one"}},
                {"id": "case-2", "inputs": {"path": "out/e2.txt", "text": "two"}},
                {"id": "case-3", "edge": True,
                 "inputs": {"path": "out/e3.txt", "text": ""}},
            ],
            "checks": [{"predicate": "file_equals",
                        "path": {"input": "path"}, "value": {"input": "text"}}]})

        # --- two novel tasks, each judged independently
        agent = loop.Agent(root)
        t1 = agent.add_task(
            "ta", "write the alpha artifact",
            done_check=self._gate("out/a.txt", "alpha"),
            judge_id="judge-a", family=self.FAMILY,
            inputs={"path": "out/a.txt", "text": "alpha"})
        t2 = agent.add_task(
            "tb", "write the beta artifact",
            done_check=self._gate("out/b.txt", "beta"),
            judge_id="judge-b", family=self.FAMILY,
            inputs={"path": "out/b.txt", "text": "beta"})
        self.assertEqual(run_drain(root, timeout=300), 0)

        agent = loop.Agent(root)
        for tid in (t1, t2):
            self.assertEqual((agent.find_task(tid) or {}).get("status"), "done",
                             agent.find_task(tid))

        # --- induction happened, and it inferred structure rather than
        # transcribing one run: the two varying values became typed inputs.
        name = "proc-" + self.FAMILY
        rb = runbook.load(root, name)
        self.assertTrue(rb.get("procedure_version"))
        self.assertEqual(rb["operator"]["inputs"],
                         {"path": "path", "text": "string"})
        self.assertEqual(rb["steps"][0]["kind"], "deterministic")
        self.assertEqual(rb["steps"][0]["action"]["args"],
                         {"path": {"input": "path"}, "content": {"input": "text"}})
        self.assertEqual(rb["operator"]["effects"],
                         [{"predicate": "file_equals",
                           "path": {"input": "path"}, "value": {"input": "text"}}])
        self.assertEqual(sorted(rb["provenance"]["trajectory_ids"]), sorted([t1, t2]))

        # --- trust was earned on the sealed suite's fresh instances, and
        # the envelope states the scope rather than claiming generality
        self.assertEqual(runbook.status(root, name), "proven")
        trust = json.loads(Path(os.path.join(root, runbook.TRUST))
                           .read_text(encoding="utf-8"))[name]
        self.assertGreaterEqual(trust["accepted_wins"], runbook.PROMOTE_WINS)
        self.assertGreaterEqual(trust["envelope"]["distinct_inputs"], 3)
        self.assertIs(trust["envelope"]["generalization_claim"], False)

        # --- the payoff. The script is spent; only the deterministic route
        # can satisfy this task's gate.
        t3 = loop.Agent(root).add_task(
            "tc", "write the reportfile artifact for the quarter",
            done_check=self._gate("out/c.txt", "gamma"),
            family=self.FAMILY, inputs={"path": "out/c.txt", "text": "gamma"})
        self.assertEqual(run_drain(root, timeout=300), 0)

        done = loop.Agent(root).find_task(t3) or {}
        self.assertEqual(done.get("status"), "done", done)
        self.assertEqual(done.get("procedure_routed"), name)
        self.assertEqual(done.get("steps"), [], "a routed task takes no model step")
        self.assertEqual(done.get("cost_usd"), 0)
        self.assertEqual(
            Path(os.path.join(root, "out", "c.txt")).read_text(encoding="utf-8"),
            "gamma")

        events = []
        for line in Path(os.path.join(root, "logs", "agent.log")).read_text(
                encoding="utf-8", errors="replace").splitlines():
            if "{" not in line:
                continue
            try:
                events.append(json.loads(line[line.index("{"):]))
            except ValueError:
                continue
        routed = [e for e in events if e.get("event") == "procedure_route"]
        self.assertEqual(len(routed), 1, routed)
        self.assertEqual(routed[0]["model_calls"], 0)
        self.assertTrue([e for e in events if e.get("event") == "procedure_compiled"])

    def test_the_gate_still_decides_a_routed_task(self):
        """A procedure whose steps verify but whose OUTPUT the task's own
        gate refuses does not get to call itself done — the acceptor is
        never the thing being accepted."""
        root = make_sandbox(
            "loop-route-gate", providers={"m": {"script": "s.json"}},
            roles={"tester": "m"}, scripts={"s.json": []})
        name = "proc-gated"
        rbk = {"name": name, "triggers": ["gated"], "procedure_version": 1,
               "steps": [{"id": "step-1", "depends_on": [], "kind": "deterministic",
                          "action": {"tool": "write_file",
                                     "args": {"path": {"input": "path"},
                                              "content": "written"}},
                          "preconditions": [{"predicate": "file_absent",
                                             "path": {"input": "path"}}],
                          "effects": [{"predicate": "file_equals",
                                       "path": {"input": "path"},
                                       "value": "written"}]}],
               "operator": {"inputs": {"path": "path"}, "preconditions": [],
                            "effects": [], "invariants": [], "cost_usd": 0.0,
                            "cost_basis": "test", "latency_seconds": 0.0,
                            "reversibility": "conditional",
                            "authority": ["workspace-write"],
                            "reliability": {"source": "test fixture"}},
               "provenance": {"compiled": True, "trajectory_ids": [],
                              "input_hashes": [], "family": "gated",
                              "alignment": "test fixture"}}
        os.makedirs(os.path.dirname(runbook.path(root, name)), exist_ok=True)
        Path(runbook.path(root, name)).write_text(json.dumps(rbk), encoding="utf-8")
        trust = {name: {"status": "proven", "wins": 3, "accepted_wins": 3,
                        "losses": 0, "streak_losses": 0, "history": [],
                        "content_hash": procedure.digest(rbk)}}
        Path(os.path.join(root, runbook.TRUST)).write_text(
            json.dumps(trust), encoding="utf-8")

        a = loop.Agent(root)
        task = {"id": "gated-1", "role": "tester", "status": "running",
                "goal": "run the gated procedure", "steps": [], "cost_usd": 0,
                "inputs": {"path": "out/g.txt"},
                # the gate demands content the procedure does not produce
                "done_check": self._gate("out/g.txt", "something else")}
        self.assertFalse(a._try_procedure_route(task))
        self.assertEqual(task["status"], "running")
        self.assertIsNone(task.get("procedure_routed"))
        # the refusal is recorded against the procedure, not swallowed
        self.assertEqual(runbook.status(root, name), "proven")
        rec = json.loads(Path(os.path.join(root, runbook.TRUST))
                         .read_text(encoding="utf-8"))[name]
        self.assertEqual(rec["accepted_wins"], 3)
        self.assertEqual(rec["wins"], 4, "the run happened and was counted")


if __name__ == "__main__":
    unittest.main()
