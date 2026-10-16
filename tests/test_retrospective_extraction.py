"""Synthetic checks for retrospective cutoffs, report bins and data integrity."""
import importlib.util
from pathlib import Path
import unittest

from google.protobuf.json_format import ParseDict
from minknow_api import report_data_pb2

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('extract_retrospective', ROOT / 'tools/paper/extract_retrospective.py')
extract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract)


def acquisition(bucket=30):
    raw = {
        'acquisition_run_info': {
            'target_run_until_criteria': {'stop_criteria': {'criteria': {'runtime': {'@type': 'type.googleapis.com/google.protobuf.UInt64Value', 'value': '43200'}}}},
            'bream_info': {'mux_scan_results': [
                {'counts': {'single_pore': 11}},  # Missing time must not be treated as time zero.
                {'mux_scan_timestamp': '300', 'counts': {'single_pore': 12}},
                {'mux_scan_timestamp': '1900', 'counts': {'single_pore': 999}},
            ]},
        },
        'bucket_size': bucket,
        'basecaller_config': {'read_filtering': {'min_qscore': 10}},
        'acquisition_output': [{'plot': [{'snapshots': [{'snapshots': [
            {'seconds': 600, 'yield_summary': {'read_count': '10', 'estimated_selected_bases': '100', 'basecalled_pass_bases': '80', 'basecalled_pass_read_count': '8'}},
            {'seconds': 1800, 'yield_summary': {'read_count': '20', 'estimated_selected_bases': '200', 'basecalled_pass_bases': '160', 'basecalled_pass_read_count': '16'}},
            {'seconds': 3600, 'yield_summary': {'read_count': '99999', 'basecalled_pass_bases': '999999'}},
        ]}]}]}],
        'basecall_boxplot': [
            {'plot': {'datasets': [{'count': '10', 'mode': 11}, {'count': '10', 'mode': 22}, {'count': '10', 'mode': 33}]}},
            {'type': 'BASES_PER_SECOND', 'plot': {'datasets': [{'count': '10', 'q25': 390, 'q50': 400, 'q75': 410}]}},
        ],
        'temperature': [{'temperatures': [{'minion': {'heatsink_temperature': 999}}]}],
        'duty_time': [{'bucket_ranges': [{'end': 1800}, {'start': 1800, 'end': 3600}], 'channel_states': {
            'strand': {'state_times': ['75', '1']}, 'pore': {'state_times': ['25', '99']},
        }}],
    }
    return ParseDict(raw, report_data_pb2.AcquistionReportData())


