"""Held-out binary calibration metrics and conservative histogram calibration.

Prediction labels are mechanical outcomes, not worker/verifier self-reports.
Calibration-set fitting, threshold tuning and holdout evaluation are separate.
No metric here proves live-provider performance.
"""
import hashlib
import json
import math


def _validate(rows, split, forbidden=()):
    seen = set()
    clean = []
    for raw in rows:
        row = dict(raw)
        tid = row.get('task_id')
        if not tid or tid in seen or tid in forbidden:
            raise ValueError('duplicate, missing or contaminated task identity')
        if row.get('split') != split:
            raise ValueError(f'{split} split required')
        if row.get('verified_l0') is not True or type(row.get('success')) is not bool:
            raise ValueError('independent mechanical binary outcome required')
        p = float(row.get('prediction', -1))
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('prediction must be finite in [0,1]')
        seen.add(tid)
        row.update(prediction=p, task_class=str(row.get('task_class') or 'general'))
        clean.append(row)
    return clean


def _metrics(rows, bins):
    groups = [[] for _ in range(bins)]
    for row in rows:
        groups[min(bins - 1, int(row['prediction'] * bins))].append(row)
    curve = []
    for i, bucket in enumerate(groups):
        n = len(bucket)
        curve.append({'lower': i / bins, 'upper': (i + 1) / bins, 'n': n,
                      'predicted': sum(r['prediction'] for r in bucket) / n if n else None,
                      'observed': sum(r['success'] for r in bucket) / n if n else None})
    n = len(rows)
    return {'n': n, 'brier': sum((r['prediction'] - r['success']) ** 2 for r in rows) / n if n else None,
            'ece': sum(b['n'] * abs(b['predicted'] - b['observed']) for b in curve if b['n']) / n if n else None,
            'verified_success_rate': sum(r['success'] for r in rows) / n if n else None,
            'reliability_curve': curve}


def evaluate(rows, bins=10, training_ids=(), min_samples=100):
    if not 1 <= bins <= 100:
        raise ValueError('bins must be in [1,100]')
    data = _validate(rows, 'holdout', set(training_ids))
    classes = sorted({r['task_class'] for r in data})
    by_class = {cls: _metrics([r for r in data if r['task_class'] == cls], bins) for cls in classes}
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return {**_metrics(data, bins), 'by_task_class': by_class, 'split': 'holdout',
            'task_ids': [r['task_id'] for r in data], 'dataset_hash': digest,
            'evidence_tier': 'offline_heldout',
            'sufficient_data': bool(data) and all(v['n'] >= min_samples for v in by_class.values()),
            'claim': 'measured calibration on these held-out labels only; no deployment generalization'}


def fit(rows, bins=10, min_bin=10):
    if not 1 <= bins <= 100 or min_bin < 1:
        raise ValueError('invalid calibration settings')
    data = _validate(rows, 'calibration')
    tables = {}
    for cls in sorted({r['task_class'] for r in data}):
        metrics = _metrics([r for r in data if r['task_class'] == cls], bins)
        tables[cls] = [{'n': b['n'], 'probability': ((b['observed'] * b['n'] + 1) / (b['n'] + 2))
                       if b['n'] >= min_bin else None} for b in metrics['reliability_curve']]
    return {'method': 'class_conditional_histogram_laplace', 'bins': bins, 'min_bin': min_bin,
            'fit_task_ids': [r['task_id'] for r in data], 'tables': tables,
            'validated': False, 'claim': 'candidate calibrator; requires disjoint holdout evaluation'}


def predict(model, score, task_class):
    score = float(score)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError('invalid heuristic score')
    table = model['tables'].get(task_class, [])
    idx = min(model['bins'] - 1, int(score * model['bins']))
    cell = table[idx] if table else {}
    p = cell.get('probability')
    return {'prediction': p if p is not None else score,
            'kind': 'empirical_calibration_candidate' if p is not None else 'heuristic_score',
            'calibrated': False, 'support': cell.get('n', 0)}


def validate(model, holdout_rows, min_samples=100):
    data = _validate(holdout_rows, 'holdout', set(model['fit_task_ids']))
    predicted = [{**r, 'prediction': predict(model, r['prediction'], r['task_class'])['prediction']} for r in data]
    before = evaluate(data, bins=model['bins'], training_ids=model['fit_task_ids'], min_samples=min_samples)
    after = evaluate(predicted, bins=model['bins'], training_ids=model['fit_task_ids'], min_samples=min_samples)
    return {'before': before, 'after': after,
            'sufficient_data': after['sufficient_data'],
            'brier_delta': after['brier'] - before['brier'] if data else None,
            'ece_delta': after['ece'] - before['ece'] if data else None,
            'claim': 'comparison is a measured held-out result, not automatic threshold promotion'}


def tune_threshold(rows, *, max_false_accept_rate=.05, min_accepted=10):
    """Tune on calibration data only. Frozen threshold then needs holdout test."""
    data = _validate(rows, 'calibration')
    options = []
    for threshold in sorted({r['prediction'] for r in data}):
        accepted = [r for r in data if r['prediction'] >= threshold]
        false_rate = sum(not r['success'] for r in accepted) / len(accepted)
        if len(accepted) >= min_accepted and false_rate <= max_false_accept_rate:
            options.append((len(accepted), -threshold, threshold, false_rate))
    best = max(options) if options else None
    return {'threshold': best[2] if best else None, 'accepted_n': best[0] if best else 0,
            'false_accept_rate': best[3] if best else None,
            'fit_task_ids': [r['task_id'] for r in data], 'requires_holdout': True}
