"""Entirely SYNTHETIC fixture; not NVIDIA specifications or measured performance."""

from dataclasses import replace

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.gpu import GPUTrace, software_versions
from datacenter_simulator.methods.communications import CommunicationNetwork
from datacenter_simulator.methods.cooling import CoolingPlant
from datacenter_simulator.methods.electrical import DCBranch, DCBus, DCNetwork
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.gpu_lab import (
    GPULabResult,
    forecast_error_replay,
    inference_job,
    run_gpu_policy,
)
from datacenter_simulator.methods.workloads import Job
from datacenter_simulator.models import Device, Electrical
from datacenter_simulator.models.gpu import GPUOperatingPoint, GPUPerformanceModel
from datacenter_simulator.models.performance import Provenance
from datacenter_simulator.simulation import DataCenter

POLICIES = ("immediate_default", "immediate_efficient", "price_aware", "coordinated")


def synthetic_trace() -> GPUTrace:
    """A 10-second counter-backed fixture with explicit synthetic provenance."""
    elapsed = np.asarray([0.0, 0.5, 1.5, 3.0, 5.0, 8.0, 10.0])
    power = np.asarray([35.0, 140.0, 140.0, 140.0, 140.0, 140.0, 35.0])
    energy = np.r_[0.0, np.cumsum((power[1:] + power[:-1]) / 2 * np.diff(elapsed))]
    return GPUTrace(
        pd.DataFrame(
            {
                "timestamp": pd.Timestamp("2026-01-01", tz="UTC")
                + pd.to_timedelta(elapsed, unit="s"),
                "elapsed_s": elapsed,
                "power_w": power,
                "energy_j": energy,
                "temperature_c": [30, 32, 35, 39, 41, 42, 39],
                "power_limit_w": 150.0,
            }
        ),
        {
            "schema_version": 1,
            "kind": "synthetic",
            "boundary": "gpu_board",
            "source": "ASVA deterministic integration fixture; no hardware measurements",
            "configuration": {"workload": "illustrative batch inference", "seed": None},
            "software_versions": software_versions(),
        },
    )


def synthetic_performance() -> GPUPerformanceModel:
    return GPUPerformanceModel(
        (
            GPUOperatingPoint(150, 140, 80),
            GPUOperatingPoint(220, 190, 100),
            GPUOperatingPoint(300, 280, 120),
        ),
        Provenance(
            "ASVA synthetic fixture, not GPU specifications",
            "fixed FP32 inference",
            kind="illustrative",
            boundary="component",
            relative_uncertainty=0.2,
        ),
        "synthetic-fixed-batch",
        "synthetic-constant-quality",
        35,
        default_limit_w=300,
        evidence_kind="synthetic",
    )


def gpu_scenario() -> tuple[DataCenter, pd.DataFrame, list[Job], GPUPerformanceModel, Battery]:
    """24 h / 30 min planning; one GPU server, 48 V terminal, AC-coupled PV/storage."""
    model = synthetic_performance()
    buses = [DCBus("source", 400), DCBus("shelf", 48), DCBus("server-terminal", 48)]
    network = DCNetwork(
        buses,
        [
            DCBranch(
                "dc-converter",
                "source",
                "shelf",
                efficiency=0.97,
                kind="converter",
                rated_current_a=30,
                rated_power_kw=1,
            ),
            DCBranch.copper_cable("server-cable", "shelf", "server-terminal", 1, 10, 30),
        ],
        "source",
    )
    device = Device("gpu-server", "GPU server", "server-terminal", Electrical(48, 0.17, 0.6))
    center = DataCenter(
        "ASVA • GPU Energy & Performance Lab • SIMULATED",
        [device],
        network,
        CommunicationNetwork([device.id], []),
        CoolingPlant("Illustrative room cooling", 0.7, 4.5),
        auxiliary_kw=0.02,
    )
    index = pd.date_range("2026-01-01", periods=48, freq="30min", tz="UTC")
    hour = np.arange(48) / 2
    profiles = pd.DataFrame(
        {
            "ambient_c": 25 + 5 * np.sin((hour - 8) * np.pi / 12),
            "import_price": np.where(
                (hour >= 16) & (hour < 21), 0.45, np.where(hour < 7, 0.10, 0.22)
            ),
            "generation_kw": 0.55 * np.maximum(0, np.sin((hour - 6) * np.pi / 12)),
            "grid_limit_kw": 0.55,
        },
        index=index,
    )
    jobs = [
        inference_job(
            f"batch-{i + 1}",
            device.id,
            tasks,
            model,
            release_s=release * 3600,
            deadline_s=deadline * 3600,
        )
        for i, (release, deadline, tasks) in enumerate(
            [
                (0, 7, 648000),
                (4, 12, 648000),
                (8, 16, 864000),
                (12, 20, 648000),
                (16, 24, 864000),
                (18, 24, 432000),
            ]
        )
    ]
    return center, profiles, jobs, model, Battery(1.2, 0.35, 0.35)


