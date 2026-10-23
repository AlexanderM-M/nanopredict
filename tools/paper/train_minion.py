"""Train staged MinION-only candidates with grouped tuning and calibration.

Only a specified development feature table is read. Artifacts are written to a
new output directory, never to the package's bundled model directory. The saved
development selection/calibration scores are not independent validation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
import csv
import joblib
import numpy as np
import sklearn
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from nanopredict.predict_calibrated import CalibratedYieldPredictor

FEATURES = tuple(json.loads((ROOT/'tools/paper/feature_contract.json').read_text()))
DEVICE = 'MINION_MK1D'
SEED = 20261016
CANDIDATES = tuple([{'family': 'log_ridge', 'alpha': a} for a in (1., 10., 100.)] +
                   [{'family': 'extra_trees', 'min_samples_leaf': leaf} for leaf in (3, 5)])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')


def write_csv(path, rows):
    with Path(path).open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader(); writer.writerows(rows)


def read_development(path):
    with Path(path).open(newline='') as handle:
        all_rows = list(csv.DictReader(handle))
    rows = [r for r in all_rows if r.get('device_type') == DEVICE]
    if not rows:
        raise ValueError('No supported MinION development observations')
    seen = set()
    outcomes = {}
    for r in rows:
        key = (r['sample_label'], r['run_label'], int(r['horizon_minutes']))
        if not all(key[:2]) or key in seen or key[2] not in (30, 60, 120):
            raise ValueError('Invalid or duplicate development checkpoint')
        seen.add(key)
        y = float(r['target_final_passed_bases'])
        if not math.isfinite(y) or y < 0:
            raise ValueError('Invalid final yield')
        run = key[:2]
        if run in outcomes and outcomes[run] != y:
            raise ValueError('Inconsistent outcome within acquisition')
        outcomes[run] = y
        if float(r['device_is_promethion']) != 0:
            raise ValueError('MinION label conflicts with device feature')
        t = float(r['observed_through_seconds'])
        if not math.isfinite(t) or not 0 < t <= key[2]*60:
            raise ValueError('Invalid observation cutoff')
        for feature in FEATURES:
            if r[feature] and not math.isfinite(float(r[feature])):
                raise ValueError('Non-finite feature; encode missing as empty')
        observed = float(r['observed_passed_bases']) if r['observed_passed_bases'] else 0.
        if observed < 0 or observed > y:
            raise ValueError('Observed passed yield exceeds final yield or is negative')
    return rows, len(all_rows)-len(rows)


def related_groups(rows, membership):
    """Join sample, flowcell and any supplied biological-group identifiers."""
    lookup = {}
    parent = {}
    def find(k):
        parent.setdefault(k, k)
        if parent[k] != k:
            parent[k] = find(parent[k])
        return parent[k]
    for r in membership:
        key = (r['sample_label'], r['run_label'])
        if key in lookup or not r.get('flow_cell_id'):
            raise ValueError('Duplicate membership or missing flowcell ID')
        lookup[key] = r
        nodes = ['sample:'+r['sample_label'], 'flowcell:'+r['flow_cell_id']]
        if r.get('related_group_id'):
            nodes.append('biological:'+r['related_group_id'])
        for node in nodes[1:]:
            parent[find(node)] = find(nodes[0])
    roots = {}
    for r in rows:
        key = (r['sample_label'], r['run_label'])
        if key not in lookup:
            raise ValueError('Missing development membership')
        roots[key] = find('sample:'+r['sample_label'])
    names = {k: f'Group{i+1:03d}' for i, k in enumerate(sorted(set(roots.values())))}
    return {key: names[value] for key, value in roots.items()}


def partition_groups(groups, seed=SEED):
    unique = sorted(set(groups))
    if len(unique) < 12:
        raise ValueError('Insufficient related groups for fitting and calibration')
    shuffled = np.random.default_rng(seed).permutation(unique)
    n = math.ceil(len(unique)*.25)
    calibration = set(shuffled[:n])
    fitting = set(shuffled[n:])
    assert not calibration & fitting
    return fitting, calibration


def make_model(config, trees=600):
    imputer = SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True)
    if config['family'] == 'log_ridge':
        return TransformedTargetRegressor(
            regressor=make_pipeline(imputer, StandardScaler(), Ridge(alpha=config['alpha'])),
            func=np.log1p, inverse_func=np.expm1)
    if config['family'] == 'extra_trees':
        return make_pipeline(imputer, ExtraTreesRegressor(n_estimators=trees, max_features=.8,
                             min_samples_leaf=config['min_samples_leaf'], random_state=SEED, n_jobs=2))
    raise ValueError('Unknown candidate')


def matrix(rows):
    return np.array([[float(r[f]) if r[f] else np.nan for f in FEATURES] for r in rows])


def observed_floor(X):
    values = X[:, FEATURES.index('observed_passed_bases')]/1e9
    return np.where(np.isfinite(values), np.maximum(values, 0), 0)


def predict(model, X):
    values = model.predict(X)
    if not np.isfinite(values).all():
        raise ValueError('Non-finite candidate prediction')
    return np.maximum(values, observed_floor(X))


def group_mae(actual, predicted, groups):
    return float(np.mean([np.mean(abs(predicted[groups==g]-actual[groups==g])) for g in sorted(set(groups))]))


def tune(X, y, groups, candidates=CANDIDATES, trees=600):
    """Calibration rows are never accepted here; refit preprocessing per fold."""
    if len(set(groups)) < 5:
        raise ValueError('Need five fitting groups for tuning')
    splits = list(GroupKFold(5, shuffle=True, random_state=SEED).split(X, y, groups))
    scores, predictions = [], []
    for config in candidates:
        values = np.full(len(y), np.nan)
        for fit, validation in splits:
            if set(groups[fit]) & set(groups[validation]):
                raise ValueError('Tuning group overlap')
            model = make_model(config, trees)
            model.fit(X[fit], y[fit])
            values[validation] = predict(model, X[validation])
        if not np.isfinite(values).all():
            raise ValueError('Missing tuning prediction')
        scores.append({'config': config, 'group_mae_gb': group_mae(y, values, groups),
                       'run_mae_gb': float(np.mean(abs(values-y)))})
        predictions.append(values)
    winner = min(range(len(scores)), key=lambda i: (scores[i]['group_mae_gb'], i))
    model = make_model(candidates[winner], trees)
    model.fit(X, y)
    return model, scores, winner, predictions[winner]


def calibrate(y, predicted, groups):
    signed = np.log1p(y)-np.log1p(predicted)
    scores = sorted(float(np.max(abs(signed[groups==g]))) for g in sorted(set(groups)))
    counts = Counter(groups)
    weights = [1./counts[g] for g in groups]
    radii = {}
    for coverage in (80, 90, 95):
        rank = math.ceil((len(scores)+1)*coverage/100)
        radii[str(coverage)] = scores[rank-1] if rank <= len(scores) else math.inf
    return signed.tolist(), weights, radii


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--membership', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be a new directory')
    rows, excluded = read_development(args.features)
    membership = json.loads(args.membership.read_text())['training_runs']
    groups_by_run = related_groups(rows, membership)
    fitting, calibration = partition_groups(groups_by_run.values())
    args.output.mkdir(parents=True, exist_ok=False)
    models = args.output/'models'; models.mkdir()
    source_hashes = {str(p.resolve()): digest(p) for p in [args.features, args.membership, Path(__file__), ROOT/'src/nanopredict/predict_calibrated.py']}
    bundled = {p.name: digest(p) for p in (ROOT/'src/nanopredict/data/models').glob('*.joblib')}
    plan = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'allowed_device_types': [DEVICE],
            'source_sha256': source_hashes, 'bundled_model_sha256': bundled,
            'candidates': CANDIDATES, 'tree_count': 600, 'seed': SEED,
            'selection_metric': 'mean of within-related-group MAEs in fitting-only five-fold CV',
            'calibration_fraction_of_groups': .25, 'point_postprocess': 'observed_yield_floor',
            'fit_groups': sorted(fitting), 'calibration_groups': sorted(calibration),
            'uncertainty': 'Separate development calibration groups; max absolute log1p residual per group; finite-sample order statistic. Signed residuals weighted to give each group total weight one.',
            'limitations': 'Previously inspected historical development data; no independent performance or coverage claim. Only recorded relationships can be grouped. Live feature parity still requires qualification.'}
    dump(args.output/'plan.json', plan)
    splits = [{**{k: r[k] for k in ('sample_label','run_label','horizon_minutes','device_type')},
               'group': groups_by_run[(r['sample_label'],r['run_label'])],
               'partition': 'fit' if groups_by_run[(r['sample_label'],r['run_label'])] in fitting else 'calibration'} for r in rows]
    write_csv(args.output/'private_split_manifest.csv', splits)
    results = []
    with threadpool_limits(limits=1):
        for horizon in (30, 60, 120):
            selected = [r for r in rows if int(r['horizon_minutes']) == horizon]
            X = matrix(selected); y = np.array([float(r['target_final_passed_bases'])/1e9 for r in selected])
            groups = np.array([groups_by_run[(r['sample_label'],r['run_label'])] for r in selected])
            fit = np.array([g in fitting for g in groups]); cal = ~fit
            assert not set(groups[fit]) & set(groups[cal])
            if not cal.any():
                raise ValueError('No calibration observations at checkpoint')
            model, scores, winner, oof = tune(X[fit], y[fit], groups[fit])
            calibration_predictions = predict(model, X[cal])
            signed, weights, radii = calibrate(y[cal], calibration_predictions, groups[cal])
            config = scores[winner]['config']
            artifact = {'artifact_schema': 'nanopredict-minion-development-v2', 'horizon_minutes': horizon,
                        'model_name': 'minion_'+config['family'], 'target': 'final_passed_gb',
                        'feature_columns': list(FEATURES), 'model': model, 'allowed_device_types': [DEVICE],
                        'point_postprocess': 'observed_yield_floor', 'calibration_transform': 'log1p',
                        'signed_log_residuals': {'__global__': signed, DEVICE: signed},
                        'signed_residual_weights': {'__global__': weights, DEVICE: weights},
                        'interval_log_scores': {'__global__': radii, DEVICE: radii},
                        'calibration_method': 'development_held_group_max_absolute_log_residuals',
                        'training_samples': int(fit.sum()), 'calibration_samples': int(cal.sum()),
                        'training_groups': len(set(groups[fit])), 'calibration_groups': len(set(groups[cal])),
                        'training_latest_start': max(r['run_start_time'] for r, keep in zip(selected, fit) if keep),
                        'development_latest_start': max(r['run_start_time'] for r in selected),
                        'plan_sha256': digest(args.output/'plan.json'),
                        'warning': 'MinION-only development candidate; independent accuracy, calibration and live feature parity remain unvalidated.'}
            path = models/f'calibrated_yield_{horizon}min.joblib'
            joblib.dump(artifact, path)
            # Check actual consumer serialization and scientific constraints.
            consumer = CalibratedYieldPredictor(models)
            for r, expected in zip([r for r, keep in zip(selected, cal) if keep], calibration_predictions):
                result = consumer.predict(r, horizon, (1., 5., 10.))
                json.dumps(result, allow_nan=False)
                if not math.isclose(result['point_prediction_gb'], float(expected), rel_tol=1e-10, abs_tol=1e-10):
                    raise ValueError('Training/consumer prediction mismatch')
            try:
                consumer.predict({**selected[0], 'device_type': 'PromethION 2 Solo'}, horizon)
            except ValueError:
                pass
            else:
                raise AssertionError('Non-MinION inference was not rejected')
            linear = []
            for r, keep in zip(selected, fit):
                if not keep:
                    continue
                try:
                    passed, time, duration = (float(r[k]) for k in ('observed_passed_bases','observed_through_seconds','planned_run_limit_hours'))
                    linear.append(passed/1e9/time*3600*duration if time>0 and duration>=time/3600 else np.nan)
                except (TypeError, ValueError):
                    linear.append(np.nan)
            linear = np.array(linear); common = np.isfinite(linear)
            record = {'horizon_minutes': horizon, 'chosen_config': config,
                      'fit_rows': int(fit.sum()), 'calibration_rows': int(cal.sum()),
                      'fit_groups': len(set(groups[fit])), 'calibration_groups': len(set(groups[cal])),
                      'selection_scores': scores, 'selected_fitting_cv_mae_gb': scores[winner]['run_mae_gb'],
                      'common_baseline_rows': int(common.sum()),
                      'selected_fitting_cv_mae_on_common_gb': float(np.mean(abs(oof[common]-y[fit][common]))) if common.any() else None,
                      'linear_mae_on_common_gb': float(np.mean(abs(linear[common]-y[fit][common]))) if common.any() else None,
                      'development_calibration_mae_gb': float(np.mean(abs(calibration_predictions-y[cal]))),
                      'calibration_radii': {k: v if math.isfinite(v) else None for k,v in radii.items()},
                      'artifact_sha256': digest(path)}
            results.append(record)
            print(horizon, config, 'fit', int(fit.sum()), 'calibration', int(cal.sum()), flush=True)
    for path, expected in source_hashes.items():
        if digest(Path(path)) != expected:
            raise ValueError('Source changed during training')
    assert bundled == {p.name: digest(p) for p in (ROOT/'src/nanopredict/data/models').glob('*.joblib')}
    dump(args.output/'manifest.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
         'status': 'Frozen development candidates for future qualification/evaluation; not promoted to bundled production models',
         'scope': 'MinION only; no PromethION fitting, tuning or calibration observations',
         'unique_minion_runs': len(groups_by_run), 'minion_checkpoint_rows': len(rows),
         'excluded_non_minion_checkpoint_rows': excluded, 'related_groups': len(fitting|calibration),
         'split_manifest_sha256': digest(args.output/'private_split_manifest.csv'),
         'plan_sha256': digest(args.output/'plan.json'), 'sklearn_version': sklearn.__version__,
         'runtime_predictor_sha256': digest(ROOT/'src/nanopredict/predict_calibrated.py'),
         'results': results, 'bundled_models_unchanged': True,
         'limitations': plan['limitations']})


if __name__ == '__main__':
    main()
