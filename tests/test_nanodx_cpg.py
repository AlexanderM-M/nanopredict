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
    _BGZF_EOF,
    _bam_is_complete,
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

    def test_bam_completion_requires_the_standard_28_byte_bgzf_marker(self):
        expected = bytes.fromhex(
            "1f8b08040000000000ff0600424302001b0003000000000000000000"
        )
        self.assertEqual(len(_BGZF_EOF), 28)
        self.assertEqual(_BGZF_EOF, expected)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete = root / "complete.bam"
            complete.write_bytes(b"BAM payload" + expected)
            self.assertTrue(_bam_is_complete(complete))

            truncated = root / "truncated.bam"
            truncated.write_bytes(b"BAM payload" + expected[:-1])
            self.assertFalse(_bam_is_complete(truncated))

            still_open = root / "still-open.bam"
            still_open.write_bytes(b"BAM payload")
            self.assertFalse(_bam_is_complete(still_open))

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

    def test_counter_estimates_threshold_time_from_successive_bam_batches(self):
        starts = []
        with gzip.open(nanodx_cpg_targets(), "rt", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("#"):
                    continue
                chrom, start, _end, _probe = line.rstrip().split("\t")
                start = int(start)
                if chrom == "chr1" and len(self.targets.probes_at(chrom, start)) == 1:
                    starts.append(start)
                if len(starts) == 60:
                    break

        alignments = {
            "batch1.bam": FakeAlignment([FakeRead(start) for start in starts[:30]]),
            "batch2.bam": FakeAlignment([FakeRead(start) for start in starts[30:]]),
        }

        def opener(path, *_args):
            return alignments[Path(path).name]

        now = [0.0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            (root / "batch1.bam").write_bytes(b"complete")
            counter = NanoDxCpgCounter(
                self.targets,
                "eta-run",
                persistence_root=state,
                opener=opener,
                ready_check=lambda _path: True,
                clock=lambda: now[0],
            )
            counter.scan_directory(root)
            self.assertEqual(counter.status()["count"], 30)
            self.assertIsNone(counter.status()["eta_minutes"])

            now[0] = 60.0
            (root / "batch2.bam").write_bytes(b"complete")
            counter.scan_directory(root)
            status = counter.status()
            self.assertEqual(status["count"], 60)
            self.assertAlmostEqual(status["rate_cpg_per_minute"], 30.0)
            self.assertAlmostEqual(status["eta_minutes"], 4.0)
            self.assertEqual(status["estimated_threshold_at"], "1970-01-01T00:05:00+00:00")

            resumed = NanoDxCpgCounter(
                self.targets,
                "eta-run",
                persistence_root=state,
                opener=opener,
                ready_check=lambda _path: True,
                clock=lambda: now[0],
            )
            self.assertAlmostEqual(resumed.status()["eta_minutes"], 4.0)

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
