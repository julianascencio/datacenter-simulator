"""CPU-only contract tests. Fake telemetry is NOT hardware validation."""

import importlib
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.connectors.gpu import GPUTrace, NVMLCollector, import_zeus_measurement
from datacenter_simulator.models.gpu import server_terminal_power
from datacenter_simulator.use_cases.gpu_lab import synthetic_trace
from datacenter_simulator.utilities.timeseries import resample_intervals


class FakeNVMLError(Exception):
    pass


class FakeNotSupported(FakeNVMLError):
    pass


class FakeNoPermission(FakeNVMLError):
    pass


class FakeNVML:
    NVMLError = FakeNVMLError
    NVML_TEMPERATURE_GPU = 0
    NVML_CLOCK_GRAPHICS = 0
    NVML_CLOCK_MEM = 2

    def __init__(self):
        self.limit = 250000
        self.writes = []
        self.closed = False
        self.fail_write = False

    def nvmlInit(self):
        pass

    def nvmlShutdown(self):
        self.closed = True

    def nvmlDeviceGetHandleByIndex(self, index):
        return index

    def nvmlDeviceGetName(self, handle):
        return b"FAKE GPU"

    def nvmlDeviceGetUUID(self, handle):
        return "GPU-FAKE"

    def nvmlSystemGetDriverVersion(self):
        return "fake-driver"

    def nvmlSystemGetNVMLVersion(self):
        return "fake-nvml"

    def nvmlDeviceGetPowerUsage(self, handle):
        return 123456

    def nvmlDeviceGetTotalEnergyConsumption(self, handle):
        raise FakeNotSupported("counter unavailable")

    def nvmlDeviceGetTemperature(self, handle, sensor):
        raise FakeNoPermission("temperature permission denied")

    def nvmlDeviceGetPowerManagementLimit(self, handle):
        return self.limit

    def nvmlDeviceGetUtilizationRates(self, handle):
        return SimpleNamespace(gpu=80, memory=20)

    def nvmlDeviceGetPowerManagementLimitConstraints(self, handle):
        return 100000, 300000

    def nvmlDeviceSetPowerManagementLimit(self, handle, value):
        self.writes.append(value)
        if self.fail_write and value != 250000:
            raise FakeNoPermission("write denied")
        self.limit = value


@pytest.fixture
def fake(monkeypatch):
    api = FakeNVML()
    real_import = importlib.import_module
    monkeypatch.setattr(
        importlib, "import_module", lambda name: api if name == "pynvml" else real_import(name)
    )
    return api


def test_missing_gpu_library_has_actionable_error_and_core_imports(monkeypatch):
    real_import = importlib.import_module

    def missing(name):
        if name == "pynvml":
            raise ModuleNotFoundError("pynvml")
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", missing)
    import datacenter_simulator
    from datacenter_simulator.gpu_benchmark import read_performance_model

    assert datacenter_simulator.simulate and read_performance_model
    with pytest.raises(RuntimeError, match="gpu"):
        with NVMLCollector():
            pass
    assert synthetic_trace().replay(step_s=2, max_gap_s=5).sum() > 0


def test_optional_fields_and_permissions_remain_missing(fake):
    with NVMLCollector() as collector:
        row = collector.sample()
        assert row["power_w"] == pytest.approx(123.456)
        assert row["power_limit_w"] == 250
        assert row["energy_j"] is None
        assert "NotSupported" in row["energy_j_status"]
        assert row["temperature_c"] is None
        assert "Permission" in row["temperature_c_status"]
        assert row["graphics_clock_mhz"] is None
        assert row["graphics_clock_mhz_status"] == "missing_api"
        assert collector.metadata["identity"]["gpu_model"] == "FAKE GPU"
        assert row["gpu_utilization_pct"] == 80
    assert fake.closed and fake.writes == []


def test_power_control_requires_optin_and_restores_on_failure(fake):
    with NVMLCollector() as collector:
        with pytest.raises(PermissionError):
            with collector.power_limit(150):
                pass
        with pytest.raises(ValueError, match="range"):
            with collector.power_limit(500, allow_control=True):
                pass
        assert fake.writes == []
        with pytest.raises(RuntimeError, match="workload failure"):
            with collector.power_limit(150, allow_control=True):
                assert fake.limit == 150000
                raise RuntimeError("workload failure")
        assert fake.limit == 250000
        with collector.power_limit(175, allow_control=True):
            assert fake.limit == 175000
        assert fake.limit == 250000
        fake.fail_write = True
        with pytest.raises(FakeNoPermission):
            with collector.power_limit(180, allow_control=True):
                pass
        assert fake.limit == 250000


def test_init_and_lookup_failure_are_not_empty_success(monkeypatch):
    fake = FakeNVML()

    def fail(*args):
        raise FakeNVMLError("GPU lost")

    fake.nvmlDeviceGetHandleByIndex = fail
    monkeypatch.setattr(importlib, "import_module", lambda _: fake)
    with pytest.raises(FakeNVMLError):
        with NVMLCollector():
            pass
    assert fake.closed
    fake.nvmlInit = fail
    with pytest.raises(RuntimeError, match="unavailable"):
        with NVMLCollector():
            pass


