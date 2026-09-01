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
from nanopredict.live import (
    CheckpointNotReadyError,
    LiveMonitor,
    MinknowCollector,
    NoActiveRunError,
)
from nanopredict.paths import diagnostic_reference, models_dir
from nanopredict.predict_calibrated import CalibratedYieldPredictor


class FakeStatistics:
    def __init__(self):
        self.calls = []
        self.acquisition_output_requests = []

    def stream_acquisition_output(self, **kwargs):
        self.calls.append("stream_acquisition_output")
        self.acquisition_output_requests.append(kwargs)
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
        self.current_acquisition = acquisition
        self.statistics = FakeStatistics()
        version = instance_pb2.GetVersionInfoResponse()
        version.minknow.major, version.minknow.minor, version.minknow.patch = (
            core_version
        )
        version.minknow.full = ".".join(str(item) for item in core_version)
        self.instance = SimpleNamespace(get_version_info=lambda **kwargs: version)
        self.acquisition = SimpleNamespace(
            get_current_acquisition_run=lambda **kwargs: self.current_acquisition
        )
        basecaller = analysis_configuration_pb2.BasecallerConfiguration()
        basecaller.read_filtering.min_qscore.value = 10.0
        self.analysis_configuration = SimpleNamespace(
            get_basecaller_configuration=lambda **kwargs: basecaller
        )


