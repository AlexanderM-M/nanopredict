"""Duration dependence, sampling invariance and strict model selection."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np

from nanopredict.duration_model import DurationYieldRegressor, FEATURE_COLUMNS
from nanopredict.predict_calibrated import CalibratedYieldPredictor
from nanopredict.diagnose_run import RunDecisionEngine
from nanopredict import study
from nanopredict.paths import DATA_DIR
from nanopredict.server import DashboardApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/paper'))
import train_duration as training


class DurationModelTests(unittest.TestCase):
    def test_units_schedule_and_floor(self):
        m = DurationYieldRegressor().fit([[50e6, 3600, 3]], [.15])
        np.testing.assert_allclose(m.predict([[50e6, 3600, 3], [50e6, 3600, 12],
                                             [50e6, 3600, 1], [50e6, 3600, .5],
                                             [0, 3600, 3]]), [.15, .6, .05, .05, 0])

    def test_decay_monotonic_and_below_constant_rate(self):
        X = [[50e6, 3600, h] for h in [1, 2, 3, 6, 12, 72]]
        decay = DurationYieldRegressor(half_life_hours=6).fit(X, [10] * len(X)).predict(X)
        constant = DurationYieldRegressor().fit(X, [10] * len(X)).predict(X)
        self.assertTrue((np.diff(decay) > 0).all())
        self.assertTrue((decay <= constant).all())
        self.assertAlmostEqual(decay[0], .05)

    def test_missing_duration_is_not_imputed_and_invalid_inputs_fail(self):
        m = DurationYieldRegressor().fit([[50e6, 3600, 3]], [.1])
        for x in [[50e6, 3600, np.nan], [50e6, 0, 3], [-1, 3600, 3], [50e6, 3600, 0]]:
            with self.assertRaises(ValueError):
                m.predict([x])
        with self.assertRaises(ValueError):
            DurationYieldRegressor().fit([[50e6, 3600, 3]], [.01])

    def test_learned_scale_and_bounds(self):
        X = [[50e6, 3600, 3]] * 3
        m = DurationYieldRegressor(learn_scale=True).fit(X, [.1, .1, 3], [1, 1, .01])
        self.assertAlmostEqual(m.scale_, .5)
        np.testing.assert_allclose(m.predict(X), .1)
        self.assertEqual(DurationYieldRegressor(learn_scale=True).fit(X, [3] * 3).scale_, 2)

    def test_group_folds_and_baseline_selection(self):
        # Binary-exact Gb values keep the baseline error exactly zero on every
        # platform; rounding noise must not decide this perfect-fit fixture.
        X = np.array([[i / 32 * 1e9, 1800, 3] for i in range(1, 21)])
        y = X[:, 0] / 1e9 * 6
        groups = np.repeat(np.arange(10), 2)
        original = DurationYieldRegressor.fit
        fits = []
        def inspect(model, x, outcomes, *args):
            fits.append(set(x[:, 0]))
            return original(model, x, outcomes, *args)
        with patch.object(DurationYieldRegressor, 'fit', inspect):
            winner, _, p = training.select(X, y, groups)
        self.assertEqual(winner, 0)
        np.testing.assert_allclose(p, y)
        for values in fits:
            for a, b in zip(X[::2, 0], X[1::2, 0]):
                self.assertEqual(a in values, b in values)


class DurationArtifactTests(unittest.TestCase):
    def test_initializer_closes_database_and_commits_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            protocol = tmp / 'protocol.txt'; protocol.write_text('Database lifecycle check')
            connect = study.sqlite3.connect
            connections = []
            def retain_connection(*args, **kwargs):
                connection = connect(*args, **kwargs)
                connections.append(connection)
                return connection
            with patch.object(study.sqlite3, 'connect', side_effect=retain_connection):
                study.initialize(tmp / 'study', protocol, qualification=True)
            self.assertEqual(len(connections), 1)
            with self.assertRaises(study.sqlite3.ProgrammingError):
                connections[0].execute('SELECT 1')
            reopened = study.Study(tmp / 'study')
            try:
                reopened.verify()
            finally:
                reopened.close()

    def test_default_dashboard_and_new_freeze_use_replacement(self):
        with patch.dict('os.environ', {}, clear=True):
            app = DashboardApplication(source='replay')
            predictor = app.replay.engine.predictor
            self.assertEqual(predictor.horizons, [30, 60, 120])
            for horizon, artifact in predictor.artifacts.items():
                self.assertEqual(artifact['model_name'], 'minion_duration_extrapolation')
                self.assertEqual(artifact['feature_columns'], list(FEATURE_COLUMNS))
                row = dict(zip(FEATURE_COLUMNS, [50e6, horizon * 60, 3]), device_type='MINION_MK1D')
                short = predictor.predict(row, horizon, [.25])
                long = predictor.predict({**row, 'planned_run_limit_hours': 72}, horizon, [.25])
                self.assertGreater(long['point_prediction_gb'], short['point_prediction_gb'])
                self.assertGreaterEqual(long['threshold_probabilities']['0.25'],
                                        short['threshold_probabilities']['0.25'])
            app.close()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            protocol = tmp / 'protocol.txt'; protocol.write_text('Default model qualification')
            study.initialize(tmp / 'study', protocol, qualification=True)
            s = study.Study(tmp / 'study')
            try:
                self.assertEqual(s.manifest['model_selection'], 'bundled_default')
                self.assertIn('observed_recent_passed_bases_per_hour', s.features)
                for name, digest in s.manifest['models'].items():
                    self.assertEqual(digest, hashlib.sha256((DATA_DIR / 'models' / name).read_bytes()).hexdigest())
                self.assertEqual(s.manifest['baselines'], predictor.artifacts[30]['study_baselines'])
                s.verify()
            finally:
                s.close()

    def artifacts(self, root):
        root.mkdir()
        for h in (30, 60, 120):
            m = DurationYieldRegressor().fit([[1e7, h * 60, 3]], [.1])
            a = {'horizon_minutes': h, 'model_name': 'duration_test', 'model': m,
                 'feature_columns': list(FEATURE_COLUMNS),
                 'recording_feature_columns': [*FEATURE_COLUMNS, 'observed_recent_passed_bases_per_hour'],
                 'allowed_device_types': ['MINION_MK1D'], 'point_postprocess': 'observed_yield_floor',
                 'signed_log_residuals': {'__global__': [-.1, 0, .1]},
                 'interval_log_scores': {'__global__': {'80': .2, '90': .3, '95': .4}}, 'warning': 'test'}
            joblib.dump(a, root / f'calibrated_yield_{h}min.joblib')

    def test_serialized_runtime_ignores_sampling_and_qc_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / 'models'; self.artifacts(models)
            p = CalibratedYieldPredictor(models)
            row = dict(zip(FEATURE_COLUMNS, [50e6, 3600, 3]), device_type='MINION_MK1D')
            a = p.predict({**row, 'series_resolution_seconds': 600, 'observed_recent_passed_bases_per_hour': 1}, 60, [.15])
            b = p.predict({**row, 'series_resolution_seconds': 1800, 'observed_recent_passed_bases_per_hour': None}, 60, [.15])
            self.assertEqual(a, b)
            self.assertAlmostEqual(a['point_prediction_gb'], .15)
            with self.assertRaises(ValueError):
                p.predict({**row, 'planned_run_limit_hours': None}, 60)

    def test_explicit_freeze_visibility_and_recording_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); models = tmp / 'models'; self.artifacts(models)
            protocol = tmp / 'protocol.txt'; protocol.write_text('Synthetic protocol')
            root = tmp / 'study'
            study.initialize(root, protocol, qualification=True, models_dir=models, predictions_visible=True)
            s = study.Study(root)
            try:
                self.assertEqual(s.manifest['model_selection'], 'explicit')
                self.assertTrue(s.manifest['predictions_shown_to_operator'])
                self.assertIn('observed_recent_passed_bases_per_hour', s.features)
                for p in models.glob('*.joblib'):
                    self.assertEqual(p.read_bytes(), (root / 'models' / p.name).read_bytes())
                (root / 'models/calibrated_yield_30min.joblib').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'Frozen model changed'):
                    s.verify()
            finally:
                s.close()

    def test_missing_selection_does_not_create_recorder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); protocol = tmp / 'protocol.txt'; protocol.write_text('Test')
            with self.assertRaisesRegex(ValueError, 'Missing selected model'):
                study.initialize(tmp / 'study', protocol, models_dir=tmp)
            self.assertFalse((tmp / 'study').exists())

    def test_unbounded_interval_is_assessable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); models = tmp / 'models'; self.artifacts(models)
            path = models / 'calibrated_yield_30min.joblib'
            artifact = joblib.load(path)
            artifact['interval_log_scores']['__global__']['90'] = float('inf')
            joblib.dump(artifact, path)
            reference = tmp / 'reference.json'
            reference.write_text(json.dumps({'references': {}, 'diagnostics': {}, 'warning': 'synthetic'}))
            engine = RunDecisionEngine(CalibratedYieldPredictor(models), reference)
            result = engine.assess({'device_type': 'MINION_MK1D', 'observed_passed_bases': 1e7,
                                    'observed_through_seconds': 1800, 'planned_run_limit_hours': 3}, 30, 1)
            self.assertIsNone(result['prediction']['prediction_intervals']['90']['upper_gb'])
            json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