def test_csv_units_counter_energy_alignment_and_tail_padding(tmp_path):
    trace = synthetic_trace()
    target = trace.write_csv(tmp_path / "trace.csv")
    loaded = GPUTrace.read_csv(target)
    energy_j = loaded.samples.energy_j.iloc[-1] - loaded.samples.energy_j.iloc[0]
    profile = loaded.replay(step_s=3, max_gap_s=5, start=pd.Timestamp("2026-02-01", tz="UTC"))
    assert profile.sum() * 3 * 1000 == pytest.approx(energy_j)
    assert len(profile) == 4  # last 2 seconds are explicit zero padding
    assert profile.index[0] == pd.Timestamp("2026-02-01", tz="UTC")
    assert loaded.samples.memory_utilization_pct.isna().all()
    assert loaded.metadata["kind"] == "synthetic"


def test_power_integration_is_trapezoidal_and_no_counter_reset_or_gap():
    trace = synthetic_trace()
    frame = trace.samples.copy()
    frame["energy_j"] = np.nan
    fallback = GPUTrace(frame, trace.metadata)
    assert fallback.replay(step_s=7, max_gap_s=5).sum() * 7000 == pytest.approx(
        trace.samples.energy_j.iloc[-1]
    )
    frame.loc[2, "power_w"] = np.nan
    assert GPUTrace(frame, trace.metadata).intervals(max_gap_s=5).power_kw.isna().any()
    with pytest.raises(ValueError, match="finite"):
        GPUTrace(frame, trace.metadata).replay(step_s=1, max_gap_s=5)
    with pytest.raises(ValueError, match="gap"):
        trace.intervals(max_gap_s=1)
    frame = trace.samples.copy()
    frame.loc[3, "energy_j"] = 0
    with pytest.raises(ValueError, match="reset"):
        GPUTrace(frame, trace.metadata).intervals(max_gap_s=5)


@pytest.mark.parametrize(
    "corruption", ["duplicate", "naive", "negative", "wall_mismatch", "infinity"]
)
def test_trace_validation(corruption):
    trace = synthetic_trace()
    f = trace.samples.copy()
    if corruption == "duplicate":
        f.loc[2, "elapsed_s"] = f.loc[1, "elapsed_s"]
    elif corruption == "naive":
        f["timestamp"] = f.timestamp.dt.tz_localize(None)
    elif corruption == "negative":
        f.loc[1, "power_w"] = -1
    elif corruption == "wall_mismatch":
        f["timestamp"] += pd.to_timedelta(np.arange(len(f)), unit="s")
    else:
        f.loc[1, "power_w"] = np.inf
    with pytest.raises(ValueError):
        GPUTrace(f, trace.metadata)


def test_resampling_known_integral_gaps_and_refinement():
    f = pd.DataFrame({"time_s": [0, 1, 3], "duration_s": [1, 2, 4], "power_kw": [1, 3, 2]})
    start = pd.Timestamp("2026-01-01", tz="UTC")
    for step in (0.1, 1, 2.3, 10):
        result = resample_intervals(f, start, step_s=step)
        assert result.sum() * step == pytest.approx(15)
    for times in ([0, 2, 3], [0, 0.5, 3], [1, 2, 4]):
        with pytest.raises(ValueError, match="contiguous"):
            resample_intervals(f.assign(time_s=times), start, step_s=1)


def test_measurement_boundary_no_double_counting():
    power = pd.Series([0.2, 0.3])
    terminal = server_terminal_power(
        power, boundary="gpu_board", other_server_kw=0.1, internal_efficiency=0.9
    )
    assert terminal.tolist() == pytest.approx([1 / 3, 4 / 9])
    assert server_terminal_power(terminal, boundary="server_dc").equals(terminal)
    assert server_terminal_power(
        power, boundary="server_ac", ac_psu_efficiency=0.95
    ).tolist() == pytest.approx([0.19, 0.285])
    for boundary in ("server_dc", "server_ac"):
        with pytest.raises(ValueError, match="already includes"):
            server_terminal_power(power, boundary=boundary, other_server_kw=0.1)
    with pytest.raises(ValueError, match="PSU"):
        server_terminal_power(power, boundary="server_ac")
    with pytest.raises(ValueError, match="separate"):
        server_terminal_power(power, boundary="gpu_board")
    with pytest.raises(ValueError, match="missing"):
        server_terminal_power(pd.Series([np.nan]), boundary="server_dc")
    with pytest.raises(ValueError, match="timestamps"):
        server_terminal_power(power, boundary="gpu_board", other_server_kw=pd.Series([0.1]))


def test_zeus_import_gpu_only_and_preserves_missing():
    window = SimpleNamespace(time=2, gpu_energy={0: 200}, cpu_energy={0: 100})
    provenance = {"source": "synthetic test", "configuration": "test"}
    result = import_zeus_measurement(window, gpu_index=0, provenance=provenance)
    assert result["gpu_energy_j"] == 200 and result["mean_power_w"] == 100
    assert result["kind"] == "imported" and result["boundary"] == "gpu_board"
    missing = import_zeus_measurement(window, gpu_index=1, provenance=provenance)
    assert missing["gpu_energy_j"] is None and missing["mean_power_w"] is None
