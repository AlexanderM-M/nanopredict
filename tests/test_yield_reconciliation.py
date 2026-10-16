"""Synthetic endpoint reconciliation: pass filter, identity and duplicates."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('reconcile', ROOT / 'tools/paper/reconcile_retrospective_yield.py')
reconcile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reconcile)
HEADER = 'read_id\trun_id\tpasses_filtering\tsequence_length_template\n'


class YieldReconciliationTests(unittest.TestCase):
    def test_pass_counts_and_content_hash(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'summary.txt'
            path.write_text(HEADER + 'a\trun\tTrue\t100\nb\trun\tFalse\t80\nc\trun\t1\t50\n')
            out = reconcile.summarize(path, {'run'})
            self.assertEqual(out['summary_passed_bases'], 150)
            self.assertEqual(out['summary_failed_bases'], 80)
            self.assertEqual(out['summary_passed_reads'], 2)
            self.assertEqual(out['summary_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_duplicates_and_wrong_run_remain_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'summary.txt'
            path.write_text(HEADER + 'a\trun\tTrue\t100\na\trun\tTrue\t100\nb\twrong\tTrue\t5\n')
            out = reconcile.summarize(path, {'run'})
            self.assertEqual(out['duplicate_read_ids'], 1)
            self.assertEqual(out['rows_with_unmatched_run_id'], 1)
            self.assertEqual(out['summary_passed_bases'], 205)  # No silent deduplication.

    def test_invalid_rows_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'summary.txt'
            for row in ['a\trun\tMaybe\t1\n', 'a\trun\tTrue\t-1\n', 'a\trun\tTrue\n']:
                path.write_text(HEADER + row)
                with self.assertRaises(ValueError):
                    reconcile.summarize(path, {'run'})


if __name__ == '__main__':
    unittest.main()
