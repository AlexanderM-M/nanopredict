"""Operator-facing preflight checks for live Nanopredict monitoring."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any, Callable

import bamnostic

from . import __version__
from .live import MinknowCollector, SUPPORTED_DEVICE_TYPES
from .nanodx_cpg import (
    _bam_is_complete,
    _path_barcode,
    _read_barcode,
    _validate_hg38_alignment,
)


class DoctorReport:
    def __init__(self) -> None:
        self.checks: list[dict[str, str]] = []

    def add(self, name: str, status: str, message: str) -> None:
        self.checks.append({"name": name, "status": status, "message": message})

    @property
    def ok(self) -> bool:
        return not any(item["status"] == "FAIL" for item in self.checks)

    def payload(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": self.checks}


def _first_completed_bam(roots: list[Path]) -> Path | None:
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.bam"):
                if _bam_is_complete(path):
                    return path
        except OSError:
            continue
    return None


def _check_bam(path: Path, report: DoctorReport) -> None:
    tagged = 0
    inspected = 0
    barcodes: set[str] = set()
    try:
        with bamnostic.AlignmentFile(str(path), "rb") as alignment:
            try:
                _validate_hg38_alignment(alignment)
            except ValueError as exc:
                report.add("hg38 alignment", "FAIL", str(exc))
                return
            report.add(
                "hg38 alignment", "PASS", "Completed BAM is aligned to hg38."
            )
            fallback = _path_barcode(path)
            for read in alignment:
                if getattr(read, "is_secondary", False) or getattr(
                    read, "is_supplementary", False
                ):
                    continue
                inspected += 1
                barcode = _read_barcode(read, fallback)
                if barcode:
                    barcodes.add(barcode)
                try:
                    read.get_tag("MM")
                    read.get_tag("ML")
                    tagged += 1
                except (KeyError, TypeError, ValueError):
                    try:
                        read.get_tag("Mm")
                        read.get_tag("Ml")
                        tagged += 1
                    except (KeyError, TypeError, ValueError):
                        pass
                if inspected >= 500:
                    break
    except Exception as exc:
        report.add("BAM readability", "FAIL", f"Could not inspect BAM: {exc}")
        return

    if inspected == 0:
        report.add("MM/ML tags", "WARN", "Completed BAM contains no primary reads yet.")
    elif tagged == 0:
        report.add("MM/ML tags", "FAIL", "No MM/ML tags found in sampled primary reads.")
    else:
        report.add(
            "MM/ML tags",
            "PASS",
            f"MM/ML tags found in {tagged}/{inspected} sampled primary reads.",
        )
    report.add(
        "barcodes",
        "PASS" if barcodes else "WARN",
        (
            f"Detected {len(barcodes)} barcode{'s' if len(barcodes) != 1 else ''}."
            if barcodes
            else "No barcode tags or barcode directory names detected."
        ),
    )


def run_doctor(
    host: str = "localhost",
    position_name: str | None = None,
    bam_dir: str | None = None,
    as_json: bool = False,
    manager_factory: Callable[..., Any] | None = None,
) -> int:
    """Run read-only setup checks, print a report, and return a process code."""
    report = DoctorReport()
    version = platform.python_version()
    major_minor = tuple(int(value) for value in platform.python_version_tuple()[:2])
    supported_python = (3, 9) <= major_minor <= (3, 12)
    report.add(
        "Python",
        "PASS" if supported_python else "FAIL",
        f"Python {version}; Nanopredict {__version__} supports Python 3.9–3.12.",
    )

    collector = MinknowCollector(
        host=host, position_name=position_name, manager_factory=manager_factory
    )
    report.add(
        "MinKNOW API client",
        "PASS" if collector.client_available() or manager_factory else "FAIL",
        f"Client version: {collector.client_version() or 'not installed'}.",
    )
    positions: list[Any] = []
    try:
        positions = list(collector._manager().flow_cell_positions())
        report.add("MinKNOW connection", "PASS", f"Connected to {host}.")
    except Exception as exc:
        report.add("MinKNOW connection", "FAIL", f"Cannot connect to {host}: {exc}")

    supported = [
        item
        for item in positions
        if str(getattr(item, "device_type", "")).upper() in SUPPORTED_DEVICE_TYPES
        and (position_name is None or getattr(item, "name", None) == position_name)
    ]
    active = [
        item
        for item in supported
        if str(getattr(item, "protocol_state", "")).lower() == "protocol_running"
    ]
    if not supported:
        report.add("sequencing positions", "WARN", "No supported position detected.")
    elif not active:
        report.add(
            "active runs",
            "WARN",
            f"Detected {len(supported)} supported position(s), but no run is active.",
        )
    else:
        report.add("active runs", "PASS", f"Detected {len(active)} active run(s).")

    roots: list[Path] = [Path(bam_dir)] if bam_dir else []
    for position in active:
        try:
            context = collector.inspect_position(position)
        except Exception as exc:
            report.add("run metadata", "FAIL", f"Could not inspect an active run: {exc}")
            continue
        report.add(
            "MinKNOW Core compatibility",
            "PASS" if context["collector_mode"] == "validated" else "WARN",
            f"Core {context['minknow_version']} is using {context['collector_mode']} mode.",
        )
        for key, label, action in (
            ("basecalling_enabled", "live basecalling", "Enable live basecalling."),
            ("bam_reads_enabled", "BAM output", "Enable BAM output."),
            ("alignment_enabled", "live alignment", "Enable live hg38 alignment."),
        ):
            enabled = context.get(key)
            report.add(
                label,
                "PASS" if enabled else "FAIL",
                "Enabled." if enabled else action,
            )
        selected = context.get("reads_directory") or context.get("output_path")
        if selected:
            roots.append(Path(selected))

    unique_roots = list(dict.fromkeys(roots))
    if unique_roots:
        accessible = [root for root in unique_roots if root.is_dir()]
        report.add(
            "BAM output directory",
            "PASS" if accessible else "FAIL",
            (
                "Output directory is accessible."
                if accessible
                else "Output directory is not accessible."
            ),
        )
        bam = _first_completed_bam(accessible)
        if bam is None:
            report.add(
                "completed BAM batch",
                "WARN",
                "No completed BAM batch is available yet; rerun during sequencing.",
            )
        else:
            report.add(
                "completed BAM batch", "PASS", "A completed BAM batch is readable."
            )
            _check_bam(bam, report)
    else:
        report.add(
            "BAM output directory",
            "WARN",
            "Start a run or pass --bam-dir to test BAM, hg38, MM/ML, and barcodes.",
        )

    if as_json:
        print(json.dumps(report.payload(), indent=2))
    else:
        print(f"Nanopredict doctor {__version__}")
        for item in report.checks:
            print(f"[{item['status']}] {item['name']}: {item['message']}")
        has_warnings = any(item["status"] == "WARN" for item in report.checks)
        result = (
            "action required"
            if not report.ok
            else "ready with warnings"
            if has_warnings
            else "ready"
        )
        print(f"Result: {result}")
    return 0 if report.ok else 1
