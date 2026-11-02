"""Opt-in fixed-quality digits batch inference; imports are lazy and hardware optional.

This small linear classifier is deliberately an overhead-sensitive integration
benchmark, not an LLM throughput claim. The fixed dataset ships with scikit-learn.
Training, data movement and reference validation are outside the measured window.
"""

import hashlib
import json
import os
import platform
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from datacenter_simulator.connectors.gpu import (
    NVMLCollector,
    import_zeus_measurement,
    software_versions,
)
from datacenter_simulator.models.devices import finite
from datacenter_simulator.models.gpu import GPUOperatingPoint, GPUPerformanceModel
from datacenter_simulator.models.performance import Provenance


def _digest(*arrays: Any) -> str:
    h = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array)
        h.update(str((value.shape, value.dtype.str)).encode())
        h.update(value.tobytes())
    return h.hexdigest()


def prepare_digits() -> dict[str, Any]:
    """Deterministic CPU reference, held-out inputs and hashes; no network fetch.

    scikit-learn load_digits (UCI optical digits), fixed stratified 75/25 split,
    seed 1729, /16 normalization, FP32 inference, L2 logistic regression C=1.
    The full input/label and weight hashes must match when comparing power limits.
    """
    from sklearn.datasets import load_digits
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    digits = load_digits()
    x = digits.data.astype(np.float32) / 16
    y = digits.target.astype(np.int64)
    train, test = train_test_split(np.arange(len(y)), test_size=0.25, random_state=1729, stratify=y)
    classifier = LogisticRegression(C=1, solver="lbfgs", max_iter=3000, tol=1e-8)
    classifier.fit(x[train], y[train])
    weights = classifier.coef_.astype(np.float32)
    bias = classifier.intercept_.astype(np.float32)
    reference = x[test] @ weights.T + bias
    predictions = reference.argmax(axis=1)
    accuracy = float(np.mean(predictions == y[test]))
    if accuracy < 0.90:
        raise RuntimeError(f"CPU quality gate failed: {accuracy}")
    return {
        "inputs": x[test],
        "labels": y[test],
        "weights": weights,
        "bias": bias,
        "reference_logits": reference,
        "accuracy": accuracy,
        "dataset_sha256": _digest(x, y, train, test),
        "weights_sha256": _digest(weights, bias),
        "reference_predictions_sha256": _digest(predictions),
    }


def matching_gpu_uuid(cuda_uuid: Any, nvml_uuid: Any) -> bool:
    """PyTorch exposes a bare UUID object; NVML prefixes physical IDs with GPU-."""
    if cuda_uuid is None or nvml_uuid is None:
        return False
    try:
        return UUID(str(cuda_uuid).removeprefix("GPU-")) == UUID(
            str(nvml_uuid).removeprefix("GPU-")
        )
    except ValueError:
        return False


