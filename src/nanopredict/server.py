"""Local-only HTTP server for the Nanopore prediction dashboard."""

from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np

from .diagnose_run import RunDecisionEngine
from .predict_calibrated import CalibratedYieldPredictor

from .paths import diagnostic_reference, models_dir, replay_features, static_dir
from .live import LiveMonitor, MinknowCollector
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
    def __init__(
        self,
        source: str = "auto",
        minknow_host: str = "localhost",
        position: str | None = None,
    ):
        predictor = CalibratedYieldPredictor(models_dir())
        engine = RunDecisionEngine(predictor, diagnostic_reference())
        catalog = ReplayCatalog(replay_features())
        self.replay = ReplaySession(catalog, engine)
        self.catalog = catalog
        if source == "auto":
            source = "minknow" if MinknowCollector.client_available() else "replay"
        if source not in {"minknow", "replay"}:
            raise ValueError(f"Unknown data source: {source}")
        self.mode = source
        self.live = (
            LiveMonitor(MinknowCollector(minknow_host, position), engine)
            if source == "minknow"
            else None
        )

    def status(self, position_name: str | None = None) -> dict[str, Any]:
        return (
            self.live.status(position_name)
            if self.live is not None
            else self.replay.status()
        )

    def configure(
        self, target_gb: float, position_name: str | None = None
    ) -> dict[str, Any]:
        if self.live is None:
            raise ValueError("Live monitoring is not active")
        return self.live.configure(target_gb, position_name)

    def close(self) -> None:
        if self.live is not None:
            self.live.close()


def make_handler(application: DashboardApplication):
    assets = static_dir().resolve()

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "Nanopredict/0.5.2"

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
            request_url = urlparse(self.path)
            path = request_url.path
            if path == "/api/health":
                self._send_json({"ok": True, "service": "nanopredict"})
            elif path == "/api/replays":
                self._send_json({"runs": application.catalog.list_runs()})
            elif path == "/api/status":
                query = parse_qs(request_url.query)
                position_name = query.get("position", [None])[0]
                self._send_json(application.status(position_name))
            elif path.startswith("/api/"):
                self._send_json({"error": "Unknown API endpoint"}, HTTPStatus.NOT_FOUND)
            else:
                self._serve_asset(path)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path == "/api/configure":
                    result = application.configure(
                        float(payload.get("target_gb", 10)),
                        payload.get("position_name"),
                    )
                elif path == "/api/start" and application.mode == "replay":
                    result = application.replay.start(
                        str(payload.get("sample_id", "")),
                        float(payload.get("target_gb", 10)),
                        float(payload.get("seconds_per_step", 8)),
                    )
                elif path == "/api/advance" and application.mode == "replay":
                    result = application.replay.advance()
                elif path == "/api/stop" and application.mode == "replay":
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


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    source: str = "auto",
    minknow_host: str = "localhost",
    position: str | None = None,
) -> None:
    application = DashboardApplication(source, minknow_host, position)
    server = ThreadingHTTPServer((host, port), make_handler(application))
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        application.close()
        server.server_close()
