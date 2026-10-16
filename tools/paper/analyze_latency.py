"""Summarize measured event timestamps; no latency inferred from replay speed."""
import argparse
import csv
from datetime import datetime
from pathlib import Path

import numpy as np

STAGES=('source_event_utc','bam_completed_utc','discovered_utc','processed_utc','displayed_utc')


def analyze(rows):
    result=[]; keys=set()
    for row in rows:
        key=(row['run_code'],row['barcode'],row['batch_id'])
        if key in keys: raise ValueError('Duplicate event boundary')
        keys.add(key); times=[]
        for field in STAGES:
            dt=datetime.fromisoformat(row[field].replace('Z','+00:00'))
            if dt.tzinfo is None: raise ValueError('Timezone required')
            times.append(dt.timestamp())
        if any(b<a for a,b in zip(times,times[1:])): raise ValueError('Negative latency; resolve clocks or event ordering')
        result.append({'run_code':key[0],'barcode':key[1],'batch_id':key[2],
                       **{a+'_to_'+b:tb-ta for a,b,ta,tb in zip(STAGES,STAGES[1:],times,times[1:])},
                       'end_to_end_seconds':times[-1]-times[0]})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--events',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    with a.events.open() as handle: rows=analyze(list(csv.DictReader(handle)))
    if not rows: raise ValueError('No measured events')
    a.output.mkdir(parents=True,exist_ok=False)
    with (a.output/'events.csv').open('w',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=rows[0]); w.writeheader(); w.writerows(rows)
    with (a.output/'summary.csv').open('w',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=['stage','n','median_seconds','p95_seconds','max_seconds']); w.writeheader()
        for key in list(rows[0])[3:]:
            values=[r[key] for r in rows]; w.writerow({'stage':key,'n':len(values),'median_seconds':np.median(values),'p95_seconds':np.quantile(values,.95),'max_seconds':max(values)})


if __name__=='__main__': main()
