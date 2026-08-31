"""Incremental NanoDx classifier CpG counting from aligned MinKNOW modBAMs."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

import bamnostic

from .paths import nanodx_cpg_targets, state_dir


INSTITUTE_CPG_THRESHOLD = 180
NANODX_MODEL = "Capper_et_al"
TARGET_ASSEMBLY = "hg38"
EXPECTED_HG38_FEATURES = 366_217
HG38_CHR1_LENGTH = 248_956_422
_STATE_VERSION = 1
_TARGET_VERSION = "6d2ad818b2b63bc4f6b5320b2348fcbc2d4198f2e173318a23f84e5aaaef6e8d"
_BGZF_EOF = bytes.fromhex("1f8b08040000000000ff0600424302001b00030000000000000000")
_MM_GROUP = re.compile(r"^([ACGTUN])([+-])([a-z]+|[0-9]+)([.?]?)(?:,(.*))?$")


def _normalise_chromosome(name: str) -> str:
    value = str(name)
    if value.startswith("chr"):
        return value
    if value in {"M", "MT"}:
        return "chrM"
    return f"chr{value}"


class NanoDxTargets:
    """Compact mapping from hg38 CpG starts to Capper model feature indices."""

    def __init__(self, path: Path):
        self.path = Path(path)
        mutable: dict[str, dict[int, list[int]]] = {}
        feature_count = 0
        with gzip.open(self.path, "rt", encoding="ascii") as handle:
            for line in handle:
                if not line or line.startswith("#"):
                    continue
                chrom, start, _end, _probe = line.rstrip("\n").split("\t")
                mutable.setdefault(chrom, {}).setdefault(int(start), []).append(
                    feature_count
                )
                feature_count += 1
        if feature_count != EXPECTED_HG38_FEATURES:
            raise ValueError(
                f"NanoDx target table contains {feature_count} features; "
                f"expected {EXPECTED_HG38_FEATURES}."
            )
        self.feature_count = feature_count
        self._starts = {
            chrom: {position: tuple(indices) for position, indices in positions.items()}
            for chrom, positions in mutable.items()
        }

    def probes_at(self, chromosome: str, cpg_start: int) -> tuple[int, ...]:
        return self._starts.get(_normalise_chromosome(chromosome), {}).get(
            int(cpg_start), ()
        )


@lru_cache(maxsize=1)
def default_nanodx_targets() -> NanoDxTargets:
    return NanoDxTargets(nanodx_cpg_targets())


@dataclass
class FileScan:
    covered: dict[int, int]
    confidence_histogram: list[int]
    reads: int
    tagged_reads: int


def _tag(read: Any, primary: str, legacy: str) -> Any:
    try:
        return read.get_tag(primary)
    except KeyError:
        return read.get_tag(legacy)


def _reverse_complement(sequence: str) -> str:
    return sequence.translate(str.maketrans("ACGTNacgtn", "TGCANtgcan"))[::-1]


def modification_confidences(read: Any) -> dict[int, int]:
    """Return NanoDx-relevant call confidence by original read coordinate."""
    mm = str(_tag(read, "MM", "Mm"))
    ml = tuple(int(value) for value in _tag(read, "ML", "Ml"))
    sequence = str(read.query_sequence)
    if not sequence or sequence == "*":
        return {}
    try:
        if int(read.get_tag("MN")) != len(sequence):
            return {}
    except KeyError:
        pass

    original = _reverse_complement(sequence) if read.is_reverse else sequence
    canonical_positions: dict[str, list[int]] = {}
    probabilities: dict[int, int] = {}
    ml_index = 0
    for raw_group in mm.rstrip(";").split(";"):
        if not raw_group:
            continue
        match = _MM_GROUP.match(raw_group)
        if match is None:
            raise ValueError("Unsupported MM tag encoding")
        base, strand, codes, _mode, encoded = match.groups()
        code_count = 1 if codes.isdigit() else len(codes)
        deltas = [] if not encoded else [int(value) for value in encoded.split(",")]
        required = len(deltas) * code_count
        if ml_index + required > len(ml):
            raise ValueError("MM and ML tag lengths do not agree")
        group_probabilities = ml[ml_index : ml_index + required]
        ml_index += required
        if (base, strand) != ("C", "+"):
            continue
        positions = canonical_positions.setdefault(
            base, [index for index, letter in enumerate(original) if letter.upper() == base]
        )
        base_index = -1
        for call_index, delta in enumerate(deltas):
            base_index += delta + 1
            if base_index >= len(positions):
                raise ValueError("MM tag coordinate exceeds read sequence")
            original_position = positions[base_index]
            if original_position >= len(original) - 27:
                continue
            offset = call_index * code_count
            combined = min(sum(group_probabilities[offset : offset + code_count]), 255)
            probabilities[original_position] = min(
                probabilities.get(original_position, 0) + combined,
                255,
            )

    return {
        position: max(probability, 255 - probability)
        for position, probability in probabilities.items()
    }


def _reference_positions(
    cigartuples: Iterable[tuple[int, int]] | None,
    reference_start: int,
    requested: Iterable[int],
) -> dict[int, int]:
    wanted = sorted(set(int(position) for position in requested))
    if not wanted or not cigartuples:
        return {}
    output: dict[int, int] = {}
    query_cursor = 0
    reference_cursor = int(reference_start)
    wanted_index = 0
    for operation, length in cigartuples:
        length = int(length)
        consumes_query = operation in {0, 1, 4, 7, 8}
        consumes_reference = operation in {0, 2, 3, 7, 8}
        if operation in {0, 7, 8}:
            query_end = query_cursor + length
            while wanted_index < len(wanted) and wanted[wanted_index] < query_cursor:
                wanted_index += 1
            while wanted_index < len(wanted) and wanted[wanted_index] < query_end:
                position = wanted[wanted_index]
                output[position] = reference_cursor + position - query_cursor
                wanted_index += 1
        if consumes_query:
            query_cursor += length
        if consumes_reference:
            reference_cursor += length
        if wanted_index >= len(wanted):
            break
    return output


def _reference_lengths(alignment: Any) -> list[tuple[str, int]]:
    """Read reference lengths from bamnostic/pysam or a small test double."""
    names = getattr(alignment, "references", None)
    lengths = getattr(alignment, "lengths", None)
    if names is not None and lengths is not None:
        return [(str(name), int(length)) for name, length in zip(names, lengths)]

    header = getattr(alignment, "header", {})
    sequences = header.get("SQ", []) if hasattr(header, "get") else []
    if sequences:
        return [
            (str(sequence["SN"]), int(sequence["LN"]))
            for sequence in sequences
        ]

    # Kept for the deliberately minimal test alignment used by this project.
    pairs = []
    for value in getattr(header, "values", lambda: [])():
        if isinstance(value, (tuple, list)) and len(value) == 2:
            pairs.append((str(value[0]), int(value[1])))
    return pairs


def _validate_hg38_alignment(alignment: Any) -> None:
    chr1_lengths = [
        length
        for name, length in _reference_lengths(alignment)
        if _normalise_chromosome(name) == "chr1"
    ]
    if not chr1_lengths:
        raise ValueError("The BAM header does not contain chromosome 1")
    if HG38_CHR1_LENGTH not in chr1_lengths:
        raise ValueError("The live BAM is not aligned to the supported hg38 assembly")


def scan_bam(
    path: Path,
    targets: NanoDxTargets,
    opener: Callable[..., Any] = bamnostic.AlignmentFile,
) -> FileScan:
    covered: dict[int, int] = {}
    histogram = [0] * 256
    reads = 0
    tagged_reads = 0
    with opener(str(path), "rb") as alignment:
        _validate_hg38_alignment(alignment)
        for read in alignment:
            reads += 1
            if read.is_unmapped or read.is_secondary or read.is_supplementary:
                continue
            try:
                calls = modification_confidences(read)
            except (KeyError, TypeError, ValueError):
                continue
            if not calls:
                continue
            tagged_reads += 1
            for confidence in calls.values():
                histogram[confidence] += 1
            stored_positions = {
                (len(read.query_sequence) - 1 - position) if read.is_reverse else position
                for position in calls
            }
            mappings = _reference_positions(
                read.cigartuples, read.reference_start, stored_positions
            )
            for original_position, confidence in calls.items():
                stored_position = (
                    len(read.query_sequence) - 1 - original_position
                    if read.is_reverse
                    else original_position
                )
                reference_position = mappings.get(stored_position)
                if reference_position is None:
                    continue
                cpg_start = reference_position - 1 if read.is_reverse else reference_position
                for feature in targets.probes_at(read.reference_name, cpg_start):
                    covered[feature] = max(covered.get(feature, 0), confidence)
    return FileScan(covered, histogram, reads, tagged_reads)


def _percentile_threshold(histogram: list[int], percentile: float = 0.10) -> int:
    total = sum(histogram)
    if total == 0:
        return 255
    rank = max(1, math.ceil(total * percentile))
    cumulative = 0
    for confidence, count in enumerate(histogram):
        cumulative += count
        if cumulative >= rank:
            return confidence
    return 255


def _bam_is_complete(path: Path) -> bool:
    try:
        if path.stat().st_size < len(_BGZF_EOF):
            return False
        with path.open("rb") as handle:
            handle.seek(-len(_BGZF_EOF), os.SEEK_END)
            return handle.read() == _BGZF_EOF
    except OSError:
        return False


class NanoDxCpgCounter:
    """Persistent, incremental state for one anonymous MinKNOW run key."""

    def __init__(
        self,
        targets: NanoDxTargets,
        run_key: str,
        persistence_root: Path | None = None,
        opener: Callable[..., Any] = bamnostic.AlignmentFile,
        ready_check: Callable[[Path], bool] = _bam_is_complete,
    ):
        self.targets = targets
        self.run_key = run_key
        self.opener = opener
        self.ready_check = ready_check
        try:
            self.persistence_root = persistence_root or state_dir() / "nanodx-cpg"
            self.persistence_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.persistence_root = None
        self.processed: set[str] = set()
        self.covered: dict[int, int] = {}
        self.histogram = [0] * 256
        self.reads = 0
        self.tagged_reads = 0
        self._load()

    @property
    def state_path(self) -> Path | None:
        if self.persistence_root is None:
            return None
        return self.persistence_root / f"{self.run_key}.json.gz"

    @staticmethod
    def _fingerprint(path: Path) -> str:
        stat = path.stat()
        payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load(self) -> None:
        if self.state_path is None:
            return
        try:
            with gzip.open(self.state_path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            if (
                payload.get("version") != _STATE_VERSION
                or payload.get("target_version") != _TARGET_VERSION
            ):
                return
            self.processed = set(payload.get("processed", []))
            self.covered = {
                int(feature): int(confidence)
                for feature, confidence in payload.get("covered", {}).items()
            }
            histogram = [int(value) for value in payload.get("histogram", [])]
            if len(histogram) == 256:
                self.histogram = histogram
            self.reads = int(payload.get("reads", 0))
            self.tagged_reads = int(payload.get("tagged_reads", 0))
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return

    def _save(self) -> None:
        if self.persistence_root is None or self.state_path is None:
            return
        payload = {
            "version": _STATE_VERSION,
            "target_version": _TARGET_VERSION,
            "processed": sorted(self.processed),
            "covered": {str(key): value for key, value in self.covered.items()},
            "histogram": self.histogram,
            "reads": self.reads,
            "tagged_reads": self.tagged_reads,
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

    def scan_directory(self, root: Path) -> None:
        root = Path(root)
        if not root.is_dir():
            return
        for path in sorted(root.rglob("*.bam")):
            try:
                fingerprint = self._fingerprint(path)
            except OSError:
                continue
            if fingerprint in self.processed or not self.ready_check(path):
                continue
            result = scan_bam(path, self.targets, self.opener)
            for feature, confidence in result.covered.items():
                self.covered[feature] = max(self.covered.get(feature, 0), confidence)
            self.histogram = [
                left + right
                for left, right in zip(self.histogram, result.confidence_histogram)
            ]
            self.reads += result.reads
            self.tagged_reads += result.tagged_reads
            self.processed.add(fingerprint)
            self._save()

    def status(self) -> dict[str, Any]:
        threshold = _percentile_threshold(self.histogram)
        count = sum(confidence >= threshold for confidence in self.covered.values())
        reached = count >= INSTITUTE_CPG_THRESHOLD
        return {
            "state": "reached" if reached else "collecting",
            "count": count,
            "threshold": INSTITUTE_CPG_THRESHOLD,
            "remaining": max(INSTITUTE_CPG_THRESHOLD - count, 0),
            "progress_percent": min(count * 100.0 / INSTITUTE_CPG_THRESHOLD, 100.0),
            "threshold_reached": reached,
            "model": NANODX_MODEL,
            "assembly": TARGET_ASSEMBLY,
            "model_features": self.targets.feature_count,
            "files_processed": len(self.processed),
            "reads_scanned": self.reads,
            "tagged_reads": self.tagged_reads,
            "message": (
                "Institute report threshold reached"
                if reached
                else f"{max(INSTITUTE_CPG_THRESHOLD - count, 0)} CpGs remaining"
            ),
        }


class NanoDxCpgMonitor:
    """Non-blocking worker that follows completed BAM batches for one position."""

    def __init__(
        self,
        targets: NanoDxTargets,
        poll_seconds: float = 20.0,
        start_thread: bool = True,
        persistence_root: Path | None = None,
    ):
        self.targets = targets
        self.poll_seconds = poll_seconds
        self.persistence_root = persistence_root
        self._lock = threading.RLock()
        self._event = threading.Event()
        self._stop = threading.Event()
        self._context: dict[str, Any] | None = None
        self._counter: NanoDxCpgCounter | None = None
        self._status = self._waiting("Waiting for MinKNOW BAM output")
        self._thread: threading.Thread | None = None
        if start_thread:
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="nanopredict-cpg"
            )
            self._thread.start()

    @staticmethod
    def _waiting(message: str, state: str = "waiting") -> dict[str, Any]:
        return {
            "state": state,
            "count": 0,
            "threshold": INSTITUTE_CPG_THRESHOLD,
            "remaining": INSTITUTE_CPG_THRESHOLD,
            "progress_percent": 0.0,
            "threshold_reached": False,
            "model": NANODX_MODEL,
            "assembly": TARGET_ASSEMBLY,
            "model_features": EXPECTED_HG38_FEATURES,
            "files_processed": 0,
            "reads_scanned": 0,
            "tagged_reads": 0,
            "message": message,
        }

    def update_context(self, context: dict[str, Any]) -> None:
        plain = {
            "run_key": context["run_key"],
            "output_path": context.get("output_path"),
            "reads_directory": context.get("reads_directory"),
            "bam_reads_enabled": bool(context.get("bam_reads_enabled")),
            "alignment_enabled": bool(context.get("alignment_enabled")),
        }
        with self._lock:
            if self._counter is None or self._counter.run_key != plain["run_key"]:
                self._counter = NanoDxCpgCounter(
                    self.targets,
                    plain["run_key"],
                    persistence_root=self.persistence_root,
                )
                self._status = self._counter.status()
            self._context = plain
        self._event.set()
        if self._thread is None:
            self.scan_once()

    def set_waiting(self) -> None:
        with self._lock:
            self._context = None
            self._counter = None
            self._status = self._waiting("Waiting for an active sequencing run")

    def _run(self) -> None:
        while not self._stop.is_set():
            self._event.wait(self.poll_seconds)
            self._event.clear()
            if not self._stop.is_set():
                self.scan_once()

    def scan_once(self) -> None:
        with self._lock:
            context = dict(self._context) if self._context is not None else None
            counter = self._counter
        if context is None or counter is None:
            return
        if not context["bam_reads_enabled"]:
            status = self._waiting("Enable BAM output in MinKNOW", "unavailable")
        elif not context["alignment_enabled"]:
            status = self._waiting("Enable live hg38 alignment in MinKNOW", "unavailable")
        else:
            # The acquisition summary points directly at the current read tree;
            # protocol output can be a broader parent directory on some installs.
            selected = context.get("reads_directory") or context.get("output_path")
            root = Path(selected) if selected else None
            if root is None or not root.is_dir():
                status = self._waiting("Waiting for the MinKNOW output directory")
            else:
                try:
                    counter.scan_directory(root)
                    status = counter.status()
                    if not counter.processed:
                        status["state"] = "waiting"
                        status["message"] = "Waiting for a completed BAM batch"
                    elif counter.tagged_reads == 0:
                        status = self._waiting(
                            "No MM/ML methylation tags found in completed BAMs",
                            "unavailable",
                        )
                        status["files_processed"] = len(counter.processed)
                        status["reads_scanned"] = counter.reads
                except (OSError, ValueError) as exc:
                    status = self._waiting(str(exc), "error")
        status["last_update"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._status = status

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def close(self) -> None:
        self._stop.set()
        self._event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.poll_seconds + 1, 5))
