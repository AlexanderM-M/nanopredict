"""One-command launcher for the local Nanopore prediction dashboard."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from .paths import state_dir
from .server import serve


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _url(port: int, path: str = "/") -> str:
    return f"http://{DEFAULT_HOST}:{port}{path}"


def _request(port: int, path: str, method: str = "GET") -> dict | None:
    data = b"{}" if method == "POST" else None
    request = urllib.request.Request(
        _url(port, path), data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _is_running(port: int) -> bool:
    response = _request(port, "/api/health")
    return bool(response and response.get("service") == "nanopredict")


def _start_background(
    port: int,
    open_browser: bool,
    source: str,
    minknow_host: str,
    position: str | None,
    bam_dir: str | None,
) -> int:
    if _is_running(port):
        print(f"Nanopredict is already running at {_url(port)}")
        if open_browser:
            webbrowser.open(_url(port))
        return 0

    runtime = state_dir()
    log_path = runtime / "nanopredict.log"
    command = [
        sys.executable,
        "-m",
        "nanopredict",
        "_serve",
        "--port",
        str(port),
        "--source",
        source,
        "--minknow-host",
        minknow_host,
    ]
    if position:
        command.extend(["--position", position])
    if bam_dir:
        command.extend(["--bam-dir", bam_dir])
    kwargs: dict = {
        "cwd": str(runtime),
        "stdin": subprocess.DEVNULL,
    }
    log_handle = log_path.open("a", encoding="utf-8")
    kwargs["stdout"] = log_handle
    kwargs["stderr"] = subprocess.STDOUT
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(command, **kwargs)
    finally:
        log_handle.close()

    for _ in range(60):
        if _is_running(port):
            print(f"Nanopredict is running at {_url(port)}")
            if open_browser:
                webbrowser.open(_url(port))
            return 0
        time.sleep(0.25)
    print(f"Nanopredict did not start. Check {log_path}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanopredict",
        description="Start the local Nanopore yield prediction dashboard.",
    )
    parser.add_argument(
        "command", nargs="?", default="start", choices=("start", "status", "stop", "_serve")
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument(
        "--source",
        choices=("auto", "minknow", "replay"),
        default="auto",
        help="Data source. Auto uses MinKNOW when its client is installed.",
    )
    parser.add_argument("--minknow-host", default="localhost")
    parser.add_argument(
        "--bam-dir",
        help=(
            "MinKNOW output directory for version-independent BAM fallback. "
            "Usually detected automatically."
        ),
    )
    parser.add_argument(
        "--position",
        help="Monitor only this MinKNOW position instead of all active positions",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Use anonymous historical runs (alias for --source replay).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = "replay" if args.replay else args.source
    if not 1024 <= args.port <= 65535:
        print("Port must be between 1024 and 65535.", file=sys.stderr)
        return 2

    if args.command == "_serve":
        serve(
            port=args.port,
            source=source,
            minknow_host=args.minknow_host,
            position=args.position,
            bam_dir=args.bam_dir,
        )
        return 0
    if args.command == "status":
        if _is_running(args.port):
            print(f"Nanopredict is running at {_url(args.port)}")
            return 0
        print("Nanopredict is not running.")
        return 1
    if args.command == "stop":
        if not _is_running(args.port):
            print("Nanopredict is not running.")
            return 0
        _request(args.port, "/api/shutdown", method="POST")
        for _ in range(20):
            if not _is_running(args.port):
                print("Nanopredict stopped.")
                return 0
            time.sleep(0.25)
        print("Nanopredict is still stopping.", file=sys.stderr)
        return 1
    if args.foreground:
        if not args.no_browser:
            webbrowser.open(_url(args.port))
        serve(
            port=args.port,
            source=source,
            minknow_host=args.minknow_host,
            position=args.position,
            bam_dir=args.bam_dir,
        )
        return 0
    return _start_background(
        args.port,
        not args.no_browser,
        source,
        args.minknow_host,
        args.position,
        args.bam_dir,
    )
