"""Simulated prospective collection; these fixtures are not instrument validation."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nanopredict import study

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('evaluate_frozen',ROOT/'tools/paper/evaluate_frozen.py')
evaluation=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(evaluation)


class Collector:
    def __init__(self): self.calls=0; self.stale=False; self.fail=False
    def collect(self,horizon,context):
        self.calls+=1
        if self.fail: raise OSError('/private/patient/secret')
        return {'observed_through_seconds': 1 if self.stale else horizon*60,
                'observed_passed_bases':1e9,'planned_run_limit_hours':24,
                'observed_recent_passed_bases_per_hour':2e9,'patient_name':'must-not-export'}


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'study'
        self.clock=1800000000.; self.patch=patch.object(study,'now',side_effect=lambda:datetime.fromtimestamp(self.clock,timezone.utc).isoformat()); self.patch.start()
        protocol=Path(self.tmp.name)/'protocol.md'; protocol.write_text('SYNTHETIC TEST PROTOCOL')
        study.initialize(self.root,protocol)
        self.clock+=60; self.start=self.clock; self.clock+=10
        self.context={'run_id':'private-acquisition-secret','acquisition':SimpleNamespace(start_time=SimpleNamespace(seconds=self.start,nanos=0)),
                      'prediction_available':True,'device_api_type':'MINION','elapsed_seconds':10,'minknow_version':'fixture','api_client_version':'fixture','collector_mode':'synthetic'}
        self.study=study.Study(self.root); self.group=str(uuid.uuid4()); self.code=self.study.enroll(self.context,self.group,'eligible','consecutive_eligible',True)
        self.collector=Collector()
    def tearDown(self):
        self.study.close(); self.patch.stop(); self.tmp.cleanup()
    def checkpoint(self):
        self.clock=self.start+1805; self.context['elapsed_seconds']=1805
        self.study.record_context(self.context,self.collector)
    def export(self):
        path=Path(self.tmp.name)/'export.json'; self.study.export(path)
        return json.loads(path.read_text())

    def test_qualification_is_separate_and_refused_by_evaluator(self):
        root=Path(self.tmp.name)/'qualification'
        study.initialize(root,Path(self.tmp.name)/'protocol.md',qualification=True)
        self.clock+=60; self.start=self.clock; self.context['acquisition'].start_time.seconds=self.start
        qualified=study.Study(root)
        try:
            with self.assertRaisesRegex(ValueError,'must not assert'):
                qualified.enroll(self.context,self.group,'eligible','qualification',True)
            qualified.enroll(self.context,self.group,'eligible','qualification',False)
            self.clock=self.start+1805; self.context['elapsed_seconds']=1805
            qualified.record_context(self.context,self.collector)
            path=Path(self.tmp.name)/'qualification-export.json'; qualified.export(path)
            data=json.loads(path.read_text())
            self.assertEqual(data['freeze']['purpose'],'qualification')
            self.assertFalse(data['runs'][0]['independence_reviewed'])
            self.assertEqual(data['runs'][0]['checkpoints'][0]['status'],'recorded')
            with self.assertRaisesRegex(ValueError,'Non-study qualification'):
                evaluation.analyze(data)
        finally:
            qualified.close()
        with self.assertRaisesRegex(ValueError,'Invalid eligibility'):
            self.study.enroll(self.context,self.group,'eligible','qualification',False)

    def test_restart_exactly_once_and_export_no_direct_identifiers(self):
        self.checkpoint(); self.study.close(); self.study=study.Study(self.root)
        self.study.record_context(self.context,self.collector)
        self.assertEqual(self.collector.calls,1)
        self.clock=self.start+8000
        self.study.outcome(self.code,study.now(),'intentional_stop',5_000_000_000,'a'*64,True)
        data=self.export(); text=json.dumps(data)
        self.assertNotIn('private-acquisition-secret',text); self.assertNotIn('must-not-export',text)
        self.assertNotIn('private_key',text)
        cp=data['runs'][0]['checkpoints'][0]
        self.assertEqual(cp['status'],'recorded'); self.assertEqual(cp['features']['observed_passed_bases'],1e9)
        self.assertEqual(set(cp['predictions']),set(study.METHODS))
        self.assertFalse(cp['predictions_shown_to_operator'])
        self.assertIsNone(evaluation.exclusion(data['runs'][0],cp,30,data['freeze']))

    def test_late_start_is_missing_not_backfilled(self):
        self.clock=self.start+2200; self.context['elapsed_seconds']=2200
        self.study.record_context(self.context,self.collector)
        self.assertEqual(self.collector.calls,0)
        self.assertEqual(self.export()['runs'][0]['checkpoints'][0]['status'],'missed_deadline')

    def test_error_retry_and_redaction_then_missed_checkpoint(self):
        self.collector.fail=True; self.checkpoint()
        self.assertEqual(self.study.db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0],0)
        self.assertNotIn('/private',str(list(self.study.db.execute('SELECT * FROM events'))))
        self.clock=self.start+1921; self.context['elapsed_seconds']=1921
        self.study.record_context(self.context,self.collector)
        self.assertEqual(self.export()['runs'][0]['checkpoints'][0]['status'],'missed_deadline')

    def test_stale_input_rejected(self):
        self.collector.stale=True; self.checkpoint()
        self.assertEqual(self.study.db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0],0)

    def test_frozen_model_change_rejected(self):
        path=next((self.root/'models').glob('*.joblib'))
        with path.open('ab') as handle: handle.write(b'changed')
        with self.assertRaisesRegex(ValueError,'model changed'): self.study.verify()

    def test_manifest_change_rejected(self):
        with (self.root/'freeze.json').open('a') as handle: handle.write(' ')
        with self.assertRaisesRegex(ValueError,'manifest changed'): self.study.verify()

    def test_freeze_export_validates_with_windows_text_newlines(self):
        root=Path(self.tmp.name)/'windows-study'

        def windows_write_text(path, data, encoding=None, errors=None):
            with path.open('w', encoding=encoding, errors=errors, newline='\r\n') as handle:
                return handle.write(data)

        # Emulate Windows text writes even when this test runs on Linux.
        with patch.object(Path, 'write_text', windows_write_text):
            study.initialize(root, Path(self.tmp.name)/'protocol.md')
        recorded=study.Study(root)
        try:
            path=Path(self.tmp.name)/'windows-export.json'
            recorded.export(path)
            data=json.loads(path.read_text())
            self.assertEqual(evaluation.validate(data), data['freeze'])
            self.assertNotIn(b'\r\n', (root/'freeze.json').read_bytes())
        finally:
            recorded.close()

    def test_end_before_checkpoint_kept_in_flow_and_no_invented_yield(self):
        self.clock=self.start+300
        self.study.outcome(self.code,study.now(),'failure',None,'a'*64,True)
        data=self.export(); result=evaluation.analyze(data)
        self.assertFalse(result[0]); self.assertEqual(result[1][0]['reason'],'ended_before_checkpoint')
        self.assertIsNone(data['runs'][0]['outcome']['final_passed_bases'])

    def test_outcome_cannot_be_overwritten(self):
        self.clock=self.start+300
        self.study.outcome(self.code,study.now(),'failure',0,'a'*64,True)
        with self.assertRaises(sqlite3.IntegrityError): self.study.outcome(self.code,study.now(),'failure',1,'b'*64,True)

    def test_independence_and_uuid_required(self):
        with self.assertRaises(ValueError): self.study.enroll(self.context,'patient-name','eligible','consecutive_eligible',True)
        with self.assertRaisesRegex(ValueError,'independent'): self.study.enroll(self.context,self.group,'eligible','consecutive_eligible',False)

    def test_frozen_evaluation_same_cohort_without_training(self):
        self.checkpoint(); self.clock=self.start+8000
        self.study.outcome(self.code,study.now(),'planned_completion',3_000_000_000,'a'*64,True)
        data=self.export()
        # Reduce bootstrap count in this explicitly synthetic export, resealing test-only manifest.
        data['freeze']['bootstrap_replicates']=5
        import hashlib
        data['freeze_sha256']=hashlib.sha256((study.encode(data['freeze'])+'\n').encode()).hexdigest()
        for r in data['runs']:
            for c in r['checkpoints']: c['freeze_sha256']=data['freeze_sha256']
        result=evaluation.analyze(data)
        allrows=[r for r in result[0] if r['stratum']=='all']
        self.assertEqual(len(allrows),5); self.assertEqual({r['n_runs'] for r in allrows},{1})
        self.assertTrue(all(r['mae_gb_ci_low']=='' for r in allrows))
        data['runs'][0]['checkpoints'][0]['predictions']['recent_planned']=None
        self.assertEqual(evaluation.analyze(data)[0],[])

    def test_all_covered_wilson_interval_is_not_degenerate(self):
        lo,hi=evaluation.wilson(20,20)
        self.assertLess(lo,0.9); self.assertAlmostEqual(hi,1)

    def test_unconfirmed_blinding_excluded(self):
        self.checkpoint(); self.clock=self.start+8000
        self.study.outcome(self.code,study.now(),'unknown',0,'a'*64,False)
        self.assertEqual(evaluation.analyze(self.export())[1][0]['reason'],'blinding_not_confirmed')


if __name__=='__main__': unittest.main()
