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
    cpg_status: dict[str, Any] | None,
    live_progress: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Return concise issues supported directly by current run evidence."""
    issues: list[dict[str, str]] = []
    elapsed = float(context.get("elapsed_seconds") or 0.0)
    basecalling = context.get("basecalling_enabled")
    bam_enabled = context.get("bam_reads_enabled")
    alignment_enabled = context.get("alignment_enabled")
    output_available = bool(
        context.get("reads_directory") or context.get("output_path")
    )

    if basecalling is False:
        issues.append(
            _issue(
                "BASECALLING_DISABLED",
                "high",
                "Live basecalling is disabled",
                "Passed-yield and modified-base monitoring require basecalled reads.",
                "Enable live basecalling in the MinKNOW run configuration.",
            )
        )
    if bam_enabled is False:
        issues.append(
            _issue(
                "BAM_DISABLED",
                "high",
                "BAM output is disabled",
                "Barcode-aware yield and NanoDx CpG monitoring require BAM batches.",
                "Enable BAM output in MinKNOW.",
            )
        )
    if alignment_enabled is False:
        issues.append(
            _issue(
                "ALIGNMENT_DISABLED",
                "high",
                "Live alignment is disabled",
                "NanoDx sites cannot be matched without reference coordinates.",
                "Enable live alignment against hg38 in MinKNOW.",
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

    cpg = cpg_status or {}
    files = int(cpg.get("files_processed") or 0)
    reads = int(cpg.get("reads_scanned") or 0)
    tagged = int(cpg.get("tagged_reads") or 0)
    cpg_state = str(cpg.get("state") or "")
    cpg_message = str(cpg.get("message") or "")
    if (
        elapsed >= 600
        and bam_enabled is not False
        and alignment_enabled is not False
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
    if cpg_state == "error" or (cpg_state == "unavailable" and files > 0):
        if "MM/ML" in cpg_message:
            issues.append(
                _issue(
                    "MM_ML_MISSING",
                    "high",
                    "Modified-base tags are missing",
                    "Completed BAM records do not contain usable MM/ML tags.",
                    "Select a modified-base basecalling model that emits MM and ML tags.",
                )
            )
        elif "hg38" in cpg_message or "chromosome 1" in cpg_message:
            issues.append(
                _issue(
                    "REFERENCE_MISMATCH",
                    "high",
                    "BAM reference is not hg38",
                    cpg_message,
                    "Configure live alignment with the supported hg38 reference.",
                )
            )
        else:
            issues.append(
                _issue(
                    "CPG_SCAN_ERROR",
                    "high",
                    "NanoDx CpG scan failed",
                    cpg_message or "The completed BAM could not be processed.",
                    "Run nanopredict doctor for the exact BAM and reference checks.",
                )
            )
    if reads >= 100 and tagged > 0 and tagged / reads < 0.5:
        issues.append(
            _issue(
                "LOW_TAGGED_READ_FRACTION",
                "moderate",
                "Few reads contain modified-base calls",
                f"Only {tagged / reads:.0%} of scanned BAM records contain usable calls.",
                "Check the modified-base model and MM/ML output settings.",
            )
        )

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
