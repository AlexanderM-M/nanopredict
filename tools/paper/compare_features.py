"""Compare matched live/historical numerical features and report timing/definition gaps."""
import argparse
import csv
import math
from datetime import datetime
from pathlib import Path

FIELDS = ('run_code','horizon_minutes','feature','value','unit','definition_id','observed_through_seconds','available_at_utc','checkpoint_at_utc')


def load(path):
    with path.open() as handle:
        reader=csv.DictReader(handle)
        if not set(FIELDS)<=set(reader.fieldnames or []): raise ValueError('Missing feature schema columns')
        rows={}
        for row in reader:
            key=tuple(row[k] for k in FIELDS[:3])
            if key in rows or not all(key): raise ValueError('Duplicate or missing feature key')
            rows[key]=row
    return rows


def number(text):
    if text=='': return None
    value=float(text)
    if not math.isfinite(value): raise ValueError('Nonfinite feature')
    return value


def timestamp(text):
    if not text: return None
    value=datetime.fromisoformat(text.replace('Z','+00:00'))
    if value.tzinfo is None: raise ValueError('Timezone required')
    return value.timestamp()


def compare(left,right,atol,rtol):
    if not left or left.keys()!=right.keys(): raise ValueError('Feature keys must match; missing values require explicit empty cells')
    output=[]
    for key in sorted(left):
        a,b=left[key],right[key]; x,y=number(a['value']),number(b['value'])
        same_definition=bool(a['definition_id']) and a['definition_id']==b['definition_id'] and a['definition_id']!='UNVERIFIED' and a['unit']==b['unit']
        result=dict(zip(FIELDS[:3],key)); result.update(live_value=x,historical_value=y,definition_agrees=same_definition,
            missingness_disagrees=(x is None)!=(y is None),absolute_difference=abs(x-y) if x is not None and y is not None else '',
            within_numeric_tolerance=math.isclose(x,y,abs_tol=atol,rel_tol=rtol) if x is not None and y is not None else '')
        for name,r in [('live',a),('historical',b)]:
            checkpoint=timestamp(r['checkpoint_at_utc']); available=timestamp(r['available_at_utc']); observed=number(r['observed_through_seconds'])
            result[name+'_availability_lag_seconds']=available-checkpoint if available is not None and checkpoint is not None else ''
            result[name+'_availability_known']=available is not None and checkpoint is not None
            result[name+'_future_observation']=observed>int(key[1])*60 if observed is not None else ''
        result['checkpoint_time_agrees']=a['checkpoint_at_utc']==b['checkpoint_at_utc']
        # Numeric agreement is never promoted to proof of historical real-time availability.
        output.append(result)
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--live',type=Path,required=True); p.add_argument('--historical',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--atol',type=float,default=0); p.add_argument('--rtol',type=float,default=0)
    a=p.parse_args()
    if not math.isfinite(a.atol) or not math.isfinite(a.rtol) or min(a.atol,a.rtol)<0: p.error('Tolerances must be finite and nonnegative')
    rows=compare(load(a.live),load(a.historical),a.atol,a.rtol)
    with a.output.open('x',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=rows[0]); w.writeheader(); w.writerows(rows)


if __name__=='__main__': main()
