"""Keyless regressions for scheduling, verification, calibration and context."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import candidates
import confidence
import context


class CognitiveTests(unittest.TestCase):
    def test_scheduler_conditions_on_task_class_and_cost(self):
        scheduler = importlib.import_module('scheduler')
        opts = [{'id': 'cheap', 'kind': 'cheap_local', 'cost_usd': .01},
                {'id': 'strong', 'kind': 'strong_model', 'cost_usd': .1}]
        rows = []
        for cls in ('code', 'research'):
            for strategy in ('cheap', 'strong'):
                for i in range(10):
                    rows.append({'task_id': f'{cls}-{strategy}-{i}',
                                 'features': {'role': 'worker', 'task_class': cls},
                                 'strategy_id': strategy, 'verified_l0': True,
                                 'success': strategy == 'strong' or cls == 'code',
                                 'cost_usd': .01 if strategy == 'cheap' else .1})
        easy = scheduler.choose({'role': 'worker', 'task_class': 'code'}, opts, rows)
        hard = scheduler.choose({'role': 'worker', 'task_class': 'research'}, opts, rows)
        self.assertEqual(easy['strategy']['id'], 'cheap')
        self.assertEqual(hard['strategy']['id'], 'strong')
        self.assertEqual(hard['features']['task_class'], 'research')

    def test_scheduler_rejects_unproven_runbook_and_unverified_history(self):
        scheduler = importlib.import_module('scheduler')
        opts = [{'id': 'unsafe', 'kind': 'runbook', 'cost_usd': 0},
                {'id': 'static', 'kind': 'cheap_hosted', 'fallback': True, 'cost_usd': .01}]
        rows = [{'task_id': str(i), 'strategy_id': 'unsafe', 'features': {'task_class': 'general'},
                 'success': True, 'verified_l0': False} for i in range(50)]
        got = scheduler.choose({}, opts, rows)
        self.assertEqual(got['strategy']['id'], 'static')
        self.assertIn('unproven', str(got['rejected']))

    def test_sequential_economic_stop_success_stop_and_hard_budget(self):
        self.assertTrue(hasattr(candidates, 'next_attempt'))
        task = {'task_value_usd': 1, 'budget_usd': 1}
        cfg = {'agent': {'candidates_max': 5, 'candidate_model_cost_usd': .1,
                         'candidate_verifier_cost_usd': .01}}
        a = [{'passed': False, 'score': .5, 'cost_usd': .1, 'fingerprint': 'one'}]
        self.assertTrue(candidates.next_attempt(task, a, cfg, recovery_probability=.8)['continue'])
        self.assertFalse(candidates.next_attempt(task, a, cfg, recovery_probability=.01)['continue'])
        self.assertFalse(candidates.next_attempt(task, a, cfg, recovery_probability=.8,
                                                remaining_budget_usd=.05)['continue'])
        self.assertFalse(candidates.next_attempt(task, [{'passed': True}], cfg,
                                                recovery_probability=.8)['continue'])
        self.assertFalse(candidates.next_attempt(task, a * 5, cfg,
                                                recovery_probability=1)['continue'])

    def test_verifier_mechanical_failure_dominates_and_logs_separately(self):
        verification = importlib.import_module('verification')
        with tempfile.TemporaryDirectory() as root:
            agent = SimpleNamespace(root=root, cfg={})
            layer = {'level': 4, 'family': 'different',
                     'verify': lambda task: {'passed': True, 'evidence': 'looks correct'}}
            rep = verification.run(agent, {'id': 'v1'}, (False, 'frozen test failed'), [layer])
            self.assertFalse(rep['passed'])
            self.assertEqual(rep['decided_by'], 'L0')
            self.assertTrue(os.path.isfile(os.path.join(root, 'logs', 'verifier-outcomes.jsonl')))
            self.assertFalse(os.path.exists(os.path.join(root, 'logs', 'model-outcomes.jsonl')))

    def test_openended_verifier_errors_fail_closed_and_family_is_checked(self):
        verification = importlib.import_module('verification')
        with tempfile.TemporaryDirectory() as root:
            agent = SimpleNamespace(root=root, cfg={})
            layer = {'level': 2, 'family': 'same', 'verify': lambda task: {'passed': True, 'evidence': 'yes'}}
            rep = verification.run(agent, {'id': 'v2', 'high_value': True,
                                          'actor_family': 'same'}, (None, 'open'), [layer])
            self.assertFalse(rep['passed'])
            self.assertIn('family', str(rep['layers']))

    def test_calibration_metrics_by_class_and_no_split_leakage(self):
        calibration = importlib.import_module('calibration')
        rows = [{'task_id': f'h{i}', 'split': 'holdout', 'task_class': 'code',
                 'prediction': p, 'success': y, 'verified_l0': True}
                for i, (p, y) in enumerate(((0., False), (1., True), (.5, True), (.5, False)))]
        rep = calibration.evaluate(rows, bins=2)
        self.assertAlmostEqual(rep['brier'], .125)
        self.assertAlmostEqual(rep['by_task_class']['code']['brier'], .125)
        self.assertEqual(rep['n'], 4)
        with self.assertRaises(ValueError):
            calibration.evaluate(rows, training_ids={'h0'})
        with self.assertRaises(ValueError):
            calibration.fit(rows)

    def test_confidence_is_explicitly_heuristic_without_calibration(self):
        with tempfile.TemporaryDirectory() as root:
            agent = SimpleNamespace(root=root)
            rep = confidence.score(agent, {'goal': 'test', 'role': 'worker'})
            self.assertEqual(rep.get('kind'), 'heuristic_score')
            self.assertFalse(rep.get('calibrated', True))
            self.assertIn('HEURISTIC', confidence.render(rep))

    def test_context_global_unicode_limit_and_mission_priority(self):
        self.assertTrue(hasattr(context, 'fit_request'))
        cfg = {'agent': {'context_completion_reserve': 100, 'context_safety_margin': 20,
                         'context_tool_schema_budget': 20},
               'providers': {'p': {'context_limit': 700}}}
        blocks = {'mission': ['MISSION CONTRACT: never change judges'],
                  'memory_files': ['漢字' * 2000]}
        user, rep = context.fit_request(cfg, 'p', 'm', 'system', 'Task: act', blocks)
        self.assertTrue(user.startswith('MISSION CONTRACT'))
        self.assertLessEqual(rep['used_upper_bound'], rep['maximum_compiled_context'])
        self.assertTrue(rep['dropped'] or rep['trimmed'])
        with self.assertRaises(context.ContextBudgetError):
            context.fit_request(cfg, 'p', 'm', 'system' * 200, 'Task: act', blocks)

    def test_context_completion_and_tools_reserved_at_request_gate(self):
        self.assertTrue(hasattr(context, 'assert_request_budget'))
        cfg = {'agent': {'context_safety_margin': 10}, 'providers': {'p': {'context_limit': 100}}}
        with self.assertRaises(context.ContextBudgetError):
            context.assert_request_budget(cfg, 'p', 'm', [{'role': 'user', 'content': 'x' * 50}], 30, [{'name': 'tool' * 20}])


if __name__ == '__main__':
    unittest.main()