def compare_policies(
    *,
    tariff_scale: float = 1,
    pv_scale: float = 1,
    throughput_scale: float = 1,
    performance_model: GPUPerformanceModel | None = None,
) -> dict[str, GPULabResult]:
    """All work amounts fixed before performance perturbation; no fairness drift."""
    from datacenter_simulator.models.devices import finite

    finite("tariff_scale", tariff_scale)
    finite("pv_scale", pv_scale)
    finite("throughput_scale", throughput_scale, strict=True)
    center, profiles, jobs, model, battery = gpu_scenario()
    if performance_model is not None:
        tasks = [j.phases[0].amount * model.default_point.tasks_per_s for j in jobs]
        model = performance_model
        jobs = [
            inference_job(
                j.id, j.device_id, work, model, release_s=j.release_s, deadline_s=j.deadline_s
            )
            for j, work in zip(jobs, tasks, strict=True)
        ]
    profiles["import_price"] *= tariff_scale
    profiles["generation_kw"] *= pv_scale
    if throughput_scale != 1:
        # Job seconds are referenced to default throughput: preserve task counts.
        tasks = [j.phases[0].amount * model.default_point.tasks_per_s for j in jobs]
        model = replace(
            model,
            points=tuple(
                replace(p, tasks_per_s=p.tasks_per_s * throughput_scale) for p in model.points
            ),
        )
        jobs = [
            inference_job(
                j.id, j.device_id, work, model, release_s=j.release_s, deadline_s=j.deadline_s
            )
            for j, work in zip(jobs, tasks, strict=True)
        ]
    return {
        policy: run_gpu_policy(
            center,
            profiles,
            jobs,
            model,
            battery,
            policy=policy,
            other_server_kw=0.12,
            internal_efficiency=0.94,
        )
        for policy in POLICIES
    }


def sensitivity_study() -> pd.DataFrame:
    """Reoptimized tariff/PV/performance sensitivity plus frozen forecast replay."""
    records = []
    for label, parameters in (
        ("reference", {}),
        ("tariff +50%", {"tariff_scale": 1.5}),
        ("PV -50%", {"pv_scale": 0.5}),
        ("throughput -20%", {"throughput_scale": 0.8}),
        ("throughput +20%", {"throughput_scale": 1.2}),
    ):
        results = compare_policies(
            tariff_scale=parameters.get("tariff_scale", 1),
            pv_scale=parameters.get("pv_scale", 1),
            throughput_scale=parameters.get("throughput_scale", 1),
        )
        for result in results.values():
            records.append({"scenario": label, **result.summary})
    _, profiles, _, _, battery = gpu_scenario()
    actual = profiles.copy()
    actual["generation_kw"] *= 0.5
    actual["import_price"] = np.roll(profiles.import_price.to_numpy(), 4)
    for result in compare_policies().values():
        replay = forecast_error_replay(result, actual, battery)
        validated = result.jobs.completed.copy()
        for job_id, row in result.jobs.iterrows():
            if row.completed:
                first = int(row.start_s // 1800)
                last = int(np.ceil(row.completion_s / 1800))
                if (replay.unserved_kw.iloc[first:last] > 1e-7).any():
                    validated.loc[str(job_id)] = False
        records.append(
            {
                "scenario": "forecast error: frozen plan",
                "policy": result.policy,
                "dataset_kind": "synthetic",
                "result_kind": "simulated",
                "energy_cost": float(replay.cost.sum()),
                "unserved_kwh": float(replay.unserved_kw.sum() / 2),
                "completed_tasks": float(result.jobs.loc[validated, "completed_tasks"].sum()),
                "completed_jobs": float(validated.sum()),
                "unfinished_jobs": float((~validated).sum()),
                "deadline_misses": float((~validated | result.jobs.deadline_missed).sum()),
                "feasible": bool(validated.all() and replay.unserved_kw.max() < 1e-7),
                "final_battery_energy_kwh": float(replay.battery_energy_kwh.iloc[-1]),
                "facility_kwh": result.summary["facility_kwh"],
            }
        )
    return pd.DataFrame(records)
