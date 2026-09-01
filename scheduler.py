"""Interpretable, contextual expected-utility scheduling. No learned lift claim.

Only trusted callers supply executable strategies. This module neither grants
authority nor executes a tool. All selected work still crosses the existing
execution/model/runbook authorities. Logged empirical outcomes are observations,
not proof that a strategy caused a success.
"""
import json
import math
import os
import time

LEDGER = os.path.join('logs', 'scheduler-outcomes.jsonl')
DECISIONS = os.path.join('logs', 'scheduler-decisions.jsonl')
KINDS = {'runbook', 'tool_api', 'cheap_local', 'cheap_hosted', 'strong_model', 'frontier_model'}


def _number(value, default=0):
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else default
    except (TypeError, ValueError):
        return default


# Deterministic goal-text buckets. First hit wins, 'general' is the honest
# fallback — a keyword table, not a claim about the task's true nature. It
# exists so every downstream conditioner (routing profiles, the candidate
# stopping rule, calibration-by-class) stops collapsing to one bucket.
_CLASSES = (
    ("coding", {"code", "bug", "test", "tests", "refactor", "function",
                "script", "python", "compile", "build", "class", "module",
                "api", "endpoint", "fix", "lint", "typecheck"}),
    ("research", {"research", "investigate", "sources", "evidence", "study",
                  "literature", "compare", "survey", "cite", "verify",
                  "question", "answer"}),
    ("data", {"csv", "data", "dataset", "table", "metrics", "analyze",
              "analysis", "chart", "report", "aggregate", "sum", "average"}),
    ("browser", {"browser", "web", "website", "site", "scrape", "url",
                 "page", "download", "crawl"}),
    ("ops", {"deploy", "server", "docker", "install", "configure", "backup",
             "restore", "monitor", "restart", "provision", "migrate"}),
    ("writing", {"write", "draft", "document", "summary", "summarize",
                 "article", "email", "notes", "readme", "manual"}),
)


def classify(goal_text):
    """Deterministic task_class from goal words; no model call, no learning."""
    words = {w for w in str(goal_text or "").lower().split() if w}
    words = {w.strip(".,:;!?()[]'\"") for w in words}
    for label, vocabulary in _CLASSES:
        if words & vocabulary:
            return label
    return "general"


def features(task):
    return {'role': str(task.get('role') or 'worker'),
            'task_class': str(task.get('task_class') or task.get('kind') or 'general'),
            'complexity': min(1., _number(task.get('complexity'), .5)),
            'required_tools': sorted(set(task.get('required_tools') or [])),
            'prior_failures': int(_number(task.get('done_rejects', task.get('prior_failures', 0)))),
            'context_size': int(_number(task.get('context_size', len(str(task.get('goal', '')).encode('utf-8'))))),
            'memory_coverage': min(1., _number(task.get('memory_coverage'))),
            'uncertainty': min(1., _number(task.get('uncertainty'), .5)),
            'proven_runbook_available': bool(task.get('proven_runbook_available'))}


def _similarity(a, b):
    if a['role'] != b.get('role', 'worker') or a['task_class'] != b.get('task_class', 'general'):
        return 0.
    weight = 1. / (1. + abs(a['complexity'] - _number(b.get('complexity'), .5))
                   + abs(a['memory_coverage'] - _number(b.get('memory_coverage')))
                   + abs(a['uncertainty'] - _number(b.get('uncertainty'), .5)))
    weight /= 1 + abs(a['prior_failures'] - _number(b.get('prior_failures')))
    weight /= 1 + abs(math.log1p(a['context_size']) - math.log1p(_number(b.get('context_size')))) / 10
    wanted, used = set(a['required_tools']), set(b.get('required_tools') or [])
    if wanted or used:
        weight *= (len(wanted & used) + 1) / (len(wanted | used) + 1)
    return weight


