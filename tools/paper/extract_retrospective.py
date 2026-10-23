"""Extract candidate inputs from completed MinKNOW reports; never score models.

Report-native time bins are not equivalent to live availability. Raw report
identifiers stay in memory; outputs use S<number> folder labels and coded groups.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from google.protobuf.json_format import ParseDict
from minknow_api import report_data_pb2, statistics_pb2
from nanopredict.live import _number, _pore_activity, _pore_scan, _planned_hours, _ratio

HORIZONS = (30, 60, 120)
FEATURES = tuple(json.loads((ROOT / 'tools/paper/feature_contract.json').read_text()))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value):
    value = re.sub(r'(\.\d{6})\d+', r'\1', value)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def parse_report(raw):
    """Project only required fields, preserving the original report unchanged.

    Empty boxplots can contain out-of-range float sentinels in min/max. Those
    fields are not model inputs; zero-count bins contribute no feature values.
    """
    protocol = raw['protocol_run_info']
    projected = {'protocol_run_info': {
        'run_id': protocol['run_id'],
        'flow_cell': {'flow_cell_id': protocol['flow_cell']['flow_cell_id']},
    }, 'acquisitions': []}
    for acquisition in raw['acquisitions']:
        if not acquisition.get('acquisition_output'):
            continue
        info = acquisition['acquisition_run_info']
        item = {key: acquisition[key] for key in ('bucket_size', 'acquisition_output', 'duty_time') if key in acquisition}
        item['acquisition_run_info'] = {key: info[key] for key in ('run_id', 'bream_info', 'target_run_until_criteria') if key in info}
        item['acquisition_run_info']['config_summary'] = {
            'channel_state_info': info.get('config_summary', {}).get('channel_state_info', {})}
        item['basecaller_config'] = {'read_filtering': acquisition.get('basecaller_config', {}).get('read_filtering', {})}
        item['basecall_boxplot'] = []
        used = ('count', 'q25', 'q50', 'q75', 'lower_full_width_half_maximum', 'mode', 'upper_full_width_half_maximum')
        for box in acquisition.get('basecall_boxplot', []):
            datasets = []
            for data in box.get('plot', {}).get('datasets', []):
                datasets.append({k: data[k] for k in used if k in data} if int(data.get('count', 0)) > 0 else {'count': '0'})
            item['basecall_boxplot'].append({'type': box.get('type', 0), 'plot': {'datasets': datasets}})
        projected['acquisitions'].append(item)
    return ParseDict(projected, report_data_pb2.ReportData())


def select_acquisition(report):
    candidates = [a for a in report.acquisitions if a.acquisition_output]
    if len(candidates) != 1:
        raise ValueError('Expected exactly one sequencing acquisition; review acquisition scope')
    return candidates[0]


def aggregate_snapshots(acquisition):
    # Omitted enum fields mean AllData under the protobuf schema, not an
    # unspecified barcode. Never choose the largest filtered/barcoded series.
    outputs = [o for o in acquisition.acquisition_output if o.type == report_data_pb2.AllData]
    groups = [g for o in outputs for p in o.plot for g in p.snapshots if not g.filtering]
    if len(groups) != 1:
        raise ValueError('Expected exactly one unfiltered AllData series')
    snapshots = sorted(groups[0].snapshots, key=lambda s: s.seconds)
    times = [s.seconds for s in snapshots]
    if not times or len(times) != len(set(times)):
        raise ValueError('Missing or duplicated aggregate snapshot times')
    return snapshots


def report_temperature(html_text, raw):
    """Read embedded JSON, never execute HTML/JavaScript; verify report linkage."""
    match = re.search(r'\bconst\s+reportData\s*=\s*', html_text)
    if not match:
        raise ValueError('HTML reportData JSON not found')
    chart, _ = json.JSONDecoder().raw_decode(html_text[match.end():])
    protocol = raw['protocol_run_info']
    if chart.get('header', {}).get('protocol_run_id') != protocol['run_id'] or chart.get('flow_cell_id') != protocol['flow_cell']['flow_cell_id']:
        raise ValueError('HTML/JSON protocol or flow-cell linkage mismatch')
    series = [x for x in chart.get('temperature', {}).get('series_data', []) if x.get('name') == 'Measured']
    if len(series) != 1:
        raise ValueError('Expected one measured-temperature chart series')
    acquisitions = [a for a in raw['acquisitions'] if a.get('acquisition_output')]
    if len(acquisitions) != 1:
        raise ValueError('Ambiguous temperature acquisition')
    packets = [p for response in acquisitions[0].get('temperature', []) for p in response.get('temperatures', [])]
    points = series[0].get('data', [])
    if len(points) != len(packets) or not points:
        raise ValueError('Temperature chart/packet count mismatch')
    result = []
    for pair, packet in zip(points, packets):
        if len(pair) != 2:
            raise ValueError('Invalid temperature point')
        time, value = map(_number, pair)
        recorded = _number(packet.get('minion', {}).get('heatsink_temperature'))
        if time is None or value is None or recorded is None or time < 0 or not math.isclose(value, recorded, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError('Invalid or mismatched temperature chart value')
        if result and time <= result[-1][0]:
            raise ValueError('Temperature times must increase strictly')
        result.append((time, value))
    return result


def candidate_features(acquisition, horizon, temperature_points=None):
    cutoff = horizon * 60
    row = {key: None for key in FEATURES}
    basis = {key: 'unavailable' for key in FEATURES}
    def put(name, value, source):
        row[name] = _number(value)
        basis[name] = source if row[name] is not None else 'missing_' + source
    snapshots = [s for s in aggregate_snapshots(acquisition) if s.seconds <= cutoff]
    bucket_seconds = acquisition.bucket_size * 60
    if bucket_seconds <= 0:
        raise ValueError('Missing report bucket size')
    put('device_is_promethion', 0, 'MinION_report_device')
    filtering = acquisition.basecaller_config.read_filtering
    put('minimum_q_score_setting', filtering.min_qscore.value if filtering.HasField('min_qscore') else None, 'final_report_configuration_not_checkpoint_verified')
    put('planned_run_limit_hours', _planned_hours(acquisition.acquisition_run_info), 'final_report_configuration_not_checkpoint_verified')
    put('series_resolution_seconds', bucket_seconds, 'report_bucket_size_not_live_resolution')
    # Preserve the deployed model's known encoding; this is not a measurement.
    put('observed_target_temperature', 0, 'deployed_zero_placeholder_not_physical_temperature')
    if snapshots:
        last = snapshots[-1]
        if not last.HasField('yield_summary'):
            raise ValueError('Aggregate snapshot lacks a yield summary')
        summary = last.yield_summary
        put('observed_through_seconds', last.seconds, 'explicit_report_snapshot_time')
        fields = {
            'observed_estimated_bases': 'estimated_selected_bases',
            'observed_passed_bases': 'basecalled_pass_bases',
            'observed_failed_bases': 'basecalled_fail_bases',
            'observed_total_reads': 'read_count',
            'observed_passed_reads': 'basecalled_pass_read_count',
            'observed_failed_reads': 'basecalled_fail_read_count',
        }
        for key, field in fields.items():
            # Proto3 scalar omission represents zero inside a present message.
            put(key, getattr(summary, field), 'report_snapshot_at_or_before_checkpoint')
        est, passed, failed = (row[k] for k in ('observed_estimated_bases', 'observed_passed_bases', 'observed_failed_bases'))
        total_reads, pass_reads, fail_reads = (row[k] for k in ('observed_total_reads', 'observed_passed_reads', 'observed_failed_reads'))
        derived = {
            'observed_passed_base_fraction': _ratio(passed, passed + failed),
            'observed_passed_read_fraction': _ratio(pass_reads, total_reads),
            'observed_mean_passed_read_length': _ratio(passed, pass_reads),
            'observed_mean_failed_read_length': _ratio(failed, fail_reads),
            'observed_mean_estimated_read_length': _ratio(est, total_reads),
            'observed_basecalling_completion_ratio': _ratio(passed + failed, est),
            'observed_average_estimated_bases_per_hour': _ratio(est, last.seconds / 3600),
            'observed_average_passed_bases_per_hour': _ratio(passed, last.seconds / 3600),
        }
        for key, value in derived.items():
            put(key, value, 'derived_from_report_snapshot')
        for key, field in [('observed_recent_estimated_bases_per_hour', 'estimated_selected_bases'), ('observed_recent_passed_bases_per_hour', 'basecalled_pass_bases')]:
            value = None
            if len(snapshots) >= 2 and snapshots[-2].HasField('yield_summary'):
                before = snapshots[-2]
                value = (getattr(summary, field) - getattr(before.yield_summary, field)) * 3600 / (last.seconds - before.seconds)
            put(key, value, 'native_report_recent_window_not_live_window')
    # The report schema documents bucket_size (minutes) for all statistics and
    # boxplots ordered from acquisition start. Never index a 30-min report as
    # though it contains 10-min bins or fall back to a future/final dataset.
    index = cutoff // bucket_seconds - 1
    for kind, mapping in [
        (statistics_pb2.StreamBoxplotRequest.QSCORE, {'observed_qscore_lower': 'lower_full_width_half_maximum', 'observed_qscore_mode': 'mode', 'observed_qscore_upper': 'upper_full_width_half_maximum'}),
        (statistics_pb2.StreamBoxplotRequest.BASES_PER_SECOND, {'observed_translocation_q25': 'q25', 'observed_translocation_median': 'q50', 'observed_translocation_q75': 'q75'}),
    ]:
        plots = [p.plot for p in acquisition.basecall_boxplot if p.type == kind]
        if len(plots) > 1:
            raise ValueError('Ambiguous boxplot series')
        dataset = plots[0].datasets[index] if plots and cutoff % bucket_seconds == 0 and 0 <= index < len(plots[0].datasets) else None
        for key, field in mapping.items():
            put(key, getattr(dataset, field) if dataset is not None and dataset.count > 0 else None, 'inferred_report_bin_end_not_live_10min_boxplot')
    # Temperature packets lack timestamps. bucket_size alone does not establish
    # their point origin or aggregation relative to the live one-minute stream.
    basis['observed_temperature'] = 'unresolved_temperature_packet_timing'
    if temperature_points is not None:
        eligible = [point for point in temperature_points if point[0] <= cutoff]
        if eligible:
            put('observed_temperature', eligible[-1][1], 'linked_HTML_explicit_report_temperature_time_not_live_1min_window')
    duties = list(acquisition.duty_time)
    if len(duties) > 1:
        raise ValueError('Multiple duty-time responses need scope review')
    selected = None
    if duties:
        ranges = list(duties[0].bucket_ranges)
        ends = [r.end for r in ranges]
        if ends != sorted(set(ends)):
            raise ValueError('Invalid duty-time bucket ordering')
        eligible = [i for i, r in enumerate(ranges) if r.start >= 0 and r.start < r.end <= cutoff]
        if eligible:
            selected = eligible[-1]
            trimmed = statistics_pb2.StreamDutyTimeResponse()
            for name, values in duties[0].channel_states.items():
                if len(values.state_times) != len(ranges):
                    raise ValueError('Duty state count differs from bucket ranges')
                trimmed.channel_states[name].state_times.append(values.state_times[selected])
            for key, value in _pore_activity(trimmed, acquisition.acquisition_run_info.config_summary.channel_state_info).items():
                put(key, value, 'explicit_duty_bucket_at_or_before_checkpoint')
    info = acquisition.acquisition_run_info.bream_info
    # An absent proto timestamp would look like zero. Exclude those ambiguous
    # scans instead of allowing them through the helper's default-zero cutoff.
    clean = type(info)()
    clean.CopyFrom(info)
    del clean.mux_scan_results[:]
    for scan in info.mux_scan_results:
        if scan.mux_scan_timestamp > 0 and scan.mux_scan_timestamp <= cutoff:
            clean.mux_scan_results.add().CopyFrom(scan)
    for key, value in _pore_scan(clean, cutoff).items():
        put(key, value, 'explicit_mux_timestamp_at_or_before_checkpoint')
    assert set(row) == set(FEATURES)
    return row, basis


def write_csv(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    with path.open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(data_root, output, declarations):
    folders = sorted([p for p in data_root.iterdir() if p.is_dir()], key=lambda p: int(p.name[1:]) if re.fullmatch(r'S\d+', p.name) else -1)
    if not folders or any(not re.fullmatch(r'S\d+', p.name) for p in folders):
        raise ValueError('Expected coded S<number> run folders only')
    all_rows, audit, cohorts, hashes = [], [], [], {}
    cells, protocols, acquisitions, report_hashes = {}, set(), set(), set()
    for folder in folders:
        reports = list(folder.glob('report*.json'))
        finals = list(folder.glob('final_summary*.txt'))
        summaries = list(folder.glob('sequencing_summary*.txt'))
        if len(reports) != 1 or len(finals) != 1 or len(summaries) != 1:
            raise ValueError(f'{folder.name}: expected one report, final summary and sequencing summary')
        html = list(folder.glob('report*.html'))
        if len(html) != 1:
            raise ValueError(f'{folder.name}: expected one HTML report')
        raw = json.loads(reports[0].read_text())
        temperatures = report_temperature(html[0].read_text(), raw)
        report = parse_report(raw)
        device = raw['protocol_run_info']['device']['device_type']
        if device not in ('MINION', 'MINION_MK1C', 'MINION_MK1D'):
            raise ValueError(f'{folder.name}: unsupported forecast device')
        acquisition = select_acquisition(report)
        info = acquisition.acquisition_run_info
        digest = sha256(reports[0])
        if report.protocol_run_info.run_id in protocols or info.run_id in acquisitions or digest in report_hashes:
            raise ValueError('Duplicate protocol, acquisition or report across folders')
        protocols.add(report.protocol_run_info.run_id); acquisitions.add(info.run_id); report_hashes.add(digest)
        cell = report.protocol_run_info.flow_cell.flow_cell_id
        if not cell:
            raise ValueError('Missing flow-cell group identity')
        if cell not in cells:
            cells[cell] = f'FlowcellGroup{len(cells)+1}'
        raw_info = next(a['acquisition_run_info'] for a in raw['acquisitions'] if a['acquisition_run_info']['run_id'] == info.run_id)
        start, end = (timestamp(raw_info[k]) for k in ('data_read_start_time', 'data_read_end_time'))
        final = dict(line.split('=', 1) for line in finals[0].read_text().splitlines() if '=' in line)
        linkage = final.get('protocol_run_id') == report.protocol_run_info.run_id and final.get('acquisition_run_id') == info.run_id
        end_delta = abs((timestamp(final['acquisition_stopped']) - end).total_seconds())
        if not linkage or end_delta > 1:
            raise ValueError(f'{folder.name}: final summary linkage/timing mismatch')
        with summaries[0].open() as handle:
            columns = handle.readline().rstrip('\n').split('\t')
        decl = declarations.get('runs', {}).get(folder.name, {})
        cohort = {
            'run_label': folder.name, 'device_type': device, 'flowcell_group': cells[cell],
            'kit': raw['protocol_run_info'].get('meta_info', {}).get('tags', {}).get('kit', {}).get('string_value'),
            'reported_runtime_limit_hours': _planned_hours(info),
            'acquisition_duration_hours': (end - start).total_seconds() / 3600,
            'protocol_state': raw['protocol_run_info'].get('state'),
            'stop_reason_adjudicated': decl.get('stop_reason', 'pending'),
            'development_overlap_declaration': decl.get('development_overlap', 'unknown'),
            'distinct_specimen_library_declaration': decl.get('distinct_specimen_library', 'unknown'),
            'distinct_patient_declaration': decl.get('distinct_patient', 'unknown'),
            'forecast_influence_declaration': decl.get('forecasts_used', 'unknown'),
            'report_bucket_minutes': acquisition.bucket_size,
            'final_summary_linkage_matches': linkage,
            'final_summary_end_delta_seconds': end_delta,
            'sequencing_summary_required_columns_present': all(c in columns for c in ('run_id', 'start_time', 'duration', 'passes_filtering', 'sequence_length_template')),
            'bam_file_count': len(list(folder.rglob('*.bam'))),
            'has_temperature_packets': any(a.get('temperature') for a in raw['acquisitions'] if a['acquisition_run_info']['run_id'] == info.run_id),
            'intended_workflow_hours': decl.get('intended_workflow_hours'),
            'configuration_error_declared': decl.get('configuration_error', False),
        }
        cohorts.append(cohort)
        hashes[folder.name] = {'report_sha256': digest, 'html_report_sha256': sha256(html[0]), 'final_summary_sha256': sha256(finals[0]), 'sequencing_summary_bytes': summaries[0].stat().st_size}
        for horizon in HORIZONS:
            row, basis = candidate_features(acquisition, horizon, temperatures)
            meta = {'run_label': folder.name, 'device_type': device, 'horizon_minutes': horizon, 'flowcell_group': cells[cell], 'evidence_type': 'retrospective_candidate_inputs', 'live_availability_verified': False}
            all_rows.append({**meta, **row})
            for feature in FEATURES:
                audit.append({'run_label': folder.name, 'horizon_minutes': horizon, 'feature': feature, 'numeric_value_present': row[feature] is not None, 'extraction_basis': basis[feature], 'live_availability_verified': False})
    manifest = {
        'schema': 'nanopredict-retrospective-extraction-v1',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Candidate feature extraction and metadata audit only; no predictions, final-yield computation, fitting or performance scoring.',
        'run_count': len(cohorts), 'checkpoint_rows': len(all_rows), 'distinct_flowcells': len(cells),
        'script_sha256': sha256(Path(__file__)),
        'feature_contract_sha256': sha256(ROOT / 'tools/paper/feature_contract.json'),
        'live_helper_sha256': sha256(ROOT / 'src/nanopredict/live.py'),
        'declarations': declarations,
        'report_sources': hashes,
        'model_hashes': {p.name: sha256(p) for p in sorted((ROOT / 'src/nanopredict/data/models').glob('*.joblib'))},
        'missing_by_feature': {f: sum(row[f] is None for row in all_rows) for f in FEATURES},
        'limitations': [
            'Retrospective reports do not establish when historical basecalls/statistics were available live.',
            'Report-native 10/30-minute bins differ from the deployed collector windows, especially boxplots and recent rates.',
            'Temperature times are recovered from linked HTML chart points and values checked against JSON packets; report aggregation still differs from the live one-minute stream.',
            'Reported planned duration and quality threshold are final-report configuration; checkpoint-time configuration remains unverified.',
            'Zero target temperature is the deployed representation placeholder, not a physical reading.',
            'Original training feature extraction and membership cannot be reconstructed from these reports alone.',
            'Known reused flow cells define related groups even when patients/specimens/libraries are distinct by investigator declaration.',
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / 'candidate_features.csv', all_rows)
    write_csv(output / 'feature_audit.csv', audit)
    write_csv(output / 'cohort.csv', cohorts)
    with (output / 'manifest.json').open('x') as handle:
        json.dump(manifest, handle, indent=2, allow_nan=False); handle.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--declarations', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.data_root, args.output, json.loads(args.declarations.read_text()))
    print(json.dumps({k: result[k] for k in ('run_count', 'checkpoint_rows', 'distinct_flowcells', 'missing_by_feature')}))


if __name__ == '__main__':
    main()
