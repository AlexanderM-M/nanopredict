"""Opt-in, headless prospective study recording. No dashboard or run-control RPCs."""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
import hashlib
import hmac
import importlib.metadata
import json
import math
import os
import platform
import secrets
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .live import MinknowCollector, MINION_DEVICE_TYPES, NoActiveRunError, _timestamp_seconds
from .paths import DATA_DIR, PACKAGE_DIR
from .predict_calibrated import CalibratedYieldPredictor

HORIZONS = (30, 60, 120)
METHODS = ('bundled', 'linear_planned', 'recent_planned', 'development_median', 'development_mean')
END_REASONS = ('planned_completion', 'intentional_stop', 'interrupted', 'failure', 'unknown')


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(text):
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('A timezone-aware UTC timestamp is required')
    return value.timestamp()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def software():
    return {
        'python': platform.python_version(),
        'packages': {p: importlib.metadata.version(p) for p in
                     ('nanopredict', 'numpy', 'scikit-learn', 'joblib', 'minknow_api', 'bamnostic', 'scipy', 'protobuf', 'grpcio')},
        'source_sha256': {p.name: digest(p) for p in sorted(PACKAGE_DIR.glob('*.py'))},
    }


def baseline_points(features, config):
    passed = finite(features.get('observed_passed_bases'))
    elapsed = finite(features.get('observed_through_seconds'))
    planned = finite(features.get('planned_run_limit_hours'))
    recent = finite(features.get('observed_recent_passed_bases_per_hour'))
    output = {'development_median': config['median_gb'], 'development_mean': config['mean_gb'],
              'linear_planned': None, 'recent_planned': None}
    if passed is not None and passed >= 0 and elapsed is not None and elapsed > 0 and planned is not None and planned >= elapsed / 3600:
        hours = planned - elapsed / 3600
        output['linear_planned'] = passed / 1e9 + passed / elapsed * 3600 * hours / 1e9
        if recent is not None and recent >= 0:
            output['recent_planned'] = passed / 1e9 + recent * hours / 1e9
    return output


def development_baselines():
    """Freeze simple comparators on inspected development data, never on study outcomes."""
    path = DATA_DIR / 'replay_features_anonymous.csv'
    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    labels = np.random.default_rng(20261008).permutation(sorted({r['sample_label'] for r in rows}))
    calibration = set(labels[:math.ceil(len(labels) * .25)])
    result = {}
    for horizon in HORIZONS:
        subset = [r for r in rows if int(r['horizon_minutes']) == horizon]
        fit = [float(r['target_final_passed_bases']) / 1e9 for r in subset if r['sample_label'] not in calibration]
        config = {'median_gb': float(np.median(fit)), 'mean_gb': float(np.mean(fit)), 'residuals': {m: [] for m in METHODS[1:]}}
        for row in subset:
            if row['sample_label'] in calibration:
                for method, pred in baseline_points(row, config).items():
                    if pred is not None:
                        config['residuals'][method].append(math.log1p(float(row['target_final_passed_bases']) / 1e9) - math.log1p(pred))
        result[str(horizon)] = config
    return {'source_sha256': digest(path), 'evidence': 'previously inspected development data only',
            'seed': 20261008, 'calibration_labels': sorted(calibration),
            'fit_labels': sorted(set(labels) - calibration), 'horizons': result}


def interval_prediction(point, residuals, thresholds):
    if point is None:
        return None
    intervals = {}
    scores = sorted(abs(r) for r in residuals)
    for coverage in (80, 90, 95):
        rank = math.ceil((len(scores) + 1) * coverage / 100)
        q = scores[rank - 1] if 0 < rank <= len(scores) else math.inf
        try:
            upper = math.expm1(math.log1p(point) + q)
        except OverflowError:
            upper = math.inf
        intervals[str(coverage)] = {'lower_gb': max(math.expm1(math.log1p(point) - q), 0),
                                    'upper_gb': upper if math.isfinite(upper) else None,
                                    'unbounded': not math.isfinite(upper)}
    probabilities = {str(t): (sum(r >= math.log1p(t) - math.log1p(point) for r in residuals) + 1) / (len(residuals) + 2)
                     if residuals else None for t in thresholds}
    return {'point_prediction_gb': point, 'prediction_intervals': intervals, 'threshold_probabilities': probabilities}


