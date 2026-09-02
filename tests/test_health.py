from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

from nanopredict.cli import build_parser
from nanopredict.doctor import run_doctor
from nanopredict.health import evaluate_run_health


class HealthTests(unittest.TestCase):
    def test_doctor_is_a_first_class_command_and_can_emit_json(self):
        args = build_parser().parse_args(["doctor", "--json"])
        self.assertEqual(args.command, "doctor")
        output = StringIO()
        manager = SimpleNamespace(flow_cell_positions=lambda: [])
        with redirect_stdout(output):
            code = run_doctor(
                as_json=True, manager_factory=lambda **_kwargs: manager
            )
        self.assertEqual(code, 0)
        self.assertIn('"MinKNOW connection"', output.getvalue())

    def test_reports_only_evidence_backed_setup_and_backlog_problems(self):
        context = {
            "elapsed_seconds": 1200,
            "basecalling_enabled": True,
            "bam_reads_enabled": True,
            "alignment_enabled": True,
            "reads_directory": "output",
        }
        cpg = {
            "files_processed": 2,
            "reads_scanned": 200,
            "tagged_reads": 10,
            "state": "collecting",
        }
        progress = {
            "passed_bases": 10,
            "failed_bases": 5,
            "estimated_bases": 1_000,
        }
        issues = evaluate_run_health(context, cpg, progress)
        codes = {item["code"] for item in issues}
        self.assertEqual(codes, {"LOW_TAGGED_READ_FRACTION", "BASECALLING_BACKLOG"})
        self.assertTrue(all(item["action"] for item in issues))

    def test_reports_disabled_run_outputs(self):
        issues = evaluate_run_health(
            {
                "elapsed_seconds": 60,
                "basecalling_enabled": False,
                "bam_reads_enabled": False,
                "alignment_enabled": False,
            },
            None,
            None,
        )
        self.assertEqual(
            {item["code"] for item in issues},
            {
                "BASECALLING_DISABLED",
                "BAM_DISABLED",
                "ALIGNMENT_DISABLED",
                "OUTPUT_UNAVAILABLE",
            },
        )


if __name__ == "__main__":
    unittest.main()
