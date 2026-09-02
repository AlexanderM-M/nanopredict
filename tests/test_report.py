from __future__ import annotations

import csv
import io
import json
import unittest
from datetime import datetime, timezone

import numpy as np

from nanopredict.report import build_anonymous_report, report_csv, report_download


def example_status():
    return {
        "mode": "minknow",
        "state": "running",
        "sample_id": "PRIVATE-SAMPLE",
        "position_name": "PRIVATE-POSITION",
        "run_id": "PRIVATE-RUN",
        "output_path": "C:\\PRIVATE\\PATIENT",
        "device_type": "PromethION",
        "device_api_type": "P2_SOLO",
        "collector_mode": "validated",
        "read_only": True,
        "elapsed_minutes": 45.0,
        "last_update": "2026-09-02T12:00:00+00:00",
        "target_gb": 1.0,
        "prediction_available": False,
        "minknow_version": "6.10.12",
        "api_client_version": "6.10.3",
        "live_progress": {
            "passed_bases": 250_000_000,
            "failed_bases": 10_000_000,
            "total_reads": 2_000,
            "progress_percent": 25.0,
            "remaining_bases": 750_000_000,
            "rate_bases_per_minute": 5_000_000,
            "eta_minutes": 150.0,
            "target_reached": False,
            "target_reached_elapsed_minutes": None,
        },
        "nanodx_cpg": {
            "state": "collecting",
            "count": 90,
            "threshold": 180,
            "remaining": 90,
            "progress_percent": 50.0,
            "threshold_reached": False,
            "rate_cpg_per_minute": 2.0,
            "eta_minutes": 45.0,
            "model": "Capper_et_al",
            "assembly": "hg38",
            "barcodes": [
                {
                    "barcode": "barcode01",
                    "passed_bases": 125_000_000,
                    "failed_bases": 2_000_000,
                    "target_gb": 0.2,
                    "yield_progress_percent": 62.5,
                    "yield_target_reached": False,
                    "yield_eta_minutes": 15.0,
                    "count": 50,
                    "threshold": 180,
                    "progress_percent": np.float64(27.8),
                    "threshold_reached": False,
                    "eta_minutes": 65.0,
                }
            ],
        },
        "live_problems": [
            {
                "code": "BASECALLING_BACKLOG",
                "severity": "moderate",
                "title": "Basecalling is behind acquisition",
                "detail": "Potentially identifying raw detail is deliberately omitted",
                "action": "Check basecaller utilisation.",
            }
        ],
        "assessment": None,
        "history": [],
        "actual_final_gb": None,
    }


class AnonymousReportTests(unittest.TestCase):
    def test_report_excludes_identifiers_and_keeps_operational_metrics(self):
        generated = datetime(2026, 9, 2, 12, 30, tzinfo=timezone.utc)
        report = build_anonymous_report(example_status(), generated)
        serialised = json.dumps(report)
        for private_value in (
            "PRIVATE-SAMPLE",
            "PRIVATE-POSITION",
            "PRIVATE-RUN",
            "C:\\PRIVATE\\PATIENT",
            "Potentially identifying raw detail",
        ):
            self.assertNotIn(private_value, serialised)
        self.assertFalse(report["privacy"]["contains_patient_identifiers"])
        self.assertTrue(report["research_use_only"])
        self.assertEqual(report["yield"]["passed_bases"], 250_000_000)
        self.assertEqual(report["nanodx_cpg"]["count"], 90)
        self.assertEqual(report["barcodes"][0]["barcode"], "barcode01")
        self.assertEqual(
            report["problems"][0]["code"], "BASECALLING_BACKLOG"
        )

    def test_csv_has_an_aggregate_and_barcode_row(self):
        report = build_anonymous_report(example_status())
        rows = list(csv.DictReader(io.StringIO(report_csv(report))))
        self.assertEqual([row["scope"] for row in rows], ["run", "barcode"])
        self.assertEqual(rows[1]["barcode"], "barcode01")
        self.assertEqual(rows[1]["cpg_count"], "50")
        self.assertNotIn("PRIVATE", report_csv(report))

    def test_download_supports_json_and_csv_only(self):
        for output_format, content_type in (
            ("json", "application/json"),
            ("csv", "text/csv"),
        ):
            body, mime, filename = report_download(
                example_status(), output_format
            )
            self.assertTrue(body)
            self.assertTrue(mime.startswith(content_type))
            self.assertTrue(filename.endswith(f".{output_format}"))
            self.assertNotIn("PRIVATE", filename)
        with self.assertRaisesRegex(ValueError, "json or csv"):
            report_download(example_status(), "xlsx")


if __name__ == "__main__":
    unittest.main()
