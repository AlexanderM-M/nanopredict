"""Inventory repository evidence; never score bundled models."""
import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'src/nanopredict/data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with (DATA / 'replay_features_anonymous.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    models = []
    for path in sorted((DATA / 'models').glob('*.joblib')):
        a = joblib.load(path)  # Trusted, cloned project assets only.
        models.append({
            'file': path.name, 'sha256': sha(path),
            **{k: v for k, v in a.items() if k not in ('model', 'signed_log_residuals')},
            'pipeline': repr(a['model']),
            'residual_counts': {k: len(v) for k, v in a['signed_log_residuals'].items()},
        })
    groups = {}
    for row in rows:
        groups.setdefault(row['sample_label'], []).append(row)
    fields = []
    for col in rows[0]:
        values = [r[col] for r in rows if r[col] != '']
        numeric = []
        try:
            numeric = [float(v) for v in values]
        except ValueError:
            pass
        fields.append({'field': col, 'missing': len(rows)-len(values),
                       'unique_nonmissing': len(set(values)),
                       'minimum': min(numeric) if numeric else None,
                       'maximum': max(numeric) if numeric else None})
    reference = json.loads((DATA / 'diagnostic_reference.json').read_text())
    inventory = {
        'base_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'replay': {'rows': len(rows), 'anonymous_labels': len(groups),
                   'devices': dict(Counter(r['device_type'] for r in rows)),
                   'horizons': dict(Counter(r['horizon_minutes'] for r in rows)),
                   'group_horizon_patterns': dict(Counter(','.join(sorted(r['horizon_minutes'] for r in rr)) for rr in groups.values())),
                   'inconsistent_outcome_labels': [g for g, rr in groups.items() if len({r['target_final_passed_bases'] for r in rr}) != 1],
                   'zero_outcome_labels': sum(float(rr[0]['target_final_passed_bases']) == 0 for rr in groups.values()),
                   'fields': fields,
                   'split_limitations': 'No dates, original run IDs, sample/flow-cell linkage, stop reasons or observed final durations. Anonymous labels support exploratory within-label grouping only.'},
        'models': models,
        'diagnostic_reference': {'source': reference['source'], 'generated_utc': reference['generated_utc'],
                                 'group_counts': {k: v['run_count'] for k,v in reference['references'].items()}},
        'files': [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': sha(p)}
                  for p in sorted(DATA.rglob('*')) if p.is_file()],
        'historical_analysis': 'Not included in git checkout; a bounded depth-3 search of the current home and GPFS user directories did not locate nanoprediction. This is not an exhaustive cluster search.',
    }
    (args.output / 'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
    with (args.output / 'replay_fields.csv').open('w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=fields[0]); w.writeheader(); w.writerows(fields)
    print(f"Inventoried {len(rows)} snapshots, {len(groups)} labels, {len(models)} artifacts")


if __name__ == '__main__':
    main()
