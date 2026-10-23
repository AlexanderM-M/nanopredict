"""Develop duration-aware candidates without reading new qualification outcomes.

Uses the original fitting/calibration group assignment. Selection happens only
in fitting-group CV, with a short-run non-inferiority guard against extrapolation.
All metrics are development results, not independent validation.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import joblib
import numpy as np
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from nanopredict.duration_model import DurationYieldRegressor, FEATURE_COLUMNS
from nanopredict.predict_calibrated import CalibratedYieldPredictor
from nanopredict.study import baseline_points
from train_minion import read_development, related_groups, partition_groups, calibrate, group_mae, SEED, FEATURES

# Fixed before inspecting scores. Baseline is first to win exact ties.
CANDIDATES = tuple({'half_life_hours': h, 'learn_scale': scale}
                   for scale in (False, True) for h in (None, 3., 6., 12., 24.))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def matrix(rows):
    return np.asarray([[float(r[f]) if r[f] else np.nan for f in FEATURE_COLUMNS] for r in rows])


def group_weights(groups):
    counts = Counter(groups)
    return np.asarray([1 / counts[g] for g in groups])


def select(X, y, groups):
    splits = list(GroupKFold(5, shuffle=True, random_state=SEED).split(X, y, groups))
    short = X[:, 2] <= 6
    predictions, records = [], []
    for config in CANDIDATES:
        p = np.full(len(y), np.nan)
        for fit, val in splits:
            assert not set(groups[fit]) & set(groups[val])
            m = DurationYieldRegressor(**config).fit(X[fit], y[fit], group_weights(groups[fit]))
            p[val] = m.predict(X[val])
        records.append({'config': config, 'group_mae_gb': group_mae(y, p, groups),
                        'short_group_mae_gb': group_mae(y[short], p[short], groups[short]) if short.any() else None,
                        'run_mae_gb': float(np.mean(abs(p - y)))})
        predictions.append(p)
    baseline = records[0]
    # Require at least 1% overall improvement and no >5% short-run degradation.
    eligible = [i for i, r in enumerate(records) if i == 0 or (
        r['group_mae_gb'] <= baseline['group_mae_gb'] * .99 and
        (not short.any() or r['short_group_mae_gb'] <= baseline['short_group_mae_gb'] * 1.05))]
    winner = min(eligible, key=lambda i: (records[i]['group_mae_gb'], i))
    return winner, records, predictions[winner]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--membership', type=Path, required=True)
    parser.add_argument('--previous-development', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be new')
    previous = json.loads((args.previous_development / 'plan.json').read_text())
    for p in (args.features, args.membership):
        if previous['source_sha256'].get(str(p.resolve())) != sha(p):
            raise ValueError('Input differs from the frozen original development source')
    rows, excluded_devices = read_development(args.features)
    groups = related_groups(rows, json.loads(args.membership.read_text())['training_runs'])
    fitting, calibration = partition_groups(groups.values())
    assert set(previous['fit_groups']) == fitting and set(previous['calibration_groups']) == calibration
    args.output.mkdir(parents=True)
    modeldir = args.output / 'models'
    modeldir.mkdir()
    plan = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'purpose': 'Development after live mismatch diagnosis; no independent accuracy claim',
            'candidate_grid': CANDIDATES, 'feature_columns': FEATURE_COLUMNS,
            'selection': 'Fitting-only five-fold grouped MAE; require >=1% improvement over cumulative extrapolation and <=5% worsening for planned duration <=6h; otherwise select cumulative extrapolation.',
            'scale_bound': [0, 2], 'short_run_definition_hours': 6,
            'fit_groups': sorted(fitting), 'calibration_groups': sorted(calibration),
            'source_sha256': {str(p.resolve()): sha(p) for p in (args.features, args.membership, Path(__file__), ROOT / 'src/nanopredict/duration_model.py')},
            'endpoint': 'Observed-ending final passed Gb; not counterfactual yield after an intentional stop',
            'live_runs_used_for_design_not_fitting': ['2026-10-20', '2026-10-21'],
            'missing_required_input': 'Unavailable; never impute a planned duration',
            'future_evaluation': 'Freeze this selected model before collecting new evaluation acquisitions'}
    dump(args.output / 'plan.json', plan)  # written before any CV scores
    artifacts, results, predictions, availability = [], [], [], []
    baselines = {'source_sha256': sha(args.features), 'evidence': 'Original MinION development rows, original related-group split; constants fit only on fitting rows', 'horizons': {}}
    for h in (30, 60, 120):
        subset = [r for r in rows if int(r['horizon_minutes']) == h]
        valid = []
        for r in subset:
            x = matrix([r])[0]
            usable = bool(np.isfinite(x).all() and x[0] >= 0 and x[1] > 0 and x[2] > 0 and x[2] * 3600 >= x[1])
            availability.append({'sample_label': r['sample_label'], 'run_label': r['run_label'], 'horizon_minutes': h, 'usable': usable, 'group': groups[r['sample_label'], r['run_label']], 'partition': 'fit' if groups[r['sample_label'], r['run_label']] in fitting else 'calibration'})
            if usable:
                valid.append(r)
        X = matrix(valid)
        y = np.asarray([float(r['target_final_passed_bases']) / 1e9 for r in valid])
        g = np.asarray([groups[r['sample_label'], r['run_label']] for r in valid])
        fit = np.asarray([group in fitting for group in g]); cal = ~fit
        winner, scores, oof = select(X[fit], y[fit], g[fit])
        model = DurationYieldRegressor(**CANDIDATES[winner]).fit(X[fit], y[fit], group_weights(g[fit]))
        point = model.predict(X[cal])
        signed, weights, radii = calibrate(y[cal], point, g[cal])
        config = {'median_gb': float(np.median(y[fit])), 'mean_gb': float(np.mean(y[fit])), 'residuals': {m: [] for m in ('linear_planned', 'recent_planned', 'development_median', 'development_mean')}}
        for r, outcome, iscal in zip(valid, y, cal):
            if iscal:
                for name, p in baseline_points(r, config).items():
                    if p is not None:
                        config['residuals'][name].append(math.log1p(outcome) - math.log1p(p))
        baselines['horizons'][str(h)] = config
        artifact = {'artifact_schema': 'nanopredict-duration-development-v3', 'horizon_minutes': h,
                    'model_name': 'minion_duration_extrapolation', 'model': model,
                    'feature_columns': list(FEATURE_COLUMNS), 'recording_feature_columns': list(FEATURES),
                    'allowed_device_types': ['MINION_MK1D'], 'point_postprocess': 'observed_yield_floor',
                    'target': 'final_passed_gb', 'plan_sha256': sha(args.output / 'plan.json'),
                    'signed_log_residuals': {'__global__': signed, 'MINION_MK1D': signed},
                    'signed_residual_weights': {'__global__': weights, 'MINION_MK1D': weights},
                    'interval_log_scores': {'__global__': radii, 'MINION_MK1D': radii},
                    'warning': 'Duration-aware development candidate. Assumes continued sequencing to the configured limit; independent accuracy and calibration remain unvalidated.'}
        artifacts.append(artifact)
        baseline = DurationYieldRegressor().fit(X[fit], y[fit]).predict(X[cal])
        old = CalibratedYieldPredictor(args.previous_development / 'models')
        previous_points = np.asarray([old.predict(r, h)['point_prediction_gb'] for r, keep in zip(valid, cal) if keep])
        metrics = {}
        for label, p in [('candidate', point), ('cumulative', baseline), ('previous_candidate', previous_points)]:
            metrics[label] = {'mae_gb': float(np.mean(abs(p - y[cal]))), 'group_mae_gb': group_mae(y[cal], p, g[cal])}
            short = X[cal, 2] <= 6
            metrics[label]['short_mae_gb'] = float(np.mean(abs(p[short] - y[cal][short]))) if short.any() else None
        for r, outcome, p, b, oldp in zip([r for r, keep in zip(valid, cal) if keep], y[cal], point, baseline, previous_points):
            predictions.append({'sample_label': r['sample_label'], 'run_label': r['run_label'], 'horizon_minutes': h, 'group': groups[r['sample_label'], r['run_label']], 'actual_gb': outcome, 'candidate_gb': p, 'cumulative_gb': b, 'previous_candidate_gb': oldp})
        result = {'horizon_minutes': h, 'chosen_config': CANDIDATES[winner], 'fitted_scale': model.scale_, 'fit_rows': int(fit.sum()), 'calibration_rows': int(cal.sum()), 'fit_groups': len(set(g[fit])), 'calibration_groups': len(set(g[cal])), 'selection_scores': scores, 'calibration_metrics_same_rows': metrics}
        results.append(result)
        print(h, result, flush=True)
    for artifact in artifacts:
        artifact['study_baselines'] = baselines
        joblib.dump(artifact, modeldir / f"calibrated_yield_{artifact['horizon_minutes']}min.joblib")
    consumer = CalibratedYieldPredictor(modeldir)
    runtime_checks = 0
    for r in rows:
        key = (r['sample_label'], r['run_label'], int(r['horizon_minutes']))
        matches = [p for p in predictions if (p['sample_label'], p['run_label'], p['horizon_minutes']) == key]
        if matches:
            actual = consumer.predict(r, key[2], (.1, .2, 1.))
            assert math.isclose(actual['point_prediction_gb'], matches[0]['candidate_gb'], rel_tol=1e-12, abs_tol=1e-12)
            json.dumps(actual, allow_nan=False)
            runtime_checks += 1
    for name, data in [('calibration_predictions.csv', predictions), ('availability.csv', availability)]:
        with (args.output / name).open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
    dump(args.output / 'manifest.json', {'status': 'Development candidate; not independently validated or automatically deployed', 'results': results, 'runtime_predictions_verified': runtime_checks, 'non_minion_rows_excluded': excluded_devices, 'models': {p.name: sha(p) for p in modeldir.glob('*.joblib')}, 'plan_sha256': sha(args.output / 'plan.json'), 'baseline_provenance': baselines['evidence'], 'calibration_selection_used': False})


if __name__ == '__main__':
    main()
