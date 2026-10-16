"""Export the exact frozen-model input values in the matched-feature comparison schema."""
import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--study-export',type=Path,required=True)
    p.add_argument('--contract',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); study=json.loads(a.study_export.read_text()); contract=json.loads(a.contract.read_text())
    fields=['run_code','horizon_minutes','feature','value','unit','definition_id','observed_through_seconds','available_at_utc','checkpoint_at_utc']
    with a.output.open('x',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader()
        for run in study['runs']:
            for cp in run['checkpoints']:
                h=cp['horizon_minutes']; due=datetime.fromisoformat(run['started_utc'].replace('Z','+00:00'))+timedelta(minutes=h)
                for name,value in cp['features'].items():
                    if name not in contract: raise ValueError('Contract must specify all exported features')
                    writer.writerow(dict(run_code=run['run_code'],horizon_minutes=h,feature=name,value=value,unit=contract[name]['unit'],
                        definition_id=contract[name]['definition_id'],observed_through_seconds=cp['source_observed_through_seconds'],
                        available_at_utc=cp['source_available_at_utc'],checkpoint_at_utc=due.isoformat()))


if __name__=='__main__': main()
