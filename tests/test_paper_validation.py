"""Check scientific comparison utilities with explicitly synthetic fixtures."""
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class ValidationUtilityTests(unittest.TestCase):
    @unittest.skipIf(sys.platform=='win32','POSIX resource helper')
    def test_resource_helper_propagates_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'resources.json'
            result=subprocess.run([sys.executable,str(ROOT/'tools/paper/measure_resources.py'),'--output',str(p),'--',sys.executable,'-c','raise SystemExit(3)'])
            self.assertEqual(result.returncode,3)
            data=json.loads(p.read_text())
            self.assertEqual(data['exit_code'],3)
            self.assertGreater(data['wall_seconds'],0)


if __name__=='__main__': unittest.main()
