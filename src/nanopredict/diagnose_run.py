#!/usr/bin/env python3
"""Combine calibrated yield prediction with peer-based run diagnostics."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .predict_calibrated import CalibratedYieldPredictor, select_feature_row


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def metric_value(features: dict[str, Any], metric: str) -> float | None:
    if metric == "observed_temperature_deviation":
        measured = number(features.get("observed_temperature"))
        target = number(features.get("observed_target_temperature"))
        return None if measured is None or target is None else abs(measured - target)
    return number(features.get(metric))


def display_value(value: float, unit: str) -> tuple[float, str]:
    if unit == "bases_per_hour":
        return value / 1e9, "GB/hour"
    if unit == "fraction":
        return value * 100.0, "%"
    return value, unit


class RunDecisionEngine:
    def __init__(
        self,
        predictor: CalibratedYieldPredictor,
        diagnostic_reference: Path | str,
    ):
        self.predictor = predictor
        self.reference = json.loads(Path(diagnostic_reference).read_text(encoding="utf-8"))

    def _issue(
        self,
        metric: str,
        value: float,
        reference: dict[str, float],
        config: dict[str, str],
    ) -> dict[str, Any] | None:
        direction = config["direction"]
        severity = None
        peer_region = None
        trigger = None
        if direction == "low":
            if value <= reference["p05"]:
                severity, peer_region, trigger = "high", "bottom_5_percent", reference["p05"]
            elif value <= reference["p10"]:
                severity, peer_region, trigger = "moderate", "bottom_10_percent", reference["p10"]
        elif direction == "high":
            if value >= reference["p95"]:
                severity, peer_region, trigger = "high", "top_5_percent", reference["p95"]
            elif value >= reference["p90"]:
                severity, peer_region, trigger = "moderate", "top_10_percent", reference["p90"]
        elif direction == "two_sided":
            if value <= reference["p05"] or value >= reference["p95"]:
                severity, peer_region = "high", "outside_central_90_percent"
                trigger = reference["p05"] if value <= reference["p05"] else reference["p95"]
            elif value <= reference["p10"] or value >= reference["p90"]:
                severity, peer_region = "moderate", "outside_central_80_percent"
                trigger = reference["p10"] if value <= reference["p10"] else reference["p90"]
        if severity is None:
            return None

        shown_value, shown_unit = display_value(value, config["unit"])
        shown_median, _ = display_value(reference["p50"], config["unit"])
        shown_trigger, _ = display_value(float(trigger), config["unit"])
        return {
            "code": config["code"],
            "severity": severity,
            "title": config["title"],
            "metric": metric,
            "evidence": {
                "observed": shown_value,
                "peer_median": shown_median,
                "trigger_boundary": shown_trigger,
                "unit": shown_unit,
                "peer_region": peer_region,
                "peer_count": int(reference["n"]),
            },
            "interpretation": config["interpretation"],
            "suggested_check": config["suggested_check"],
        }

    def assess(
        self,
        features: dict[str, Any],
        horizon_minutes: int,
        target_gb: float,
    ) -> dict[str, Any]:
        if target_gb <= 0:
            raise ValueError("target_gb must be positive")
        prediction = self.predictor.predict(
            features, horizon_minutes, thresholds_gb=[target_gb]
        )
        probability = prediction["threshold_probabilities"][str(float(target_gb))]
        interval_90 = prediction["prediction_intervals"]["90"]

        if interval_90["lower_gb"] >= target_gb:
            status = "GOOD"
            confidence = "high"
            explanation = "The complete 90% prediction interval is above the target."
        elif interval_90["upper_gb"] < target_gb:
            status = "BAD"
            confidence = "high"
            explanation = "The complete 90% prediction interval is below the target."
        elif probability >= 0.80:
            status = "GOOD"
            confidence = "moderate"
            explanation = "The calibrated probability of reaching the target is at least 80%."
        elif probability <= 0.20:
            status = "BAD"
            confidence = "moderate"
            explanation = "The calibrated probability of reaching the target is at most 20%."
        else:
            status = "UNCERTAIN"
            confidence = "low"
            explanation = "The target lies within the uncertain outcome region."

        device = str(features.get("device_type", "unknown"))
        reference_key = f"{device}|{horizon_minutes}"
        peer_reference = self.reference["references"].get(reference_key)
        issues: list[dict[str, Any]] = []
        if peer_reference:
            for metric, config in self.reference["diagnostics"].items():
                value = metric_value(features, metric)
                metric_reference = peer_reference["metrics"].get(metric)
                if value is None or not metric_reference or metric_reference["n"] < 15:
                    continue
                issue = self._issue(metric, value, metric_reference, config)
                if issue:
                    issues.append(issue)
        issues.sort(key=lambda item: (item["severity"] != "high", item["code"]))

        if status == "BAD" and not issues:
            issues.append(
                {
                    "code": "NO_CLEAR_QC_ANOMALY",
                    "severity": "moderate",
                    "title": "Low target probability without a clear peer anomaly",
                    "interpretation": "The combined production trajectory is unfavorable, but no individual QC metric is in the extreme peer range.",
                    "suggested_check": "Review intended run duration, target choice, interruptions, and the complete MinKNOW event log.",
                }
            )

        reliability_warnings = []
        if prediction["calibration_residual_count"] < 30:
            reliability_warnings.append(
                "The device-specific calibration group contains fewer than 30 historical residuals."
            )
        if device == "PromethION 2 Solo" and horizon_minutes == 30:
            reliability_warnings.append(
                "Thirty-minute PromethION intervals under-covered in retrospective testing; treat this status as preliminary."
            )

        return {
            "status": status,
            "status_confidence": confidence,
            "status_explanation": explanation,
            "target_gb": target_gb,
            "probability_of_reaching_target": probability,
            "prediction": prediction,
            "suspected_problems": issues,
            "peer_reference": {
                "device_type": device,
                "horizon_minutes": horizon_minutes,
                "run_count": peer_reference["run_count"] if peer_reference else 0,
            },
            "reliability_warnings": reliability_warnings,
            "diagnostic_warning": self.reference["warning"],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--diagnostic-reference", type=Path, required=True)
    parser.add_argument("--sample-label", required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--horizon", type=int, required=True)
    parser.add_argument("--target-gb", type=float, required=True)
    args = parser.parse_args()

    row = select_feature_row(
        args.features, args.sample_label, args.run_label, args.horizon
    )
    predictor = CalibratedYieldPredictor(args.models_dir)
    engine = RunDecisionEngine(predictor, args.diagnostic_reference)
    print(json.dumps(engine.assess(row, args.horizon, args.target_gb), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