def choose(task, strategies, observations=(), cfg=None):
    """Return a reviewable decision with every utility term and exclusion.

    A Beta(1,1) smoothed empirical rate is a routing estimate, not calibrated
    confidence. Unmeasured models cannot displace the configured fallback.
    Runbooks/tools need accepted independent execution evidence to be eligible.
    """
    cfg = cfg or {}
    ag = cfg.get('agent', {}) or {}
    policy = ag.get('scheduler', {}) or {}
    state = features(task)
    value = _number(task.get('task_value_usd'), _number(policy.get('task_value_usd'), 1.))
    budget = _number(task.get('budget_usd'), _number(policy.get('budget_usd'), 1.))
    remaining = max(0., budget - _number(task.get('cost_usd')))
    min_n = max(1, int(policy.get('min_observations', 5)))
    latency_price = _number(policy.get('latency_usd_per_second'))
    risk_price = _number(policy.get('risk_cost_usd'))
    rejected, scored = [], []
    for raw in strategies:
        s = dict(raw)
        ident, kind = s.get('id'), s.get('kind')
        why = None
        if not ident or kind not in KINDS:
            why = 'unknown strategy identity/kind'
        elif s.get('available') is False:
            why = 'strategy unavailable'
        elif kind in {'runbook', 'tool_api'} and not (s.get('accepted') is True and
                int(s.get('independent_wins', 0)) >= min_n):
            why = 'unproven executable strategy'
        elif not set(state['required_tools']).issubset(set(s.get('tools', state['required_tools']))):
            why = 'required tools unavailable'
        elif state['context_size'] > _number(s.get('context_limit'), float('inf')):
            why = 'context exceeds strategy limit'
        weights, wins, costs, times, seen = [], [], [], [], set()
        for r in observations:
            tid = r.get('task_id')
            if r.get('strategy_id') != ident or r.get('verified_l0') is not True or \
                    type(r.get('success')) is not bool or not tid or tid in seen:
                continue
            # A STRATEGY IS ONLY CREDITED WITH WORK IT ACTUALLY DID. Shadow
            # rows record what this planner WOULD have chosen while something
            # else ran; counting their outcome as this strategy's evidence is
            # the same mis-attribution the routing ledger was already
            # corrected for. A shadow row still counts when the pair that
            # served is the very pair this strategy names — then the
            # counterfactual and the fact coincide, and the outcome is
            # genuinely evidence about this strategy.
            if r.get('executed') is False:
                continue
            w = _similarity(state, r.get('features', {}))
            if not w:
                continue
            seen.add(tid)
            weights.append(w)
            wins.append(w * r['success'])
            costs.append(w * _number(r.get('cost_usd')))
            times.append(w * _number(r.get('latency_seconds')))
        support = sum(weights)
        measured = len(seen) >= min_n and support >= min_n / 2
        prior_n = int(s.get('independent_wins', 0)) if kind in {'runbook', 'tool_api'} else 0
        if not measured and prior_n < min_n and not s.get('fallback') and why is None:
            why = 'insufficient similar verified observations'
        probability = ((sum(wins) + 1.) / (support + 2.) if measured else
                       (prior_n + 1.) / (prior_n + 2.) if prior_n else .5)
        model_cost = _number(s.get('cost_usd'), sum(costs) / support if support else .01)
        tool_cost = _number(s.get('tool_cost_usd'))
        verifier_cost = _number(s.get('verifier_cost_usd'))
        latency = _number(s.get('latency_seconds'), sum(times) / support if support else 0.)
        retry = (1. - probability) * _number(s.get('retry_cost_usd'), model_cost)
        risk = (1. - probability) * risk_price
        compute = model_cost + tool_cost + verifier_cost
        if compute > remaining:
            why = 'remaining task budget would be exceeded'
        if why:
            rejected.append({'strategy': ident, 'why': why})
            continue
        terms = {'expected_verified_benefit': probability * value, 'model_cost': model_cost,
                 'tool_cost': tool_cost, 'verifier_cost': verifier_cost,
                 'latency_cost': latency * latency_price, 'retry_cost': retry, 'risk_cost': risk}
        utility = terms['expected_verified_benefit'] - sum(v for k, v in terms.items()
                                                                       if k != 'expected_verified_benefit')
        scored.append({'strategy': s, 'utility': utility, 'terms': terms,
                       'success_estimate': probability, 'similar_observations': len(seen),
                       'effective_support': support, 'estimate_kind': 'empirical_smoothed' if measured else 'heuristic_prior'})
    scored.sort(key=lambda r: (-r['utility'], r['terms']['model_cost'], r['strategy']['id']))
    result = {'features': state, 'rejected': rejected, 'alternatives': scored,
              'remaining_budget_usd': remaining, 'rule': 'contextual_expected_utility',
              'calibrated': False}
    if not scored:
        return dict(result, strategy=None, stop=True, why='no authorized strategy fits evidence and budget')
    best = scored[0]
    s = dict(best['strategy'])
    # Merely requesting parallelism never licenses it for dependent work.
    s['parallelism'] = min(max(1, int(s.get('parallelism', 1))), max(1, int(policy.get('max_parallelism', 1)))) if task.get('independent_work') else 1
    s['candidate_ceiling'] = min(max(1, int(s.get('candidate_ceiling', 1))), max(1, int(ag.get('candidates_max', 5))))
    s['verification_depth'] = max(0, min(4, int(s.get('verification_depth', 0 if task.get('done_check') else 3))))
    result.update(strategy=s, selected=best, stop=False,
                  escalation=bool(state['prior_failures'] and s['kind'] in {'strong_model', 'frontier_model'}),
                  why='maximum expected verified value minus declared/measured costs among eligible strategies')
    return result


