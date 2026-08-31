from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nanopredict.bam_fallback import BamFallbackCollector, BamYieldCounter
from nanopredict.live import AdaptiveCollector, MinknowUnavailableError


class FakeRead:
    def __init__(
        self,
        length: int,
        *,
        secondary: bool = False,
        supplementary: bool = False,
    ):
        self.query_sequence = "A" * length
        self.is_secondary = secondary
        self.is_supplementary = supplementary


class FakeAlignment:
    def __init__(self, reads):
        self.reads = reads

    def __enter__(self):
        return iter(self.reads)

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class BamFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run = self.root / "experiment" / "sample" / "run"
        self.pass_bam = self.run / "bam_pass" / "pass_0.bam"
        self.fail_bam = self.run / "bam_fail" / "fail_0.bam"
        self.pass_bam.parent.mkdir(parents=True)
        self.fail_bam.parent.mkdir(parents=True)
        self.pass_bam.write_bytes(b"test")
        self.fail_bam.write_bytes(b"test")
        self.open_calls = []
        self.reads = {
            self.pass_bam.name: [
                FakeRead(100),
                FakeRead(50),
                FakeRead(500, secondary=True),
            ],
            self.fail_bam.name: [FakeRead(25), FakeRead(75)],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def opener(self, filename, mode):
        path = Path(filename)
        self.open_calls.append(path.name)
        return FakeAlignment(self.reads[path.name])

    def collector(self):
        return BamFallbackCollector(
            self.root,
            opener=self.opener,
            ready_check=lambda path: True,
            persistence_root=self.root / "state",
        )

    def test_discovers_anonymous_run_and_counts_completed_batches(self):
        collector = self.collector()
        positions = collector.active_positions()
        self.assertEqual(len(positions), 1)
        self.assertRegex(positions[0].name, r"^BAM-[A-F0-9]{6}$")
        self.assertNotIn("sample", positions[0].name.lower())

        context = collector.inspect_position(positions[0])
        progress = collector.collect_live_progress(context)
        self.assertEqual(context["collector_mode"], "bam_fallback")
        self.assertFalse(context["prediction_available"])
        self.assertEqual(progress["passed_bases"], 150)
        self.assertEqual(progress["failed_bases"], 100)
        self.assertEqual(progress["passed_reads"], 2)
        self.assertEqual(progress["total_reads"], 4)

    def test_persistent_counter_does_not_recount_batches_after_restart(self):
        persistence = self.root / "state"
        first = BamYieldCounter(
            self.run,
            "anonymous-key",
            persistence_root=persistence,
            opener=self.opener,
            ready_check=lambda path: True,
        )
        first.scan()
        self.assertEqual(len(self.open_calls), 2)

        second = BamYieldCounter(
            self.run,
            "anonymous-key",
            persistence_root=persistence,
            opener=self.opener,
            ready_check=lambda path: True,
        )
        second.scan()
        self.assertEqual(len(self.open_calls), 2)
        self.assertEqual(second.passed_bases, 150)
        self.assertEqual(second.failed_bases, 100)

    def test_adaptive_collector_uses_bam_when_api_is_unreachable(self):
        class UnreachableApi:
            def active_positions(self):
                raise MinknowUnavailableError("Cannot reach MinKNOW")

        adaptive = AdaptiveCollector(UnreachableApi(), self.collector())
        positions = adaptive.active_positions()
        context = adaptive.inspect_position(positions[0])
        progress = adaptive.collect_live_progress(context)
        self.assertEqual(context["collector_mode"], "bam_fallback")
        self.assertEqual(progress["passed_bases"], 150)

    def test_adaptive_collector_uses_bam_when_position_rpc_is_incompatible(self):
        class PartlyReachableApi:
            def active_positions(self):
                return [object()]

            def inspect_position(self, position):
                raise MinknowUnavailableError("Position RPC schema mismatch")

        adaptive = AdaptiveCollector(PartlyReachableApi(), self.collector())
        positions = adaptive.active_positions()
        self.assertEqual(len(positions), 1)
        self.assertRegex(positions[0].name, r"^BAM-")


if __name__ == "__main__":
    unittest.main()