def fake_run(run_id="private-run-id", elapsed_seconds=1805):
    acquisition = acquisition_pb2.AcquisitionRunInfo(run_id=run_id)
    acquisition.config_summary.basecalling_enabled = True
    acquisition.config_summary.bam_reads_enabled = True
    acquisition.config_summary.alignment_enabled = True
    acquisition.config_summary.alignment_reference_files.append("hg38.fa")
    acquisition.config_summary.reads_directory = "C:\\data\\reads"
    acquisition.start_time.FromSeconds(int(time.time()) - elapsed_seconds)
    acquisition.data_read_start_time.FromSeconds(int(time.time()) - elapsed_seconds)
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
        progress = self.collector.collect_live_progress(context)
        artifact = joblib.load(models_dir() / "calibrated_yield_30min.joblib")
        self.assertFalse(set(artifact["feature_columns"]) - set(row))
        self.assertEqual(context["minknow_version"], "6.10.12")
        self.assertEqual(context["collector_mode"], "validated")
        self.assertTrue(context["prediction_available"])
        self.assertTrue(context["bam_reads_enabled"])
        self.assertTrue(context["alignment_enabled"])
        self.assertEqual(context["alignment_reference_files"], ["hg38.fa"])
        self.assertEqual(context["reads_directory"], "C:\\data\\reads")
        self.assertNotIn("private-run-id", context["run_key"])
        self.assertAlmostEqual(row["observed_passed_base_fraction"], 0.9)
        self.assertAlmostEqual(row["observed_average_passed_bases_per_hour"], 1.8e9)
        self.assertAlmostEqual(row["pore_activity_sequencing_percent"], 70.0)
        self.assertEqual(row["pore_scan_pore_available_count"], 420.0)
        self.assertEqual(row["planned_run_limit_hours"], 24.0)
        self.assertEqual(row["observed_target_temperature"], 0.0)
        self.assertEqual(progress["passed_bases"], 900_000_000)
        live_selection = self.connection.statistics.acquisition_output_requests[-1][
            "data_selection"
        ]
        self.assertEqual(live_selection.step, 60)
        self.assertLessEqual(live_selection.end - live_selection.start, 121)
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

    def test_uses_compatibility_mode_for_another_core_version(self):
        connection = FakeConnection(fake_run(), core_version=(6, 4, 9))
        position = SimpleNamespace(
            name="MN12345",
            device_type="MINION_MK1D",
            protocol_state="protocol_running",
            connect=lambda: connection,
        )
        manager = SimpleNamespace(flow_cell_positions=lambda: [position])
        collector = MinknowCollector(manager_factory=lambda **kwargs: manager)
        context = collector.inspect()
        row = collector.collect(30, context)
        self.assertEqual(context["minknow_version"], "6.4.9")
        self.assertEqual(context["collector_mode"], "compatibility")
        self.assertIn("Compatibility mode", context["compatibility_warning"])
        self.assertEqual(row["observed_passed_bases"], 900_000_000)

    def test_optional_statistics_are_non_fatal_in_compatibility_mode(self):
        connection = FakeConnection(fake_run(), core_version=(6, 4, 9))

        def unavailable(**kwargs):
            raise RuntimeError("RPC is not exposed by this Core version")

        connection.statistics.stream_basecall_boxplots = unavailable
        connection.statistics.stream_duty_time = unavailable
        connection.statistics.stream_temperature = unavailable
        connection.analysis_configuration = SimpleNamespace(
            get_basecaller_configuration=unavailable
        )
        position = SimpleNamespace(
            name="MN12345",
            device_type="MINION_MK1D",
            protocol_state="protocol_running",
            connect=lambda: connection,
        )
        manager = SimpleNamespace(flow_cell_positions=lambda: [position])
        collector = MinknowCollector(manager_factory=lambda **kwargs: manager)
        row = collector.collect(30, collector.inspect())
        self.assertEqual(row["observed_passed_bases"], 900_000_000)
        self.assertIsNone(row["observed_qscore_mode"])
        self.assertIsNone(row["observed_temperature"])
        self.assertIsNone(row["minimum_q_score_setting"])

    def test_discovers_all_supported_promethion_position_types(self):
        for device_type in ("PROMETHION", "P2_SOLO", "P2_INTEGRATED"):
            with self.subTest(device_type=device_type):
                position = SimpleNamespace(
                    name=f"{device_type}-position",
                    device_type=device_type,
                    protocol_state="protocol_running",
                )
                manager = SimpleNamespace(flow_cell_positions=lambda: [position])
                collector = MinknowCollector(
                    manager_factory=lambda **kwargs: manager
                )
                self.assertEqual(collector.active_positions(), [position])

    def test_promethion_is_monitored_without_using_the_minion_model(self):
        connection = FakeConnection(fake_run("promethion-private-run"))
        position = SimpleNamespace(
            name="P2S-00001",
            device_type="P2_SOLO",
            protocol_state="protocol_running",
            connect=lambda: connection,
        )
        manager = SimpleNamespace(flow_cell_positions=lambda: [position])
        collector = MinknowCollector(manager_factory=lambda **kwargs: manager)
        context = collector.inspect()

        self.assertEqual(context["device_type"], "PromethION")
        self.assertEqual(context["device_api_type"], "P2_SOLO")
        self.assertFalse(context["prediction_available"])
        self.assertIn("trained on MinION", context["prediction_unavailable_reason"])
        with self.assertRaisesRegex(CheckpointNotReadyError, "PromethION"):
            collector.collect(30, context)

        engine = RunDecisionEngine(
            CalibratedYieldPredictor(models_dir()), diagnostic_reference()
        )
        monitor = LiveMonitor(collector, engine, start_thread=False)
        monitor.poll_once()
        status = monitor.status()
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["device_type"], "PromethION")
        self.assertEqual(status["device_api_type"], "P2_SOLO")
        self.assertIsNone(status["assessment"])
        self.assertIsNone(status["current_horizon_minutes"])
        self.assertEqual(status["live_progress"]["passed_bases"], 900_000_000)
        self.assertFalse(status["prediction_available"])
        self.assertIn("Live yield", status["message"])

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
        self.assertEqual(status["sample_id"], "MN12345")
        self.assertEqual(status["active_position_count"], 1)
        self.assertEqual(status["live_progress"]["passed_bases"], 900_000_000)
        self.assertEqual(status["live_progress"]["progress_percent"], 9.0)
        self.assertGreater(status["live_progress"]["rate_bases_per_minute"], 0)
        self.assertGreater(status["live_progress"]["eta_minutes"], 0)
        self.assertIn("eta_minutes", status["nanodx_cpg"])
        self.assertIn("nanodx_cpg_eta_minutes", status["positions"][0])

        reached = monitor.configure(0.5, "MN12345")
        self.assertTrue(reached["live_progress"]["target_reached"])
        self.assertEqual(reached["live_progress"]["remaining_bases"], 0)

    def test_live_monitor_supervises_and_selects_multiple_positions(self):
        engine = RunDecisionEngine(
            CalibratedYieldPredictor(models_dir()), diagnostic_reference()
        )
        connections = {
            "MN11111": FakeConnection(fake_run("private-run-one")),
            "MN22222": FakeConnection(fake_run("private-run-two")),
        }
        positions = [
            SimpleNamespace(
                name=name,
                device_type="MINION_MK1D",
                protocol_state="protocol_running",
                connect=lambda name=name: connections[name],
            )
            for name in reversed(connections)
        ]
        manager = SimpleNamespace(flow_cell_positions=lambda: positions)
        collector = MinknowCollector(manager_factory=lambda **kwargs: manager)
        monitor = LiveMonitor(collector, engine, start_thread=False)

        monitor.poll_once()
        first = monitor.status()
        second = monitor.status("MN22222")

        self.assertEqual(first["active_position_count"], 2)
        self.assertEqual(
            [item["position_name"] for item in first["positions"]],
            ["MN11111", "MN22222"],
        )
        self.assertEqual(first["selected_position"], "MN11111")
        self.assertEqual(second["position_name"], "MN22222")
        self.assertEqual(second["current_horizon_minutes"], 30)
        self.assertTrue(all(item["prediction_gb"] for item in first["positions"]))

        updated = monitor.configure(15, "MN22222")
        self.assertEqual(updated["target_gb"], 15)
        self.assertEqual(monitor.status("MN11111")["target_gb"], 10)

    def test_new_run_on_a_position_resets_earlier_predictions(self):
        engine = RunDecisionEngine(
            CalibratedYieldPredictor(models_dir()), diagnostic_reference()
        )
        monitor = LiveMonitor(self.collector, engine, start_thread=False)
        monitor.poll_once()
        self.assertEqual(monitor.status()["current_horizon_minutes"], 30)

        self.connection.current_acquisition = fake_run(
            "different-private-run", elapsed_seconds=300
        )
        monitor.poll_once()
        status = monitor.status()
        self.assertIsNone(status["current_horizon_minutes"])
        self.assertIsNone(status["assessment"])
        self.assertEqual(status["history"], [])


if __name__ == "__main__":
    unittest.main()
