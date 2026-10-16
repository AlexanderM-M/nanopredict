"""Synthetic feature/latency comparisons and incremental BAM state tests."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/f'tools/paper/{name}.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


class MatchedValidationTests(unittest.TestCase):
    def test_numeric_match_does_not_verify_definition_or_timing(self):
        mod=load('compare_features')
        row=dict(run_code='synthetic',horizon_minutes='30',feature='observed_passed_bases',value='100',unit='bases',definition_id='UNVERIFIED',observed_through_seconds='1801',available_at_utc='',checkpoint_at_utc='2026-01-01T00:30:00Z')
        key=('synthetic','30','observed_passed_bases'); result=mod.compare({key:row},{key:row},0,0)[0]
        self.assertTrue(result['within_numeric_tolerance']); self.assertFalse(result['definition_agrees'])
        self.assertFalse(result['live_availability_known']); self.assertTrue(result['live_future_observation'])

    def test_unmatched_feature_keys_rejected(self):
        mod=load('compare_features')
        with self.assertRaises(ValueError): mod.compare({'x':{}},{'y':{}},0,0)

    def test_negative_latency_rejected(self):
        mod=load('analyze_latency'); row=dict(run_code='r',barcode='aggregate',batch_id='1')
        row.update({name:'2026-01-01T00:00:01Z' for name in mod.STAGES}); row['displayed_utc']='2026-01-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'Negative'): mod.analyze([row])
        row['displayed_utc']='2026-01-01T00:00:03Z'
        self.assertEqual(mod.analyze([row])[0]['end_to_end_seconds'],2)



if __name__=='__main__': unittest.main()
