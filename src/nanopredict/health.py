"""Deterministic live setup and run-health checks."""

from __future__ import annotations

from typing import Any


_SEVERITY_ORDER = {"high": 0, "moderate": 1, "info": 2}


def _issue(
    code: str,
    severity: str,
    title: str,
    detail: str,
    action: str,
) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "action": action,
    }


def evaluate_run_health(
    context: dict[str, Any],
    bam_status: dict[str, Any] | None,
    live_progress: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Return concise issues supported directly by current run evidence."""
    issues: list[dict[str, str]] = []
    elapsed = float(context.get("elapsed_seconds") or 0.0)
    basecalling = context.get("basecalling_enabled")
    bam_enabled = context.get("bam_reads_enabled")
    output_available = bool(
        context.get("reads_directory") or context.get("output_path")
    )

    if basecalling is False:
        issues.append(
            _issue(
                "BASECALLING_DISABLED",
                "high",
                "Live basecalling is disabled",
                "Passed-yield monitoring requires basecalled reads.",
                "Enable live basecalling in the MinKNOW run configuration.",
            )
        )
    if bam_enabled is False:
        issues.append(
            _issue(
                "BAM_DISABLED",
                "high",
                "BAM output is disabled",
                "Barcode-aware yield monitoring requires BAM batches.",
                "Enable BAM output in MinKNOW.",
            )
        )
    if not output_available:
        issues.append(
            _issue(
                "OUTPUT_UNAVAILABLE",
                "moderate",
                "Run output directory is unavailable",
                "Nanopredict cannot inspect completed BAM batches.",
                "Check the MinKNOW output location and filesystem permissions.",
            )
        )

    bam = bam_status or {}
    files = int(bam.get("files_processed") or 0)
    if (
        elapsed >= 600
        and bam_enabled is not False
        and output_available
        and files == 0
    ):
        issues.append(
            _issue(
                "NO_COMPLETED_BAM",
                "moderate",
                "No completed BAM batch detected",
                "The run has been active for at least 10 minutes without a readable batch.",
                "Check BAM batching and confirm MinKNOW is writing into this run directory.",
            )
        )
    if bam.get("state") == "error":
        issues.append(_issue("BAM_SCAN_ERROR", "high", "BAM yield scan failed",
                             bam.get("message") or "The completed BAM could not be processed.",
                             "Run nanopredict doctor to check BAM readability."))

    progress = live_progress or {}
    passed = float(progress.get("passed_bases") or 0.0)
    failed = float(progress.get("failed_bases") or 0.0)
    estimated = progress.get("estimated_bases")
    if elapsed >= 900 and passed <= 0 and basecalling is not False:
        issues.append(
            _issue(
                "NO_PASSED_YIELD",
                "high",
                "No passed bases after 15 minutes",
                "No passed basecalled yield is available for the selected run or barcode.",
                "Check acquisition, basecalling, and the configured Q-score threshold.",
            )
        )
    if estimated:
        completion = (passed + failed) / float(estimated)
        if elapsed >= 600 and completion < 0.2:
            issues.append(
                _issue(
                    "BASECALLING_BACKLOG",
                    "high",
                    "Basecalling is substantially behind acquisition",
                    f"Only {completion:.0%} of estimated bases have been basecalled.",
                    "Check basecaller/GPU utilisation and consider a faster model.",
                )
            )
        elif elapsed >= 600 and completion < 0.5:
            issues.append(
                _issue(
                    "BASECALLING_BACKLOG",
                    "moderate",
                    "Basecalling is behind acquisition",
                    f"About {completion:.0%} of estimated bases have been basecalled.",
                    "Check basecaller/GPU utilisation.",
                )
            )

    issues.sort(key=lambda item: (_SEVERITY_ORDER[item["severity"]], item["code"]))
    return issues
