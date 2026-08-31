#!/usr/bin/env python3
"""Reusable calibrated ONT yield predictor and command-line interface."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np


class CalibratedYieldPredictor:
    """Load horizon-specific models and return GUI-friendly prediction data."""

    def __init__(self, models_dir: Path | str):
        self.models_dir = Path(models_dir)
        self.artifacts: dict[int, dict[str, Any]] = {}
        for path in sorted(self.models_dir.glob("calibrated_yield_*min.joblib")):
            artifact = joblib.load(path)
            self.artifacts[int(artifact["horizon_minutes"])] = artifact
        if not self.artifacts:
            raise FileNotFoundError(
                f"No calibrated_yield_*min.joblib models in {self.models_dir}"
            )

    @property
    def horizons(self) -> list[int]:
        return sorted(self.artifacts)

    @staticmethod
    def _number(value: Any) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return math.nan
        return result if math.isfinite(result) else math.nan

    def _feature_matrix(
        self, artifact: dict[str, Any], features: dict[str, Any]
    ) -> np.ndarray:
        return np.asarray(
            [
                [self._number(features.get(name)) for name in artifact["feature_columns"]]
            ],
            dtype=float,
        )

    @staticmethod
    def _group_values(
        groups: dict[str, Any], device_type: str
    ) -> tuple[str, np.ndarray]:
        group = device_type if device_type in groups else "__global__"
        return group, np.asarray(groups[group], dtype=float)

    def predict(
        self,
        features: dict[str, Any],
        horizon_minutes: int,
        thresholds_gb: Iterable[float] = (),
    ) -> dict[str, Any]:
        if horizon_minutes not in self.artifacts:
            raise ValueError(
                f"Unsupported horizon {horizon_minutes}; available: {self.horizons}"
            )
        artifact = self.artifacts[horizon_minutes]
        X = self._feature_matrix(artifact, features)
        point = max(float(artifact["model"].predict(X)[0]), 0.0)
        device = str(features.get("device_type", "unknown"))

        interval_groups = artifact["interval_log_scores"]
        calibration_group = device if device in interval_groups else "__global__"
        center = math.log1p(point)
        intervals: dict[str, dict[str, float]] = {}
        for coverage in (80, 90, 95):
            score = float(interval_groups[calibration_group][str(coverage)])
            intervals[str(coverage)] = {
                "lower_gb": max(math.expm1(center - score), 0.0),
                "upper_gb": max(math.expm1(center + score), 0.0),
            }

        residual_group, signed_residuals = self._group_values(
            artifact["signed_log_residuals"], device
        )
        probabilities: dict[str, float] = {}
        for threshold in thresholds_gb:
            threshold = float(threshold)
            required_residual = math.log1p(max(threshold, 0.0)) - center
            successes = int(np.sum(signed_residuals >= required_residual))
            # Laplace smoothing avoids reporting exactly 0% or 100% from a
            # modest empirical calibration set.
            probabilities[str(threshold)] = (successes + 1) / (
                len(signed_residuals) + 2
            )

        return {
            "horizon_minutes": horizon_minutes,
            "model": artifact["model_name"],
            "device_type": device,
            "point_prediction_gb": point,
            "prediction_intervals": intervals,
            "threshold_probabilities": probabilities,
            "interval_calibration_group": calibration_group,
            "probability_calibration_group": residual_group,
            "calibration_residual_count": int(len(signed_residuals)),
            "warning": artifact["warning"],
        }


def select_feature_row(
    path: Path,
    sample_label: str,
    run_label: str,
    horizon_minutes: int,
) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        matches = [
            row
            for row in csv.DictReader(handle)
            if row.get("sample_label") == sample_label
            and row.get("run_label") == run_label
            and int(row.get("horizon_minutes", -1)) == horizon_minutes
        ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one feature row, found {len(matches)} for "
            f"{sample_label}, {run_label}, {horizon_minutes} min"
        )
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--sample-label", required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--horizon", type=int, required=True)
    parser.add_argument("--thresholds", type=float, nargs="*", default=[])
    args = parser.parse_args()

    row = select_feature_row(
        args.features, args.sample_label, args.run_label, args.horizon
    )
    predictor = CalibratedYieldPredictor(args.models_dir)
    result = predictor.predict(row, args.horizon, args.thresholds)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
