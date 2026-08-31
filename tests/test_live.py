from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

import joblib
from google.protobuf import wrappers_pb2
from minknow_api import (
    acquisition_pb2,
    analysis_configuration_pb2,
    instance_pb2,
    statistics_pb2,
)

from nanopredict.diagnose_run import RunDecisionEngine
from nanopredict.live import LiveMonitor, MinknowCollector, NoActiveRunError
from nanopredict.paths import diagnostic_reference, models_dir
from nanopredict.predict_calibrated import CalibratedYieldPredictor


class FakeStatistics:
    def __init__(self):
        self.calls = []

    def stream_acquisition_output(self, **kwargs):
        self.calls.append("stream_acquisition_output")
        response = statistics_pb2.StreamAcquisitionOutputResponse()
        group = response.snapshots.add()
        for seconds, estimated, passed, failed, reads, pass_reads, fail_reads in (
            (0, 0, 0, 0, 0, 0, 0),
            (1800, 1_200_000_000, 900_000_000, 100_000_000, 100_000, 80_000, 20_000),
        ):
            snapshot = group.snapshots.add(seconds=seconds)
            summary = snapshot.yield_summary
            summary.estimated_selected_bases = estimated
            summary.basecalled_pass_bases = passed
            summary.basecalled_fail_bases = failed
            summary.read_count = reads
            summary.basecalled_pass_read_count = pass_reads
            summary.basecalled_fail_read_count = fail_reads
        return iter([response])

    def stream_basecall_boxplots(self, **kwargs):
        self.calls.append("stream_basecall_boxplots")
        response = statistics_pb2.BoxplotResponse()
        for _ in range(3):
            dataset = response.datasets.add(count=100)
            if kwargs["data_type"] == statistics_pb2.StreamBoxplotRequest.QSCORE:
                dataset.lower_full_width_half_maximum = 10.1
                dataset.mode = 13.2
                dataset.upper_full_width_half_maximum = 15.3
            else:
                dataset.q25 = 350
                dataset.q50 = 400
                dataset.q75 = 450
        return iter([response])

    def stream_duty_time(self, **kwargs):
        self.calls.append("stream_duty_time")
        response = statistics_pb2.StreamDutyTimeResponse()
        response.channel_states["strand"].state_times.extend([0, 70])
        response.channel_states["pore"].state_times.extend([0, 20])
        response.channel_states["unavailable"].state_times.extend([0, 10])
        return iter([response])

    def stream_temperature(self, **kwargs):
        self.calls.append("stream_temperature")
        response = statistics_pb2.StreamTemperatureResponse()
        packet = response.temperatures.add()
        packet.minion.heatsink_temperature = 35.2
        packet.target_temperature.minimum = 34.0
        packet.target_temperature.maximum = 36.0
        return iter([response])


class FakeConnection:
    def __init__(self, acquisition, core_version=(6, 10, 12)):
        self.statistics = FakeStatistics()
        version = instance_pb2.GetVersionInfoResponse()
        version.minknow.major, version.minknow.minor, version.minknow.patch = (
            core_version
        )
        version.minknow.full = ".".join(str(item) for item in core_version)
        self.instance = SimpleNamespace(get_version_info=lambda **kwargs: version)
        self.acquisition = SimpleNamespace(
            get_current_acquisition_run=lambda **kwargs: acquisition
        )
        basecaller = analysis_configuration_pb2.BasecallerConfiguration()
        basecaller.read_filtering.min_qscore.value = 10.0
        self.analysis_configuration = SimpleNamespace(
            get_basecaller_configuration=lambda **kwargs: basecaller
        )


