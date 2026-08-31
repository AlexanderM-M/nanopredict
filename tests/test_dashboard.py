from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace

from nanopredict.diagnose_run import RunDecisionEngine
from nanopredict.paths import diagnostic_reference, models_dir, replay_features, static_dir
from nanopredict.predict_calibrated import CalibratedYieldPredictor
from nanopredict.replay import ReplayCatalog, ReplaySession
from nanopredict.server import make_handler


class ReplayCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = ReplayCatalog(replay_features())

    def test_catalog_is_anonymous_and_naturally_sorted(self):
        listed = self.catalog.list_runs()
        self.assertEqual(len(listed), 171)
        self.assertEqual(listed[0]["sample_id"], "Sample1")
        labels = [item["sample_id"] for item in listed]
        self.assertLess(labels.index("Sample99"), labels.index("Sample100"))
        for item in listed:
            self.assertEqual(set(item), {"sample_id", "device_type", "horizons"})
            self.assertEqual(item["horizons"], [30, 60, 120])

    def test_unknown_sample_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown replay sample"):
            self.catalog.get("SampleDoesNotExist")

    def test_packaged_dashboard_entrypoint_exists(self):
        self.assertTrue((static_dir() / "index.html").is_file())

    def test_javascript_element_ids_exist_in_dashboard(self):
        html = (static_dir() / "index.html").read_text(encoding="utf-8")
        javascript = (static_dir() / "app.js").read_text(encoding="utf-8")
        referenced = set(re.findall(r"getElementById\('([^']+)'\)", javascript))

        class IdCollector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = set()

            def handle_starttag(self, tag, attrs):
                self.ids.update(value for name, value in attrs if name == "id")

        collector = IdCollector()
        collector.feed(html)
        self.assertFalse(referenced - collector.ids)

    def test_dashboard_copy_is_concise(self):
        html = (static_dir() / "index.html").read_text(encoding="utf-8")
        javascript = (static_dir() / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("Calibrated yield forecasts", html)
        self.assertNotIn("item.suggested_check", javascript)
        self.assertIn("LIVE PASSED YIELD", html)
        self.assertIn("NANODX CLASSIFIER CPGS", html)
        self.assertIn("/ 180 NanoDx CpGs", html)
        self.assertIn("Estimated time to 180 CpGs", html)
        self.assertIn("TARGET REACHED", javascript)
        self.assertIn("THRESHOLD REACHED", javascript)
        self.assertIn("rate_cpg_per_minute", javascript)
        self.assertIn("CpG ETA", javascript)

    def test_prediction_display_uses_adaptive_yield_units(self):
        javascript = (static_dir() / "app.js").read_text(encoding="utf-8")
        self.assertIn("function yieldParts(gb)", javascript)
        self.assertIn("unit: 'Mb'", javascript)
        self.assertIn("unit: 'kb'", javascript)
        self.assertIn("yieldText(interval.lower_gb)", javascript)


class ReplaySessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        predictor = CalibratedYieldPredictor(models_dir())
        engine = RunDecisionEngine(predictor, diagnostic_reference())
        cls.session = ReplaySession(ReplayCatalog(replay_features()), engine)

    def test_all_checkpoints_produce_calibrated_assessments(self):
        status = self.session.start("Sample1", target_gb=10, seconds_per_step=120)
        self.assertEqual(status["state"], "running")
        self.assertIsNone(status["assessment"])
        for expected_horizon in (30, 60, 120):
            status = self.session.advance()
            assessment = status["assessment"]
            self.assertEqual(
                assessment["prediction"]["horizon_minutes"], expected_horizon
            )
            self.assertIn(assessment["status"], {"GOOD", "BAD", "UNCERTAIN"})
            self.assertIn("90", assessment["prediction"]["prediction_intervals"])
        self.assertEqual(status["state"], "complete")
        self.assertIsNotNone(status["actual_final_gb"])

    def test_invalid_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            self.session.start("Sample1", target_gb=0)


class PositionApiTests(unittest.TestCase):
    def test_status_selection_and_target_position_reach_application(self):
        class FakeApplication:
            mode = "minknow"
            catalog = SimpleNamespace(list_runs=lambda: [])

            def __init__(self):
                self.status_position = None
                self.configuration = None

            def status(self, position_name=None):
                self.status_position = position_name
                return {"selected_position": position_name}

            def configure(self, target_gb, position_name=None):
                self.configuration = (target_gb, position_name)
                return {"target_gb": target_gb, "selected_position": position_name}

        application = FakeApplication()
        handler_type = make_handler(application)
        handler = object.__new__(handler_type)
        sent = []
        handler._send_json = lambda payload, status=200: sent.append((payload, status))

        handler.path = "/api/status?position=MN22222"
        handler.do_GET()
        self.assertEqual(sent[-1][0]["selected_position"], "MN22222")
        self.assertEqual(application.status_position, "MN22222")

        handler.path = "/api/configure"
        handler._read_json = lambda: {
            "target_gb": 15,
            "position_name": "MN22222",
        }
        handler.do_POST()
        self.assertEqual(sent[-1][0]["target_gb"], 15)
        self.assertEqual(application.configuration, (15.0, "MN22222"))


if __name__ == "__main__":
    unittest.main()
