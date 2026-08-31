"""Version-independent live yield collection from completed MinKNOW BAM batches."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import bamnostic

from .nanodx_cpg import _bam_is_complete
from .paths import state_dir


_START_TIME_PATTERN = re.compile(r"(?<!\d)(\d{8}_\d{4})(?!\d)")


class BamFallbackUnavailable(RuntimeError):
    """Raised when no recent MinKNOW BAM output can be discovered."""


@dataclass(frozen=True)
class BamPosition:
    """Minimal position descriptor understood by the shared live supervisor."""

    name: str
    root: Path
    device_type: str = "MINION"
    protocol_state: str = "protocol_running"


def default_bam_search_roots(configured: Path | str | None = None) -> list[Path]:
    """Return existing explicit/environment/default MinKNOW output roots."""
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    else:
        environment = os.environ.get("NANOPREDICT_BAM_DIR")
        if environment:
            candidates.append(Path(environment))
        elif os.name == "nt":
            candidates.append(Path("C:/data"))
        else:
            candidates.extend((Path("/data"), Path.home() / "data"))

    output = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in seen:
            output.append(resolved)
            seen.add(resolved)
    return output


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run_root(path: Path, search_root: Path) -> Path:
    for parent in path.parents:
        if parent.name.lower() in {"bam_pass", "bam_fail"}:
            return parent.parent
        if parent == search_root:
            break
    return path.parent


def _is_failed_bam(path: Path) -> bool:
    lowered = {part.lower() for part in path.parts}
    return "bam_fail" in lowered or "fail" in path.name.lower()


def _query_length(read: Any) -> int:
    sequence = getattr(read, "query_sequence", None)
    if sequence and sequence != "*":
        return len(sequence)
    value = getattr(read, "query_length", 0)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


class BamYieldCounter:
    """Persistent cumulative yield counter for one anonymous BAM run root."""

    def __init__(
        self,
        root: Path,
        run_key: str,
        persistence_root: Path | None = None,
        opener: Callable[..., Any] = bamnostic.AlignmentFile,
        ready_check: Callable[[Path], bool] = _bam_is_complete,
    ):
        self.root = Path(root)
        self.run_key = run_key
        self.opener = opener
        self.ready_check = ready_check
        self.processed: set[str] = set()
        self.passed_bases = 0
        self.failed_bases = 0
        self.total_reads = 0
        self.passed_reads = 0
        try:
            self.persistence_root = persistence_root or state_dir() / "bam-yield"
            self.persistence_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.persistence_root = None
        self._load()

    @property
    def state_path(self) -> Path | None:
        if self.persistence_root is None:
            return None
        return self.persistence_root / f"{self.run_key}.json.gz"

    def _load(self) -> None:
        if self.state_path is None:
            return
        try:
            with gzip.open(self.state_path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("version") != 1:
                return
            self.processed = set(payload.get("processed", []))
            self.passed_bases = int(payload.get("passed_bases", 0))
            self.failed_bases = int(payload.get("failed_bases", 0))
            self.total_reads = int(payload.get("total_reads", 0))
            self.passed_reads = int(payload.get("passed_reads", 0))
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return

    def _save(self) -> None:
        if self.persistence_root is None or self.state_path is None:
            return
        payload = {
            "version": 1,
            "processed": sorted(self.processed),
            "passed_bases": self.passed_bases,
            "failed_bases": self.failed_bases,
            "total_reads": self.total_reads,
            "passed_reads": self.passed_reads,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.run_key}.", suffix=".tmp", dir=self.persistence_root
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with gzip.open(temporary, "wt", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            temporary.replace(self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    def scan(self) -> None:
        changed = False
        for path in sorted(self.root.rglob("*.bam")):
            try:
                fingerprint = _fingerprint(path)
            except OSError:
                continue
            if fingerprint in self.processed or not self.ready_check(path):
                continue
            failed = _is_failed_bam(path)
            bases = 0
            reads = 0
            try:
                with self.opener(str(path), "rb") as alignment:
                    for read in alignment:
                        if (
                            getattr(read, "is_secondary", False)
                            or getattr(read, "is_supplementary", False)
                        ):
                            continue
                        bases += _query_length(read)
                        reads += 1
            except (OSError, TypeError, ValueError):
                continue
            if failed:
                self.failed_bases += bases
            else:
                self.passed_bases += bases
                self.passed_reads += reads
            self.total_reads += reads
            self.processed.add(fingerprint)
            changed = True
        if changed:
            self._save()

    def status(self, elapsed_seconds: float) -> dict[str, float]:
        return {
            "observed_seconds": max(float(elapsed_seconds), 0.0),
            "passed_bases": float(self.passed_bases),
            "failed_bases": float(self.failed_bases),
            "total_reads": float(self.total_reads),
            "passed_reads": float(self.passed_reads),
        }


class BamFallbackCollector:
    """Discover recent MinKNOW run folders and expose BAM-derived live yield."""

    def __init__(
        self,
        search_root: Path | str | None = None,
        position_name: str | None = None,
        recent_hours: float = 12.0,
        clock: Callable[[], float] = time.time,
        opener: Callable[..., Any] = bamnostic.AlignmentFile,
        ready_check: Callable[[Path], bool] = _bam_is_complete,
        persistence_root: Path | None = None,
    ):
        self.search_roots = default_bam_search_roots(search_root)
        self.position_name = position_name
        self.recent_seconds = recent_hours * 3600.0
        self.clock = clock
        self.opener = opener
        self.ready_check = ready_check
        self.persistence_root = persistence_root
        self._counters: dict[str, BamYieldCounter] = {}
        self._cached_positions: list[BamPosition] = []
        self._last_discovery = 0.0

    def _discover(self) -> list[BamPosition]:
        now = float(self.clock())
        if self._cached_positions and now - self._last_discovery < 60.0:
            return self._cached_positions
        roots: dict[Path, float] = {}
        for search_root in self.search_roots:
            for path in search_root.rglob("*.bam"):
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if modified < now - self.recent_seconds:
                    continue
                run_root = _run_root(path, search_root)
                roots[run_root] = max(roots.get(run_root, 0.0), modified)
        positions = []
        for root, _modified in sorted(roots.items(), key=lambda item: item[1], reverse=True):
            digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:6].upper()
            name = f"BAM-{digest}"
            if self.position_name and self.position_name != name:
                continue
            positions.append(BamPosition(name=name, root=root))
        self._cached_positions = positions
        self._last_discovery = now
        return positions

    def active_positions(self) -> list[BamPosition]:
        positions = self._discover()
        if not self.search_roots:
            raise BamFallbackUnavailable(
                "MinKNOW API unavailable and no BAM search directory was found. "
                "Set NANOPREDICT_BAM_DIR or launch with --bam-dir."
            )
        if not positions:
            raise BamFallbackUnavailable(
                "MinKNOW API unavailable; waiting for a recent completed BAM batch."
            )
        return positions

    @staticmethod
    def _start_time(root: Path, bam_paths: Iterable[Path]) -> float:
        for part in reversed(root.parts):
            match = _START_TIME_PATTERN.search(part)
            if match:
                try:
                    return datetime.strptime(match.group(1), "%Y%m%d_%H%M").timestamp()
                except ValueError:
                    pass
        times = []
        for path in bam_paths:
            try:
                times.append(path.stat().st_mtime)
            except OSError:
                continue
        return min(times) if times else time.time()

    def inspect_position(self, position: BamPosition) -> dict[str, Any]:
        bam_paths = list(position.root.rglob("*.bam"))
        started = self._start_time(position.root, bam_paths)
        run_key = hashlib.sha256(str(position.root).encode("utf-8")).hexdigest()[:12]
        return {
            "position": position,
            "connection": None,
            "acquisition": None,
            "run_id": None,
            "run_key": run_key,
            "elapsed_seconds": max(float(self.clock()) - started, 0.0),
            "minknow_version": "API unavailable",
            "api_client_version": None,
            "collector_mode": "bam_fallback",
            "compatibility_warning": (
                "BAM fallback active: live yield and CpGs are available; calibrated "
                "final-yield prediction requires a compatible MinKNOW statistics API."
            ),
            "prediction_available": False,
            "output_path": str(position.root),
            "reads_directory": str(position.root),
            "bam_reads_enabled": True,
            "alignment_enabled": True,
            "alignment_reference_files": [],
        }

    def collect_live_progress(self, context: dict[str, Any]) -> dict[str, float]:
        selected = context.get("reads_directory") or context.get("output_path")
        if not selected:
            raise BamFallbackUnavailable("No MinKNOW BAM output directory is available")
        run_key = str(context["run_key"])
        counter = self._counters.get(run_key)
        if counter is None:
            counter = BamYieldCounter(
                Path(selected),
                run_key,
                persistence_root=self.persistence_root,
                opener=self.opener,
                ready_check=self.ready_check,
            )
            self._counters[run_key] = counter
        counter.scan()
        return counter.status(float(context.get("elapsed_seconds", 0.0)))
