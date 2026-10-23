"""Freeze, then score reconstructed report inputs; never a prospective export.

No fitting, recalibration, or substitution of actual for configured duration.
The freeze command does not load predictors or calculate evaluation predictions.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools/paper'))
import numpy as np
from nanopredict.paths import models_dir
from nanopredict.predict_calibrated import CalibratedYieldPredictor
from nanopredict.study import (METHODS, baseline_points, development_baselines,
                              interval_prediction, software)
from evaluate_frozen import point_stats, write_csv

HORIZONS = (30, 60, 120)
THRESHOLDS = (1., 5., 10.)
FEATURES = tuple(json.loads((ROOT / 'tools/paper/feature_contract.json').read_text()))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    with Path(path).open('x') as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write('\n')


def read_csv(path):
    with Path(path).open() as handle:
        return list(csv.DictReader(handle))


def keyed(rows, field):
    result = {r[field]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate ' + field)
    return result


def validate_inputs(plan, manifest, features, cohort, outcomes):
    """Reject altered scope, linkage, device, grouping, duration or cutoff."""
    if plan.get('analysis_scope') != 'retrospective_report_reconstruction':
        raise ValueError('Explicit report-reconstruction scope required')
    labels = set(plan['cohort']['run_labels'])
    meta = keyed(cohort, 'run_label')
    ends = keyed(outcomes['runs'], 'run_label')
    if labels != set(meta) or labels != set(ends) or labels != set(manifest['report_sources']):
        raise ValueError('Cohort differs between plan, features and outcomes')
    groups = {}
    for group, members in plan['cohort']['known_related_groups'].items():
        for label in members:
            if label in groups:
                raise ValueError('Run belongs to multiple related groups')
            groups[label] = group
    if set(groups) != labels:
        raise ValueError('Incomplete related groups')
    for label in labels:
        m, end = meta[label], ends[label]
        if m['device_type'] != 'MINION_MK1D' or m['flowcell_group'] != groups[label]:
            raise ValueError('Unexpected device or group')
        if m['development_overlap_declaration'] != 'none_reported' or m['forecast_influence_declaration'] != 'False':
            raise ValueError('Eligibility declaration unresolved')
        if m['distinct_patient_declaration'] != 'True' or m['distinct_specimen_library_declaration'] != 'True':
            raise ValueError('Related-material declaration unresolved')
        report_hash = manifest['report_sources'][label]['report_sha256']
        if end['report_sha256'] != report_hash or plan['extraction']['source_report_hashes'][label] != report_hash:
            raise ValueError('Outcome/report linkage mismatch')
        if not end['passed_yield_reconciled'] or end['status'] != 'exact_passed_yield_and_count_match':
            raise ValueError('Unreconciled outcome')
        actual = end['accepted_final_passed_bases']
        if actual is None or not math.isfinite(actual) or actual < 0:
            raise ValueError('Invalid outcome')
    seen = set()
    for row in features:
        label, horizon = row['run_label'], int(row['horizon_minutes'])
        key = (label, horizon)
        if key in seen or label not in labels or horizon not in HORIZONS:
            raise ValueError('Duplicate or unexpected checkpoint')
        seen.add(key)
        if row['device_type'] != meta[label]['device_type'] or row['flowcell_group'] != groups[label]:
            raise ValueError('Feature metadata mismatch')
        if row['evidence_type'] != 'retrospective_candidate_inputs' or row['live_availability_verified'] != 'False':
            raise ValueError('Cannot relabel report inputs as live observations')
        if set(FEATURES) - row.keys():
            raise ValueError('Missing feature columns')
        for feature in FEATURES:
            if row[feature] != '' and not math.isfinite(float(row[feature])):
                raise ValueError('Use empty cells for missing features')
        if not 0 < float(row['observed_through_seconds']) <= horizon * 60:
            raise ValueError('Future or missing observation time')
        if float(meta[label]['acquisition_duration_hours']) * 60 < horizon:
            raise ValueError('Acquisition ended before checkpoint')
        if float(row['planned_run_limit_hours']) != float(meta[label]['reported_runtime_limit_hours']):
            raise ValueError('Configured duration changed')
    if seen != {(label, h) for label in labels for h in HORIZONS}:
        raise ValueError('Missing checkpoint rows')
    for feature in FEATURES:
        if sum(row[feature] == '' for row in features) != manifest['missing_by_feature'][feature]:
            raise ValueError('Feature missingness differs from extraction audit')
    return meta, ends


def verify_files(files):
    for name, expected in files.items():
        if digest(name) != expected:
            raise ValueError('Frozen file changed: ' + name)


def freeze(extraction, outcomes_path, plan_path, output):
    extraction, outcomes_path, plan_path, output = map(Path, (extraction, outcomes_path, plan_path, output))
    plan = json.loads(plan_path.read_text())
    manifest = json.loads((extraction / 'manifest.json').read_text())
    outcomes = json.loads(outcomes_path.read_text())
    validate_inputs(plan, manifest, read_csv(extraction / 'candidate_features.csv'), read_csv(extraction / 'cohort.csv'), outcomes)
    checks = {
        ROOT / 'tools/paper/extract_retrospective.py': manifest['script_sha256'],
        ROOT / 'src/nanopredict/live.py': manifest['live_helper_sha256'],
        ROOT / 'tools/paper/feature_contract.json': manifest['feature_contract_sha256'],
        ROOT / 'tools/paper/reconcile_retrospective_yield.py': outcomes['script_sha256'],
        outcomes_path: plan['endpoint']['reconciliation_manifest_sha256'],
    }
    if plan['extraction']['candidate_script_sha256'] != manifest['script_sha256'] or plan['extraction']['candidate_live_helper_sha256'] != manifest['live_helper_sha256']:
        raise ValueError('Plan and extraction source versions differ')
    if manifest['model_hashes'] != plan['model_sha256']:
        raise ValueError('Plan and extraction models differ')
    checks.update({models_dir() / n: h for n, h in plan['model_sha256'].items()})
    verify_files(checks)
    output.mkdir(parents=True, exist_ok=False)
    sources = {'plan.json': plan_path, 'extraction.json': extraction / 'manifest.json',
               'features.csv': extraction / 'candidate_features.csv', 'cohort.csv': extraction / 'cohort.csv',
               'feature_audit.csv': extraction / 'feature_audit.csv', 'outcomes.json': outcomes_path}
    for name, source in sources.items():
        shutil.copyfile(source, output / name)
    # Freeze every runtime module plus analysis/extraction sources, models and contract.
    files = list((ROOT / 'src/nanopredict').glob('*.py')) + list(models_dir().glob('*.joblib'))
    files += [ROOT / 'tools/paper' / n for n in ('evaluate_retrospective.py', 'evaluate_frozen.py', 'extract_retrospective.py', 'reconcile_retrospective_yield.py')]
    files += [ROOT / 'tools/paper/feature_contract.json', ROOT / 'src/nanopredict/data/replay_features_anonymous.csv']
    files += [output / name for name in sources]
    frozen = {'schema': 'nanopredict-retrospective-freeze-v1', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Retrospective report reconstruction; not contemporaneous or prospective prediction',
              'files': {str(p.resolve()): digest(p) for p in files}, 'software': software(),
              'methods': METHODS, 'thresholds_gb': THRESHOLDS, 'bootstrap_replicates': 2000, 'bootstrap_seed': 20261008,
              'baselines': development_baselines(), 'inputs': {k: str((output / k).resolve()) for k in sources}}
    dump(output / 'freeze.json', frozen)
    print('Frozen without evaluation predictions:', output / 'freeze.json')


def predict_rows(features, meta, ends, predictor, baselines):
    rows = []
    for row in features:
        label, h = row['run_label'], int(row['horizon_minutes'])
        config = baselines['horizons'][str(h)]
        # No outcome, actual duration, identity, or adjudication enters the model.
        inputs = {key: row[key] for key in FEATURES}
        inputs['device_type'] = row['device_type']
        predictions, errors = {}, {}
        try:
            predictions['bundled'] = predictor.predict(inputs, h, THRESHOLDS)
        except Exception as exc:
            predictions['bundled'] = None
            errors['bundled'] = type(exc).__name__ + ': ' + str(exc)
        for method, point in baseline_points(inputs, config).items():
            predictions[method] = interval_prediction(point, config['residuals'][method], THRESHOLDS)
        rows.append({'run_code': label, 'group_code': meta[label]['flowcell_group'], 'horizon_minutes': h,
                     'actual_gb': ends[label]['accepted_final_passed_bases'] / 1e9,
                     'end_reason': meta[label]['stop_reason_adjudicated'],
                     'configuration_error': meta[label]['configuration_error_declared'] == 'True',
                     'predictions': predictions, 'errors': errors})
    return rows


def bootstrap_samples(rows, replicates, seed):
    groups = sorted({r['group_code'] for r in rows})
    grouped = [[r for r in rows if r['group_code'] == g] for g in groups]
    draws = np.random.default_rng(seed).integers(len(groups), size=(replicates, len(groups)))
    return [[r for i in draw for r in grouped[i]] for draw in draws]


def summarize(rows, replicates=2000, seed=20261008):
    metrics, paired, availability, probabilities = [], [], [], []
    for h in HORIZONS:
        at_h = [r for r in rows if r['horizon_minutes'] == h]
        for r in at_h:
            for method in METHODS:
                availability.append({'run_label': r['run_code'], 'horizon_minutes': h, 'method': method,
                                     'available': r['predictions'][method] is not None,
                                     'reason': r['errors'].get(method, 'available' if r['predictions'][method] is not None else 'missing_required_baseline_input')})
        strata = {'all': at_h, 'excluding_configuration_errors': [r for r in at_h if not r['configuration_error']],
                  'protocol_completion': [r for r in at_h if r['end_reason'] == 'reported_protocol_completion'],
                  'sufficient_data_stop': [r for r in at_h if r['end_reason'] == 'intentional_stop_sufficient_data']}
        for stratum, selected in strata.items():
            for method in METHODS:
                available = [r for r in selected if r['predictions'][method] is not None]
                if not available:
                    continue
                groups = len({r['group_code'] for r in available})
                fields = {'horizon_minutes': h, 'stratum': stratum, 'method': method,
                          'n_runs': len(available), 'n_groups': groups, 'n_eligible': len(selected)}
                estimate = point_stats(available, method)
                samples = bootstrap_samples(available, replicates, seed)
                boot = [point_stats(sample, method) for sample in samples]
                output = {**fields, **estimate}
                for key in estimate:
                    values = np.array([b[key] for b in boot])
                    lo, hi = np.quantile(values, [.025, .975]) if groups >= 2 and np.isfinite(values).all() else ('', '')
                    output[key + '_ci_low'], output[key + '_ci_high'] = lo, hi
                metrics.append(output)
                # Compare only the same runs, without complete-case filtering all methods.
                matched = [r for r in available if r['predictions']['linear_planned'] is not None]
                if matched:
                    n_groups = len({r['group_code'] for r in matched})
                    method_mae = point_stats(matched, method)['mae_gb']
                    reference_mae = point_stats(matched, 'linear_planned')['mae_gb']
                    deltas = [point_stats(sample, method)['mae_gb'] - point_stats(sample, 'linear_planned')['mae_gb']
                              for sample in bootstrap_samples(matched, replicates, seed)]
                    lo, hi = np.quantile(deltas, [.025, .975]) if n_groups >= 2 else ('', '')
                    paired.append({**fields, 'n_runs': len(matched), 'n_groups': n_groups, 'reference': 'linear_planned',
                                   'method_mae_gb': method_mae, 'reference_mae_gb': reference_mae,
                                   'delta_mae_gb': method_mae - reference_mae, 'ci_low': lo, 'ci_high': hi})
                for threshold in THRESHOLDS:
                    eligible = [r for r in available if r['predictions'][method]['threshold_probabilities'].get(str(threshold)) is not None]
                    if not eligible:
                        continue
                    prob = np.array([r['predictions'][method]['threshold_probabilities'][str(threshold)] for r in eligible])
                    if not np.isfinite(prob).all() or ((prob < 0) | (prob > 1)).any():
                        raise ValueError('Invalid probability')
                    events = np.array([r['actual_gb'] >= threshold for r in eligible])
                    probabilities.append({**fields, 'n_runs': len(eligible), 'threshold_gb': threshold,
                                          'events': int(events.sum()), 'non_events': int((~events).sum()),
                                          'mean_probability': float(prob.mean()), 'brier_score': float(np.mean((prob - events) ** 2))})
    return metrics, paired, availability, probabilities


def score(freeze_path, output):
    frozen = json.loads(Path(freeze_path).read_text())
    if frozen['schema'] != 'nanopredict-retrospective-freeze-v1':
        raise ValueError('Retrospective freeze required')
    verify_files(frozen['files'])
    if frozen['software'] != software():
        raise ValueError('Frozen software environment changed')
    inputs = frozen['inputs']
    plan, manifest, outcomes = [json.loads(Path(inputs[n]).read_text()) for n in ('plan.json', 'extraction.json', 'outcomes.json')]
    features, cohort = read_csv(inputs['features.csv']), read_csv(inputs['cohort.csv'])
    meta, ends = validate_inputs(plan, manifest, features, cohort, outcomes)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    predictor = CalibratedYieldPredictor(models_dir())
    for artifact in predictor.artifacts.values():
        if set(artifact['feature_columns']) != set(FEATURES):
            raise ValueError('Model feature contract differs')
    rows = predict_rows(features, meta, ends, predictor, frozen['baselines'])
    dump(output / 'predictions.json', {'scope': frozen['scope'], 'freeze_sha256': digest(freeze_path), 'rows': rows})
    results = summarize(rows, frozen['bootstrap_replicates'], frozen['bootstrap_seed'])
    for name, content in zip(('metrics.csv', 'paired.csv', 'availability.csv', 'probabilities.csv'), results):
        write_csv(output / name, content)
    verify_files(frozen['files'])
    dump(output / 'provenance.json', {'scope': frozen['scope'], 'freeze_sha256': digest(freeze_path),
                                    'scored_at_utc': datetime.now(timezone.utc).isoformat(),
                                    'output_sha256': {p.name: digest(p) for p in sorted(output.iterdir())},
                                    'n_runs': len(meta), 'n_checkpoints': len(rows),
                                    'limitations': manifest['limitations']})
    print('Retrospective reconstruction results:', output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    f = sub.add_parser('freeze')
    for name in ('extraction', 'outcomes', 'plan', 'output'):
        f.add_argument('--' + name, type=Path, required=True)
    s = sub.add_parser('score')
    s.add_argument('--freeze', type=Path, required=True)
    s.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    if a.action == 'freeze':
        freeze(a.extraction, a.outcomes, a.plan, a.output)
    else:
        score(a.freeze, a.output)


if __name__ == '__main__':
    main()
