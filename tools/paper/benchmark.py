"""Retrain exploratory models or use an explicit held-out split; no bundled model scoring."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / 'src/nanopredict/data/replay_features_anonymous.csv'
# Explicit allow-list: IDs, dates, outcomes and actual final durations are never features.
with REPLAY.open() as _feature_file:
    FEATURES = tuple(next(csv.reader(_feature_file)))[4:]
COVERAGES = (80, 90, 95)
METHODS = ('train_median', 'train_mean', 'linear_planned', 'recent_planned', 'ridge', 'extra_trees')


def number(x):
    if x is None or x == '':
        return np.nan
    value = float(x)
    if not math.isfinite(value):
        raise ValueError('Non-finite numeric input; use an empty cell for missing values')
    return value


def read_data(path):
    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError('Empty input')
    required = {'sample_label', 'device_type', 'horizon_minutes', 'target_final_passed_bases', *FEATURES}
    if required - rows[0].keys():
        raise ValueError(f'Missing columns: {sorted(required - rows[0].keys())}')
    keys = set()
    outcomes = {}
    for row in rows:
        key = (row['sample_label'], int(row['horizon_minutes']))
        if not key[0] or key in keys or key[1] not in (30,60,120):
            raise ValueError('Require a unique nonempty run label per 30/60/120-minute checkpoint')
        keys.add(key)
        y = number(row['target_final_passed_bases'])
        if not np.isfinite(y) or y < 0:
            raise ValueError('Outcome must be observed, finite and nonnegative')
        if key[0] in outcomes and outcomes[key[0]] != y:
            raise ValueError('Inconsistent outcome within run')
        outcomes[key[0]] = y
        t = number(row['observed_through_seconds'])
        if not np.isfinite(t) or not 0 < t <= key[1]*60:
            raise ValueError('Observation time must be positive and no later than checkpoint')
        for f in FEATURES:
            number(row[f])
        row['group_id'] = key[0]
    return rows


def utc(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Split timestamps must include timezone')
    return dt


def manifest_split(rows, path):
    with path.open() as handle:
        manifest = list(csv.DictReader(handle))
    by_label = {r['sample_label']: r for r in manifest}
    if len(by_label) != len(manifest) or set(by_label) != {r['sample_label'] for r in rows}:
        raise ValueError('Manifest must contain exactly one entry for every run label')
    partitions = {name: set() for name in ('train','calibration','test')}
    starts = {name: [] for name in partitions}
    ends = {name: [] for name in partitions}
    for label, item in by_label.items():
        name = item['partition']
        if name not in partitions or not item['group_id'] or item['timing_verified'] != 'true':
            raise ValueError('Require known partition, group_id and timing_verified=true')
        start, end = utc(item['run_start_utc']), utc(item['outcome_available_utc'])
        if end < start:
            raise ValueError('Outcome available before run start')
        partitions[name].add(item['group_id']); starts[name].append(start); ends[name].append(end)
    if any(not g for g in partitions.values()):
        raise ValueError('All three partitions are required')
    if any(partitions[a] & partitions[b] for a,b in [('train','calibration'),('train','test'),('calibration','test')]):
        raise ValueError('Related groups overlap partitions')
    if max(ends['train']) >= min(starts['calibration']) or max(ends['calibration']) >= min(starts['test']):
        raise ValueError('Chronology requires training outcomes before calibration starts and calibration outcomes before test starts')
    for row in rows:
        row['group_id'] = by_label[row['sample_label']]['group_id']
    return [partitions]


def exploratory_splits(rows, folds, seed):
    groups = np.array(sorted({r['group_id'] for r in rows}))
    if folds < 2 or len(groups) < folds*2:
        raise ValueError('Insufficient groups for requested folds')
    rng = np.random.default_rng(seed)
    groups = rng.permutation(groups)
    result = []
    for test in np.array_split(groups, folds):
        remaining = rng.permutation(np.array(sorted(set(groups)-set(test))))
        ncal = max(1, math.ceil(len(remaining)*0.25))
        result.append({'test': set(test), 'calibration': set(remaining[:ncal]), 'train': set(remaining[ncal:])})
    return result


def matrix(rows):
    return np.array([[number(r[f]) for f in FEATURES] for r in rows])


def outcome(rows):
    return np.array([number(r['target_final_passed_bases'])/1e9 for r in rows])


def baseline(rows, method, constant=None):
    if method in ('train_mean', 'train_median'):
        return np.full(len(rows), constant)
    pred=[]
    for row in rows:
        passed=number(row['observed_passed_bases'])/1e9
        elapsed=number(row['observed_through_seconds'])/3600
        planned=number(row['planned_run_limit_hours'])
        rate=passed/elapsed if method=='linear_planned' else number(row['observed_recent_passed_bases_per_hour'])/1e9
        valid = np.isfinite([passed, elapsed, planned, rate]).all() and passed >= 0 and planned >= elapsed and rate >= 0
        pred.append(passed + rate*(planned-elapsed) if valid else np.nan)
    return np.array(pred)


def fit_predict(train, calibration, test, method, seed):
    y=outcome(train)
    if method in ('train_mean','train_median','linear_planned','recent_planned'):
        c = float(np.median(y)) if method=='train_median' else float(np.mean(y))
        return baseline(calibration,method,c),baseline(test,method,c)
    imputer=SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)
    # Fixed configurations: no tuning or model selection using outer test outcomes.
    estimator = make_pipeline(imputer, StandardScaler(), Ridge(alpha=100.0)) if method=='ridge' else make_pipeline(imputer,ExtraTreesRegressor(n_estimators=200,min_samples_leaf=3,max_features=0.8,n_jobs=1,random_state=seed))
    estimator.fit(matrix(train), y)
    return np.maximum(estimator.predict(matrix(calibration)),0),np.maximum(estimator.predict(matrix(test)),0)


def conformal_radius(scores, coverage):
    n=len(scores)
    rank=math.ceil((n+1)*coverage/100)
    return float(np.sort(scores)[rank-1]) if 0 < rank <= n else math.inf


def calibrate(rows, predictions):
    residuals = {}
    for row,y,p in zip(rows,outcome(rows),predictions):
        if np.isfinite(p):
            residuals.setdefault(row['group_id'],[]).append(float(np.log1p(y)-np.log1p(p)))
    # Max score per related group protects all its run outcomes at this horizon.
    scores=[max(abs(x) for x in rr) for rr in residuals.values()]
    # Probability estimator is group-weighted empirical residual mixing, not a calibration guarantee.
    signed=[(r,1/len(rr)) for rr in residuals.values() for r in rr]
    return scores,signed


def evaluate(rows, splits, seed, thresholds):
    predictions=[]; assignments=[]
    for fold,split in enumerate(splits):
        for partition,groups in split.items():
            assignments.extend({'fold':fold,'group_id':g,'partition':partition} for g in sorted(groups))
        for horizon in (30,60,120):
            subset=[r for r in rows if int(r['horizon_minutes'])==horizon]
            parts={p:[r for r in subset if r['group_id'] in groups] for p,groups in split.items()}
            if any(not rr for rr in parts.values()):
                raise ValueError(f'Empty partition at horizon {horizon}; cannot silently drop it')
            for method in METHODS:
                cp,tp=fit_predict(parts['train'],parts['calibration'],parts['test'],method,seed+fold)
                scores,signed=calibrate(parts['calibration'],cp)
                for row,p,y in zip(parts['test'],tp,outcome(parts['test'])):
                    rec={'fold':fold,'sample_label':row['sample_label'],'group_id':row['group_id'],
                         'horizon_minutes':horizon,'method':method,'actual_gb':y,'prediction_gb':p,
                         'calibration_groups':len(scores)}
                    for coverage in COVERAGES:
                        q=conformal_radius(scores,coverage)
                        lo=max(float(np.expm1(np.log1p(p)-q)),0) if np.isfinite(p) else np.nan
                        with np.errstate(over='ignore'):
                            hi=float(np.expm1(np.log1p(p)+q)) if np.isfinite(p) else np.nan
                        rec[f'lower_{coverage}']=lo; rec[f'upper_{coverage}']=hi
                    for threshold in thresholds:
                        success=sum(w for r,w in signed if r >= np.log1p(threshold)-np.log1p(p))
                        rec[f'probability_{threshold:g}']=(success+1)/(len(scores)+2) if scores and np.isfinite(p) else np.nan
                    predictions.append(rec)
    return predictions,assignments


def summarize(predictions, thresholds, seed, bootstrap=1000):
    metrics=[]
    for horizon in (30,60,120):
        rr=[r for r in predictions if r['horizon_minutes']==horizon]
        available={m:{(r['fold'],r['sample_label']) for r in rr if r['method']==m and np.isfinite(r['prediction_gb'])} for m in METHODS}
        common=set.intersection(*available.values())
        for method in METHODS:
            allrows=[r for r in rr if r['method']==method]
            for scope in ('available','common'):
                selected=[r for r in allrows if np.isfinite(r['prediction_gb']) and (scope=='available' or (r['fold'],r['sample_label']) in common)]
                stat={'horizon_minutes':horizon,'method':method,'scope':scope,'n_eligible':len(allrows),'n_predicted':len(selected)}
                if selected:
                    y=np.array([r['actual_gb'] for r in selected]); p=np.array([r['prediction_gb'] for r in selected]); error=p-y
                    stat.update(mae_gb=float(np.mean(abs(error))),rmse_gb=float(np.sqrt(np.mean(error**2))),bias_gb=float(np.mean(error)),median_ae_gb=float(np.median(abs(error))),rmsle=float(np.sqrt(np.mean((np.log1p(p)-np.log1p(y))**2))))
                    groups=sorted({r['group_id'] for r in selected})
                    sums=np.array([sum(abs(r['prediction_gb']-r['actual_gb']) for r in selected if r['group_id']==g) for g in groups])
                    counts=np.array([sum(r['group_id']==g for r in selected) for g in groups])
                    rng=np.random.default_rng(seed)
                    draws=rng.integers(len(groups),size=(bootstrap,len(groups)))
                    ci=np.quantile(sums[draws].sum(axis=1)/counts[draws].sum(axis=1),[.025,.975])
                    stat.update(mae_ci_low=ci[0],mae_ci_high=ci[1],n_groups=len(groups))
                    for c in COVERAGES:
                        lo=np.array([r[f'lower_{c}'] for r in selected]); hi=np.array([r[f'upper_{c}'] for r in selected]); alpha=1-c/100
                        width=hi-lo
                        score=width+2/alpha*np.maximum(lo-y,0)+2/alpha*np.maximum(y-hi,0)
                        stat.update({f'coverage_{c}':float(np.mean((lo<=y)&(y<=hi))),f'mean_width_{c}_gb':float(np.mean(width)),f'interval_score_{c}':float(np.mean(score)),f'unbounded_intervals_{c}':int(np.sum(~np.isfinite(hi)))})
                    for t in thresholds:
                        prob=np.array([r[f'probability_{t:g}'] for r in selected]); valid=np.isfinite(prob)
                        stat[f'brier_{t:g}']=float(np.mean((prob[valid]-(y[valid]>=t))**2)) if valid.any() else np.nan
                        stat[f'n_probability_{t:g}']=int(valid.sum())
                        stat[f'n_events_{t:g}']=int(np.sum(y[valid]>=t))
                metrics.append(stat)
    return metrics


def write_csv(path, rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        w.writerows({k:('' if isinstance(v,(float,np.floating)) and np.isnan(v) else v) for k,v in row.items()} for row in rows)


def reject_development_overlap(rows):
    """Reject known replay observations even when relabelled, reordered or reformatted."""
    def key(row):
        return (int(row['horizon_minutes']), tuple(None if row[f] == '' else float(row[f]) for f in FEATURES))
    known = {key(r) for r in read_data(REPLAY)}
    if any(key(r) in known for r in rows):
        raise ValueError('Previously inspected replay observations are development evidence, not a reserved test cohort')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=REPLAY)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--split-manifest',type=Path)
    parser.add_argument('--folds',type=int,default=5)
    parser.add_argument('--seed',type=int,default=20261008)
    parser.add_argument('--threshold-gb',action='append',type=float)
    args=parser.parse_args()
    thresholds=args.threshold_gb or [1.,5.,10.]
    if any(not math.isfinite(t) or t<=0 for t in thresholds):
        parser.error('Thresholds must be positive and finite')
    rows=read_data(args.data)
    if args.split_manifest:
        reject_development_overlap(rows)
        if hashlib.sha256(args.data.read_bytes()).digest()==hashlib.sha256(REPLAY.read_bytes()).digest():
            parser.error('Anonymous packaged replay has no verified chronological metadata; use exploratory folds')
        splits=manifest_split(rows,args.split_manifest)
        label='HELD-OUT RETRAINING: independence and provenance require external review'
    else:
        splits=exploratory_splits(rows,args.folds,args.seed)
        label='EXPLORATORY anonymous-group cross-validation; NOT independent validation'
    args.output.mkdir(parents=True,exist_ok=True)
    preds,assignments=evaluate(rows,splits,args.seed,thresholds)
    write_csv(args.output/'predictions.csv',preds)
    write_csv(args.output/'split_assignments.csv',assignments)
    write_csv(args.output/'metrics.csv',summarize(preds,thresholds,args.seed))
    metadata={'evidence_label':label,'seed':args.seed,'thresholds_gb':thresholds,'features':FEATURES,'methods':METHODS,
              'data_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),
              'benchmark_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'split_manifest_sha256':hashlib.sha256(args.split_manifest.read_bytes()).hexdigest() if args.split_manifest else None,
              'python':platform.python_version(),'numpy':np.__version__,'sklearn':sklearn.__version__,
              'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'configuration':'25% outer-development groups held for calibration; fixed Ridge alpha=100; ExtraTrees 200 trees leaf=3 max_features=0.8; group bootstrap 1000 draws conditional on fitted folds',
              'limitations':['Unknown cross-run relationships in anonymous data','No historical timing parity proof','Observed final yield is subject to stopping decisions','Intervals require exchangeability; chronological shift can break coverage','No bundled models loaded or evaluated']}
    (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(label)


if __name__=='__main__':
    main()
