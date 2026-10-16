"""Render recorded-study estimates; claims of independence still require evidence review."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--results',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    with (a.results/'metrics.csv').open() as handle: rows=[r for r in csv.DictReader(handle) if r.get('stratum')=='all']
    if not rows: raise ValueError('No eligible recorded comparisons; cannot invent a figure')
    meta=json.loads((a.results/'metadata.json').read_text()); a.output.mkdir(parents=True,exist_ok=False)
    fig,axes=plt.subplots(1,2,figsize=(9,4))
    for method in dict.fromkeys(r['method'] for r in rows):
        records=[r for r in rows if r['method']==method]
        for ax,metric in zip(axes,('mae_gb','coverage_90')):
            x=np.array([int(r['horizon_minutes']) for r in records]); y=np.array([float(r[metric]) for r in records])
            ax.plot(x,y,'o-',label=method)
            for xx,yy,r in zip(x,y,records):
                if r.get(metric+'_ci_low') and r.get(metric+'_ci_high'):
                    low,high=float(r[metric+'_ci_low']),float(r[metric+'_ci_high'])
                    # Percentile intervals need not contain the point estimate.
                    ax.vlines(xx,low,high,alpha=.6)
    axes[0].set(ylabel='MAE (Gb)',xlabel='Checkpoint (min)',title='Same eligible runs across methods')
    axes[1].set(ylabel='Empirical 90% coverage',xlabel='Checkpoint (min)',ylim=(0,1.05),title='Includes unbounded intervals')
    axes[1].axhline(.9,color='black',linestyle='--')
    fig.suptitle('Recorded study estimates — independence review required',fontsize=11)
    fig.legend(*axes[0].get_legend_handles_labels(),loc='lower center',fontsize=7,ncol=5)
    fig.tight_layout(rect=(0,.12,1,.93))
    for ext in ('pdf','png'): fig.savefig(a.output/f'frozen_evaluation.{ext}',dpi=350)
    plt.close(fig)
    (a.output/'caption.txt').write_text('Common eligible runs at each horizon; group bootstrap 95% intervals where available. Consult metrics.csv for denominators, unbounded intervals and separately labelled joint-group Wilson coverage intervals. These plots do not establish independence of recruitment or feature timing. Source freeze: '+meta['freeze_sha256']+'\n')


if __name__=='__main__': main()
