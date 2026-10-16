"""Render benchmark CSVs into a labelled table and figure without inventing results."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    meta=json.loads((a.results/'metadata.json').read_text())
    with (a.results/'metrics.csv').open() as handle:
        rows=list(csv.DictReader(handle))
    with (a.results/'predictions.csv').open() as handle:
        preds=list(csv.DictReader(handle))
    a.output.mkdir(parents=True,exist_ok=True)
    selected=[r for r in rows if r['scope']=='common' and int(r['n_predicted'])>0]
    if not selected:
        raise ValueError('No common evaluable observations; no comparative figure generated')
    table=[f"# {meta['evidence_label']}",'','All methods use the same complete-case comparison set at each horizon. Native availability is in metrics.csv.','',
           '| Minutes | Method | N | MAE Gb | RMSE Gb | 90% coverage | Mean width Gb | Unbounded 90% intervals |',
           '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in selected:
        table.append('| '+ ' | '.join([r['horizon_minutes'],r['method'],r['n_predicted'],*[f"{float(r[k]):.3f}" for k in ('mae_gb','rmse_gb','coverage_90','mean_width_90_gb')],r['unbounded_intervals_90']])+' |')
    table.extend(['', 'Unbounded intervals are vacuous and contribute to empirical coverage. High coverage alone is not calibration evidence.'])
    (a.output/'benchmark_table.md').write_text('\n'.join(table)+'\n')
    fig,ax=plt.subplots(1,3,figsize=(12,3.8))
    methods=meta['methods']
    for method in methods:
        rr=[r for r in selected if r['method']==method]
        ax[0].plot([int(r['horizon_minutes']) for r in rr],[float(r['mae_gb']) for r in rr],marker='o',label=method)
        ax[1].plot([int(r['horizon_minutes']) for r in rr],[float(r['coverage_90']) for r in rr],marker='o')
    ax[0].set(ylabel='MAE (Gb)',xlabel='Checkpoint (min)',title='A  Common-case point error')
    ax[1].axhline(.9,color='black',linestyle='--'); ax[1].set(ylabel='Empirical 90% coverage',xlabel='Checkpoint (min)',ylim=(0,1.05),title='B  Coverage (includes unbounded)')
    threshold=meta['thresholds_gb'][0]
    reliability=[]
    for method in methods:
        rr=[r for r in preds if r['method']==method and r['horizon_minutes']=='120' and r.get(f'probability_{threshold:g}')]
        for left,right in zip(np.linspace(0,1,6)[:-1],np.linspace(0,1,6)[1:]):
            bb=[r for r in rr if left<=float(r[f'probability_{threshold:g}']) and (float(r[f'probability_{threshold:g}'])<right or right==1)]
            if bb:
                reliability.append(dict(method=method,horizon_minutes=120,threshold_gb=threshold,bin_left=left,bin_right=right,n=len(bb),mean_probability=np.mean([float(r[f'probability_{threshold:g}']) for r in bb]),observed_frequency=np.mean([float(r['actual_gb'])>=threshold for r in bb])))
        points=[r for r in reliability if r['method']==method]
        ax[2].plot([r['mean_probability'] for r in points],[r['observed_frequency'] for r in points],marker='o')
    ax[2].plot([0,1],[0,1],color='black',linestyle='--'); ax[2].set(xlabel='Predicted probability',ylabel='Observed fraction',title=f'C  120 min, target {threshold:g} Gb',xlim=(0,1),ylim=(0,1))
    fig.suptitle(meta['evidence_label'],fontsize=10)
    fig.legend(*ax[0].get_legend_handles_labels(),loc='lower center',ncol=6,fontsize=8)
    fig.tight_layout(rect=(0,.12,1,.90))
    for suffix in ('pdf','png'):
        fig.savefig(a.output/f'benchmark.{suffix}',dpi=350)
    if reliability:
        with (a.output/'reliability.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=reliability[0]); w.writeheader(); w.writerows(reliability)
    plt.close(fig)


if __name__=='__main__': main()
