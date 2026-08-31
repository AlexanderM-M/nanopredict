"""Read-only MinKNOW 6.4 feature collection for live MinION runs."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .diagnose_run import RunDecisionEngine
from .replay import SUPPORTED_HORIZONS


MINION_DEVICE_TYPES = {"MINION", "MINION_MK1C", "MINION_MK1D"}
MODEL_DEVICE_TYPE = "MINION_MK1D"
CALIBRATION_PURPOSE = 3  # minknow_api.acquisition_pb2.CALIBRATION in API 6.4


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
                "The MinKNOW 6.4 client is not installed. Reinstall Nanopredict."
            ) from exc
        return Manager(host=self.host)

    def _active_connection(self) -> tuple[Any, Any]:
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
        if len(active) > 1:
            raise NoActiveRunError(
                "More than one MinION run is active; select one with --position."
            )
        try:
            return active[0], active[0].connect()
        except Exception as exc:
            raise MinknowUnavailableError(
                "MinKNOW found the run but could not connect to it."
            ) from exc

    def inspect(self) -> dict[str, Any]:
        """Return active-run metadata without collecting checkpoint statistics."""
        position, connection = self._active_connection()
        try:
            version = connection.instance.get_version_info(_timeout=self.rpc_timeout)
        except Exception as exc:
            raise MinknowUnavailableError(
                "Connected to the MinION position but could not read its MinKNOW version."
            ) from exc
        major = int(getattr(version.minknow, "major", 0))
        minor = int(getattr(version.minknow, "minor", 0))
        if (major, minor) != (6, 4):
            raise MinknowUnavailableError(
                f"Connected MinKNOW Core is {major}.{minor}; this collector requires 6.4.x."
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
        if not bool(getattr(acquisition.config_summary, "basecalling_enabled", False)):
            raise MinknowUnavailableError(
                "The active run has live basecalling disabled; passed-yield prediction "
                "requires basecalling."
            )
        started = _timestamp_seconds(getattr(acquisition, "start_time", None))
        if not started:
            started = _timestamp_seconds(getattr(acquisition, "data_read_start_time", None))
        elapsed = 0.0 if started is None else max(time.time() - started, 0.0)
        run_id = str(acquisition.run_id)
        return {
            "position": position,
            "connection": connection,
            "acquisition": acquisition,
            "run_id": run_id,
            "run_key": hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12],
            "elapsed_seconds": elapsed,
            "minknow_version": getattr(version.minknow, "full", f"{major}.{minor}"),
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
            raise MinknowUnavailableError("The MinKNOW 6.4 client is not installed.") from exc

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
        duty = _first_response(
            connection.statistics.stream_duty_time(
                acquisition_run_id=run_id,
                data_selection=selection,
                _timeout=self.rpc_timeout,
            )
        )
        temperature = self._temperature(connection, run_id, horizon_seconds, statistics_pb2)
        basecaller = connection.analysis_configuration.get_basecaller_configuration(
            run_id=run_id, _timeout=self.rpc_timeout
        )

        estimated = _number(summary.estimated_selected_bases)
        passed = _number(summary.basecalled_pass_bases)
        failed = _number(summary.basecalled_fail_bases)
        total_reads = _number(summary.read_count)
        passed_reads = _number(summary.basecalled_pass_read_count)
        failed_reads = _number(summary.basecalled_fail_read_count)
        observed_seconds = _number(latest.seconds)
        called = None if passed is None or failed is None else passed + failed

        row: dict[str, Any] = {
            "device_type": MODEL_DEVICE_TYPE,
            "device_is_promethion": 0,
            "minimum_q_score_setting": _wrapped_number(basecaller.read_filtering, "min_qscore"),
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

    def _boxplot(self, connection: Any, run_id: str, horizon: int, data_type: int) -> Any | None:
        response = _first_response(
            connection.statistics.stream_basecall_boxplots(
                acquisition_run_id=run_id,
                data_type=data_type,
                dataset_width=10,
                poll_time=60,
                _timeout=self.rpc_timeout,
            )
        )
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
        response = _first_response(
            connection.statistics.stream_temperature(
                acquisition_run_id=run_id,
                data_selection=statistics_pb2.DataSelection(
                    start=0, step=60, end=horizon_seconds + 1
                ),
                _timeout=self.rpc_timeout,
            )
        )
        packets = list(getattr(response, "temperatures", []))
        if not packets:
            return None, None
        packet = packets[-1]
        measured = _number(getattr(getattr(packet, "minion", None), "heatsink_temperature", None))
        # The MinION reports used for training encoded this report field as
        # 0.0 in all 513 snapshots, so preserve that representation rather
        # than introducing an out-of-distribution target temperature here.
        return measured, 0.0


class LiveMonitor:
    """Poll MinKNOW in the background and retain checkpoint predictions."""

    def __init__(
        self,
        collector: MinknowCollector,
        engine: RunDecisionEngine,
        poll_seconds: float = 20.0,
        start_thread: bool = True,
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
        self._rows: dict[int, dict[str, Any]] = {}
        self._assessments: dict[int, dict[str, Any]] = {}
        self._state = "connecting"
        self._message = "Connecting to local MinKNOW."
        self._last_update: str | None = None
        self._warning: str | None = None
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
            return self.status()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.poll_seconds)

    def poll_once(self) -> None:
        try:
            context = self.collector.inspect()
            run_key = context["run_key"]
            elapsed = float(context["elapsed_seconds"])
            with self._lock:
                if run_key != self._run_key:
                    self._run_key = run_key
                    self._rows.clear()
                    self._assessments.clear()
                self._elapsed_seconds = elapsed
                self._minknow_version = context["minknow_version"]
                self._warning = None

            eligible = [h for h in SUPPORTED_HORIZONS if elapsed >= h * 60]
            for horizon in eligible:
                with self._lock:
                    missing = horizon not in self._rows
                if missing:
                    try:
                        row = self.collector.collect(horizon, context)
                    except CheckpointNotReadyError:
                        break
                    assessment = self.engine.assess(row, horizon, self._target_gb)
                    with self._lock:
                        self._rows[horizon] = row
                        self._assessments[horizon] = assessment

            with self._lock:
                current = max(self._rows, default=None)
                self._state = "complete" if current == SUPPORTED_HORIZONS[-1] else "running"
                next_horizon = next((h for h in SUPPORTED_HORIZONS if h not in self._rows), None)
                self._message = (
                    "All early prediction checkpoints have been collected."
                    if next_horizon is None
                    else f"Collecting data for the {next_horizon}-minute checkpoint."
                )
                self._last_update = datetime.now(timezone.utc).isoformat()
        except NoActiveRunError as exc:
            with self._lock:
                self._state = "waiting"
                self._message = str(exc)
                self._run_key = None
                self._elapsed_seconds = 0.0
                self._rows.clear()
                self._assessments.clear()
                self._last_update = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            with self._lock:
                self._state = "error"
                self._message = str(exc) or type(exc).__name__
                self._warning = "Live collection will retry automatically."
                self._last_update = datetime.now(timezone.utc).isoformat()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.poll_seconds + 1, 5))

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
                "minknow_core_target": "6.4.x",
                "device_target": "MinION",
                "read_only": True,
            }
