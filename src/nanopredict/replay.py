"""Historical-run replay source for developing and demonstrating the GUI."""

from __future__ import annotations

import csv
import math
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diagnose_run import RunDecisionEngine


SUPPORTED_HORIZONS = (30, 60, 120)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _sample_sort_key(label: str) -> tuple[int, str]:
    match = re.fullmatch(r"Sample(\d+)", label, re.IGNORECASE)
    return (int(match.group(1)), label) if match else (10**9, label)


@dataclass(frozen=True)
class ReplayRun:
    sample_id: str
    device_type: str
    snapshots: tuple[dict[str, str], ...]

    @property
    def horizons(self) -> list[int]:
        return [int(row["horizon_minutes"]) for row in self.snapshots]

    @property
    def final_passed_gb(self) -> float | None:
        bases = _number(self.snapshots[-1].get("target_final_passed_bases"))
        return None if bases is None else bases / 1e9


class ReplayCatalog:
    """Load anonymous, complete MinION histories from the feature table."""

    def __init__(self, path: Path | str, device_type: str = "MINION_MK1D"):
        grouped: dict[str, list[dict[str, str]]] = {}
        with Path(path).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("device_type") != device_type:
                    continue
                grouped.setdefault(row["sample_label"], []).append(row)

        self.runs: dict[str, ReplayRun] = {}
        for sample_id, rows in grouped.items():
            rows.sort(key=lambda item: int(item["horizon_minutes"]))
            horizons = tuple(int(row["horizon_minutes"]) for row in rows)
            if horizons != SUPPORTED_HORIZONS:
                continue
            self.runs[sample_id] = ReplayRun(
                sample_id=sample_id,
                device_type=device_type,
                snapshots=tuple(rows),
            )
        if not self.runs:
            raise ValueError(f"No complete MinION replay histories found in {path}")

    def list_runs(self) -> list[dict[str, Any]]:
        return [
            {
                "sample_id": run.sample_id,
                "device_type": run.device_type,
                "horizons": run.horizons,
            }
            for run in sorted(
                self.runs.values(), key=lambda item: _sample_sort_key(item.sample_id)
            )
        ]

    def get(self, sample_id: str) -> ReplayRun:
        try:
            return self.runs[sample_id]
        except KeyError as exc:
            raise ValueError(f"Unknown replay sample: {sample_id}") from exc


class ReplaySession:
    """Thread-safe accelerated playback of 30/60/120-minute snapshots."""

    def __init__(self, catalog: ReplayCatalog, engine: RunDecisionEngine):
        self.catalog = catalog
        self.engine = engine
        self._lock = threading.RLock()
        self._run: ReplayRun | None = None
        self._target_gb = 10.0
        self._seconds_per_step = 8.0
        self._started_at = 0.0
        self._manual_steps = 0
        self._stopped = False
        self._frozen_available: int | None = None
        self._assessments: list[dict[str, Any]] = []

    def start(
        self, sample_id: str, target_gb: float, seconds_per_step: float = 8.0
    ) -> dict[str, Any]:
        if not math.isfinite(target_gb) or target_gb <= 0:
            raise ValueError("Target yield must be a positive number")
        if not math.isfinite(seconds_per_step) or not 1 <= seconds_per_step <= 120:
            raise ValueError("Replay step duration must be between 1 and 120 seconds")
        with self._lock:
            self._run = self.catalog.get(sample_id)
            self._target_gb = float(target_gb)
            self._seconds_per_step = float(seconds_per_step)
            self._started_at = time.monotonic()
            self._manual_steps = 0
            self._stopped = False
            self._frozen_available = None
            self._assessments = []
            return self.status()

    def advance(self) -> dict[str, Any]:
        with self._lock:
            if self._run is None:
                raise ValueError("No replay is active")
            self._manual_steps += 1
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._frozen_available = self._available_count()
            self._stopped = True
            return self.status()

    def _available_count(self) -> int:
        if self._run is None:
            return 0
        if self._stopped and self._frozen_available is not None:
            return self._frozen_available
        automatic = int((time.monotonic() - self._started_at) / self._seconds_per_step)
        return min(automatic + self._manual_steps, len(self._run.snapshots))

    @staticmethod
    def _observations(row: dict[str, str]) -> dict[str, float | int | None]:
        passed_bases = _number(row.get("observed_passed_bases"))
        return {
            "passed_yield_gb": None if passed_bases is None else passed_bases / 1e9,
            "total_reads": _number(row.get("observed_total_reads")),
            "temperature_c": _number(row.get("observed_temperature")),
            "sequencing_percent": _number(
                row.get("pore_activity_sequencing_percent")
            ),
            "pore_available_percent": _number(
                row.get("pore_activity_pore_available_percent")
            ),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._run is None:
                return {
                    "mode": "replay",
                    "state": "waiting",
                    "message": "Choose an anonymous historical run to begin.",
                    "minknow_core_target": "6.10.x",
                    "device_target": "MinION",
                }

            available = self._available_count()
            while len(self._assessments) < available:
                row = self._run.snapshots[len(self._assessments)]
                horizon = int(row["horizon_minutes"])
                self._assessments.append(
                    self.engine.assess(row, horizon, self._target_gb)
                )

            current_index = len(self._assessments) - 1
            current_row = (
                self._run.snapshots[current_index] if current_index >= 0 else None
            )
            completed = available == len(self._run.snapshots)
            state = "stopped" if self._stopped else "complete" if completed else "running"
            next_horizon = None if completed else self._run.horizons[available]

            return {
                "mode": "replay",
                "state": state,
                "sample_id": self._run.sample_id,
                "device_type": "MinION",
                "target_gb": self._target_gb,
                "seconds_per_step": self._seconds_per_step,
                "current_horizon_minutes": (
                    None if current_row is None else int(current_row["horizon_minutes"])
                ),
                "next_horizon_minutes": next_horizon,
                "observations": (
                    None if current_row is None else self._observations(current_row)
                ),
                "assessment": (
                    None if current_index < 0 else self._assessments[current_index]
                ),
                "history": [
                    {
                        "horizon_minutes": item["prediction"]["horizon_minutes"],
                        "status": item["status"],
                        "prediction_gb": item["prediction"]["point_prediction_gb"],
                        "probability": item["probability_of_reaching_target"],
                    }
                    for item in self._assessments
                ],
                "actual_final_gb": self._run.final_passed_gb if completed else None,
                "message": (
                    "Replay paused by the operator."
                    if self._stopped
                    else "Historical replay complete."
                    if completed
                    else f"Collecting data for the {next_horizon}-minute checkpoint."
                ),
                "minknow_core_target": "6.10.x",
                "device_target": "MinION",
            }
