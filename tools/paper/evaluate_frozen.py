"""Score recorded predictions only. Never fit, select, or recalibrate a model."""
import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

METHODS = ('bundled', 'linear_planned', 'recent_planned', 'development_median', 'development_mean')


def stamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timezone required')
    return dt.timestamp()


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r)) or ['no_records']
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def validate(data):
    if data['schema'] != 'nanopredict-prospective-study-v1':
        raise ValueError('Use a prospective study export, not replay')
    manifest = data['freeze']
    if manifest.get('purpose', 'independent_evaluation') != 'independent_evaluation':
        raise ValueError('Non-study qualification exports cannot enter independent evaluation')
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, allow_nan=False).encode() + b'\n').hexdigest()
    if digest != data['freeze_sha256'] or tuple(manifest['methods']) != METHODS:
        raise ValueError('Invalid freeze or method set')
    if manifest['analysis_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Evaluation script differs from the frozen version')
    seen = set()
    for run in data['runs']:
        if run['run_code'] in seen or not run['group_code']:
            raise ValueError('Duplicate run or missing related-group code')
        seen.add(run['run_code'])
        checkpoints = set()
        for c in run['checkpoints']:
            if c['horizon_minutes'] in checkpoints or c['horizon_minutes'] not in (30,60,120) or c['freeze_sha256'] != digest:
                raise ValueError('Duplicate/invalid checkpoint or changed freeze')
            checkpoints.add(c['horizon_minutes'])
    return manifest


def exclusion(run, checkpoint, horizon, manifest):
    if run['eligibility'] != 'eligible': return 'protocol_excluded'
    if not run['independence_reviewed']: return 'independence_unreviewed'
    if stamp(run['started_utc']) <= stamp(manifest['frozen_at_utc']): return 'started_before_freeze'
    outcome = run.get('outcome')
    if not outcome: return 'outcome_not_recorded'
    if not outcome['predictions_hidden_confirmed']: return 'blinding_not_confirmed'
    end = stamp(outcome['ended_utc']); start = stamp(run['started_utc'])
    if end < start or stamp(outcome['outcome_available_utc']) < end: raise ValueError('Invalid outcome chronology')
    if end - start < horizon * 60: return 'ended_before_checkpoint'
    if outcome['final_passed_bases'] is None: return 'missing_final_yield'
    if not math.isfinite(outcome['final_passed_bases']) or outcome['final_passed_bases'] < 0: raise ValueError('Invalid final yield')
    if not checkpoint: return 'checkpoint_not_recorded'
    if checkpoint['status'] != 'recorded': return checkpoint['status']
    if checkpoint['predictions_shown_to_operator']: return 'predictions_visible'
    due = start + horizon * 60
    if stamp(run['enrolled_utc']) > due: return 'late_enrolment'
    if not due <= stamp(checkpoint['collected_at_utc']) <= stamp(checkpoint['source_available_at_utc']) <= stamp(checkpoint['prediction_ready_at_utc']) <= min(due + manifest['deadline_seconds'], end): return 'invalid_prediction_timing'
    observed = checkpoint['source_observed_through_seconds']
    if observed is None or not horizon * 60 - manifest['max_snapshot_age_seconds'] <= observed <= horizon * 60: return 'stale_or_future_input'
    if any(checkpoint['predictions'].get(m) is None for m in METHODS): return 'comparator_unavailable'
    return None


def point_stats(rows, method):
    actual = np.array([r['actual_gb'] for r in rows]); preds = [r['predictions'][method] for r in rows]
    points = np.array([p['point_prediction_gb'] for p in preds])
    if not np.isfinite(points).all() or (points < 0).any(): raise ValueError('Invalid point prediction')
    error = points - actual
    stats = {'mae_gb': float(abs(error).mean()), 'rmse_gb': float(np.sqrt((error**2).mean())),
             'bias_gb': float(error.mean()), 'median_ae_gb': float(np.median(abs(error)))}
    for c in (80,90,95):
        bounds = [p['prediction_intervals'][str(c)] for p in preds]
        lo = np.array([v['lower_gb'] for v in bounds]); hi = np.array([math.inf if v.get('unbounded') else v['upper_gb'] for v in bounds], dtype=float)
        if not np.isfinite(lo).all() or np.isnan(hi).any() or (lo < 0).any() or (hi < lo).any(): raise ValueError('Invalid interval')
        width = hi-lo; alpha = 1-c/100
        stats.update({f'coverage_{c}': float(((lo<=actual)&(actual<=hi)).mean()), f'width_{c}_gb': float(width.mean()),
                      f'interval_score_{c}': float((width+2/alpha*(np.maximum(lo-actual,0)+np.maximum(actual-hi,0))).mean())})
    return stats


def wilson(successes, total):
    """95% Wilson interval for independent group-level binary coverage indicators."""
    z=1.959963984540054; rate=successes/total; denominator=1+z*z/total
    center=(rate+z*z/(2*total))/denominator
    half=z*math.sqrt(rate*(1-rate)/total+z*z/(4*total*total))/denominator
    return max(0.,center-half), min(1.,center+half)