def initialize(root, protocol, thresholds=(1., 5., 10.), *, qualification=False,
               models_dir=None, predictions_visible=False):
    root, protocol = Path(root), Path(protocol)
    if not protocol.is_file() or not thresholds or any(not math.isfinite(t) or t <= 0 for t in thresholds):
        raise ValueError('Require a protocol file and positive finite targets')
    selected = Path(models_dir).resolve() if models_dir is not None else DATA_DIR / 'models'
    # Validate a complete explicit selection before creating a study directory.
    expected_files = [f'calibrated_yield_{h}min.joblib' for h in HORIZONS]
    for filename in expected_files:
        if not (selected / filename).is_file():
            raise ValueError(f'Missing selected model: {filename}')
    selected_hashes = {name: digest(selected / name) for name in expected_files}
    predictor = CalibratedYieldPredictor(selected)
    if predictor.horizons != list(HORIZONS):
        raise ValueError('Selected models must contain exactly the 30/60/120-minute checkpoints')
    for horizon, filename in zip(HORIZONS, expected_files):
        import joblib
        if joblib.load(selected / filename)['horizon_minutes'] != horizon:
            raise ValueError('Selected model filename/checkpoint mismatch')
        predictor.predict({'device_type': 'MINION_MK1D', 'observed_passed_bases': 1e7,
                           'observed_through_seconds': horizon * 60,
                           'planned_run_limit_hours': 3}, horizon, thresholds)
    references = [a.get('study_baselines') for a in predictor.artifacts.values()]
    if any(r is not None for r in references):
        if any(r != references[0] for r in references) or references[0] is None:
            raise ValueError('Selected models disagree on comparator provenance')
        baseline_config = references[0]
        if set(baseline_config['horizons']) != {str(h) for h in HORIZONS}:
            raise ValueError('Selected comparator checkpoints are incomplete')
    else:
        baseline_config = development_baselines()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    (root / 'models').mkdir()
    for horizon in HORIZONS:
        filename = f'calibrated_yield_{horizon}min.joblib'
        shutil.copyfile(selected / filename, root / 'models' / filename)
        if digest(root / 'models' / filename) != selected_hashes[filename]:
            raise ValueError('Selected model changed during initialization')
    shutil.copyfile(protocol, root / 'protocol.md')
    (root / 'key').write_bytes(secrets.token_bytes(32))
    (root / 'key').chmod(0o600)
    manifest = {'schema_version': 1, 'study_id': str(uuid.uuid4()), 'frozen_at_utc': now(),
                'purpose': 'qualification' if qualification else 'independent_evaluation',
                'software': software(), 'analysis_sha256': digest(PACKAGE_DIR.parents[1] / 'tools/paper/evaluate_frozen.py'), 'models': {p.name: digest(p) for p in sorted((root / 'models').glob('*.joblib'))},
                'protocol_sha256': digest(root / 'protocol.md'), 'thresholds_gb': sorted(set(thresholds)),
                'horizons': list(HORIZONS), 'deadline_seconds': 120, 'max_snapshot_age_seconds': 120,
                'poll_seconds': 20, 'bootstrap_seed': 20261008, 'bootstrap_replicates': 2000,
                'methods': list(METHODS), 'baselines': baseline_config,
                'model_selection': 'explicit' if models_dir is not None else 'bundled_default',
                'predictions_shown_to_operator': bool(predictions_visible),
                'interpretation': ('NON-STUDY qualification only; never eligible for independent evaluation' if qualification else 'Frozen prospective evaluation candidate; original training membership unresolved; independence requires recruitment review')}
    # The evaluator reconstructs these exact UTF-8 bytes with an LF terminator.
    # Binary output prevents Windows text mode from translating LF to CRLF.
    (root / 'freeze.json').write_bytes((encode(manifest) + '\n').encode('utf-8'))
    # SQLite's context manager commits/rolls back but does not close the handle.
    # Close explicitly so Windows can release the database without waiting for GC.
    with closing(sqlite3.connect(root / 'study.sqlite')) as db, db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE metadata (freeze_sha256 TEXT NOT NULL);
        CREATE TABLE candidates (private_key TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
        CREATE TABLE runs (run_code TEXT PRIMARY KEY, group_code TEXT NOT NULL, private_key TEXT UNIQUE NOT NULL,
                           started_utc TEXT NOT NULL, enrolled_utc TEXT NOT NULL, eligibility TEXT NOT NULL,
                           reason TEXT NOT NULL, independence_reviewed INTEGER NOT NULL);
        CREATE TABLE checkpoints (run_code TEXT NOT NULL, horizon INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                                  PRIMARY KEY (run_code,horizon));
        CREATE TABLE outcomes (run_code TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE events (event_utc TEXT NOT NULL, run_code TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL);
        ''')
        db.execute('INSERT INTO metadata VALUES (?)', (digest(root / 'freeze.json'),))
    return manifest['study_id']


class Study:
    def __init__(self, root):
        self.root = Path(root)
        if not (self.root / 'study.sqlite').is_file():
            raise ValueError('Study does not exist; initialize it first')
        self.db = sqlite3.connect(self.root / 'study.sqlite', timeout=60)
        self.db.row_factory = sqlite3.Row
        self.manifest = json.loads((self.root / 'freeze.json').read_text())
        try:
            self.verify()
        except Exception:
            self.db.close()
            raise
        self.predictor = CalibratedYieldPredictor(self.root / 'models')
        self.features = sorted(set().union(*(
            set(a['feature_columns']) | set(a.get('recording_feature_columns', []))
            for a in self.predictor.artifacts.values())))

    def close(self):
        self.db.close()

    def verify(self):
        if digest(self.root / 'freeze.json') != self.db.execute('SELECT freeze_sha256 FROM metadata').fetchone()[0]:
            raise ValueError('Freeze manifest changed')
        if digest(PACKAGE_DIR.parents[1] / 'tools/paper/evaluate_frozen.py') != self.manifest['analysis_sha256']:
            raise ValueError('Frozen evaluation script changed')
        if self.manifest['software'] != software():
            raise ValueError('Software or environment changed after freeze; start a separate study phase')
        if digest(self.root / 'protocol.md') != self.manifest['protocol_sha256']:
            raise ValueError('Frozen protocol changed')
        for name, expected in self.manifest['models'].items():
            if digest(self.root / 'models' / name) != expected:
                raise ValueError('Frozen model changed')

    def private_key(self, context):
        return hmac.new((self.root / 'key').read_bytes(), context['run_id'].encode(), hashlib.sha256).hexdigest()

    def enroll(self, context, group_code, eligibility, reason, independence_reviewed):
        group_code = str(uuid.UUID(group_code))
        started = _timestamp_seconds(getattr(context['acquisition'], 'start_time', None))
        if started is None or started <= 0 or started > timestamp(now()):
            raise ValueError('Verified acquisition start timestamp required')
        if started <= timestamp(self.manifest['frozen_at_utc']):
            raise ValueError('Run began before study freeze; development evidence only')
        qualification = self.manifest.get('purpose') == 'qualification'
        reasons = ('consecutive_eligible', 'not_minion', 'no_live_basecalling', 'prior_development_relation', 'other_protocol_exclusion')
        if qualification:
            reasons = ('qualification', 'not_minion', 'no_live_basecalling', 'other_protocol_exclusion')
            if independence_reviewed:
                raise ValueError('Qualification must not assert independent study eligibility')
        if eligibility not in ('eligible', 'excluded') or reason not in reasons:
            raise ValueError('Invalid eligibility or reason')
        if eligibility == 'eligible':
            if not context.get('prediction_available') or context.get('device_api_type') not in MINION_DEVICE_TYPES:
                raise ValueError('Recording requires MinION and live basecalling')
            if qualification:
                if reason != 'qualification':
                    raise ValueError('Non-study capture requires qualification reason')
            elif not independence_reviewed or reason != 'consecutive_eligible':
                raise ValueError('Eligible runs require independent recruitment review, MinION and live basecalling')
        code = str(uuid.uuid4())
        with self.db:
            self.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)',
                            (code, group_code, self.private_key(context), datetime.fromtimestamp(started, timezone.utc).isoformat(), now(), eligibility, reason, int(independence_reviewed)))
        return code

    def event(self, code, kind, detail):
        self.db.execute('INSERT INTO events VALUES (?,?,?,?)', (now(), code, kind, detail))

    def record_context(self, context, collector):
        self.verify()
        key = self.private_key(context)
        with self.db:
            self.db.execute('INSERT INTO candidates VALUES (?,?,?) ON CONFLICT(private_key) DO UPDATE SET last_seen=excluded.last_seen', (key, now(), now()))
        run = self.db.execute('SELECT * FROM runs WHERE private_key=?', (key,)).fetchone()
        if run is None or run['eligibility'] != 'eligible':
            return
        elapsed = finite(context.get('elapsed_seconds'))
        if elapsed is None:
            raise ValueError('Run elapsed time unavailable')
        for horizon in HORIZONS:
            if elapsed < horizon * 60:
                continue
            # One durable checkpoint per run/horizon, even across concurrent processes and restarts.
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                if self.db.execute('SELECT 1 FROM outcomes WHERE run_code=?', (run['run_code'],)).fetchone() or self.db.execute('SELECT 1 FROM checkpoints WHERE run_code=? AND horizon=?', (run['run_code'], horizon)).fetchone():
                    continue
                collected = now()
                due = timestamp(run['started_utc']) + horizon * 60
                if timestamp(collected) < due:
                    self.event(run['run_code'], 'clock_mismatch', 'elapsed_vs_utc')
                    continue
                late = elapsed > horizon * 60 + self.manifest['deadline_seconds'] or timestamp(collected) > due + self.manifest['deadline_seconds'] or timestamp(run['enrolled_utc']) > due
                status = 'missed_deadline' if late else 'recorded'
                payload = {'collected_at_utc': collected, 'collection_elapsed_seconds': elapsed,
                           'source_observed_through_seconds': None, 'source_available_at_utc': None,
                           'minknow_core_version': context.get('minknow_version'), 'api_version': context.get('api_client_version'),
                           'collector_mode': context.get('collector_mode'), 'device_api_type': context.get('device_api_type'),
                           'freeze_sha256': digest(self.root / 'freeze.json'), 'features': {}, 'predictions': {},
                           'availability_semantics': 'received by collector; earlier API/internal feature availability unknown',
                           'predictions_shown_to_operator': self.manifest.get('predictions_shown_to_operator', False)}
                if not late:
                    begin = time.perf_counter()
                    try:
                        if not context.get('prediction_available'):
                            raise ValueError('Forecast unavailable')
                        raw = collector.collect(horizon, context)
                        payload['source_available_at_utc'] = now()
                        values = {f: finite(raw.get(f)) for f in self.features}
                        observed = values['observed_through_seconds']
                        if observed is None or not horizon * 60 - self.manifest['max_snapshot_age_seconds'] <= observed <= horizon * 60:
                            raise ValueError('Stale or future yield snapshot')
                        payload['features'] = values
                        payload['source_observed_through_seconds'] = observed
                        payload['missing_features'] = [f for f,v in values.items() if v is None]
                        pred = self.predictor.predict({**values, 'device_type': 'MINION_MK1D'}, horizon, self.manifest['thresholds_gb'])
                        payload['predictions']['bundled'] = pred
                        config = self.manifest['baselines']['horizons'][str(horizon)]
                        for method, point in baseline_points(values, config).items():
                            payload['predictions'][method] = interval_prediction(point, config['residuals'][method], self.manifest['thresholds_gb'])
                        payload['prediction_ready_at_utc'] = now()
                        payload['processing_seconds'] = time.perf_counter() - begin
                        if timestamp(payload['prediction_ready_at_utc']) > due + self.manifest['deadline_seconds']:
                            status = 'late_completion'
                    except Exception as exc:
                        # Error text can contain identifying paths; persist only the exception class.
                        self.event(run['run_code'], 'checkpoint_attempt_failed', type(exc).__name__)
                        continue  # retry until deadline; never backfill a missed window
                self.db.execute('INSERT INTO checkpoints VALUES (?,?,?,?)', (run['run_code'], horizon, status, encode(payload)))

    def outcome(self, code, ended_utc, reason, final_bases, source_sha256, hidden, outcome_available_utc=None):
        if reason not in END_REASONS or len(source_sha256) != 64 or any(c not in '0123456789abcdef' for c in source_sha256):
            raise ValueError('Require controlled end reason and SHA-256 of reconciled outcome source')
        if final_bases is not None and (not math.isfinite(final_bases) or final_bases < 0 or int(final_bases) != final_bases):
            raise ValueError('Final bases must be a nonnegative integer or missing')
        run = self.db.execute('SELECT * FROM runs WHERE run_code=?', (code,)).fetchone()
        available = outcome_available_utc or now()
        if run is None or not timestamp(run['started_utc']) <= timestamp(ended_utc) <= timestamp(available) <= timestamp(now()):
            raise ValueError('Inconsistent run/outcome times')
        payload = {'ended_utc': ended_utc, 'end_reason': reason, 'final_passed_bases': final_bases,
                   'outcome_available_utc': available, 'recorded_at_utc': now(), 'source_sha256': source_sha256,
                   'predictions_hidden_confirmed': hidden, 'endpoint': 'observed_final_passed_bases_after_basecalling_drain'}
        with self.db:
            self.db.execute('INSERT INTO outcomes VALUES (?,?)', (code, encode(payload)))

    def export(self, path):
        """Pseudonymous research export: no MinKNOW IDs, paths, positions or private linkage key."""
        self.verify()
        runs = []
        for r in self.db.execute('SELECT * FROM runs ORDER BY run_code'):
            out = {k: r[k] for k in ('run_code','group_code','started_utc','enrolled_utc','eligibility','reason','independence_reviewed')}
            out['checkpoints'] = [{'horizon_minutes': c['horizon'], 'status': c['status'], **json.loads(c['payload'])}
                                  for c in self.db.execute('SELECT * FROM checkpoints WHERE run_code=? ORDER BY horizon', (r['run_code'],))]
            outcome = self.db.execute('SELECT payload FROM outcomes WHERE run_code=?', (r['run_code'],)).fetchone()
            out['outcome'] = json.loads(outcome[0]) if outcome else None
            runs.append(out)
        data = {'schema': 'nanopredict-prospective-study-v1', 'exported_at_utc': now(),
                'freeze': self.manifest, 'freeze_sha256': digest(self.root / 'freeze.json'),
                'unregistered_candidates': self.db.execute('SELECT COUNT(*) FROM candidates WHERE private_key NOT IN (SELECT private_key FROM runs)').fetchone()[0],
                'events': [dict(r) for r in self.db.execute('SELECT * FROM events')], 'runs': runs,
                'privacy': 'Pseudonymous, not anonymous: UTC times and group links require controlled access'}
        with Path(path).open('x') as handle:
            handle.write(encode(data) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('new-group', help='Generate an opaque related-patient/sample group UUID')
    init = sub.add_parser('init'); init.add_argument('--study', type=Path, required=True); init.add_argument('--protocol', type=Path, required=True)
    init.add_argument('--threshold-gb', type=float, action='append')
    init.add_argument('--qualification', action='store_true', help='Non-study device qualification; evaluator refuses these exports')
    init.add_argument('--models-dir', type=Path, help='Explicit candidate directory; validated and copied into the new freeze')
    init.add_argument('--predictions-visible', action='store_true', help='Record possible operator exposure through a dashboard')
    for name in ('enroll', 'collect', 'status', 'end', 'export'):
        p = sub.add_parser(name); p.add_argument('--study', type=Path, required=True)
        if name in ('enroll', 'collect'):
            p.add_argument('--host', default='localhost'); p.add_argument('--position')
        if name == 'enroll':
            p.add_argument('--group', required=True); p.add_argument('--eligibility', choices=['eligible','excluded'], required=True)
            p.add_argument('--reason', required=True); p.add_argument('--independence-reviewed', action='store_true')
        if name == 'collect':
            p.add_argument('--once', action='store_true')
        if name == 'end':
            p.add_argument('--run', required=True); p.add_argument('--ended-utc', required=True)
            p.add_argument('--reason', choices=END_REASONS, required=True); p.add_argument('--final-bases', type=int)
            p.add_argument('--source-sha256', required=True); p.add_argument('--predictions-hidden', action='store_true')
        if name == 'export':
            p.add_argument('--output', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.action == 'new-group':
        print(uuid.uuid4()); return
    if a.action == 'init':
        print(initialize(a.study, a.protocol, a.threshold_gb or (1.,5.,10.), qualification=a.qualification,
                         models_dir=a.models_dir, predictions_visible=a.predictions_visible)); return
    study = Study(a.study)
    try:
        if a.action == 'enroll':
            print(study.enroll(MinknowCollector(host=a.host, position_name=a.position).inspect(), a.group, a.eligibility, a.reason, a.independence_reviewed))
        elif a.action == 'collect':
            collector = MinknowCollector(host=a.host, position_name=a.position)
            while True:
                study.verify()  # configuration drift is fatal, not a transient connection error
                try:
                    for position in collector.active_positions():
                        try:
                            study.record_context(collector.inspect_position(position), collector)
                        except NoActiveRunError:
                            continue
                        except Exception as exc:
                            with study.db:
                                study.event(None, 'position_collection_error', type(exc).__name__)
                            print('Position collection error; predictions remain hidden.', flush=True)
                except NoActiveRunError:
                    pass  # Waiting for sequencing is an expected state.
                except Exception as exc:
                    with study.db:
                        study.event(None, 'collection_error', type(exc).__name__)
                    print('Collection error; see restricted event log (predictions remain hidden).', flush=True)
                if a.once:
                    break
                time.sleep(study.manifest['poll_seconds'])
        elif a.action == 'end':
            study.outcome(a.run, a.ended_utc, a.reason, a.final_bases, a.source_sha256, a.predictions_hidden)
        elif a.action == 'export':
            study.export(a.output)
        elif a.action == 'status':
            print('Purpose:', study.manifest.get('purpose', 'independent_evaluation'))
            for r in study.db.execute('SELECT run_code,eligibility FROM runs ORDER BY run_code'):
                checkpoints = study.db.execute('SELECT horizon,status FROM checkpoints WHERE run_code=?', (r['run_code'],)).fetchall()
                print(r['run_code'], r['eligibility'], [(x[0], x[1]) for x in checkpoints])
    finally:
        study.close()


if __name__ == '__main__':
    main()
