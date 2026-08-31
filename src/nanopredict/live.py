"""Adaptive, read-only feature collection for live MinION runs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .bam_fallback import (
    BamFallbackCollector,
    BamFallbackUnavailable,
    BamPosition,
)
from .diagnose_run import RunDecisionEngine
from .nanodx_cpg import NanoDxCpgMonitor, NanoDxTargets, default_nanodx_targets
from .replay import SUPPORTED_HORIZONS


MINION_DEVICE_TYPES = {"MINION", "MINION_MK1C", "MINION_MK1D"}
MODEL_DEVICE_TYPE = "MINION_MK1D"
CALIBRATION_PURPOSE = 3  # minknow_api.acquisition_pb2.CALIBRATION in API 6.x
VALIDATED_CORE_VERSION = (6, 10)


class MinknowUnavailableError(RuntimeError):
    """Raised when the supported MinKNOW client cannot be loaded or reached."""


class NoActiveRunError(RuntimeError):
    """Raised while no active MinION sequencing acquisition is available."""


class CheckpointNotReadyError(RuntimeError):
    """Raised when MinKNOW has not completed a statistics bucket yet."""


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _field_number(message: Any, *names: str) -> float | None:
    for name in names:
        value = _number(getattr(message, name, None))
        if value is not None:
            return value
    return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _timestamp_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if hasattr(value, "ToDatetime"):
        moment = value.ToDatetime(tzinfo=timezone.utc)
        return moment.timestamp()
    seconds = _number(getattr(value, "seconds", None))
    nanos = _number(getattr(value, "nanos", 0)) or 0
    return None if seconds is None else seconds + nanos / 1e9


def _message_has(message: Any, field: str) -> bool:
    try:
        return bool(message.HasField(field))
    except (AttributeError, ValueError):
        return getattr(message, field, None) is not None


def _wrapped_number(message: Any, field: str) -> float | None:
    if message is None or not _message_has(message, field):
        return None
    return _number(getattr(getattr(message, field), "value", None))


def _first_response(stream: Iterable[Any]) -> Any:
    try:
        return next(iter(stream))
    finally:
        cancel = getattr(stream, "cancel", None)
        if callable(cancel):
            cancel()


def _series_resolution(snapshots: list[Any]) -> float | None:
    clean = sorted(
        item
        for item in {_number(getattr(snapshot, "seconds", None)) for snapshot in snapshots}
        if item is not None
    )
    for left, right in zip(clean, clean[1:]):
        if right > left:
            return right - left
    return None


def _recent_rate(snapshots: list[Any], field: str) -> float | None:
    if len(snapshots) < 2:
        return None
    left, right = snapshots[-2:]
    elapsed = _number(right.seconds) - _number(left.seconds)
    if elapsed <= 0:
        return None
    left_value = _number(getattr(left.yield_summary, field, None))
    right_value = _number(getattr(right.yield_summary, field, None))
    if left_value is None or right_value is None:
        return None
    return (right_value - left_value) * 3600.0 / elapsed


def _planned_hours(acquisition: Any) -> float | None:
    criteria = getattr(
        getattr(getattr(acquisition, "target_run_until_criteria", None), "stop_criteria", None),
        "criteria",
        {},
    )
    for key in ("runtime", "run_time", "duration"):
        packed = criteria.get(key) if hasattr(criteria, "get") else None
        if packed is None:
            continue
        for wrapper in ("UInt64Value", "Int64Value", "DoubleValue"):
            try:
                from google.protobuf import wrappers_pb2

                target = getattr(wrappers_pb2, wrapper)()
                if packed.Unpack(target):
                    return float(target.value) / 3600.0
            except (AttributeError, TypeError, ValueError):
                continue
    return None


def _pore_activity(
    response: Any, channel_state_info: Any = None
) -> dict[str, float | None]:
    totals = {
        "sequencing": 0.0,
        "pore_available": 0.0,
        "unavailable": 0.0,
        "inactive": 0.0,
        "unclassified": 0.0,
    }
    state_groups: dict[str, str] = {}
    valid_groups = set(totals)
    for group in getattr(channel_state_info, "groups", []):
        group_name = _normalise(
            getattr(getattr(group, "style", None), "label", None) or group.name
        )
        if group_name not in valid_groups:
            continue
        for state in getattr(group, "states", []):
            state_groups[_normalise(state.name)] = group_name
            label = _normalise(getattr(getattr(state, "style", None), "label", ""))
            if label:
                state_groups[label] = group_name

    states = getattr(response, "channel_states", {})
    for name, values in states.items():
        state_times = list(getattr(values, "state_times", []))
        if not state_times:
            continue
        amount = float(state_times[-1])
        key = _normalise(name)
        if key in state_groups:
            target = state_groups[key]
        elif key in {"strand", "sequencing", "adapter"} or "sequenc" in key:
            target = "sequencing"
        elif key in {"pore", "pore_available"} or "available" in key and "unavailable" not in key:
            target = "pore_available"
        elif key in {
            "inactive",
            "no_pore",
            "channel_disabled",
            "multiple",
            "saturated",
            "zero",
        } or "inactive" in key or "out_of_range" in key:
            target = "inactive"
        elif "unavailable" in key or "active_feedback" in key:
            target = "unavailable"
        else:
            target = "unclassified"
        totals[target] += amount
    denominator = sum(totals.values())
    return {
        f"pore_activity_{key}_percent": (
            None if denominator == 0 else value * 100.0 / denominator
        )
        for key, value in totals.items()
    }


def _pore_scan(
    bream_info: Any, horizon_seconds: int | None = None
) -> dict[str, float | None]:
    output = {
        "pore_available": None,
        "reserved_pore": None,
        "unavailable": None,
        "saturated": None,
        "zero": None,
        "inactive": None,
    }
    results = list(getattr(bream_info, "mux_scan_results", []))
    if horizon_seconds is not None:
        results = [
            result
            for result in results
            if int(getattr(result, "mux_scan_timestamp", 0)) <= horizon_seconds
        ]
    results.sort(key=lambda result: int(getattr(result, "mux_scan_timestamp", 0)))
    if not results:
        return {f"pore_scan_{key}_count": value for key, value in output.items()}

    labels: dict[str, str] = {}
    metadata = getattr(bream_info, "mux_scan_metadata", None)
    for group in getattr(metadata, "category_groups", []):
        for category in getattr(group, "category", []):
            labels[_normalise(category.name)] = _normalise(category.style.label)

    for raw_name, count in getattr(results[-1], "counts", {}).items():
        name = labels.get(_normalise(raw_name), _normalise(raw_name))
        if name in {"pore_available", "single_pore", "single"}:
            target = "pore_available"
        elif "reserved" in name:
            target = "reserved_pore"
        elif "saturat" in name:
            target = "saturated"
        elif name == "zero" or "zero" in name:
            target = "zero"
        elif "inactive" in name or name in {"no_pore", "channel_disabled"}:
            target = "inactive"
        elif "unavailable" in name or "multiple" in name or "out_of_range" in name:
            target = "unavailable"
        else:
            continue
        output[target] = (output[target] or 0) + float(count)
    return {f"pore_scan_{key}_count": value for key, value in output.items()}


class MinknowCollector:
    """Collect a model feature row using side-effect-free MinKNOW RPCs only."""

    def __init__(
        self,
        host: str = "localhost",
        position_name: str | None = None,
        rpc_timeout: float = 8.0,
        manager_factory: Callable[..., Any] | None = None,
    ):
        self.host = host
        self.position_name = position_name
        self.rpc_timeout = rpc_timeout
        self._manager_factory = manager_factory

    @staticmethod
    def client_available() -> bool:
        try:
            import minknow_api  # noqa: F401

            return True
        except ImportError:
            return False

    def _manager(self) -> Any:
        if self._manager_factory is not None:
            return self._manager_factory(host=self.host)
        try:
            from minknow_api.manager import Manager
        except ImportError as exc:
            raise MinknowUnavailableError(
                "The MinKNOW API client is not installed. Reinstall Nanopredict."
            ) from exc
        return Manager(host=self.host)

    @staticmethod
    def client_version() -> str | None:
        try:
            return importlib.metadata.version("minknow_api")
        except importlib.metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _version_pair(value: str | None) -> tuple[int, int] | None:
        match = re.match(r"^(\d+)\.(\d+)", value or "")
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))

    def active_positions(self) -> list[Any]:
        """Return every active MinION position allowed by the CLI filter."""
        try:
            positions = list(self._manager().flow_cell_positions())
        except Exception as exc:
            raise MinknowUnavailableError(
                f"Cannot reach MinKNOW at {self.host}. Start MinKNOW and try again."
            ) from exc

        active = []
        for position in positions:
            device_type = str(getattr(position, "device_type", "")).upper()
            if device_type not in MINION_DEVICE_TYPES:
                continue
            if self.position_name and getattr(position, "name", None) != self.position_name:
                continue
            if str(getattr(position, "protocol_state", "")).lower() == "protocol_running":
                active.append(position)
        if not active:
            raise NoActiveRunError("Waiting for an active MinION sequencing run in MinKNOW.")
        return sorted(active, key=lambda item: str(getattr(item, "name", "")))

    def inspect(self) -> dict[str, Any]:
        """Return metadata for a single active position."""
        active = self.active_positions()
        if len(active) > 1:
            raise NoActiveRunError(
                "More than one MinION run is active; select a position."
            )
        return self.inspect_position(active[0])

    def inspect_position(self, position: Any) -> dict[str, Any]:
        """Return active-run metadata for one discovered position."""
        try:
            connection = position.connect()
        except Exception as exc:
            raise MinknowUnavailableError(
                "MinKNOW found the run but could not connect to it."
            ) from exc
        try:
            version = connection.instance.get_version_info(_timeout=self.rpc_timeout)
        except Exception as exc:
            raise MinknowUnavailableError(
                "Connected to the MinION position but could not read its MinKNOW version."
            ) from exc
        major = int(getattr(version.minknow, "major", 0))
        minor = int(getattr(version.minknow, "minor", 0))
        client_version = self.client_version()
        api_matches_core = self._version_pair(client_version) == (major, minor)
        collector_mode = (
            "validated"
            if api_matches_core and (major, minor) == VALIDATED_CORE_VERSION
            else "compatibility"
        )
        compatibility_warning = None
        if collector_mode == "compatibility":
            compatibility_warning = (
                f"Compatibility mode: MinKNOW Core {major}.{minor} is being read with "
                f"minknow_api {client_version or 'unknown'}. "
                + (
                    "The API minor versions differ. "
                    if not api_matches_core
                    else "This Core generation has not been prospectively validated. "
                )
                + "Unsupported statistics fall back to completed BAM batches."
            )
        try:
            acquisition = connection.acquisition.get_current_acquisition_run(
                _timeout=self.rpc_timeout
            )
        except Exception as exc:
            code = getattr(exc, "code", lambda: None)()
            if str(code).endswith("FAILED_PRECONDITION"):
                raise NoActiveRunError(
                    "MinION protocol detected; waiting for the sequencing acquisition to start."
                ) from exc
            raise MinknowUnavailableError(
                "Connected to MinKNOW but could not read the active acquisition."
            ) from exc
        if int(getattr(acquisition.config_summary, "purpose", 0)) == CALIBRATION_PURPOSE:
            raise NoActiveRunError(
                "MinION calibration detected; waiting for the sequencing acquisition."
            )
        if (
            collector_mode == "validated"
            and not bool(getattr(acquisition.config_summary, "basecalling_enabled", False))
        ):
            raise MinknowUnavailableError(
                "The active run has live basecalling disabled; passed-yield prediction "
                "requires basecalling."
            )
        started = _timestamp_seconds(getattr(acquisition, "start_time", None))
        if not started:
            started = _timestamp_seconds(getattr(acquisition, "data_read_start_time", None))
        elapsed = 0.0 if started is None else max(time.time() - started, 0.0)
        run_id = str(acquisition.run_id)
        config_summary = acquisition.config_summary
        output_path = None
        try:
            protocol_response = connection.protocol.get_current_protocol_run(
                _timeout=self.rpc_timeout
            )
            protocol_run = getattr(protocol_response, "run_info", protocol_response)
            output_path = str(getattr(protocol_run, "output_path", "")) or None
        except Exception:
            pass
        reads_directory = str(getattr(config_summary, "reads_directory", "")) or None
        output_root = reads_directory or output_path
        bam_on_disk = False
        if output_root:
            try:
                candidate = Path(output_root)
                bam_on_disk = any(
                    (candidate / name).is_dir() for name in ("bam_pass", "bam_fail")
                ) or candidate.name.lower() in {"bam_pass", "bam_fail"}
            except OSError:
                pass
        return {
            "position": position,
            "connection": connection,
            "acquisition": acquisition,
            "run_id": run_id,
            "run_key": hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12],
            "elapsed_seconds": elapsed,
            "minknow_version": getattr(version.minknow, "full", f"{major}.{minor}"),
            "api_client_version": client_version,
            "collector_mode": collector_mode,
            "compatibility_warning": compatibility_warning,
            "prediction_available": True,
            "output_path": output_path,
            "reads_directory": reads_directory,
            "bam_reads_enabled": bool(
                getattr(config_summary, "bam_reads_enabled", False)
            ) or bam_on_disk,
            "alignment_enabled": bool(
                getattr(config_summary, "alignment_enabled", False)
            ) or bam_on_disk,
            "alignment_reference_files": list(
                getattr(config_summary, "alignment_reference_files", [])
            ),
        }

    def collect(
        self, horizon_minutes: int, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if horizon_minutes not in SUPPORTED_HORIZONS:
            raise ValueError(f"Unsupported checkpoint: {horizon_minutes} minutes")
        context = context or self.inspect()
        connection = context["connection"]
        acquisition = context["acquisition"]
        run_id = context["run_id"]
        horizon_seconds = horizon_minutes * 60

        try:
            from minknow_api import statistics_pb2
        except ImportError as exc:
            raise MinknowUnavailableError(
                "The MinKNOW API client is not installed."
            ) from exc

        selection = statistics_pb2.DataSelection(
            start=0, step=1800, end=horizon_seconds + 1
        )
        output = _first_response(
            connection.statistics.stream_acquisition_output(
                acquisition_run_id=run_id,
                data_selection=selection,
                _timeout=self.rpc_timeout,
            )
        )
        groups = list(getattr(output, "snapshots", []))
        snapshots = max((list(group.snapshots) for group in groups), key=len, default=[])
        snapshots = [item for item in snapshots if item.seconds <= horizon_seconds]
        if not snapshots:
            raise CheckpointNotReadyError(
                "MinKNOW has not produced yield statistics for this checkpoint yet."
            )
        snapshots.sort(key=lambda item: item.seconds)
        latest = snapshots[-1]
        summary = latest.yield_summary

        qscore = self._boxplot(
            connection,
            run_id,
            horizon_minutes,
            statistics_pb2.StreamBoxplotRequest.QSCORE,
        )
        speed = self._boxplot(
            connection,
            run_id,
            horizon_minutes,
            statistics_pb2.StreamBoxplotRequest.BASES_PER_SECOND,
        )
        try:
            duty = _first_response(
                connection.statistics.stream_duty_time(
                    acquisition_run_id=run_id,
                    data_selection=selection,
                    _timeout=self.rpc_timeout,
                )
            )
        except Exception:
            duty = None
        temperature = self._temperature(connection, run_id, horizon_seconds, statistics_pb2)
        try:
            basecaller = connection.analysis_configuration.get_basecaller_configuration(
                run_id=run_id, _timeout=self.rpc_timeout
            )
        except Exception:
            basecaller = None

        estimated = _field_number(summary, "estimated_selected_bases", "estimated_bases")
        passed = _field_number(summary, "basecalled_pass_bases", "passed_bases")
        failed = _field_number(summary, "basecalled_fail_bases", "failed_bases")
        total_reads = _field_number(summary, "read_count", "total_read_count")
        passed_reads = _field_number(
            summary, "basecalled_pass_read_count", "passed_read_count"
        )
        failed_reads = _field_number(
            summary, "basecalled_fail_read_count", "failed_read_count"
        )
        observed_seconds = _number(latest.seconds)
        called = None if passed is None or failed is None else passed + failed

        row: dict[str, Any] = {
            "device_type": MODEL_DEVICE_TYPE,
            "device_is_promethion": 0,
            "minimum_q_score_setting": _wrapped_number(
                getattr(basecaller, "read_filtering", None), "min_qscore"
            ),
            "planned_run_limit_hours": _planned_hours(acquisition),
            "series_resolution_seconds": _series_resolution(snapshots) or 1800.0,
            "observed_through_seconds": observed_seconds,
            "observed_estimated_bases": estimated,
            "observed_passed_bases": passed,
            "observed_failed_bases": failed,
            "observed_total_reads": total_reads,
            "observed_passed_reads": passed_reads,
            "observed_failed_reads": failed_reads,
            "observed_passed_base_fraction": _ratio(passed, called),
            "observed_passed_read_fraction": _ratio(passed_reads, total_reads),
            "observed_mean_passed_read_length": _ratio(passed, passed_reads),
            "observed_mean_failed_read_length": _ratio(failed, failed_reads),
            "observed_mean_estimated_read_length": _ratio(estimated, total_reads),
            "observed_basecalling_completion_ratio": _ratio(called, estimated),
            "observed_average_estimated_bases_per_hour": _ratio(
                estimated, observed_seconds / 3600.0 if observed_seconds else None
            ),
            "observed_average_passed_bases_per_hour": _ratio(
                passed, observed_seconds / 3600.0 if observed_seconds else None
            ),
            "observed_recent_estimated_bases_per_hour": _recent_rate(
                snapshots, "estimated_selected_bases"
            ),
            "observed_recent_passed_bases_per_hour": _recent_rate(
                snapshots, "basecalled_pass_bases"
            ),
            "observed_qscore_lower": _number(
                getattr(qscore, "lower_full_width_half_maximum", None)
            ),
            "observed_qscore_mode": _number(getattr(qscore, "mode", None)),
            "observed_qscore_upper": _number(
                getattr(qscore, "upper_full_width_half_maximum", None)
            ),
            "observed_translocation_q25": _number(getattr(speed, "q25", None)),
            "observed_translocation_median": _number(getattr(speed, "q50", None)),
            "observed_translocation_q75": _number(getattr(speed, "q75", None)),
            "observed_temperature": temperature[0],
            "observed_target_temperature": temperature[1],
        }
        row.update(_pore_activity(duty, acquisition.config_summary.channel_state_info))
        row.update(_pore_scan(acquisition.bream_info, horizon_seconds))
        return row

    def collect_live_progress(self, context: dict[str, Any]) -> dict[str, float]:
        """Read the latest cumulative passed-base counters for the dashboard."""
        try:
            from minknow_api import statistics_pb2
        except ImportError as exc:
            raise MinknowUnavailableError(
                "The MinKNOW API client is not installed."
            ) from exc

        elapsed = max(int(float(context["elapsed_seconds"])), 0)
        selection = statistics_pb2.DataSelection(
            start=max(elapsed - 120, 0),
            step=60,
            end=elapsed + 1,
        )
        output = _first_response(
            context["connection"].statistics.stream_acquisition_output(
                acquisition_run_id=context["run_id"],
                data_selection=selection,
                _timeout=self.rpc_timeout,
            )
        )
        snapshots = [
            snapshot
            for group in getattr(output, "snapshots", [])
            for snapshot in getattr(group, "snapshots", [])
        ]
        if not snapshots:
            raise CheckpointNotReadyError(
                "Waiting for the first live basecalling statistics."
            )
        latest = max(snapshots, key=lambda snapshot: float(snapshot.seconds))
        summary = latest.yield_summary
        passed = _field_number(summary, "basecalled_pass_bases", "passed_bases")
        if passed is None:
            raise MinknowUnavailableError(
                "This MinKNOW API does not expose a compatible passed-base counter."
            )
        return {
            "observed_seconds": float(latest.seconds),
            "passed_bases": passed,
            "failed_bases": _field_number(
                summary, "basecalled_fail_bases", "failed_bases"
            ) or 0.0,
            "total_reads": _field_number(summary, "read_count", "total_read_count")
            or 0.0,
            "passed_reads": _field_number(
                summary, "basecalled_pass_read_count", "passed_read_count"
            ) or 0.0,
        }

    def _boxplot(self, connection: Any, run_id: str, horizon: int, data_type: int) -> Any | None:
        try:
            response = _first_response(
                connection.statistics.stream_basecall_boxplots(
                    acquisition_run_id=run_id,
                    data_type=data_type,
                    dataset_width=10,
                    poll_time=60,
                    _timeout=self.rpc_timeout,
                )
            )
        except Exception:
            return None
        datasets = list(getattr(response, "datasets", []))
        index = horizon // 10 - 1
        if 0 <= index < len(datasets):
            return datasets[index]
        return datasets[-1] if datasets else None

    def _temperature(
        self,
        connection: Any,
        run_id: str,
        horizon_seconds: int,
        statistics_pb2: Any,
    ) -> tuple[float | None, float | None]:
        try:
            response = _first_response(
                connection.statistics.stream_temperature(
                    acquisition_run_id=run_id,
                    data_selection=statistics_pb2.DataSelection(
                        start=0, step=60, end=horizon_seconds + 1
                    ),
                    _timeout=self.rpc_timeout,
                )
            )
        except Exception:
            return None, None
        packets = list(getattr(response, "temperatures", []))
        if not packets:
            return None, None
        packet = packets[-1]
        measured = _number(getattr(getattr(packet, "minion", None), "heatsink_temperature", None))
        # The MinION reports used for training encoded this report field as
        # 0.0 in all 513 snapshots, so preserve that representation rather
        # than introducing an out-of-distribution target temperature here.
        return measured, 0.0


class AdaptiveCollector:
    """Use compatible MinKNOW RPCs, with a version-independent BAM fallback."""

    def __init__(
        self,
        minknow: MinknowCollector,
        bam: BamFallbackCollector,
    ):
        self.minknow = minknow
        self.bam = bam

    @staticmethod
    def client_available() -> bool:
        return MinknowCollector.client_available()

    def active_positions(self) -> list[Any]:
        try:
            positions = self.minknow.active_positions()
            # A Manager connection can succeed even when the position-level
            # RPC schema is incompatible. Probe metadata before committing the
            # supervisor to API mode so that this case also reaches BAM mode.
            for position in positions:
                self.minknow.inspect_position(position)
            return positions
        except NoActiveRunError:
            raise
        except MinknowUnavailableError as api_error:
            try:
                return self.bam.active_positions()
            except BamFallbackUnavailable as fallback_error:
                raise MinknowUnavailableError(
                    f"{api_error} {fallback_error}"
                ) from api_error

    def inspect(self) -> dict[str, Any]:
        active = self.active_positions()
        if len(active) > 1:
            raise NoActiveRunError(
                "More than one MinION or BAM run is active; select a position."
            )
        return self.inspect_position(active[0])

    def inspect_position(self, position: Any) -> dict[str, Any]:
        if isinstance(position, BamPosition):
            return self.bam.inspect_position(position)
        return self.minknow.inspect_position(position)

    def collect_live_progress(self, context: dict[str, Any]) -> dict[str, float]:
        if context.get("collector_mode") == "bam_fallback":
            return self.bam.collect_live_progress(context)
        try:
            return self.minknow.collect_live_progress(context)
        except Exception as exc:
            if not (context.get("reads_directory") or context.get("output_path")):
                raise
            context["collector_mode"] = "bam_fallback"
            context["prediction_available"] = False
            context["compatibility_warning"] = (
                "The MinKNOW statistics API is incompatible; using completed BAM "
                f"batches for live yield and CpGs ({type(exc).__name__})."
            )
            return self.bam.collect_live_progress(context)

    def collect(
        self, horizon_minutes: int, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        context = context or self.inspect()
        if not context.get("prediction_available", True):
            raise CheckpointNotReadyError(
                "Calibrated prediction requires compatible MinKNOW statistics."
            )
        try:
            return self.minknow.collect(horizon_minutes, context)
        except CheckpointNotReadyError:
            raise
        except Exception as exc:
            context["collector_mode"] = "bam_fallback"
            context["prediction_available"] = False
            context["compatibility_warning"] = (
                "Some MinKNOW statistics required by the calibrated model are "
                f"unavailable ({type(exc).__name__}); BAM monitoring remains active."
            )
            raise CheckpointNotReadyError(
                "Calibrated prediction is unavailable in BAM fallback mode."
            ) from exc


class _PositionMonitor:
    """Retain checkpoint predictions for one MinKNOW position."""

    def __init__(
        self,
        collector: Any,
        engine: RunDecisionEngine,
        poll_seconds: float = 20.0,
        start_thread: bool = True,
        cpg_targets: NanoDxTargets | None = None,
        start_cpg_thread: bool = True,
    ):
        self.collector = collector
        self.engine = engine
        self.poll_seconds = poll_seconds
        self._target_gb = 10.0
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._run_key: str | None = None
        self._elapsed_seconds = 0.0
        self._minknow_version: str | None = None
        self._api_client_version: str | None = None
        self._collector_mode = "connecting"
        self._prediction_available = True
        self._rows: dict[int, dict[str, Any]] = {}
        self._assessments: dict[int, dict[str, Any]] = {}
        self._live_progress: dict[str, float] | None = None
        self._progress_history: list[tuple[float, float]] = []
        self._target_reached_seconds: float | None = None
        self._state = "connecting"
        self._message = "Connecting to local MinKNOW."
        self._last_update: str | None = None
        self._warning: str | None = None
        self._cpg_monitor = NanoDxCpgMonitor(
            cpg_targets or default_nanodx_targets(),
            poll_seconds=poll_seconds,
            start_thread=start_cpg_thread,
        )
        self._thread: threading.Thread | None = None
        if start_thread:
            self._thread = threading.Thread(target=self._run, daemon=True, name="nanopredict-live")
            self._thread.start()

    def configure(self, target_gb: float) -> dict[str, Any]:
        if not math.isfinite(target_gb) or target_gb <= 0:
            raise ValueError("Target yield must be a positive number")
        with self._lock:
            self._target_gb = float(target_gb)
            self._assessments = {
                horizon: self.engine.assess(row, horizon, self._target_gb)
                for horizon, row in self._rows.items()
            }
            if self._live_progress is not None:
                if self._live_progress["passed_bases"] >= self._target_gb * 1e9:
                    self._target_reached_seconds = self._live_progress[
                        "observed_seconds"
                    ]
                else:
                    self._target_reached_seconds = None
            return self.status()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.poll_seconds)

    def poll_once(self) -> None:
        try:
            context = self.collector.inspect()
            self.poll_context(context)
        except NoActiveRunError as exc:
            self.set_waiting(str(exc))
        except Exception as exc:
            self.set_error(str(exc) or type(exc).__name__)

    def poll_context(self, context: dict[str, Any]) -> None:
        """Collect due checkpoints from already-discovered position metadata."""
        run_key = context["run_key"]
        elapsed = float(context["elapsed_seconds"])
        with self._lock:
            if run_key != self._run_key:
                self._run_key = run_key
                self._rows.clear()
                self._assessments.clear()
                self._live_progress = None
                self._progress_history.clear()
                self._target_reached_seconds = None
            self._elapsed_seconds = elapsed
            self._minknow_version = context["minknow_version"]
            self._api_client_version = context.get("api_client_version")
            self._collector_mode = context.get("collector_mode", "compatibility")
            self._prediction_available = bool(
                context.get("prediction_available", True)
            )
            self._warning = context.get("compatibility_warning")

        self._cpg_monitor.update_context(context)

        try:
            live_progress = self.collector.collect_live_progress(context)
        except CheckpointNotReadyError:
            live_progress = None
        if live_progress is not None:
            with self._lock:
                point = (
                    live_progress["observed_seconds"],
                    live_progress["passed_bases"],
                )
                if self._progress_history and point[0] == self._progress_history[-1][0]:
                    self._progress_history[-1] = point
                elif not self._progress_history or point[0] > self._progress_history[-1][0]:
                    self._progress_history.append(point)
                    self._progress_history = self._progress_history[-12:]
                self._live_progress = live_progress
                if (
                    self._target_reached_seconds is None
                    and live_progress["passed_bases"] >= self._target_gb * 1e9
                ):
                    self._target_reached_seconds = live_progress["observed_seconds"]

        eligible = [h for h in SUPPORTED_HORIZONS if elapsed >= h * 60]
        for horizon in eligible:
            with self._lock:
                missing = horizon not in self._rows
                target_gb = self._target_gb
            if missing:
                try:
                    row = self.collector.collect(horizon, context)
                except CheckpointNotReadyError:
                    break
                assessment = self.engine.assess(row, horizon, target_gb)
                with self._lock:
                    if target_gb != self._target_gb:
                        assessment = self.engine.assess(
                            row, horizon, self._target_gb
                        )
                    self._rows[horizon] = row
                    self._assessments[horizon] = assessment

        with self._lock:
            self._collector_mode = context.get(
                "collector_mode", self._collector_mode
            )
            self._prediction_available = bool(
                context.get("prediction_available", self._prediction_available)
            )
            self._warning = context.get("compatibility_warning")
            current = max(self._rows, default=None)
            self._state = "complete" if current == SUPPORTED_HORIZONS[-1] else "running"
            next_horizon = next((h for h in SUPPORTED_HORIZONS if h not in self._rows), None)
            if not self._prediction_available:
                self._message = (
                    "BAM fallback active: live yield and NanoDx CpGs are available; "
                    "calibrated final-yield prediction is unavailable."
                )
            else:
                self._message = (
                    "All early prediction checkpoints have been collected."
                    if next_horizon is None
                    else f"Collecting data for the {next_horizon}-minute checkpoint."
                )
            self._last_update = datetime.now(timezone.utc).isoformat()

    def set_waiting(self, message: str) -> None:
        with self._lock:
            self._state = "waiting"
            self._message = message
            self._warning = None
            self._run_key = None
            self._elapsed_seconds = 0.0
            self._api_client_version = None
            self._collector_mode = "waiting"
            self._prediction_available = True
            self._rows.clear()
            self._assessments.clear()
            self._live_progress = None
            self._progress_history.clear()
            self._target_reached_seconds = None
            self._cpg_monitor.set_waiting()
            self._last_update = datetime.now(timezone.utc).isoformat()

    def set_error(self, message: str) -> None:
        with self._lock:
            self._state = "error"
            self._message = message
            self._warning = "Live collection will retry automatically."
            self._last_update = datetime.now(timezone.utc).isoformat()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.poll_seconds + 1, 5))
        self._cpg_monitor.close()

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = max(self._rows, default=None)
            row = self._rows.get(current) if current is not None else None
            assessment = self._assessments.get(current) if current is not None else None
            next_horizon = next((h for h in SUPPORTED_HORIZONS if h not in self._rows), None)
            observations = None
            if row is not None:
                passed = _number(row.get("observed_passed_bases"))
                observations = {
                    "passed_yield_gb": None if passed is None else passed / 1e9,
                    "total_reads": _number(row.get("observed_total_reads")),
                    "temperature_c": _number(row.get("observed_temperature")),
                    "sequencing_percent": _number(row.get("pore_activity_sequencing_percent")),
                    "pore_available_percent": _number(
                        row.get("pore_activity_pore_available_percent")
                    ),
                }
            live_progress = None
            if self._live_progress is not None:
                passed_bases = self._live_progress["passed_bases"]
                target_bases = self._target_gb * 1e9
                remaining_bases = max(target_bases - passed_bases, 0.0)
                target_reached = passed_bases >= target_bases
                rate_per_minute = None
                if self._progress_history:
                    latest_seconds, latest_bases = self._progress_history[-1]
                    candidates = [
                        point
                        for point in self._progress_history
                        if point[0] >= latest_seconds - 600
                    ]
                    earliest_seconds, earliest_bases = candidates[0]
                    if latest_seconds > earliest_seconds:
                        rate_per_minute = max(
                            (latest_bases - earliest_bases)
                            * 60.0
                            / (latest_seconds - earliest_seconds),
                            0.0,
                        )
                    elif latest_seconds > 0:
                        rate_per_minute = max(
                            latest_bases * 60.0 / latest_seconds, 0.0
                        )
                eta_minutes = None
                if not target_reached and rate_per_minute and rate_per_minute > 0:
                    eta_minutes = remaining_bases / rate_per_minute
                live_progress = {
                    **self._live_progress,
                    "passed_yield_gb": passed_bases / 1e9,
                    "target_bases": target_bases,
                    "progress_fraction": min(passed_bases / target_bases, 1.0),
                    "progress_percent": min(passed_bases * 100.0 / target_bases, 100.0),
                    "remaining_bases": remaining_bases,
                    "rate_bases_per_minute": rate_per_minute,
                    "eta_minutes": eta_minutes,
                    "target_reached": target_reached,
                    "target_reached_elapsed_minutes": (
                        None
                        if self._target_reached_seconds is None
                        else self._target_reached_seconds / 60.0
                    ),
                }
            return {
                "mode": "minknow",
                "state": self._state,
                "sample_id": "Live MinION run" if self._run_key else None,
                "device_type": "MinION",
                "target_gb": self._target_gb,
                "elapsed_minutes": self._elapsed_seconds / 60.0,
                "current_horizon_minutes": current,
                "next_horizon_minutes": next_horizon,
                "observations": observations,
                "live_progress": live_progress,
                "nanodx_cpg": self._cpg_monitor.status(),
                "assessment": assessment,
                "history": [
                    {
                        "horizon_minutes": horizon,
                        "status": self._assessments[horizon]["status"],
                        "prediction_gb": self._assessments[horizon]["prediction"][
                            "point_prediction_gb"
                        ],
                        "probability": self._assessments[horizon][
                            "probability_of_reaching_target"
                        ],
                    }
                    for horizon in sorted(self._assessments)
                ],
                "actual_final_gb": None,
                "message": self._message,
                "warning": self._warning,
                "last_update": self._last_update,
                "minknow_version": self._minknow_version,
                "api_client_version": self._api_client_version,
                "collector_mode": self._collector_mode,
                "prediction_available": self._prediction_available,
                "minknow_core_target": "automatic with BAM fallback",
                "device_target": "MinION",
                "read_only": True,
            }


class LiveMonitor:
    """Supervise every active MinION position from one background thread."""

    def __init__(
        self,
        collector: Any,
        engine: RunDecisionEngine,
        poll_seconds: float = 20.0,
        start_thread: bool = True,
    ):
        self.collector = collector
        self.engine = engine
        self.poll_seconds = poll_seconds
        self._default_target_gb = 10.0
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitors: dict[str, _PositionMonitor] = {}
        self._state = "connecting"
        self._message = "Connecting to local MinKNOW."
        self._warning: str | None = None
        self._last_update: str | None = None
        self._start_background_workers = start_thread
        self._cpg_targets = default_nanodx_targets()
        self._thread: threading.Thread | None = None
        if start_thread:
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="nanopredict-live",
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.poll_seconds)

    def poll_once(self) -> None:
        try:
            positions = self.collector.active_positions()
        except NoActiveRunError as exc:
            with self._lock:
                monitors = list(self._monitors.values())
                self._monitors.clear()
                self._state = "waiting"
                self._message = str(exc)
                self._warning = None
                self._last_update = datetime.now(timezone.utc).isoformat()
            for monitor in monitors:
                monitor.close()
            return
        except Exception as exc:
            error_message = str(exc) or type(exc).__name__
            with self._lock:
                self._state = "error"
                self._message = error_message
                self._warning = "Live collection will retry automatically."
                self._last_update = datetime.now(timezone.utc).isoformat()
                monitors = list(self._monitors.values())
            for monitor in monitors:
                monitor.set_error(error_message)
            return

        active_names = {
            str(getattr(position, "name", "Unknown position")) for position in positions
        }
        with self._lock:
            removed = []
            for name in list(self._monitors):
                if name not in active_names:
                    removed.append(self._monitors.pop(name))
        for monitor in removed:
            monitor.close()

        for position in positions:
            name = str(getattr(position, "name", "Unknown position"))
            with self._lock:
                monitor = self._monitors.get(name)
                if monitor is None:
                    monitor = _PositionMonitor(
                        self.collector,
                        self.engine,
                        poll_seconds=self.poll_seconds,
                        start_thread=False,
                        cpg_targets=self._cpg_targets,
                        start_cpg_thread=self._start_background_workers,
                    )
                    monitor.configure(self._default_target_gb)
                    self._monitors[name] = monitor
            try:
                context = self.collector.inspect_position(position)
                monitor.poll_context(context)
            except NoActiveRunError as exc:
                monitor.set_waiting(str(exc))
            except Exception as exc:
                monitor.set_error(str(exc) or type(exc).__name__)

        with self._lock:
            self._state = "running"
            count = len(self._monitors)
            self._message = f"Monitoring {count} active MinION position{'s' if count != 1 else ''}."
            self._warning = None
            self._last_update = datetime.now(timezone.utc).isoformat()

    def configure(
        self, target_gb: float, position_name: str | None = None
    ) -> dict[str, Any]:
        if not math.isfinite(target_gb) or target_gb <= 0:
            raise ValueError("Target yield must be a positive number")
        with self._lock:
            names = sorted(self._monitors)
            if position_name is None:
                if len(names) > 1:
                    raise ValueError("Select a MinION position before applying the target")
                position_name = names[0] if names else None
            if position_name is not None and position_name not in self._monitors:
                raise ValueError(f"Active MinION position not found: {position_name}")
            if position_name is None:
                self._default_target_gb = float(target_gb)
                return self.status()
            monitor = self._monitors[position_name]
        monitor.configure(target_gb)
        return self.status(position_name)

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.poll_seconds + 1, 5))
        with self._lock:
            monitors = list(self._monitors.values())
            self._monitors.clear()
        for monitor in monitors:
            monitor.close()

    @staticmethod
    def _position_summary(name: str, status: dict[str, Any]) -> dict[str, Any]:
        assessment = status.get("assessment") or {}
        prediction = assessment.get("prediction") or {}
        live_progress = status.get("live_progress") or {}
        nanodx_cpg = status.get("nanodx_cpg") or {}
        return {
            "position_name": name,
            "state": status["state"],
            "target_gb": status["target_gb"],
            "elapsed_minutes": status["elapsed_minutes"],
            "current_horizon_minutes": status["current_horizon_minutes"],
            "next_horizon_minutes": status["next_horizon_minutes"],
            "assessment_status": assessment.get("status"),
            "prediction_gb": prediction.get("point_prediction_gb"),
            "probability": assessment.get("probability_of_reaching_target"),
            "passed_bases": live_progress.get("passed_bases"),
            "progress_percent": live_progress.get("progress_percent"),
            "eta_minutes": live_progress.get("eta_minutes"),
            "target_reached": bool(live_progress.get("target_reached")),
            "nanodx_cpg_count": nanodx_cpg.get("count"),
            "nanodx_cpg_threshold": nanodx_cpg.get("threshold"),
            "nanodx_cpg_reached": bool(nanodx_cpg.get("threshold_reached")),
            "nanodx_cpg_state": nanodx_cpg.get("state"),
            "nanodx_cpg_rate_per_minute": nanodx_cpg.get("rate_cpg_per_minute"),
            "nanodx_cpg_eta_minutes": nanodx_cpg.get("eta_minutes"),
            "collector_mode": status.get("collector_mode"),
            "prediction_available": status.get("prediction_available", True),
            "message": status["message"],
        }

    def status(self, position_name: str | None = None) -> dict[str, Any]:
        with self._lock:
            names = sorted(self._monitors)
            monitors = [(name, self._monitors[name]) for name in names]
            state = self._state
            message = self._message
            warning = self._warning
            last_update = self._last_update
            default_target = self._default_target_gb

        detailed = {name: monitor.status() for name, monitor in monitors}
        positions = [
            self._position_summary(name, detailed[name]) for name in names
        ]
        selected = position_name if position_name in detailed else (names[0] if names else None)
        common = {
            "positions": positions,
            "active_position_count": len(positions),
            "selected_position": selected,
        }
        if selected is None:
            return {
                "mode": "minknow",
                "state": state,
                "sample_id": None,
                "position_name": None,
                "device_type": "MinION",
                "target_gb": default_target,
                "elapsed_minutes": 0.0,
                "current_horizon_minutes": None,
                "next_horizon_minutes": SUPPORTED_HORIZONS[0],
                "observations": None,
                "live_progress": None,
                "assessment": None,
                "history": [],
                "actual_final_gb": None,
                "message": message,
                "warning": warning,
                "last_update": last_update,
                "minknow_version": None,
                "api_client_version": MinknowCollector.client_version(),
                "collector_mode": "connecting",
                "prediction_available": True,
                "minknow_core_target": "automatic with BAM fallback",
                "device_target": "MinION",
                "read_only": True,
                **common,
            }

        result = detailed[selected]
        result.update(
            {
                "sample_id": selected,
                "position_name": selected,
                **common,
            }
        )
        return result