def fake_run():
    acquisition = acquisition_pb2.AcquisitionRunInfo(run_id="private-run-id")
    acquisition.config_summary.basecalling_enabled = True
    acquisition.start_time.FromSeconds(int(time.time()) - 1805)
    acquisition.data_read_start_time.FromSeconds(int(time.time()) - 1801)
    runtime = wrappers_pb2.UInt64Value(value=24 * 3600)
    acquisition.target_run_until_criteria.stop_criteria.criteria["runtime"].Pack(runtime)
    metadata = acquisition.bream_info.mux_scan_metadata
    category = metadata.category_groups.add().category.add(name="single_pore")
    category.style.label = "Pore available"
    scan = acquisition.bream_info.mux_scan_results.add()
    scan.counts["single_pore"] = 420
    scan.counts["saturated"] = 5
    return acquisition


class LiveCollectorTests(unittest.TestCase):
    def setUp(self):
        acquisition = fake_run()
        self.connection = FakeConnection(acquisition)
        position = SimpleNamespace(
            name="MN12345",
            device_type="MINION_MK1D",
            protocol_state="protocol_running",
            connect=lambda: self.connection,
        )
        manager = SimpleNamespace(flow_cell_positions=lambda: [position])
        self.collector = MinknowCollector(manager_factory=lambda **kwargs: manager)

    def test_collects_every_model_feature_using_read_only_services(self):
        context = self.collector.inspect()
        row = self.collector.collect(30, context)
        artifact = joblib.load(models_dir() / "calibrated_yield_30min.joblib")
        self.assertFalse(set(artifact["feature_columns"]) - set(row))
        self.assertEqual(context["minknow_version"], "6.10.12")
        self.assertNotIn("private-run-id", context["run_key"])
        self.assertAlmostEqual(row["observed_passed_base_fraction"], 0.9)
        self.assertAlmostEqual(row["observed_average_passed_bases_per_hour"], 1.8e9)
        self.assertAlmostEqual(row["pore_activity_sequencing_percent"], 70.0)
        self.assertEqual(row["pore_scan_pore_available_count"], 420.0)
        self.assertEqual(row["planned_run_limit_hours"], 24.0)
        self.assertEqual(row["observed_target_temperature"], 0.0)
        self.assertEqual(
            set(self.connection.statistics.calls),
            {
                "stream_acquisition_output",
                "stream_basecall_boxplots",
                "stream_duty_time",
                "stream_temperature",
            },
        )

    def test_waits_when_no_minion_run_is_active(self):
        position = SimpleNamespace(
            name="MN12345",
            device_type="MINION_MK1D",
            protocol_state="protocol_idle",
        )
        manager = SimpleNamespace(flow_cell_positions=lambda: [position])
        collector = MinknowCollector(manager_factory=lambda **kwargs: manager)
        with self.assertRaisesRegex(NoActiveRunError, "Waiting"):
            collector.inspect()

    def test_rejects_a_mismatched_core_client_version(self):
        connection = FakeConnection(fake_run(), core_version=(6, 4, 9))
        position = SimpleNamespace(
            name="MN12345",
            device_type="MINION_MK1D",
            protocol_state="protocol_running",
            connect=lambda: connection,
        )
        manager = SimpleNamespace(flow_cell_positions=lambda: [position])
        collector = MinknowCollector(manager_factory=lambda **kwargs: manager)
        with self.assertRaisesRegex(RuntimeError, "requires 6.10"):
            collector.inspect()

    def test_live_monitor_emits_a_calibrated_checkpoint(self):
        engine = RunDecisionEngine(
            CalibratedYieldPredictor(models_dir()), diagnostic_reference()
        )
        monitor = LiveMonitor(self.collector, engine, start_thread=False)
        monitor.poll_once()
        status = monitor.status()
        self.assertEqual(status["mode"], "minknow")
        self.assertEqual(status["current_horizon_minutes"], 30)
        self.assertIn(status["assessment"]["status"], {"GOOD", "BAD", "UNCERTAIN"})
        self.assertTrue(status["read_only"])
        self.assertEqual(status["sample_id"], "Live MinION run")


if __name__ == "__main__":
    unittest.main()
