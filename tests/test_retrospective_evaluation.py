"""Synthetic leakage, linkage, frozen-input and paired-comparison checks."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('retrospective_evaluator', ROOT / 'tools/paper/evaluate_retrospective.py')
evaluate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate)


def fixture():
    features = []
    for h in evaluate.HORIZONS:
        row = {f: '0' for f in evaluate.FEATURES}
        row.update(run_label='S1', horizon_minutes=str(h), device_type='MINION_MK1D',
                   flowcell_group='G1', evidence_type='retrospective_candidate_inputs', live_availability_verified='False',
                   observed_through_seconds=str(h * 60), planned_run_limit_hours='72')
        features.append(row)
    cohort = [dict(run_label='S1', device_type='MINION_MK1D', flowcell_group='G1',
                   development_overlap_declaration='none_reported', forecast_influence_declaration='False',
                   distinct_patient_declaration='True', distinct_specimen_library_declaration='True',
                   acquisition_duration_hours='2.4', reported_runtime_limit_hours='72',
                   stop_reason_adjudicated='intentional_stop_sufficient_data', configuration_error_declared='True')]
    outcomes = {'runs': [dict(run_label='S1', report_sha256='hash', passed_yield_reconciled=True,
                             status='exact_passed_yield_and_count_match', accepted_final_passed_bases=100)]}
    manifest = {'report_sources': {'S1': {'report_sha256': 'hash'}}, 'missing_by_feature': {f: 0 for f in evaluate.FEATURES}}
    plan = {'analysis_scope': 'retrospective_report_reconstruction',
            'cohort': {'run_labels': ['S1'], 'known_related_groups': {'G1': ['S1']}},
            'extraction': {'source_report_hashes': {'S1': 'hash'}}}
    return plan, manifest, features, cohort, outcomes


class RetrospectiveEvaluationTests(unittest.TestCase):
    def test_duplicate_future_and_missing_checkpoints_rejected(self):
        args = fixture()
        evaluate.validate_inputs(*args)
        args[2].append(copy.deepcopy(args[2][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            evaluate.validate_inputs(*args)
        args = fixture()
        args[2][0]['observed_through_seconds'] = '1801'
        with self.assertRaisesRegex(ValueError, 'Future'):
            evaluate.validate_inputs(*args)
        args = fixture()
        args[2].pop()
        with self.assertRaisesRegex(ValueError, 'Missing checkpoint'):
            evaluate.validate_inputs(*args)

    def test_report_linkage_and_original_configuration_enforced(self):
        args = fixture()
        args[2][0]['planned_run_limit_hours'] = '3'
        with self.assertRaisesRegex(ValueError, 'Configured duration'):
            evaluate.validate_inputs(*args)
        args = fixture()
        args[4]['runs'][0]['report_sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'linkage'):
            evaluate.validate_inputs(*args)

    def test_frozen_input_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'features.csv'
            p.write_text('original')
            frozen = {str(p): evaluate.digest(p)}
            evaluate.verify_files(frozen)
            p.write_text('altered')
            with self.assertRaisesRegex(ValueError, 'Frozen file changed'):
                evaluate.verify_files(frozen)

    def test_outcomes_and_actual_duration_cannot_enter_predictor(self):
        class Predictor:
            def __init__(self): self.calls = []
            def predict(self, inputs, horizon, thresholds):
                self.calls.append(copy.deepcopy(inputs))
                return evaluate.interval_prediction(2., [0.] * 100, thresholds)
        plan, manifest, features, cohort, outcomes = fixture()
        meta, ends = evaluate.validate_inputs(plan, manifest, features, cohort, outcomes)
        config = {'horizons': {str(h): {'mean_gb': 3., 'median_gb': 2., 'residuals': {m: [0.] * 100 for m in evaluate.METHODS[1:]}} for h in evaluate.HORIZONS}}
        predictor = Predictor()
        evaluate.predict_rows(features, meta, ends, predictor, config)
        ends['S1']['accepted_final_passed_bases'] = 99999999999
        meta['S1']['acquisition_duration_hours'] = '99'
        evaluate.predict_rows(features, meta, ends, predictor, config)
        self.assertEqual(predictor.calls[:3], predictor.calls[3:])
        self.assertEqual(set(predictor.calls[0]), set(evaluate.FEATURES) | {'device_type'})
        self.assertEqual(predictor.calls[0]['planned_run_limit_hours'], '72')

    def test_bootstrap_keeps_related_runs_together(self):
        rows = [{'run_code': str(i), 'group_code': g} for i, g in enumerate(('A', 'A', 'B'))]
        for sample in evaluate.bootstrap_samples(rows, 100, 1):
            self.assertEqual(sum(r['run_code'] == '0' for r in sample), sum(r['run_code'] == '1' for r in sample))

    def test_missing_recent_rate_does_not_drop_other_methods(self):
        rows = []
        for i in range(2):
            predictions = {m: evaluate.interval_prediction(float(i + 2), [0.] * 100, evaluate.THRESHOLDS) for m in evaluate.METHODS}
            if i == 0: predictions['recent_planned'] = None
            rows.append(dict(run_code=str(i), group_code=str(i), horizon_minutes=30, actual_gb=float(i + 1),
                             end_reason='reported_protocol_completion', configuration_error=False, predictions=predictions, errors={}))
        metrics, pairs, available, _ = evaluate.summarize(rows, replicates=20, seed=1)
        all_metrics = {m['method']: m for m in metrics if m['stratum'] == 'all'}
        self.assertEqual(all_metrics['bundled']['n_runs'], 2)
        self.assertEqual(all_metrics['recent_planned']['n_runs'], 1)
        self.assertEqual(all_metrics['bundled']['mae_gb'], 1.)
        self.assertEqual(all_metrics['bundled']['bias_gb'], 1.)
        self.assertEqual(all_metrics['bundled']['coverage_95'], 0.)
        for pair in pairs:
            self.assertEqual(pair['delta_mae_gb'], 0.)
        self.assertEqual(sum(not a['available'] for a in available), 1)


if __name__ == '__main__':
    unittest.main()
