"""Local-only HTTP server for the Nanopore prediction dashboard."""

from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

from .diagnose_run import RunDecisionEngine
from .predict_calibrated import CalibratedYieldPredictor

from .paths import diagnostic_reference, models_dir, replay_features, static_dir
from .replay import ReplayCatalog, ReplaySession


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


class DashboardApplication:
    def __init__(self):
        predictor = CalibratedYieldPredictor(models_dir())
        engine = RunDecisionEngine(predictor, diagnostic_reference())
        catalog = ReplayCatalog(replay_features())
        self.replay = ReplaySession(catalog, engine)
        self.catalog = catalog


def make_handler(application: DashboardApplication):
    assets = static_dir().resolve()

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "Nanopredict/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(_json_safe(payload), allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                raise ValueError("Request is too large")
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _serve_asset(self, requested: str) -> None:
            relative = "index.html" if requested in ("", "/") else requested.lstrip("/")
            candidate = (assets / relative).resolve()
            if assets not in candidate.parents and candidate != assets:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/health":
                self._send_json({"ok": True, "service": "nanopredict"})
            elif path == "/api/replays":
                self._send_json({"runs": application.catalog.list_runs()})
            elif path == "/api/status":
                self._send_json(application.replay.status())
            elif path.startswith("/api/"):
                self._send_json({"error": "Unknown API endpoint"}, HTTPStatus.NOT_FOUND)
            else:
                self._serve_asset(path)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path == "/api/start":
                    result = application.replay.start(
                        str(payload.get("sample_id", "")),
                        float(payload.get("target_gb", 10)),
                        float(payload.get("seconds_per_step", 8)),
                    )
                elif path == "/api/advance":
                    result = application.replay.advance()
                elif path == "/api/stop":
                    result = application.replay.stop()
                elif path == "/api/shutdown":
                    result = {"ok": True, "message": "Dashboard is stopping."}
                    threading.Thread(
                        target=self.server.shutdown, daemon=True
                    ).start()
                else:
                    self._send_json(
                        {"error": "Unknown API endpoint"}, HTTPStatus.NOT_FOUND
                    )
                    return
                self._send_json(result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception:
                self._send_json(
                    {"error": "The dashboard could not complete that action."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

    return DashboardHandler


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    application = DashboardApplication()
    server = ThreadingHTTPServer((host, port), make_handler(application))
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
