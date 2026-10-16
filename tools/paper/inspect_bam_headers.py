"""Inspect approved non-study BAM headers only; do not scan reads or outcomes.

--manifest is a private JSON list of {case, candidate, bam_path} records, with
opaque case/candidate codes. Output omits paths, raw headers, read-group values
and command lines. A reference dictionary/header is not a full reference hash.
"""
import argparse
import hashlib
import json
from pathlib import Path

import bamnostic
from nanopredict.bam_utils import _bam_is_complete, _reference_lengths


def inspect(path):
    result = {'bytes': path.stat().st_size, 'bgzf_complete': _bam_is_complete(path)}
    with bamnostic.AlignmentFile(str(path), 'rb') as bam:
        refs = _reference_lengths(bam)
        result['reference_count'] = len(refs)
        result['chr1_lengths'] = [length for name, length in refs if name in ('1', 'chr1')]
        result['reference_dictionary_sha256'] = hashlib.sha256(json.dumps(refs, separators=(',', ':')).encode()).hexdigest()
        header = bam.header.to_dict() if hasattr(bam.header, 'to_dict') else bam.header
        if hasattr(header, 'get'):
            # Only fixed known tool names/versions are retained, never PG IDs or CL strings.
            programs = header.get('PG', [])
            result['program_versions'] = [{'program': row['PN'], 'version': row.get('VN')}
                                          for row in programs if row.get('PN') in ('minimap2', 'samtools', 'dorado', 'guppy')]
            result['read_group_count'] = len(header.get('RG', []))
            result['command_line_assembly_tokens'] = {token: any(token in row.get('CL', '').lower() for row in programs) for token in ('hg19', 'hg38')}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    rows = json.loads(a.manifest.read_text()); results = []; seen = set()
    if not rows:
        raise ValueError('No approved inputs')
    for row in rows:
        key = (row['case'], row['candidate'])
        if not all(key) or key in seen:
            raise ValueError('Empty or duplicate case/candidate key')
        seen.add(key)
        result = {'case': key[0], 'candidate': key[1]}
        try:
            result.update(inspect(Path(row['bam_path'])))
        except Exception as exc:
            result['inspection_error_class'] = type(exc).__name__
        results.append(result)
    output = {'scope': 'Approved retrospective headers and BGZF markers only. No read scan, final yield, full BAM hash, or independent/live validation. Matching headers do not prove matching BAM contents.',
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'candidates': results}
    with a.output.open('x') as handle:
        handle.write(json.dumps(output, indent=2) + '\n')


if __name__ == '__main__':
    main()
