"""Reconcile final report yields against complete sequencing summaries.

Streams each summary once, hashes its bytes, checks row identities, and reports
all disagreements. Does not load models or calculate prediction performance.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def parse_bool(value):
    if value.lower() in ('true', '1'):
        return True
    if value.lower() in ('false', '0'):
        return False
    raise ValueError('Invalid passes_filtering value')


def summarize(path, allowed_run_ids):
    digest = hashlib.sha256()
    seen = set()
    total = passed_reads = failed_reads = passed_bases = failed_bases = 0
    duplicates = wrong_run = missing_id = 0
    types = Counter()
    before = path.stat()
    with path.open('rb') as handle:
        def lines():
            for line in handle:
                digest.update(line)
                yield line.decode('utf-8')
        reader = csv.reader(lines(), delimiter='\t')
        columns = next(reader)
        if len(columns) != len(set(columns)):
            raise ValueError('Duplicate summary columns')
        required = ('read_id', 'run_id', 'passes_filtering', 'sequence_length_template')
        if any(key not in columns for key in required):
            raise ValueError('Missing required sequencing-summary columns')
        index = {key: columns.index(key) for key in required}
        type_index = columns.index('type') if 'type' in columns else None
        for row in reader:
            if len(row) != len(columns):
                raise ValueError('Malformed sequencing-summary row')
            read_id = row[index['read_id']]
            if not read_id:
                missing_id += 1
            elif read_id in seen:
                duplicates += 1
            else:
                seen.add(read_id)
            wrong_run += row[index['run_id']] not in allowed_run_ids
            length = int(row[index['sequence_length_template']])
            if length < 0:
                raise ValueError('Negative sequence length')
            passed = parse_bool(row[index['passes_filtering']])
            total += 1
            if passed:
                passed_reads += 1; passed_bases += length
            else:
                failed_reads += 1; failed_bases += length
            value = row[type_index].lower() if type_index is not None else 'unspecified'
            # Keep only known categories; arbitrary source strings are private.
            types[value if value in ('simplex', 'duplex', 'duplex_combined', 'template', 'unspecified') else 'other'] += 1
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Sequencing summary changed during reading')
    return {'summary_sha256': digest.hexdigest(), 'summary_bytes': before.st_size,
            'summary_rows': total, 'summary_passed_reads': passed_reads, 'summary_failed_reads': failed_reads,
            'summary_passed_bases': passed_bases, 'summary_failed_bases': failed_bases,
            'duplicate_read_ids': duplicates, 'missing_read_ids': missing_id,
            'rows_with_unmatched_run_id': wrong_run, 'basecall_type_counts': dict(types)}


def reconcile(folder):
    reports = list(folder.glob('report*.json')); summaries = list(folder.glob('sequencing_summary*.txt'))
    if len(reports) != 1 or len(summaries) != 1:
        raise ValueError('Expected one JSON report and sequencing summary')
    raw = reports[0].read_bytes(); report = json.loads(raw)
    acquisitions = [a for a in report['acquisitions'] if a.get('acquisition_output')]
    if len(acquisitions) != 1:
        raise ValueError('Acquisition scope ambiguous')
    info = acquisitions[0]['acquisition_run_info']
    if 'yield_summary' not in info:
        raise ValueError('Final yield summary missing')
    result = {'run_label': folder.name, 'report_sha256': hashlib.sha256(raw).hexdigest()}
    result.update(summarize(summaries[0], {report['protocol_run_info']['run_id'], info['run_id']}))
    fields = {'passed_bases': 'basecalled_pass_bases', 'failed_bases': 'basecalled_fail_bases',
              'passed_reads': 'basecalled_pass_read_count', 'failed_reads': 'basecalled_fail_read_count'}
    for label, field in fields.items():
        value = int(info['yield_summary'].get(field, 0))
        if value < 0:
            raise ValueError('Negative final report count')
        result['report_' + label] = value
        result['delta_' + label] = result['summary_' + label] - value
    yield_match = result['delta_passed_bases'] == 0 and result['delta_passed_reads'] == 0
    integrity = not any(result[k] for k in ('duplicate_read_ids', 'missing_read_ids', 'rows_with_unmatched_run_id'))
    result['passed_yield_reconciled'] = yield_match and integrity
    result['status'] = 'exact_passed_yield_and_count_match' if yield_match and integrity else 'requires_investigation'
    result['accepted_final_passed_bases'] = result['report_passed_bases'] if yield_match and integrity else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folders = sorted([p for p in args.data_root.iterdir() if p.is_dir()], key=lambda p: int(p.name[1:]) if re.fullmatch(r'S\d+', p.name) else -1)
    if not folders or any(not re.fullmatch(r'S\d+', p.name) for p in folders):
        raise ValueError('Expected coded S<number> folders')
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for folder in folders:
        result = reconcile(folder)
        results.append(result)
        (args.output / (folder.name + '.json')).write_text(json.dumps(result, indent=2) + '\n')
        print(folder.name + ': ' + result['status'], flush=True)
    manifest = {'scope': 'Final-yield source reconciliation only; no predictions or performance analysis.',
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'run_count': len(results), 'reconciled_count': sum(r['passed_yield_reconciled'] for r in results),
                'runs': results}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
