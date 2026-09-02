"""Privacy-preserving run report generation."""

from __future__ import annotations

import csv
import io
import json
import platform
from datetime import datetime, timezone
from typing import Any

from . import __version__


REPORT_SCHEMA_VERSION = 1


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return value


def _pick(source: dict[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any]:
    source = source or {}
    return {field: source.get(field) for field in fields}


def _problems(status: dict[str, Any]) -> list[dict[str, Any]]:
    assessment = status.get("assessment") or {}
    items = list(status.get("live_problems") or []) + list(
        assessment.get("suspected_problems") or []
    )
    return [
        {
            "code": item.get("code"),
            "severity": item.get("severity"),
            "title": item.get("title"),
            "action": item.get("action") or item.get("suggested_check"),
        }
        for item in items
    ]


def _prediction(status: dict[str, Any]) -> dict[str, Any] | None:
    assessment = status.get("assessment")
    if not assessment:
        return None
    prediction = assessment.get("prediction") or {}
    interval = (prediction.get("prediction_intervals") or {}).get("90") or {}
    return {
        "status": assessment.get("status"),
        "confidence": assessment.get("status_confidence"),
        "horizon_minutes": prediction.get("horizon_minutes"),
        "predicted_final_gb": prediction.get("point_prediction_gb"),
        "prediction_interval_90_gb": {
            "lower": interval.get("lower_gb"),
            "upper": interval.get("upper_gb"),
        },
        "probability_of_reaching_target": assessment.get(
            "probability_of_reaching_target"
        ),
        "reliability_warnings": list(
            assessment.get("reliability_warnings") or []
        ),
    }


def build_anonymous_report(
    status: dict[str, Any], generated_at: datetime | None = None
) -> dict[str, Any]:
    """Select only non-identifying status fields for export."""
    generated = generated_at or datetime.now(timezone.utc)
    progress = status.get("live_progress") or {}
    cpg = status.get("nanodx_cpg") or {}
    observations = status.get("observations") or {}
    barcode_fields = (
        "barcode",
        "passed_bases",
        "failed_bases",
        "reads_scanned",
        "tagged_reads",
        "tagged_read_fraction",
        "target_gb",
        "yield_progress_percent",
        "yield_remaining_bases",
        "yield_target_reached",
        "rate_bases_per_minute",
        "yield_eta_minutes",
        "count",
        "threshold",
        "remaining",
        "progress_percent",
        "threshold_reached",
        "rate_cpg_per_minute",
        "eta_minutes",
        "estimated_threshold_at",
        "threshold_reached_at",
        "state",
    )
    return _plain({
        "schema": "nanopredict-anonymous-run-report",
        "schema_version": REPORT_SCHEMA_VERSION,
        "research_use_only": True,
        "generated_at": generated.astimezone(timezone.utc).isoformat(),
        "privacy": {
            "contains_patient_identifiers": False,
            "excluded_fields": [
                "sample_id",
                "run_id",
                "position_name",
                "flow_cell_id",
                "output_path",
                "reads_directory",
            ],
        },
        "software": {
            "nanopredict_version": __version__,
            "python_version": platform.python_version(),
            "minknow_core_version": status.get("minknow_version"),
            "minknow_api_version": status.get("api_client_version"),
        },
        "run": {
            "mode": status.get("mode"),
            "state": status.get("state"),
            "scope": "barcode" if status.get("selected_barcode") else "run",
            "barcode": status.get("selected_barcode"),
            "device_type": status.get("device_type"),
            "device_api_type": status.get("device_api_type"),
            "collector_mode": status.get("collector_mode"),
            "read_only": status.get("read_only"),
            "elapsed_minutes": status.get("elapsed_minutes"),
            "last_update": status.get("last_update"),
            "target_gb": status.get("target_gb"),
            "prediction_available": status.get("prediction_available"),
        },
        "yield": {
            **_pick(
                progress,
                (
                    "passed_bases",
                    "failed_bases",
                    "total_reads",
                    "passed_reads",
                    "progress_percent",
                    "remaining_bases",
                    "rate_bases_per_minute",
                    "eta_minutes",
                    "target_reached",
                    "target_reached_elapsed_minutes",
                    "source",
                ),
            ),
            "observed_passed_yield_gb": observations.get("passed_yield_gb"),
        },
        "nanodx_cpg": _pick(
            cpg,
            (
                "state",
                "count",
                "threshold",
                "remaining",
                "progress_percent",
                "threshold_reached",
                "rate_cpg_per_minute",
                "eta_minutes",
                "estimated_threshold_at",
                "threshold_reached_at",
                "model",
                "assembly",
                "model_features",
                "files_processed",
                "reads_scanned",
                "tagged_reads",
                "tagged_read_fraction",
            ),
        ),
        "prediction": _prediction(status),
        "checkpoints": [
            _pick(
                item,
                ("horizon_minutes", "status", "prediction_gb", "probability"),
            )
            for item in status.get("history") or []
        ],
        "problems": _problems(status),
        "barcodes": [
            _pick(item, barcode_fields) for item in cpg.get("barcodes") or []
        ],
        "actual_final_gb": status.get("actual_final_gb"),
    })


_CSV_FIELDS = (
    "scope",
    "barcode",
    "state",
    "device_type",
    "collector_mode",
    "target_gb",
    "elapsed_minutes",
    "passed_bases",
    "failed_bases",
    "yield_progress_percent",
    "yield_target_reached",
    "yield_eta_minutes",
    "yield_target_reached_elapsed_minutes",
    "cpg_count",
    "cpg_threshold",
    "cpg_progress_percent",
    "cpg_threshold_reached",
    "cpg_rate_per_minute",
    "cpg_eta_minutes",
    "cpg_estimated_threshold_at",
    "cpg_threshold_reached_at",
    "prediction_status",
    "prediction_horizon_minutes",
    "predicted_final_gb",
    "prediction_interval_90_lower_gb",
    "prediction_interval_90_upper_gb",
    "probability_of_reaching_target",
    "problem_codes",
    "nanopredict_version",
    "minknow_core_version",
    "minknow_api_version",
    "generated_at",
)


def report_csv(report: dict[str, Any]) -> str:
    """Render one aggregate row plus one row per detected barcode."""
    run = report["run"]
    yield_status = report["yield"]
    cpg = report["nanodx_cpg"]
    prediction = report.get("prediction") or {}
    interval = prediction.get("prediction_interval_90_gb") or {}
    software = report["software"]
    common = {
        "state": run.get("state"),
        "device_type": run.get("device_type"),
        "collector_mode": run.get("collector_mode"),
        "elapsed_minutes": run.get("elapsed_minutes"),
        "problem_codes": "|".join(
            str(item["code"]) for item in report["problems"] if item.get("code")
        ),
        "nanopredict_version": software.get("nanopredict_version"),
        "minknow_core_version": software.get("minknow_core_version"),
        "minknow_api_version": software.get("minknow_api_version"),
        "generated_at": report.get("generated_at"),
    }
    rows = [
        {
            **common,
            "scope": "run",
            "target_gb": run.get("target_gb"),
            "passed_bases": yield_status.get("passed_bases"),
            "failed_bases": yield_status.get("failed_bases"),
            "yield_progress_percent": yield_status.get("progress_percent"),
            "yield_target_reached": yield_status.get("target_reached"),
            "yield_eta_minutes": yield_status.get("eta_minutes"),
            "yield_target_reached_elapsed_minutes": yield_status.get(
                "target_reached_elapsed_minutes"
            ),
            "cpg_count": cpg.get("count"),
            "cpg_threshold": cpg.get("threshold"),
            "cpg_progress_percent": cpg.get("progress_percent"),
            "cpg_threshold_reached": cpg.get("threshold_reached"),
            "cpg_rate_per_minute": cpg.get("rate_cpg_per_minute"),
            "cpg_eta_minutes": cpg.get("eta_minutes"),
            "cpg_estimated_threshold_at": cpg.get("estimated_threshold_at"),
            "cpg_threshold_reached_at": cpg.get("threshold_reached_at"),
            "prediction_status": prediction.get("status"),
            "prediction_horizon_minutes": prediction.get("horizon_minutes"),
            "predicted_final_gb": prediction.get("predicted_final_gb"),
            "prediction_interval_90_lower_gb": interval.get("lower"),
            "prediction_interval_90_upper_gb": interval.get("upper"),
            "probability_of_reaching_target": prediction.get(
                "probability_of_reaching_target"
            ),
        }
    ]
    for barcode in report["barcodes"]:
        rows.append(
            {
                **common,
                "scope": "barcode",
                "barcode": barcode.get("barcode"),
                "target_gb": barcode.get("target_gb"),
                "passed_bases": barcode.get("passed_bases"),
                "failed_bases": barcode.get("failed_bases"),
                "yield_progress_percent": barcode.get("yield_progress_percent"),
                "yield_target_reached": barcode.get("yield_target_reached"),
                "yield_eta_minutes": barcode.get("yield_eta_minutes"),
                "cpg_count": barcode.get("count"),
                "cpg_threshold": barcode.get("threshold"),
                "cpg_progress_percent": barcode.get("progress_percent"),
                "cpg_threshold_reached": barcode.get("threshold_reached"),
                "cpg_rate_per_minute": barcode.get("rate_cpg_per_minute"),
                "cpg_eta_minutes": barcode.get("eta_minutes"),
                "cpg_estimated_threshold_at": barcode.get(
                    "estimated_threshold_at"
                ),
                "cpg_threshold_reached_at": barcode.get("threshold_reached_at"),
            }
        )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def report_download(
    status: dict[str, Any], output_format: str
) -> tuple[bytes, str, str]:
    """Return body, MIME type, and anonymous filename for a download."""
    report = build_anonymous_report(status)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if output_format == "json":
        body = json.dumps(report, indent=2, allow_nan=False).encode("utf-8")
        return body, "application/json; charset=utf-8", f"nanopredict-report-{stamp}.json"
    if output_format == "csv":
        body = report_csv(report).encode("utf-8-sig")
        return body, "text/csv; charset=utf-8", f"nanopredict-report-{stamp}.csv"
    raise ValueError("Report format must be json or csv")
