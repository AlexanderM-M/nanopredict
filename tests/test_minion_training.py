"""Synthetic guards for MinION development splits and artifact consumption."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
from sklearn.dummy import DummyRegressor

from nanopredict.predict_calibrated import CalibratedYieldPredictor

SPEC = importlib.util.spec_from_file_location(
    'train_minion', Path(__file__).resolve().parents[1] / 'tools/paper/train_minion.py')
t = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)


def row(sample='a', device=t.DEVICE):
    return {**dict.fromkeys(t.FEATURES, ''), 'sample_label': sample, 'run_label': 'run',
            'device_type': device, 'horizon_minutes': '30',
            'target_final_passed_bases': '2000000000', 'observed_passed_bases': '1000000000',
            'device_is_promethion': '0', 'observed_through_seconds': '1800'}


class MinionTrainingTests(unittest.TestCase):
    def test_device_filter_and_endpoint_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'features.csv'
            t.write_csv(path, [row(), row('prom', 'PROMETHION')])
            rows, excluded = t.read_development(path)
            self.assertEqual([r['sample_label'] for r in rows], ['a'])
            self.assertEqual(excluded, 1)
            path = Path(directory) / 'invalid.csv'
            t.write_csv(path, [{**row(), 'target_final_passed_bases': '1'}])
            with self.assertRaisesRegex(ValueError, 'Observed passed yield'):
                t.read_development(path)

    def test_transitive_related_runs_never_cross_partition(self):
        members = [dict(sample_label='a', run_label='r1', flow_cell_id='cell1'),
                   dict(sample_label='a', run_label='r2', flow_cell_id='cell2'),
                   dict(sample_label='b', run_label='r3', flow_cell_id='cell2')]
        members += [dict(sample_label=f's{i}', run_label='r', flow_cell_id=f'other{i}')
                    for i in range(20)]
        groups = t.related_groups(members, members)
        self.assertEqual(groups['a', 'r1'], groups['b', 'r3'])
        fit, cal = t.partition_groups(groups.values())
        self.assertFalse(fit & cal)
        self.assertEqual(fit | cal, set(groups.values()))
        self.assertEqual((fit, cal), t.partition_groups(list(reversed(list(groups.values())))))

    def test_tuning_preprocessing_is_refitted_inside_group_folds(self):
        X = np.zeros((20, len(t.FEATURES)))
        X[:, 0] = np.arange(20)
        groups = np.repeat(np.arange(10), 2)
        y = np.linspace(.1, 2, 20)
        original = t.SimpleImputer.fit
        seen = []
        def inspect(instance, values, *args, **kwargs):
            seen.append(values.copy())
            return original(instance, values, *args, **kwargs)
        with patch.object(t.SimpleImputer, 'fit', inspect):
            model, scores, winner, predictions = t.tune(
                X, y, groups, candidates=({'family': 'log_ridge', 'alpha': 1.},))
        self.assertEqual(len(seen), 6)  # five fresh fold fits, then the final refit
        held_out = []
        for values in seen[:5]:
            ids = set(values[:, 0].astype(int))
            missing = set(range(20)) - ids
            self.assertFalse(set(groups[list(ids)]) & set(groups[list(missing)]))
            held_out.extend(missing)
        self.assertEqual(sorted(held_out), list(range(20)))
        np.testing.assert_array_equal(seen[-1], X)
        self.assertTrue(np.isfinite(predictions).all())

    def test_calibration_weights_groups_and_handles_small_sample(self):
        y = np.array([0., 3., 1.])
        signed, weights, radii = t.calibrate(y, np.zeros(3), np.array(['a', 'a', 'b']))
        np.testing.assert_allclose(signed, np.log1p(y))
        self.assertEqual(weights, [.5, .5, 1.])
        self.assertTrue(all(math.isinf(v) for v in radii.values()))
        _, _, radii = t.calibrate(np.expm1(np.arange(20)/10), np.zeros(20), np.arange(20))
        self.assertAlmostEqual(radii['90'], 1.8)
        self.assertAlmostEqual(radii['95'], 1.9)


class MinionArtifactTests(unittest.TestCase):
    def artifact(self, candidate=True):
        artifact = {'horizon_minutes': 30, 'model_name': 'test',
                    'feature_columns': ['observed_passed_bases'],
                    'model': DummyRegressor(strategy='constant', constant=.5).fit([[0]], [0]),
                    'signed_log_residuals': {'__global__': [-1., 0., 2.]},
                    'interval_log_scores': {'__global__': {'80': .2, '90': .4, '95': .6}},
                    'warning': 'synthetic'}
        if candidate:
            artifact.update(allowed_device_types=[t.DEVICE],
                            point_postprocess='observed_yield_floor',
                            signed_residual_weights={'__global__': [.5, .5, 1.]})
        return artifact

    def consumer(self, directory, artifact):
        joblib.dump(artifact, Path(directory) / 'calibrated_yield_30min.joblib')
        return CalibratedYieldPredictor(directory)

    def test_candidate_floor_weighted_probabilities_and_device_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            predictor = self.consumer(directory, self.artifact())
            result = predictor.predict({'device_type': t.DEVICE, 'observed_passed_bases': 1e9}, 30, (1., 2.))
            self.assertEqual(result['point_prediction_gb'], 1.)
            self.assertEqual(result['prediction_intervals']['90']['lower_gb'], 1.)
            self.assertEqual(result['threshold_probabilities'], {'1.0': 1., '2.0': .5})
            for device in ('PROMETHION', 'unknown'):
                with self.assertRaisesRegex(ValueError, 'restricted'):
                    predictor.predict({'device_type': device}, 30)

    def test_unbounded_interval_serializes_as_json(self):
        artifact = self.artifact()
        artifact['interval_log_scores']['__global__']['95'] = math.inf
        with tempfile.TemporaryDirectory() as directory:
            predictor = self.consumer(directory, artifact)
            result = predictor.predict({'device_type': t.DEVICE}, 30)
            self.assertIsNone(result['prediction_intervals']['95']['upper_gb'])
            self.assertTrue(result['prediction_intervals']['95']['unbounded'])
            json.dumps(result, allow_nan=False)

    def test_legacy_artifact_retains_unweighted_unrestricted_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            predictor = self.consumer(directory, self.artifact(candidate=False))
            result = predictor.predict({'device_type': 'PROMETHION', 'observed_passed_bases': 1e9}, 30, (2.,))
            self.assertEqual(result['point_prediction_gb'], .5)
            self.assertAlmostEqual(result['threshold_probabilities']['2.0'], 2/5)
            self.assertNotIn('unbounded', result['prediction_intervals']['95'])

    def test_invalid_calibration_weights_rejected(self):
        artifact = self.artifact()
        artifact['signed_residual_weights']['__global__'] = [-1., 1., 1.]
        with tempfile.TemporaryDirectory() as directory:
            predictor = self.consumer(directory, artifact)
            with self.assertRaisesRegex(ValueError, 'weights'):
                predictor.predict({'device_type': t.DEVICE}, 30)


if __name__ == '__main__':
    unittest.main()
