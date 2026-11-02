"""Optional read-only NVML telemetry, explicit trace boundaries and Zeus import.

No GPU library is imported until live collection is requested. Trace I/O and
replay require only core dependencies. See docs/user_guide/gpu_lab.rst.
"""

import importlib
import json
import platform
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from datacenter_simulator.models.devices import finite
from datacenter_simulator.utilities.timeseries import resample_intervals

METRICS = (
    "power_w",
    "energy_j",
    "temperature_c",
    "gpu_utilization_pct",
    "memory_utilization_pct",
    "graphics_clock_mhz",
    "memory_clock_mhz",
    "power_limit_w",
)


def software_versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {"python": platform.python_version()}
    for name in ("datacenter-simulator", "nvidia-ml-py", "zeus", "torch", "scikit-learn", "numpy"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


@dataclass
class GPUTrace:
    """Point samples with monotonic elapsed seconds, UTC timestamp and metadata."""

    samples: pd.DataFrame
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.metadata.get("schema_version") != 1:
            raise ValueError("unsupported GPU trace schema_version")
        if self.metadata.get("kind") not in {"measured", "imported", "synthetic"}:
            raise ValueError("trace kind must be measured, imported or synthetic")
        if self.metadata.get("boundary") not in {"gpu_board", "server_dc", "server_ac"}:
            raise ValueError("explicit measurement boundary required")
        for field in ("source", "configuration", "software_versions"):
            if not self.metadata.get(field):
                raise ValueError(f"trace metadata requires {field}")
        frame = self.samples.copy()
        if len(frame) < 2 or not {"timestamp", "elapsed_s"} <= set(frame):
            raise ValueError("at least two timestamped samples required")
        stamps = [pd.Timestamp(v) for v in frame.timestamp]
        if any(pd.isna(v) or v.tzinfo is None for v in stamps):
            raise ValueError("timestamps must include a timezone")
        frame["timestamp"] = pd.to_datetime(stamps, utc=True)
        elapsed = frame.elapsed_s.to_numpy(dtype=float)
        if not np.isfinite(elapsed).all() or elapsed[0] != 0 or np.any(np.diff(elapsed) <= 0):
            raise ValueError("elapsed_s must start at zero and strictly increase")
        if not frame.timestamp.is_monotonic_increasing or frame.timestamp.duplicated().any():
            raise ValueError("timestamps must strictly increase")
        wall = (frame.timestamp - frame.timestamp.iloc[0]).dt.total_seconds().to_numpy()
        if not np.allclose(wall, elapsed, atol=0.1, rtol=0):
            raise ValueError("timestamp/monotonic elapsed mismatch exceeds 0.1 s")
        for metric in METRICS:
            if metric not in frame:
                frame[metric] = np.nan
            vals = frame[metric].to_numpy(dtype=float)
            valid = vals[~np.isnan(vals)]
            if not np.isfinite(valid).all() or (metric != "temperature_c" and (valid < 0).any()):
                raise ValueError(f"invalid {metric}")
            if metric.endswith("_pct") and (valid > 100).any():
                raise ValueError(f"invalid {metric}")
        self.samples = frame

    def intervals(self, *, max_gap_s: float) -> pd.DataFrame:
        """Counter differences preferred; trapezoidal power fallback per interval.

        A counter reset is rejected. Unavailable endpoints remain NaN, preventing
        downstream replay; no bridging across missing telemetry or excessive gaps.
        """
        finite("max_gap_s", max_gap_s, strict=True)
        f = self.samples
        times = f.elapsed_s.to_numpy(dtype=float)
        dt = np.diff(times)
        if np.any(dt > max_gap_s):
            raise ValueError("telemetry gap exceeds max_gap_s")
        energy = f.energy_j.to_numpy(dtype=float)
        power = f.power_w.to_numpy(dtype=float)
        counter = np.isfinite(energy[:-1]) & np.isfinite(energy[1:])
        delta = np.diff(energy)
        if np.any(delta[counter] < 0):
            raise ValueError("energy counter reset; split the trace at the reset")
        average = (power[:-1] + power[1:]) / 2
        average[counter] = delta[counter] / dt[counter]
        return pd.DataFrame(
            {
                "time_s": times[:-1],
                "duration_s": dt,
                "power_kw": average / 1000,
                "energy_method": np.where(counter, "counter", "power_trapezoid"),
            }
        )

    def replay(
        self, *, step_s: float, max_gap_s: float, start: pd.Timestamp | None = None
    ) -> pd.Series:
        return resample_intervals(
            self.intervals(max_gap_s=max_gap_s),
            start if start is not None else self.samples.timestamp.iloc[0],
            step_s=step_s,
        )

    def write_csv(self, path: str | Path) -> Path:
        """CSV plus mandatory .metadata.json sidecar; blanks mean unavailable."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.samples.to_csv(target, index=False)
        target.with_suffix(".metadata.json").write_text(
            json.dumps(self.metadata, indent=2, allow_nan=False) + "\n"
        )
        return target

    @classmethod
    def read_csv(cls, path: str | Path) -> "GPUTrace":
        target = Path(path)
        return cls(
            pd.read_csv(target), json.loads(target.with_suffix(".metadata.json").read_text())
        )


class NVMLCollector:
    """Context-managed physical-GPU telemetry. Index is NVML, NOT CUDA-visible order.

    A UUID is preferred. Optional field errors are retained as per-field status;
    initialization/device lookup failures abort rather than producing an empty run.
    """

    def __init__(self, device: int | str = 0) -> None:
        self.device = device
        self.api: Any = None
        self.handle: Any = None
        self.metadata: dict[str, Any] = {}
        self.origin = 0.0
        self.utc_origin = pd.Timestamp.now(tz="UTC")

    def __enter__(self) -> "NVMLCollector":
        try:
            self.api = importlib.import_module("pynvml")
        except ImportError as exc:
            raise RuntimeError(
                "Live NVML requires pip install 'datacenter-simulator[gpu]'"
            ) from exc
        try:
            self.api.nvmlInit()
        except self.api.NVMLError as exc:
            raise RuntimeError(f"NVML unavailable: {exc}") from exc
        try:
            self.handle = (
                self.api.nvmlDeviceGetHandleByUUID(self.device)
                if isinstance(self.device, str)
                else self.api.nvmlDeviceGetHandleByIndex(self.device)
            )
            self.origin = time.perf_counter()
            self.utc_origin = pd.Timestamp.now(tz="UTC")
            self.metadata = {
                "schema_version": 1,
                "kind": "measured",
                "boundary": "gpu_board",
                "source": "native NVML point telemetry",
                "software_versions": software_versions(),
                "configuration": {"device_selector": self.device, "index_space": "physical NVML"},
                "identity": {},
                "identity_status": {},
            }
            for field, api in (
                ("gpu_model", "nvmlDeviceGetName"),
                ("uuid", "nvmlDeviceGetUUID"),
                ("vbios", "nvmlDeviceGetVbiosVersion"),
                ("mig_mode", "nvmlDeviceGetMigMode"),
                ("persistence_mode", "nvmlDeviceGetPersistenceMode"),
            ):
                value, status = self._query(api, self.handle)
                self.metadata["identity"][field] = value
                self.metadata["identity_status"][field] = status
            for field, api in (
                ("driver", "nvmlSystemGetDriverVersion"),
                ("nvml", "nvmlSystemGetNVMLVersion"),
            ):
                value, status = self._query(api)
                self.metadata["identity"][field] = value
                self.metadata["identity_status"][field] = status
            return self
        except BaseException:
            self.api.nvmlShutdown()
            raise

    def _query(self, name: str, *args: Any) -> tuple[Any, str]:
        function = getattr(self.api, name, None)
        if function is None:
            return None, "missing_api"
        try:
            value = function(*args)
            return value.decode() if isinstance(value, bytes) else value, "ok"
        except self.api.NVMLError as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def sample(self) -> dict[str, Any]:
        elapsed = time.perf_counter() - self.origin
        row: dict[str, Any] = {
            "elapsed_s": elapsed,
            "timestamp": self.utc_origin + pd.Timedelta(seconds=elapsed),
        }
        queries = (
            ("power_w", "nvmlDeviceGetPowerUsage", (), 0.001),
            ("energy_j", "nvmlDeviceGetTotalEnergyConsumption", (), 0.001),
            ("temperature_c", "nvmlDeviceGetTemperature", (self.api.NVML_TEMPERATURE_GPU,), 1),
            ("power_limit_w", "nvmlDeviceGetPowerManagementLimit", (), 0.001),
            ("graphics_clock_mhz", "nvmlDeviceGetClockInfo", (self.api.NVML_CLOCK_GRAPHICS,), 1),
            ("memory_clock_mhz", "nvmlDeviceGetClockInfo", (self.api.NVML_CLOCK_MEM,), 1),
        )
        for field, name, args, scale in queries:
            value, status = self._query(name, self.handle, *args)
            row[field], row[field + "_status"] = (None if value is None else value * scale), status
        rates, status = self._query("nvmlDeviceGetUtilizationRates", self.handle)
        for field, attr in (("gpu_utilization_pct", "gpu"), ("memory_utilization_pct", "memory")):
            row[field] = None if rates is None else getattr(rates, attr)
            row[field + "_status"] = status
        row["query_duration_s"] = time.perf_counter() - self.origin - elapsed
        return row

    def trace(self, rows: list[dict[str, Any]]) -> GPUTrace:
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame["elapsed_s"] -= frame.elapsed_s.iloc[0]
        return GPUTrace(frame, self.metadata.copy())

    def collect(self, duration_s: float, *, interval_s: float = 0.2) -> GPUTrace:
        finite("duration_s", duration_s, strict=True)
        finite("interval_s", interval_s, strict=True)
        rows = [self.sample()]
        until = time.perf_counter() + duration_s
        while time.perf_counter() < until:
            time.sleep(min(interval_s, max(0, until - time.perf_counter())))
            rows.append(self.sample())
        return self.trace(rows)

    @contextmanager
    def power_limit(self, watts: float | None, *, allow_control: bool = False) -> Iterator[None]:
        """Opt-in experiment; restore the captured limit even after handled failure.

        SIGKILL, power loss and driver loss cannot guarantee restoration. No clock,
        fan, persistence or other setting is changed. Permission errors propagate.
        """
        if watts is None:
            yield
            return
        if not allow_control:
            raise PermissionError("power-limit writes require explicit allow_control=True")
        finite("power limit W", watts, strict=True)
        requested = round(watts * 1000)
        minimum, maximum = self.api.nvmlDeviceGetPowerManagementLimitConstraints(self.handle)
        if not minimum <= requested <= maximum:
            raise ValueError(
                f"power limit outside device range [{minimum / 1000}, {maximum / 1000}] W"
            )
        original = self.api.nvmlDeviceGetPowerManagementLimit(self.handle)
        try:
            self.api.nvmlDeviceSetPowerManagementLimit(self.handle, requested)
            actual = self.api.nvmlDeviceGetPowerManagementLimit(self.handle)
            if actual != requested:
                raise RuntimeError(
                    f"power limit verification failed: requested {requested}, got {actual}"
                )
            yield
        finally:
            self.api.nvmlDeviceSetPowerManagementLimit(self.handle, original)
            if self.api.nvmlDeviceGetPowerManagementLimit(self.handle) != original:
                raise RuntimeError("original power limit could not be restored")

    def __exit__(self, *args: Any) -> None:
        self.api.nvmlShutdown()


def import_zeus_measurement(
    measurement: Any, *, gpu_index: int, provenance: dict[str, Any]
) -> dict[str, Any]:
    """Normalize Zeus Measurement (time s, gpu_energy J); never invent a time trace.

    cpu_energy/DRAM are deliberately not summed: they do not establish server
    input power, and some platforms expose overlapping measurement domains.
    """
    if not provenance.get("configuration") or not provenance.get("source"):
        raise ValueError("Zeus import requires configuration and source provenance")
    duration = float(measurement.time)
    finite("Zeus window duration", duration, strict=True)
    energy = measurement.gpu_energy.get(gpu_index)
    if energy is not None:
        finite("Zeus GPU energy", float(energy))
    return {
        "kind": "imported",
        "boundary": "gpu_board",
        "source_format": "Zeus Measurement",
        "duration_s": duration,
        "gpu_energy_j": energy,
        "mean_power_w": None if energy is None else float(energy) / duration,
        "provenance": provenance,
        "software_versions": software_versions(),
    }