def _append(root, path, rec):
    target = os.path.join(root, path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(rec, ensure_ascii=False, allow_nan=False) + '\n')


def outcomes(root):
    try:
        with open(os.path.join(root, LEDGER), encoding='utf-8') as stream:
            rows = []
            for line in stream:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
            return rows[-5000:]
    except OSError:
        return []


def record(root, task, decision, *, success, verified_l0, cost_usd=0.,
           latency_seconds=0., shadow=False, served=()):
    """File one outcome against the decision that produced it.

    `shadow` says the planner only WATCHED — something else chose the
    provider. `served` is the set of "provider:model" pairs that actually
    ran. Together they decide `executed`: whether this strategy may be
    credited with this outcome at all. Recording a counterfactual as if it
    were a fact is how a shadow ledger quietly becomes a false record of
    competence, and choose() filters on `executed` for exactly that reason.
    """
    strategy = decision.get('strategy') or {}
    ident = strategy.get('id')
    served = sorted({str(s) for s in (served or ()) if s})
    executed = (not shadow) or (bool(ident) and served == [ident])
    rec = {'at': time.time(), 'task_id': task.get('id'), 'features': decision['features'],
           'strategy_id': ident, 'strategy_kind': strategy.get('kind'),
           'success': success is True, 'verified_l0': verified_l0 is True,
           'cost_usd': _number(cost_usd), 'latency_seconds': _number(latency_seconds),
           'candidate_count': int(task.get('candidate_rounds') or 1),
           'verification_depth': strategy.get('verification_depth'),
           'escalation': decision.get('escalation', False),
           'shadow': bool(shadow), 'served': served, 'executed': bool(executed),
           'attribution': ('the planner chose and the work ran under that '
                           'choice' if executed else
                           'observed only: this strategy did not serve this '
                           'task, so its outcome is not evidence about it')}
    _append(root, LEDGER, rec)
    return rec


def plan(agent, task, runbooks=(), tool_strategies=()):
    """Loop entry point. Trusted runbook matching supplies proven options.

    Configured strategy descriptors are control-plane state. A task payload
    cannot introduce arbitrary providers, commands or a self-declared runbook.
    """
    cfg = agent.cfg
    rc = agent.role_cfg(task['role'])
    policy = (cfg.get('agent', {}).get('scheduler', {}) or {})
    opts = list(policy.get('strategies', [])) + list(runbooks) + list(tool_strategies)
    static_id = f"{rc.get('provider')}:{rc.get('model')}"
    if not any(s.get('id') == static_id for s in opts):
        opts.append({'id': static_id, 'kind': 'cheap_hosted', 'fallback': True,
                     'provider': rc.get('provider'), 'model': rc.get('model'),
                     'cost_usd': _number(policy.get('fallback_cost_usd'), .01)})
    decision = choose(task, opts, outcomes(agent.root), cfg)
    _append(agent.root, DECISIONS, {'at': time.time(), 'task_id': task.get('id'), **decision})
    return decision