class RetrospectiveExtractionTests(unittest.TestCase):
    def test_no_future_snapshot_duty_or_pore_scan(self):
        row, basis = extract.candidate_features(acquisition(), 30)
        self.assertEqual(row['observed_passed_bases'], 160)
        self.assertEqual(row['observed_through_seconds'], 1800)
        self.assertEqual(row['pore_activity_sequencing_percent'], 75)
        self.assertEqual(row['pore_scan_pore_available_count'], 12)
        self.assertEqual(row['planned_run_limit_hours'], 12)
        self.assertEqual(row['observed_recent_passed_bases_per_hour'], 240)
        self.assertEqual(set(row), set(extract.FEATURES))
        self.assertIsNone(row['observed_temperature'])
        self.assertEqual(basis['observed_temperature'], 'unresolved_temperature_packet_timing')
        self.assertEqual(row['observed_target_temperature'], 0)

    def test_report_bucket_width_controls_boxplot_index(self):
        coarse, _ = extract.candidate_features(acquisition(30), 30)
        fine, _ = extract.candidate_features(acquisition(10), 30)
        self.assertEqual(coarse['observed_qscore_mode'], 11)
        self.assertEqual(fine['observed_qscore_mode'], 33)
        self.assertIsNone(fine['observed_translocation_median'])  # Never fall back to final bucket.
        self.assertEqual(coarse['observed_translocation_median'], 400)

    def test_proto_default_zero_and_zero_denominator(self):
        a = acquisition()
        summary = a.acquisition_output[0].plot[0].snapshots[0].snapshots[1].yield_summary
        summary.ClearField('basecalled_pass_read_count')
        summary.ClearField('basecalled_fail_bases')
        row, _ = extract.candidate_features(a, 30)
        self.assertEqual(row['observed_failed_bases'], 0)
        self.assertEqual(row['observed_passed_reads'], 0)
        self.assertIsNone(row['observed_mean_passed_read_length'])

    def test_ambiguous_series_and_duplicate_snapshot_rejected(self):
        a = acquisition()
        a.acquisition_output.add().CopyFrom(a.acquisition_output[0])
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            extract.aggregate_snapshots(a)
        a = acquisition()
        snapshots = a.acquisition_output[0].plot[0].snapshots[0].snapshots
        snapshots.add().CopyFrom(snapshots[0])
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            extract.aggregate_snapshots(a)

    def test_duty_series_mismatch_rejected(self):
        a = acquisition()
        del a.duty_time[0].channel_states['pore'].state_times[-1]
        with self.assertRaisesRegex(ValueError, 'bucket ranges'):
            extract.candidate_features(a, 30)

    def test_empty_boxplot_sentinels_and_report_projection(self):
        from google.protobuf.json_format import MessageToDict
        a = MessageToDict(acquisition(), preserving_proto_field_name=True)
        a['basecall_boxplot'][0]['plot']['datasets'][0] = {'count': '0', 'min': 3.4028235e38, 'mode': 3.4028235e38}
        a['acquisition_run_info']['yield_summary'] = {'basecalled_pass_bases': '999999999'}
        raw = {'protocol_run_info': {'run_id': 'private-protocol', 'flow_cell': {'flow_cell_id': 'private-cell'}, 'user_info': {'sample_id': 'private-specimen'}}, 'acquisitions': [a]}
        parsed = extract.parse_report(raw)
        self.assertFalse(parsed.protocol_run_info.HasField('user_info'))
        selected = extract.select_acquisition(parsed)
        self.assertFalse(selected.acquisition_run_info.HasField('yield_summary'))
        row, _ = extract.candidate_features(selected, 30)
        self.assertIsNone(row['observed_qscore_mode'])
        self.assertEqual(raw['acquisitions'][0]['basecall_boxplot'][0]['plot']['datasets'][0]['mode'], 3.4028235e38)

    def test_linked_html_temperature_and_future_cutoff(self):
        import json
        raw = {'protocol_run_info': {'run_id': 'p', 'flow_cell': {'flow_cell_id': 'f'}}, 'acquisitions': [{'acquisition_output': [{}], 'temperature': [{'temperatures': [{'minion': {'heatsink_temperature': v}} for v in (34, 35, 99)]}]}]}
        chart = {'header': {'protocol_run_id': 'p'}, 'flow_cell_id': 'f', 'temperature': {'series_data': [{'name': 'Measured', 'data': [[600, 34], [1800, 35], [3600, 99]]}]}}
        html = '<script>const reportData=' + json.dumps(chart) + ';evilJavascript();</script>'
        points = extract.report_temperature(html, raw)
        row, basis = extract.candidate_features(acquisition(), 30, points)
        self.assertEqual(row['observed_temperature'], 35)
        self.assertIn('explicit_report_temperature_time', basis['observed_temperature'])
        chart['header']['protocol_run_id'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'linkage'):
            extract.report_temperature('const reportData=' + json.dumps(chart), raw)
        chart['header']['protocol_run_id'] = 'p'
        chart['temperature']['series_data'][0]['data'][0][1] = 88
        with self.assertRaisesRegex(ValueError, 'mismatched'):
            extract.report_temperature('const reportData=' + json.dumps(chart), raw)

    def test_nanosecond_timestamp_and_timezone_requirement(self):
        self.assertEqual(extract.timestamp('2026-07-29T11:44:15.113076924Z').microsecond, 113076)
        with self.assertRaisesRegex(ValueError, 'Timezone'):
            extract.timestamp('2026-07-29T11:44:15')


if __name__ == '__main__':
    unittest.main()