def analyze(data):
    manifest = validate(data); results=[]; flow=[]; pairs=[]; probability=[]
    for h in (30,60,120):
        selected=[]
        for run in data['runs']:
            cp = next((c for c in run['checkpoints'] if c['horizon_minutes']==h),None)
            reason=exclusion(run,cp,h,manifest)
            flow.append({'run_code':run['run_code'],'group_code':run['group_code'],'horizon_minutes':h,
                         'included':reason is None,'reason':reason or 'included','end_reason':(run.get('outcome') or {}).get('end_reason','unrecorded')})
            if reason is None:
                selected.append({'run_code':run['run_code'],'group_code':run['group_code'],'actual_gb':run['outcome']['final_passed_bases']/1e9,
                                 'end_reason':run['outcome']['end_reason'],'predictions':cp['predictions']})
        strata=['all']+sorted({r['end_reason'] for r in selected})
        for stratum in strata:
            rows=[r for r in selected if stratum=='all' or r['end_reason']==stratum]
            if not rows: continue
            groups=sorted({r['group_code'] for r in rows}); rng=np.random.default_rng(manifest['bootstrap_seed'])
            # Shared group draws yield paired uncertainty across methods; one horizon at a time.
            draws=rng.integers(len(groups),size=(manifest['bootstrap_replicates'],len(groups)))
            group_rows=[[r for r in rows if r['group_code']==g] for g in groups]
            samples=[[r for i in draw for r in group_rows[i]] for draw in draws]
            method_values={m:point_stats(rows,m) for m in METHODS}
            bootstrap={m:[point_stats(sample,m) for sample in samples] for m in METHODS}
            for method in METHODS:
                output={'horizon_minutes':h,'stratum':stratum,'method':method,'n_runs':len(rows),'n_groups':len(groups),**method_values[method]}
                for metric,value in method_values[method].items():
                    values=np.array([s[metric] for s in bootstrap[method]])
                    if len(groups)>=2 and np.isfinite(values).all():
                        lower,upper=np.quantile(values,[.025,.975])
                    else: lower=upper=''  # do not fabricate precision for a single group/unbounded widths
                    output[metric+'_ci_low']=lower; output[metric+'_ci_high']=upper
                for c in (80,90,95):
                    output[f'n_unbounded_{c}']=sum(r['predictions'][method]['prediction_intervals'][str(c)].get('unbounded',False) for r in rows)
                    covered_groups=0
                    for related in group_rows:
                        covered=True
                        for r in related:
                            bounds=r['predictions'][method]['prediction_intervals'][str(c)]
                            upper=math.inf if bounds.get('unbounded') else bounds['upper_gb']
                            covered=covered and bounds['lower_gb']<=r['actual_gb']<=upper
                        covered_groups+=covered
                    output[f'group_joint_coverage_{c}']=covered_groups/len(groups)
                    output[f'group_joint_coverage_{c}_wilson_low'],output[f'group_joint_coverage_{c}_wilson_high']=wilson(covered_groups,len(groups))
                results.append(output)
                delta=np.array([s['mae_gb'] for s in bootstrap[method]])-np.array([s['mae_gb'] for s in bootstrap['linear_planned']])
                pairs.append({'horizon_minutes':h,'stratum':stratum,'method':method,'reference':'linear_planned','n_runs':len(rows),
                              'delta_mae_gb':method_values[method]['mae_gb']-method_values['linear_planned']['mae_gb'],
                              'ci_low':np.quantile(delta,.025) if len(groups)>=2 else '', 'ci_high':np.quantile(delta,.975) if len(groups)>=2 else ''})
                for target in manifest['thresholds_gb']:
                    probs=[r['predictions'][method]['threshold_probabilities'].get(str(target)) for r in rows]
                    if any(p is None for p in probs): continue
                    probs=np.asarray(probs,dtype=float)
                    if not np.isfinite(probs).all() or ((probs<0)|(probs>1)).any(): raise ValueError('Invalid probability')
                    actual=np.array([r['actual_gb']>=target for r in rows]); losses=(probs-actual)**2
                    prob_index={id(r):i for i,r in enumerate(rows)}
                    boot=[float(np.mean([losses[prob_index[id(r)]] for r in sample])) for sample in samples]
                    probability.append({'row_type':'score','horizon_minutes':h,'stratum':stratum,'method':method,'target_gb':target,'n_runs':len(rows),'n_events':int(actual.sum()),
                                        'brier':float(losses.mean()),'ci_low':np.quantile(boot,.025) if len(groups)>=2 else '', 'ci_high':np.quantile(boot,.975) if len(groups)>=2 else ''})
                    for low,high in zip(np.linspace(0,1,6)[:-1],np.linspace(0,1,6)[1:]):
                        mask=(probs>=low)&((probs<high)|(high==1))
                        if mask.any():
                            probability.append({'row_type':'reliability','horizon_minutes':h,'stratum':stratum,'method':method,'target_gb':target,
                                'bin_low':low,'bin_high':high,'n_runs':int(mask.sum()),'n_events':int(actual[mask].sum()),
                                'mean_probability':float(probs[mask].mean()),'observed_fraction':float(actual[mask].mean())})
    return results,flow,pairs,probability


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--study-export',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); data=json.loads(a.study_export.read_text()); results=analyze(data)
    a.output.mkdir(parents=True,exist_ok=False)
    for name,rows in zip(('metrics','eligibility_flow','paired_comparisons','probabilities'),results): write_csv(a.output/f'{name}.csv',rows)
    (a.output/'metadata.json').write_text(json.dumps({'input_sha256':hashlib.sha256(a.study_export.read_bytes()).hexdigest(),
         'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'freeze_sha256':data['freeze_sha256'],
         'evidence':'Recorded prospective predictions; independence, clock fidelity and recruitment assertions require external verification',
         'limits':'Same common eligible run set across all methods at each horizon. Related-group percentile bootstrap, not a guarantee with a small pilot. No fitting or recalibration.'},indent=2)+'\n')


if __name__=='__main__': main()
