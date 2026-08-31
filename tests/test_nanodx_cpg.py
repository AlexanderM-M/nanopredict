from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from nanopredict.nanodx_cpg import (
    EXPECTED_HG38_FEATURES,
    HG38_CHR1_LENGTH,
    NanoDxCpgCounter,
    NanoDxCpgMonitor,
    NanoDxTargets,
    _validate_hg38_alignment,
    modification_confidences,
)
from nanopredict.paths import nanodx_cpg_targets


class FakeRead:
    def __init__(self, cpg_start: int, reverse: bool = False, probability: int = 230):
        original = "A" * 10 + "C" + "A" * 89
        self.query_sequence = (
            original.translate(str.maketrans("ACGT", "TGCA"))[::-1]
            if reverse
            else original
        )
        self.is_reverse = reverse
        self.is_unmapped = False
        self.is_secondary = False
        self.is_supplementary = False
        self.reference_name = "chr1"
        stored_position = len(original) - 1 - 10 if reverse else 10
        reference_position = cpg_start + 1 if reverse else cpg_start
        self.reference_start = reference_position - stored_position
        self.cigartuples = [(0, len(original))]
        self._tags = {
            "MM": "C+m?,0;",
            "ML": (probability,),
            "MN": len(original),
        }

    def get_tag(self, name):
        if name not in self._tags:
            raise KeyError(name)
        return self._tags[name]


class FakeAlignment:
    def __init__(self, reads):
        self.header = {0: ("chr1", HG38_CHR1_LENGTH)}
        self.reads = reads

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.reads)


class NanoDxTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.targets = NanoDxTargets(nanodx_cpg_targets())

    def test_packaged_hg38_target_table_has_expected_model_features(self):
        self.assertEqual(self.targets.feature_count, EXPECTED_HG38_FEATURES)
        with gzip.open(nanodx_cpg_targets(), "rt", encoding="ascii") as handle:
            self.assertIn("assembly=hg38", next(handle))

    def test_real_bamnostic_style_reference_header_is_accepted(self):
        alignment = type(
            "Alignment", (), {"references": ("chr1",), "lengths": (HG38_CHR1_LENGTH,)}
        )()
        _validate_hg38_alignment(alignment)

        alignment.lengths = (249_250_621,)
        with self.assertRaisesRegex(ValueError, "not aligned.*hg38"):
            _validate_hg38_alignment(alignment)

    def test_mm_ml_confidence_and_reverse_alignment_are_counted(self):
        self.assertEqual(modification_confidences(FakeRead(15_864)), {10: 230})
        self.assertEqual(
            modification_confidences(FakeRead(15_864, reverse=True)), {10: 230}
        )

        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                alignment = FakeAlignment([FakeRead(15_864, reverse=reverse)])
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    bam = root / "batch.bam"
                    bam.write_bytes(b"complete")
                    counter = NanoDxCpgCounter(
                        self.targets,
                        f"run-{reverse}",
                        persistence_root=root / "state",
                        opener=lambda *_args, alignment=alignment: alignment,
                        ready_check=lambda _path: True,
                    )
                    counter.scan_directory(root)
                    self.assertEqual(counter.status()["count"], 1)

    def test_counter_reaches_institute_threshold_and_resumes_without_recounting(self):
        starts = []
        with gzip.open(nanodx_cpg_targets(), "rt", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("#"):
                    continue
                chrom, start, _end, _probe = line.rstrip().split("\t")
                if chrom == "chr1":
                    starts.append(int(start))
                if len(starts) == 180:
                    break
        reads = [FakeRead(start) for start in starts]
        calls = []

        def opener(*_args):
            calls.append(True)
            return FakeAlignment(reads)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bam = root / "batch.bam"
            bam.write_bytes(b"complete")
            state = root / "state"
            counter = NanoDxCpgCounter(
                self.targets,
                "institutional-run",
                persistence_root=state,
                opener=opener,
                ready_check=lambda _path: True,
            )
            counter.scan_directory(root)
            status = counter.status()
            self.assertEqual(status["count"], 180)
            self.assertTrue(status["threshold_reached"])
            self.assertEqual(status["remaining"], 0)

            resumed = NanoDxCpgCounter(
                self.targets,
                "institutional-run",
                persistence_root=state,
                opener=opener,
                ready_check=lambda _path: True,
            )
            resumed.scan_directory(root)
            self.assertEqual(resumed.status()["count"], 180)
            self.assertEqual(len(calls), 1)

    def test_monitor_reports_actionable_minknow_setup_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            monitor = NanoDxCpgMonitor(
                self.targets,
                start_thread=False,
                persistence_root=root / "state",
            )
            context = {
                "run_key": "setup-run",
                "reads_directory": str(root),
                "output_path": None,
                "bam_reads_enabled": False,
                "alignment_enabled": False,
            }
            monitor.update_context(context)
            self.assertEqual(monitor.status()["message"], "Enable BAM output in MinKNOW")

            context["bam_reads_enabled"] = True
            monitor.update_context(context)
            self.assertEqual(
                monitor.status()["message"], "Enable live hg38 alignment in MinKNOW"
            )

            context["alignment_enabled"] = True
            monitor.update_context(context)
            self.assertEqual(
                monitor.status()["message"], "Waiting for a completed BAM batch"
            )
            monitor.close()


if __name__ == "__main__":
    unittest.main()
