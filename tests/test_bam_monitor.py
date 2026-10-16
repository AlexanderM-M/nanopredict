"""Yield counting must work with ordinary unaligned, barcoded BAM reads."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nanopredict.bam_fallback import BamYieldCounter
from nanopredict.bam_monitor import BamYieldMonitor
from nanopredict.bam_utils import _bam_is_complete, _BGZF_EOF
from nanopredict.doctor import _check_bam, DoctorReport


class Read:
    is_secondary = False
    is_supplementary = False

    def __init__(self, length, tags):
        self.query_sequence = 'A' * length
        self.tags = tags

    def get_tag(self, tag):
        return self.tags[tag]


class Alignment:
    def __init__(self, reads):
        self.reads = reads

    def __enter__(self):
        return iter(self.reads)

    def __exit__(self, *args):
        return False


class BamMonitorTests(unittest.TestCase):
    def test_barcode_precedence_pass_fail_and_restart_without_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            passed = root/'bam_pass/barcode03/one.bam'
            failed = root/'bam_fail/two.bam'
            passed.parent.mkdir(parents=True); failed.parent.mkdir(parents=True)
            passed.write_bytes(b'fixture'); failed.write_bytes(b'fixture')
            def opener(name, mode):
                return Alignment([Read(100, {'BC': 'barcode01', 'RG': 'barcode02'}),
                                  Read(50, {'RG': 'barcode02'}), Read(25, {})]
                                 if Path(name) == passed else [Read(10, {'BC': 'barcode01'})])
            counter = BamYieldCounter(root, 'run', root/'state', opener, lambda _: True)
            counter.scan()
            rows = {r['barcode']: r for r in counter.barcode_status()}
            self.assertEqual(counter.passed_bases, 175)
            self.assertEqual(counter.failed_bases, 10)
            self.assertEqual(rows['barcode01']['passed_bases'], 100)
            self.assertEqual(rows['barcode01']['failed_bases'], 10)
            self.assertEqual(rows['barcode02']['passed_bases'], 50)
            self.assertEqual(rows['barcode03']['passed_bases'], 25)
            self.assertTrue(all(r['rate_bases_per_minute'] is None for r in rows.values()))
            reopened = BamYieldCounter(root, 'run', root/'state', opener, lambda _: True)
            reopened.scan()
            self.assertEqual(reopened.barcode_status(), counter.barcode_status())
            self.assertEqual(reopened.total_reads, 4)

    def test_truncated_batch_not_counted_then_counted_once_after_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bam = root/'batch.bam'; bam.write_bytes(b'incomplete')
            counter = BamYieldCounter(root, 'run', root/'state',
                                      lambda *_: Alignment([Read(10, {})]))
            self.assertFalse(_bam_is_complete(bam)); counter.scan()
            self.assertEqual(counter.total_reads, 0)
            bam.write_bytes(b'fixture'+_BGZF_EOF)
            self.assertTrue(_bam_is_complete(bam)); counter.scan(); counter.scan()
            self.assertEqual(counter.total_reads, 1)
            self.assertEqual(counter.barcode_status()[0]['barcode'], 'unclassified')

    def test_monitor_and_doctor_accept_ordinary_unaligned_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bam = root/'one.bam'; bam.write_bytes(b'fixture')
            counter = BamYieldCounter(root, 'run', root/'state',
                                      lambda *_: Alignment([Read(100, {'BC': 'barcode01'})]),
                                      lambda _: True)
            monitor = BamYieldMonitor(start_thread=False, persistence_root=root/'state')
            with patch('nanopredict.bam_monitor.BamYieldCounter', return_value=counter):
                monitor.update_context({'run_key': 'run', 'reads_directory': str(root),
                                        'bam_reads_enabled': True, 'alignment_enabled': False})
            self.assertEqual(monitor.status()['barcodes'][0]['passed_bases'], 100)
            self.assertEqual(monitor.status()['state'], 'collecting')
            report = DoctorReport()
            with patch('nanopredict.doctor.bamnostic.AlignmentFile',
                       return_value=Alignment([Read(100, {'BC': 'barcode01'})])):
                _check_bam(bam, report)
            self.assertTrue(report.ok)
            monitor.set_waiting()
            self.assertEqual(monitor.status()['barcodes'], [])


if __name__ == '__main__':
    unittest.main()