def run_benchmark(
    output: str | Path,
    *,
    nvml_device: int | str = 0,
    cuda_device: int = 0,
    batch_size: int = 128,
    repetitions: int = 1000,
    warmup: int = 100,
    windows: int = 3,
    interval_s: float = 0.2,
    power_limit_w: float | None = None,
    allow_control: bool = False,
) -> dict[str, Any]:
    """Measure with Zeus; simultaneously collect native NVML point telemetry.

    Each batch is explicitly synchronized. Latencies include Python dispatch and
    synchronization, not queueing/service latency. CUDA-visible vs NVML device
    UUIDs must match; MIG is rejected because board energy cannot be attributed.
    """
    for name, value in (
        ("batch_size", batch_size),
        ("repetitions", repetitions),
        ("warmup", warmup),
        ("windows", windows),
    ):
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    finite("interval_s", interval_s, strict=True)
    if power_limit_w is not None and not allow_control:
        raise PermissionError("explicit --allow-power-control is required")
    try:
        import torch
        from zeus.monitor import ZeusMonitor
    except ImportError as exc:
        raise RuntimeError("Install the gpu-benchmark extra for hardware collection") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU unavailable; use gpu_lab replay/study for CPU-only validation")
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    data = prepare_digits()
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    device = torch.device(f"cuda:{cuda_device}")
    torch.cuda.set_device(device)
    inputs = torch.as_tensor(data["inputs"], device=device)
    weights = torch.as_tensor(data["weights"], device=device)
    bias = torch.as_tensor(data["bias"], device=device)
    batches = list(inputs.split(batch_size))
    config = {
        "workload": "sklearn-digits-logistic-v1",
        "batch_size": batch_size,
        "warmup_passes": warmup,
        "repetitions_per_window": repetitions,
        "measurement_windows": windows,
        "telemetry_interval_s": interval_s,
        "precision": "float32",
        "tf32": False,
        "cuda_device": cuda_device,
        "input_shape": list(inputs.shape),
        "resident_inputs": True,
        "synchronize_each_batch": True,
        "dataset_sha256": data["dataset_sha256"],
        "weights_sha256": data["weights_sha256"],
        "reference_predictions_sha256": data["reference_predictions_sha256"],
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "torch_cuda_version": torch.version.cuda,
        "platform": platform.platform(),
        "software_versions": software_versions(),
    }
    with NVMLCollector(nvml_device) as collector:
        physical_uuid = collector.metadata["identity"].get("uuid")
        torch_uuid = getattr(torch.cuda.get_device_properties(device), "uuid", None)
        if not matching_gpu_uuid(torch_uuid, physical_uuid):
            raise RuntimeError(
                "CUDA and NVML UUIDs cannot be verified equal; select matching devices"
            )
        mig = collector.metadata["identity"].get("mig_mode")
        if mig is not None and mig[0] != 0:
            raise RuntimeError(
                "MIG attribution is unsupported; benchmark an exclusive physical GPU"
            )
        collector.metadata["configuration"] = config
        original_limit = collector.api.nvmlDeviceGetPowerManagementLimit(collector.handle) / 1000
        config["original_power_limit_w"] = original_limit
        config["nvml_uuid"] = physical_uuid
        config["driver"] = collector.metadata["identity"].get("driver")
        monitor = ZeusMonitor(
            gpu_indices=[cuda_device], cpu_indices=[], sync_execution_with="torch"
        )
        records, latency_rows = [], []
        with (
            collector.power_limit(power_limit_w, allow_control=allow_control),
            torch.inference_mode(),
        ):
            configured_limit = (
                collector.api.nvmlDeviceGetPowerManagementLimit(collector.handle) / 1000
            )
            for _ in range(warmup):
                for batch in batches:
                    _ = batch @ weights.T + bias
                torch.cuda.synchronize(device)
            # Validation outside windows, at the same settings and exact weights.
            observed = (inputs @ weights.T + bias).cpu().numpy()
            quality = bool(
                np.allclose(observed, data["reference_logits"], rtol=1e-4, atol=1e-4)
                and np.array_equal(observed.argmax(axis=1), data["reference_logits"].argmax(axis=1))
            )
            if not quality:
                raise RuntimeError("GPU output differs from fixed CPU quality reference")
            for window in range(windows):
                samples: list[dict[str, Any]] = [collector.sample()]
                errors: list[BaseException] = []
                stop = threading.Event()

                def poll(
                    stop: threading.Event = stop,
                    samples: list[dict[str, Any]] = samples,
                    errors: list[BaseException] = errors,
                ) -> None:
                    try:
                        while not stop.wait(interval_s):
                            samples.append(collector.sample())
                    except BaseException as exc:
                        errors.append(exc)

                thread = threading.Thread(target=poll, daemon=True)
                thread.start()
                key = f"inference-{window}"
                try:
                    torch.cuda.synchronize(device)
                    monitor.begin_window(key)
                    started = time.perf_counter()
                    predictions = []
                    for repeat in range(repetitions):
                        for batch_id, batch in enumerate(batches):
                            tick = time.perf_counter()
                            output_tensor = batch @ weights.T + bias
                            torch.cuda.synchronize(device)
                            latency_rows.append(
                                {
                                    "window": window,
                                    "repeat": repeat,
                                    "batch": batch_id,
                                    "size": len(batch),
                                    "latency_s": time.perf_counter() - tick,
                                }
                            )
                            if repeat == repetitions - 1:
                                predictions.append(output_tensor)
                    wall_s = time.perf_counter() - started
                    measured = monitor.end_window(key)
                finally:
                    stop.set()
                    thread.join(timeout=5)
                    if thread.is_alive():
                        raise RuntimeError("NVML polling thread did not terminate")
                if errors:
                    raise RuntimeError("NVML background collection failed") from errors[0]
                samples.append(collector.sample())
                # Post-window output check catches changed/invalid outputs at each power limit.
                observed = torch.cat(predictions).cpu().numpy()
                if not (
                    np.allclose(observed, data["reference_logits"], rtol=1e-4, atol=1e-4)
                    and np.array_equal(
                        observed.argmax(axis=1), data["reference_logits"].argmax(axis=1)
                    )
                ):
                    raise RuntimeError("post-window quality check failed")
                trace = collector.trace(samples)
                trace.write_csv(target / f"window-{window}-telemetry.csv")
                normalized = import_zeus_measurement(
                    measured,
                    gpu_index=cuda_device,
                    provenance={
                        "source": "ZeusMonitor live benchmark window",
                        "configuration": config,
                    },
                )
                tasks = len(inputs) * repetitions
                energy = normalized["gpu_energy_j"]
                latency = np.asarray(
                    [r["latency_s"] for r in latency_rows if r["window"] == window]
                )
                records.append(
                    {
                        **normalized,
                        "completed_tasks": tasks,
                        "quality_passed": True,
                        "accuracy": data["accuracy"],
                        "wall_s": wall_s,
                        "tasks_per_s": tasks / normalized["duration_s"],
                        "energy_per_task_j": None if energy is None else energy / tasks,
                        "latency_p50_s": float(np.quantile(latency, 0.50)),
                        "latency_p95_s": float(np.quantile(latency, 0.95)),
                        "latency_p99_s": float(np.quantile(latency, 0.99)),
                        "sampling_warning": "window shorter than 10 s" if wall_s < 10 else None,
                    }
                )
    import pandas as pd

    pd.DataFrame(latency_rows).to_csv(target / "batch-latencies.csv", index=False)
    result = {
        "schema_version": 1,
        "kind": "measured",
        "energy_backend": "ZeusMonitor",
        "configuration": config,
        "quality_id": data["reference_predictions_sha256"],
        "configuration_id": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "power_limit_w": configured_limit,
        "original_power_limit_w": original_limit,
        "warmup_passes": warmup,
        "repetitions": repetitions,
        "windows": records,
        "software_versions": software_versions(),
        "device": collector.metadata["identity"],
        "telemetry_scope": "polling brackets Zeus window; energies are NOT added together",
    }
    (target / "benchmark.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def model_from_benchmarks(
    paths: list[str | Path], *, idle_board_w: float, idle_source: str
) -> GPUPerformanceModel:
    """Combine same-quality benchmark runs; reject missing, zero/short-window energy.

    Idle demand must be measured separately or explicitly declared as an assumption.
    Keep all source benchmark JSON/CSV artifacts; this curve stores their paths.
    """
    if not paths or not idle_source:
        raise ValueError("benchmark paths and idle-power provenance are required")
    runs = [json.loads(Path(path).read_text()) for path in paths]
    identities = {(r["configuration_id"], r["quality_id"]) for r in runs}
    if len(identities) != 1 or any(r["kind"] != "measured" for r in runs):
        raise ValueError("hardware/workload/quality configuration mismatch")
    points = []
    for run in runs:
        windows = run["windows"]
        if not windows or any(
            not w["quality_passed"]
            or w["duration_s"] < 10
            or w["gpu_energy_j"] is None
            or w["gpu_energy_j"] <= 0
            or w["completed_tasks"] <= 0
            for w in windows
        ):
            raise ValueError(
                "need quality-passing >=10 s windows with positive measured energy/work"
            )
        duration = sum(w["duration_s"] for w in windows)
        points.append(
            GPUOperatingPoint(
                run["power_limit_w"],
                sum(w["gpu_energy_j"] for w in windows) / duration,
                sum(w["completed_tasks"] for w in windows) / duration,
            )
        )
    config_id, quality_id = identities.pop()
    defaults = {r["original_power_limit_w"] for r in runs}
    if len(defaults) != 1:
        raise ValueError("original default settings differ")
    return GPUPerformanceModel(
        tuple(sorted(points, key=lambda p: p.power_limit_w)),
        Provenance(
            "; ".join(map(str, paths)) + "; idle: " + idle_source,
            runs[0]["configuration_id"],
            kind="measured",
            boundary="component",
        ),
        config_id,
        quality_id,
        idle_board_w,
        default_limit_w=defaults.pop(),
        evidence_kind="measured",
    )


def write_performance_model(model: GPUPerformanceModel, path: str | Path) -> None:
    Path(path).write_text(json.dumps(asdict(model), indent=2, allow_nan=False) + "\n")


def read_performance_model(path: str | Path) -> GPUPerformanceModel:
    payload = json.loads(Path(path).read_text())
    payload["provenance"] = Provenance(**payload["provenance"])
    payload["points"] = tuple(GPUOperatingPoint(**p) for p in payload["points"])
    return GPUPerformanceModel(**payload)
