"""Check run intake with synthetic BAM headers, without sequencing reads."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

from bamnostic.bgzf import BgzfWriter

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('inventory_datasets', ROOT / 'tools/paper/inventory_datasets.py')
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)


def bam_fixture(path, run_id='private-acquisition', device='P2S-private-serial', include_id=True):
    ds = 'runid=' + run_id if include_id else 'basecall_model=synthetic'
    header = ('@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:1000\n@RG\tID:private-read-group\tDS:' + ds + '\tPM:' + device + '\tSM:private-specimen\n').encode()
    with BgzfWriter(str(path), 'wb') as out:
        out.write(b'BAM\x01' + struct.pack('<i', len(header)) + header + struct.pack('<i', 1) + struct.pack('<i', 5) + b'chr1\x00' + struct.pack('<i', 1000))


class DatasetInventoryTests(unittest.TestCase):
    def test_distinct_runs_eof_and_identifier_omission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in (1, 2):
                folder = root / ('Sample' + str(i)); folder.mkdir()
                bam = folder / 'private_filename_pass_barcode05_0.bam'
                bam_fixture(bam, 'private-acquisition-' + str(i))
                Path(str(bam) + '.bai').write_bytes(b'BAI\x01' + struct.pack('<iii', 1, 0, 0))
            result = intake.inventory(root, True, 'P2_SOLO', True)
            self.assertTrue(result['all_folders_have_one_distinct_nonoverlapping_header_run_id'])
            self.assertTrue(result['investigator_declares_distinct_runs'])
            for row in result['runs']:
                self.assertEqual(row['bam_with_eof_marker'], 1)
                self.assertEqual(row['bam_missing_index'], 0)
                self.assertEqual(row['filename_barcode_labels'], ['barcode05'])
                self.assertEqual(row['header_device_classes'], ['P2S_prefix_inferred_P2_SOLO_unconfirmed'])
                self.assertIsNone(row['whole_run_export_completeness_independently_verified'])
                self.assertTrue(row['investigator_reports_complete_run_export'])
                self.assertEqual(row['investigator_reported_device'], 'P2_SOLO')
            self.assertNotIn('private-', json.dumps(result))
            self.assertNotIn('private_filename', json.dumps(result))
            self.assertNotIn(str(root), json.dumps(result))

    def test_shared_and_mixed_acquisitions_fail_distinctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in (1, 2):
                folder = root / ('Run' + str(i)); folder.mkdir()
                bam_fixture(folder / 'one.bam', 'shared')
            bam_fixture(root / 'Run1' / 'two.bam', 'additional')
            result = intake.inventory(root)
            self.assertFalse(result['all_folders_have_one_distinct_nonoverlapping_header_run_id'])
            self.assertEqual(result['folders_sharing_header_run_ids'], [{'left': 'Run1', 'right': 'Run2'}])
            self.assertEqual(result['runs'][0]['distinct_header_run_ids'], 2)

    def test_missing_id_index_and_eof_remain_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = root / 'Sample1'; folder.mkdir()
            path = folder / 'one.bam'
            bam_fixture(path, include_id=False)
            path.write_bytes(path.read_bytes()[:-28])
            result = intake.inventory(root)
            self.assertFalse(result['all_folders_have_one_distinct_nonoverlapping_header_run_id'])
            row = result['runs'][0]
            self.assertEqual(row['bam_with_eof_marker'], 0)
            self.assertEqual(row['bam_missing_index'], 1)
            self.assertEqual(row['bam_missing_header_run_id'], 1)

    def test_uncoded_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'private-name').mkdir()
            with self.assertRaisesRegex(ValueError, 'coded'):
                intake.inventory(root)


if __name__ == '__main__':
    unittest.main()
