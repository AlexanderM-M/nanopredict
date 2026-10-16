"""Inventory coded run directories using file metadata and BAM headers only.

Does not scan reads, compute yields, load models, or establish cohort eligibility.
The output omits source paths, raw acquisition IDs, sample/library identifiers,
header command lines and acquisition dates. Directory labels must be coded IDs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import gzip
import json
from pathlib import Path
import re
import struct


BGZF_EOF = bytes.fromhex('1f8b08040000000000ff0600424302001b0003000000000000000000')


def read_header(path: Path) -> dict:
    # Read only the BAM text header; no index loading or alignment iteration.
    with gzip.open(path, 'rb') as handle:
        if handle.read(4) != b'BAM\x01':
            raise ValueError('Invalid BAM magic')
        length = struct.unpack('<i', handle.read(4))[0]
        if not 0 <= length <= 16 * 1024 * 1024:
            raise ValueError('Invalid or oversized BAM text header')
        raw = handle.read(length)
        if len(raw) != length:
            raise ValueError('Truncated BAM text header')
    header = {}
    for line in raw.decode().splitlines():
        fields = line.split('\t')
        if fields[0] not in ('@SQ', '@RG', '@PG'):
            continue
        row = dict(field.split(':', 1) for field in fields[1:] if ':' in field)
        header.setdefault(fields[0][1:], []).append(row)
    return header


def inventory(root: Path, declared_distinct: bool = False, declared_device: str | None = None, declared_complete: bool = False) -> dict:
    rows = []
    ids_by_folder = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        # Prevent accidental export of arbitrary identifying directory names.
        if not re.fullmatch(r'(?:Sample|Run)\d+', folder.name):
            raise ValueError('Use coded SampleN or RunN directory names')
        files = sorted(p for p in folder.rglob('*') if p.is_file())
        bams = [p for p in files if p.suffix.lower() == '.bam']
        run_ids = set()
        references = set()
        program_versions = set()
        barcodes = set()
        platforms = set()
        complete = 0
        missing_indexes = 0
        missing_run_id = 0
        changed_files = 0
        errors = Counter()
        for path in bams:
            before = path.stat()
            if not (Path(str(path) + '.bai').is_file() or path.with_suffix('.bai').is_file()):
                missing_indexes += 1
            barcode = re.search(r'(?:^|_)barcode(\d+)(?:_|\.)', path.name)
            if barcode:
                barcodes.add('barcode' + barcode.group(1))
            try:
                with path.open('rb') as handle:
                    if before.st_size >= len(BGZF_EOF):
                        handle.seek(-len(BGZF_EOF), 2)
                        complete += handle.read() == BGZF_EOF
                header = read_header(path)
                refs = [(row['SN'], row['LN']) for row in header.get('SQ', [])]
                references.add(hashlib.sha256(json.dumps(refs).encode()).hexdigest())
                file_ids = set()
                for group in header.get('RG', []):
                    fields = dict(token.split('=', 1) for token in group.get('DS', '').split() if '=' in token)
                    if fields.get('runid'):
                        file_ids.add(fields['runid'])
                    device = group.get('PM', '').upper()
                    if device in ('MINION', 'MINION_MK1B', 'MINION_MK1C', 'MINION_MK1D', 'GRIDION', 'PROMETHION', 'P2_SOLO', 'P2_INTEGRATED'):
                        platforms.add(device)
                    elif device.startswith('P2S-'):
                        platforms.add('P2S_prefix_inferred_P2_SOLO_unconfirmed')
                    else:
                        platforms.add('unclassified_header_device')
                run_ids.update(file_ids)
                missing_run_id += not bool(file_ids)
                for program in header.get('PG', []):
                    name, version = program.get('PN', ''), program.get('VN', '')
                    if name in ('minknow', 'dorado', 'guppy', 'samtools', 'minimap2') and re.fullmatch(r'[0-9][0-9A-Za-z.+_-]{0,60}', version):
                        program_versions.add((name, version))
            except Exception as exc:
                errors[type(exc).__name__] += 1
            after = path.stat()
            changed_files += (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        ids_by_folder[folder.name] = run_ids
        rows.append({
            'run_label': folder.name,
            'file_count': len(files),
            'extensions': dict(sorted(Counter(p.suffix.lower() for p in files).items())),
            'bytes': sum(p.stat().st_size for p in files),
            'bam_count': len(bams),
            'bam_with_eof_marker': complete,
            'bam_missing_index': missing_indexes,
            'bam_missing_header_run_id': missing_run_id,
            'distinct_header_run_ids': len(run_ids),
            'reference_dictionary_count': len(references),
            'header_device_classes': sorted(platforms),
            'header_program_versions': [{'program': n, 'version': v} for n, v in sorted(program_versions)],
            'filename_barcode_labels': sorted(barcodes),
            'header_errors': dict(errors),
            'files_changed_during_inspection': changed_files,
            'investigator_reported_device': declared_device,
            'investigator_reports_complete_run_export': declared_complete,
            'whole_run_export_completeness_independently_verified': None,
            'training_calibration_membership': 'unknown',
            'related_patient_library_flowcell_group': None,
            'checkpoint_feature_availability': 'unverified; BAM headers do not provide the full model feature history',
            'reconciled_final_yield': None,
            'analysis_role': 'unassigned; file/header intake only',
        })
    if not rows:
        raise ValueError('No coded run directories found')
    labels = sorted(ids_by_folder)
    shared = [{'left': a, 'right': b} for i, a in enumerate(labels) for b in labels[i+1:] if ids_by_folder[a] & ids_by_folder[b]]
    confirmed = all(row['bam_count'] and row['distinct_header_run_ids'] == 1 and not row['bam_missing_header_run_id'] and not row['header_errors'] and not row['files_changed_during_inspection'] for row in rows) and not shared
    return {
        'inspected_at_utc': datetime.now(timezone.utc).isoformat(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'File metadata, BAM headers and EOF markers only. No read scan, yield outcome, model prediction or performance analysis.',
        'investigator_declares_distinct_runs': declared_distinct,
        'all_folders_have_one_distinct_nonoverlapping_header_run_id': confirmed,
        'folders_sharing_header_run_ids': shared,
        'run_count': len(rows),
        'runs': rows,
        'limitations': [
            'Distinct acquisitions do not establish independent patients, materials, flow cells or exclusion from model development.',
            'EOF markers and indexes do not prove BAM body integrity, index validity or completeness of the exported run.',
            'File transfer mtimes do not establish sequencing or live availability times.',
            'Filename barcode labels may indicate a selected-barcode export; whole-run scope needs confirmation.',
            'Historical read timestamps, if present, do not establish when basecalls or live statistics became available.',
            'The inventory is a point-in-time observation; later transfers require a new inventory.',
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--declared-distinct-runs', action='store_true', help='Record an investigator statement, not inferred independence')
    parser.add_argument('--declared-device', choices=['MINION', 'P2_SOLO', 'PROMETHION'])
    parser.add_argument('--declared-complete-runs', action='store_true', help='Record investigator-reported completeness without asserting independent reconciliation')
    args = parser.parse_args()
    result = inventory(args.data_root, args.declared_distinct_runs, args.declared_device, args.declared_complete_runs)
    with args.output.open('x') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    print(json.dumps({'runs': result['run_count'], 'header_distinctness_confirmed': result['all_folders_have_one_distinct_nonoverlapping_header_run_id']}))


if __name__ == '__main__':
    main()
