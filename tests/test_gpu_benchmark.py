"""CPU reference and MOCK benchmark JSON checks; not GPU measurement validation."""

import json

import numpy as np
import pytest

from datacenter_simulator.gpu_benchmark import model_from_benchmarks, prepare_digits, run_benchmark


def mock_record(limit):
    return {
        "kind": "measured",
        "configuration_id": "MOCK-configuration",
        "quality_id": "MOCK-quality",
        "original_power_limit_w": 300,
        "power_limit_w": limit,
        "windows": [
            {
                "duration_s": 20,
                "gpu_energy_j": 20 * limit * 0.9,
                "completed_tasks": 2000,
                "quality_passed": True,
            }
        ],
    }


def test_cpu_reference_is_fixed_and_quality_checked():
    pytest.importorskip("sklearn")
    a, b = prepare_digits(), prepare_digits()
    assert a["accuracy"] >= 0.90
    assert a["inputs"].shape == (450, 64)
    assert a["dataset_sha256"] == b["dataset_sha256"]
    assert a["weights_sha256"] == b["weights_sha256"]
    assert a["reference_predictions_sha256"] == b["reference_predictions_sha256"]
    assert a["inputs"].dtype == np.float32


def test_model_import_uses_zeus_energy_and_fixed_quality(tmp_path):
    paths = []
    for limit in (150, 300):
        path = tmp_path / f"mock-{limit}.json"
        path.write_text(json.dumps(mock_record(limit)))
        paths.append(path)
    model = model_from_benchmarks(paths, idle_board_w=35, idle_source="MOCK test assumption")
    assert model.default_point.power_limit_w == 300
    assert model.points[0].board_power_w == 135
    assert model.points[0].tasks_per_s == 100
    assert "MOCK test assumption" in model.provenance.source


@pytest.mark.parametrize(
    "bad", ["quality", "energy", "short", "configuration", "default", "missing"]
)
def test_bad_benchmark_evidence_is_rejected(tmp_path, bad):
    a, b = mock_record(150), mock_record(300)
    if bad == "quality":
        b["windows"][0]["quality_passed"] = False
    elif bad == "energy":
        b["windows"][0]["gpu_energy_j"] = 0
    elif bad == "short":
        b["windows"][0]["duration_s"] = 1
    elif bad == "configuration":
        b["configuration_id"] = "OTHER-HARDWARE-OR-BATCH"
    elif bad == "default":
        b["original_power_limit_w"] = 250
    else:
        b["windows"][0]["gpu_energy_j"] = None
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    for path, record in zip(paths, (a, b), strict=True):
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        model_from_benchmarks(paths, idle_board_w=35, idle_source="MOCK test assumption")


def test_benchmark_no_optin_fails_before_importing_gpu_dependencies(tmp_path):
    with pytest.raises(PermissionError, match="allow-power-control"):
        run_benchmark(tmp_path, power_limit_w=150)


def test_cuda_uuid_and_nvml_prefix_are_normalized():
    from uuid import UUID

    from datacenter_simulator.gpu_benchmark import matching_gpu_uuid

    uuid = UUID("12345678-1234-5678-1234-567812345678")
    assert matching_gpu_uuid(uuid, f"GPU-{uuid}")
    assert matching_gpu_uuid(str(uuid), f"GPU-{uuid}")
    assert not matching_gpu_uuid(uuid, "GPU-00000000-1234-5678-1234-567812345678")
    assert not matching_gpu_uuid(uuid, f"MIG-{uuid}")
    assert not matching_gpu_uuid(None, f"GPU-{uuid}")


def test_mock_full_benchmark_window_and_restoration(tmp_path, monkeypatch):
    """Exercise the runner with NumPy tensors + fake Zeus/NVML, no hardware claim."""
    import sys
    from contextlib import nullcontext
    from types import SimpleNamespace
    from uuid import UUID

    from test_gpu_telemetry import FakeNVML

    import datacenter_simulator.connectors.gpu as connector
    import datacenter_simulator.gpu_benchmark as benchmark

    class Tensor:
        def __init__(self, array):
            self.array = np.asarray(array)
            self.shape = self.array.shape

        @property
        def T(self):
            return Tensor(self.array.T)

        def __matmul__(self, other):
            return Tensor(self.array @ other.array)

        def __add__(self, other):
            return Tensor(self.array + other.array)

        def split(self, size):
            return [Tensor(self.array[i : i + size]) for i in range(0, len(self), size)]

        def __len__(self):
            return len(self.array)

        def cpu(self):
            return self

        def numpy(self):
            return self.array

    uuid = UUID("12345678-1234-5678-1234-567812345678")
    fake_nvml = FakeNVML()
    fake_nvml.nvmlDeviceGetUUID = lambda _: f"GPU-{uuid}"
    real_import = connector.importlib.import_module
    monkeypatch.setattr(
        connector.importlib,
        "import_module",
        lambda name: fake_nvml if name == "pynvml" else real_import(name),
    )
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            get_device_properties=lambda _: SimpleNamespace(uuid=uuid),
            set_device=lambda _: None,
            synchronize=lambda _: None,
        ),
        use_deterministic_algorithms=lambda _: None,
        backends=SimpleNamespace(
            cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
            cudnn=SimpleNamespace(allow_tf32=True),
        ),
        device=lambda s: s,
        as_tensor=lambda a, device: Tensor(a),
        inference_mode=nullcontext,
        cat=lambda items: Tensor(np.concatenate([t.array for t in items])),
        version=SimpleNamespace(cuda="MOCK"),
    )

    class Monitor:
        def __init__(self, **kwargs):
            assert kwargs["gpu_indices"] == [0] and kwargs["cpu_indices"] == []

        def begin_window(self, key):
            pass

        def end_window(self, key):
            return SimpleNamespace(time=20.0, gpu_energy={0: 2000.0})

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "zeus.monitor", SimpleNamespace(ZeusMonitor=Monitor))
    x = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    reference = {
        "inputs": x,
        "labels": [0, 1, 0],
        "weights": np.eye(2, dtype=np.float32),
        "bias": np.zeros(2, dtype=np.float32),
        "reference_logits": x,
        "accuracy": 1.0,
        "dataset_sha256": "MOCK-data",
        "weights_sha256": "MOCK-weights",
        "reference_predictions_sha256": "MOCK-quality",
    }
    monkeypatch.setattr(benchmark, "prepare_digits", lambda: reference)
    result = benchmark.run_benchmark(
        tmp_path,
        batch_size=2,
        repetitions=2,
        warmup=1,
        windows=2,
        power_limit_w=150,
        allow_control=True,
    )
    assert result["power_limit_w"] == 150
    assert fake_nvml.limit == 250000 and fake_nvml.closed
    assert all(w["completed_tasks"] == 6 and w["quality_passed"] for w in result["windows"])
    assert result["windows"][0]["energy_per_task_j"] == pytest.approx(2000 / 6)
    assert (tmp_path / "benchmark.json").exists()
    assert (tmp_path / "batch-latencies.csv").exists()
    assert (tmp_path / "window-0-telemetry.metadata.json").exists()
