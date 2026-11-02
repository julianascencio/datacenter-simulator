"""Measured-throughput scheduling through the existing facility and dispatch APIs."""

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.optimization import DemandOption, optimize_dispatch
from datacenter_simulator.methods.workloads import Job, JobPhase
from datacenter_simulator.models.devices import finite
from datacenter_simulator.models.gpu import (
    GPUOperatingPoint,
    GPUPerformanceModel,
    server_terminal_power,
)
from datacenter_simulator.simulation import DataCenter, SimulationResult, simulate


@dataclass
class GPULabResult:
    policy: str
    jobs: pd.DataFrame
    facility: SimulationResult
    summary: dict[str, float | str | bool]
    feasible: bool


@dataclass(frozen=True)
class Execution:
    job: Job
    start_slot: int
    duration_s: float
    point: GPUOperatingPoint
    option: DemandOption


def inference_job(
    id: str,
    device_id: str,
    tasks: float,
    model: GPUPerformanceModel,
    *,
    release_s: float,
    deadline_s: float,
) -> Job:
    """Use existing Job's compute-seconds at the last (default) observation.

    ``tasks`` is useful input records. This adapter keeps JobPhase's seconds
    contract intact; no API silently reinterprets compute seconds as task counts.
    """
    finite("tasks", tasks, strict=True)
    return Job(
        id,
        device_id,
        (JobPhase("compute", tasks / model.default_point.tasks_per_s),),
        release_s,
        deadline_s,
    )


def _validate(center: DataCenter, profiles: pd.DataFrame, jobs: list[Job], step_s: float) -> None:
    finite("step_s", step_s, strict=True)
    if len(center.devices) != 1 or not jobs or len({j.id for j in jobs}) != len(jobs):
        raise ValueError("first GPU lab release supports one device and unique nonempty jobs")
    if not {"ambient_c", "import_price", "generation_kw", "grid_limit_kw"} <= set(profiles):
        raise ValueError("profiles need ambient_c, import_price, generation_kw, grid_limit_kw")
    if not np.isfinite(profiles.to_numpy(dtype=float)).all():
        raise ValueError("profiles must be finite")
    if (profiles[["generation_kw", "grid_limit_kw"]] < 0).any().any():
        raise ValueError("generation and grid limits must be nonnegative")
    for job in jobs:
        if job.device_id != center.devices[0].id or len(job.phases) != 1:
            raise ValueError("jobs require one compute phase on the declared GPU server")
        if job.phases[0].kind != "compute" or job.phases[0].utilization != 1:
            raise ValueError("GPU throughput applies to full-utilization compute phases only")


def run_gpu_policy(
    center: DataCenter,
    profiles: pd.DataFrame,
    jobs: list[Job],
    model: GPUPerformanceModel,
    battery: Battery,
    *,
    policy: str,
    other_server_kw: float,
    internal_efficiency: float = 1,
    step_s: float = 1800,
) -> GPULabResult:
    """Four comparable nonpreemptive policies; perfect-foresight planning.

    All policies use identical jobs, quality, horizon, idle demand, battery and
    EXACT terminal SOC. Policies 1-3 fix the schedule then optimize storage.
    Policy 4 jointly selects execution windows, observed power settings and storage
    in the existing dispatch MILP. One physical GPU/server only in this release.

    Nonlinear facility costs are evaluated at idle/active endpoints by simulate,
    then time-averaged for a partial final slot. This is exact for the declared
    piecewise-constant execution within each fixed-ambient interval; it is not
    a linearization of electrical loss at the slot-average IT load.
    """
    policies = {"immediate_default", "immediate_efficient", "price_aware", "coordinated"}
    if policy not in policies:
        raise ValueError("unknown GPU policy")
    _validate(center, profiles, jobs, step_s)
    n, dt = len(profiles), step_s / 3600
    horizon = n * step_s
    simulation_profiles = profiles.assign(utilization=0)[["utilization", "ambient_c"]]
    device_id = center.devices[0].id
    settings = (
        model.points
        if policy == "coordinated"
        else (model.default_point if policy == "immediate_default" else model.efficient_point,)
    )

    def facility_at(board_w: float) -> SimulationResult:
        terminal = server_terminal_power(
            pd.Series(board_w / 1000, index=profiles.index),
            boundary="gpu_board",
            other_server_kw=other_server_kw,
            internal_efficiency=internal_efficiency,
        )
        return simulate(
            center, simulation_profiles, device_power_kw=terminal.to_frame(device_id), dt_hours=dt
        )

    idle = facility_at(model.idle_board_w)
    active = {p.power_limit_w: facility_at(p.board_power_w) for p in settings}
    candidates: dict[str, Execution] = {}

    def candidate(job: Job, point: GPUOperatingPoint, start: int) -> Execution:
        tasks = job.phases[0].amount * model.default_point.tasks_per_s
        seconds = tasks / point.tasks_per_s
        slots = int(np.ceil(seconds / step_s))
        count = min(slots, max(0, n - start))
        fractions = np.minimum(1, np.maximum(0, seconds / step_s - np.arange(count)))
        busy = active[point.power_limit_w].timeseries
        delta = (busy.facility_kw - idle.timeseries.facility_kw).iloc[
            start : start + count
        ].to_numpy() * fractions
        option = DemandOption(
            f"{job.id}@{start}:{point.power_limit_w:g}", job.id, device_id, start, tuple(delta)
        )
        return Execution(job, start, seconds, point, option)

    chosen: list[Execution] = []
    planning_failure = ""
    if policy.startswith("immediate"):
        # FIFO release ordering, with deterministic ID ties. No deadline hiding.
        available = 0
        for job in sorted(jobs, key=lambda j: (j.release_s, j.id)):
            start = max(available, int(np.ceil(job.release_s / step_s)))
            if start >= n:
                continue
            execution = candidate(job, settings[0], start)
            chosen.append(execution)
            available = start + int(np.ceil(execution.duration_s / step_s))
    else:
        for job in jobs:
            for point in settings:
                seconds = job.phases[0].amount * model.default_point.tasks_per_s / point.tasks_per_s
                slots = int(np.ceil(seconds / step_s))
                first = int(np.ceil(job.release_s / step_s))
                # Actual completion, not rounded reservation, determines deadline.
                last = min(n - slots, int(np.floor((job.deadline_s - seconds) / step_s + 1e-10)))
                for start in range(first, last + 1):
                    execution = candidate(job, point, start)
                    busy = active[point.power_limit_w]
                    if (
                        busy.warnings
                        or (busy.timeseries.unmet_heat_kw.iloc[start : start + slots] > 1e-8).any()
                    ):
                        continue
                    candidates[execution.option.id] = execution
        planning = profiles.copy()
        planning["demand_kw"] = idle.timeseries.facility_kw
        try:
            # Price-only schedule sees tariffs and grid constraints, but not PV or
            # storage arbitrage. It is then replayed with the actual PV and battery.
            planning_battery = battery
            if policy == "price_aware":
                planning = planning.assign(generation_kw=0)
                planning_battery = replace(battery, max_charge_kw=0, max_discharge_kw=0)
            plan = optimize_dispatch(
                planning,
                planning_battery,
                dt_hours=dt,
                terminal_soc_exact=True,
                require_served=True,
                demand_options=tuple(e.option for e in candidates.values()),
                required_groups=tuple(j.id for j in jobs),
            )
            chosen = [candidates[key] for key in plan.selected_options]
        except ValueError as exc:
            planning_failure = str(exc)

    # Reconstruct all accounting columns from the same physical endpoint solves.
    frame = idle.timeseries.copy()
    physical = [
        "it_kw",
        "dc_loss_kw",
        "rectifier_loss_kw",
        "room_heat_kw",
        "cooling_kw",
        "auxiliary_kw",
        "facility_kw",
        "heat_rejected_kw",
        "unmet_heat_kw",
        "liquid_flow_kg_s",
        "air_flow_m3_s",
    ]
    for execution in chosen:
        start = execution.start_slot
        count = len(execution.option.delta_kw)
        frac = np.minimum(1, np.maximum(0, execution.duration_s / step_s - np.arange(count)))
        delta_frame = (
            active[execution.point.power_limit_w].timeseries[physical] - idle.timeseries[physical]
        ).iloc[start : start + count]
        for column in physical:
            frame.loc[frame.index[start : start + count], column] += (
                delta_frame[column].to_numpy() * frac
            )
        occupied_index = frame.index[start : start + count]
        frame.loc[occupied_index, "minimum_voltage_pu"] = np.minimum(
            frame.loc[occupied_index, "minimum_voltage_pu"],
            active[execution.point.power_limit_w].timeseries.loc[
                occupied_index, "minimum_voltage_pu"
            ],
        )
    dispatch_profiles = profiles.assign(demand_kw=frame.facility_kw)
    # Infeasible baselines retain explicit unserved demand and invalidate affected jobs.
    storage = optimize_dispatch(dispatch_profiles, battery, dt_hours=dt, terminal_soc_exact=True)
    for dispatch_column in storage.timeseries:
        frame[dispatch_column] = storage.timeseries[dispatch_column]
    frame["pue"] = frame.facility_kw / frame.it_kw
    records = []
    by_job = {e.job.id: e for e in chosen}
    for job in jobs:
        selected_execution = by_job.get(job.id)
        requested = job.phases[0].amount * model.default_point.tasks_per_s
        start_s = selected_execution.start_slot * step_s if selected_execution else float("nan")
        end_s = start_s + selected_execution.duration_s if selected_execution else float("nan")
        invalid = False
        if selected_execution:
            occupied = slice(
                selected_execution.start_slot,
                selected_execution.start_slot + len(selected_execution.option.delta_kw),
            )
            invalid = bool(
                (frame.unserved_kw.iloc[occupied] > 1e-7).any()
                or (frame.unmet_heat_kw.iloc[occupied] > 1e-7).any()
                or active[selected_execution.point.power_limit_w].warnings
            )
        completed = bool(selected_execution and end_s <= horizon + 1e-7 and not invalid)
        records.append(
            {
                "job": job.id,
                "release_s": job.release_s,
                "deadline_s": job.deadline_s,
                "start_s": start_s,
                "completion_s": end_s if completed else np.nan,
                "planned_completion_s": end_s,
                "completed": completed,
                "deadline_missed": bool(
                    (completed and end_s > job.deadline_s + 1e-7)
                    or (not completed and job.deadline_s <= horizon)
                ),
                "requested_tasks": requested,
                "completed_tasks": requested if completed else 0,
                "invalid_supply_or_thermal": invalid,
                "power_limit_w": selected_execution.point.power_limit_w
                if selected_execution
                else np.nan,
            }
        )
    job_frame = pd.DataFrame(records).set_index("job")
    completed_tasks = float(job_frame.completed_tasks.sum())
    all_work = bool(job_frame.completed.all())
    feasible = bool(
        all_work
        and not job_frame.deadline_missed.any()
        and frame.unserved_kw.max() < 1e-7
        and frame.unmet_heat_kw.max() < 1e-7
        and not idle.warnings
        and not planning_failure
    )
    summary: dict[str, float | str | bool] = {
        "policy": policy,
        "dataset_kind": model.evidence_kind,
        "result_kind": "simulated",
        "feasible": feasible,
        "planning_failure": planning_failure,
        "completed_jobs": float(job_frame.completed.sum()),
        "unfinished_jobs": float((~job_frame.completed).sum()),
        "deadline_misses": float(job_frame.deadline_missed.sum()),
        "requested_tasks": float(job_frame.requested_tasks.sum()),
        "completed_tasks": completed_tasks,
        "energy_cost": storage.summary["energy_cost"],
        "objective_with_storage_wear": storage.objective,
        "facility_energy_per_task_j": float(frame.facility_kw.sum() * dt * 3.6e6 / completed_tasks)
        if all_work and completed_tasks
        else float("nan"),
        "final_battery_energy_kwh": float(frame.battery_energy_kwh.iloc[-1]),
    }
    for name in [p for p in physical if p.endswith("_kw")] + [
        "grid_import_kw",
        "battery_loss_kw",
        "unserved_kw",
    ]:
        summary[name.removesuffix("_kw") + "_kwh"] = float(frame[name].sum() * dt)
    facility_summary = {k: float(v) for k, v in summary.items() if isinstance(v, (int, float))}
    facility_summary["pue"] = float(frame.facility_kw.sum() / frame.it_kw.sum())
    facility_summary["peak_facility_kw"] = float(frame.facility_kw.max())
    warnings = set(idle.warnings)
    if not feasible:
        warnings.add("GPU policy infeasible or unfinished: inspect job and supply flags")
    return GPULabResult(
        policy,
        job_frame,
        SimulationResult(frame, facility_summary, tuple(sorted(warnings))),
        summary,
        feasible,
    )


def forecast_error_replay(
    result: GPULabResult, actual: pd.DataFrame, battery: Battery, *, step_s: float = 1800
) -> pd.DataFrame:
    """Freeze forecast schedule AND battery actions; expose actual grid shortfalls.

    No oracle reoptimization, hidden load shedding or SOC drift. With less PV,
    imports increase up to the physical limit; deficits explicitly invalidate work.
    A full affected job receives zero validated tasks (conservative, no checkpoint model).
    """
    if not actual.index.equals(result.facility.timeseries.index):
        raise ValueError("actual and planned timelines must match")
    dt = step_s / 3600
    finite("step_s", step_s, strict=True)
    if not {"generation_kw", "import_price", "grid_limit_kw"} <= set(actual):
        raise ValueError("actual PV, tariffs and grid limits are required")
    if not np.isfinite(actual.to_numpy(dtype=float)).all():
        raise ValueError("actual profiles must be finite")
    if (actual[["generation_kw", "grid_limit_kw"]] < 0).any().any():
        raise ValueError("actual PV and limits must be nonnegative")
    f = result.facility.timeseries.copy()
    if not isinstance(f.index, pd.DatetimeIndex):
        raise ValueError("planned timeline must be a DatetimeIndex")
    if len(f) > 1 and not np.allclose(
        (f.index[1:] - f.index[:-1]).total_seconds(), step_s, atol=1e-9, rtol=0
    ):
        raise ValueError("replay step_s must match the planned intervals")
    previous = np.r_[battery.initial_soc * battery.capacity_kwh, f.battery_energy_kwh.iloc[:-1]]
    delta = dt * (
        f.charge_kw * battery.charge_efficiency - f.discharge_kw / battery.discharge_efficiency
    )
    if not np.allclose(f.battery_energy_kwh - previous, delta, atol=1e-6, rtol=0):
        raise ValueError("replay battery must match the planning battery")
    residual = f.facility_kw + f.charge_kw - f.discharge_kw - actual.generation_kw
    f["grid_import_kw"] = np.minimum(actual.grid_limit_kw, np.maximum(0, residual))
    f["unserved_kw"] = np.maximum(0, residual - f.grid_import_kw)
    f["curtailed_kw"] = np.maximum(0, -residual)
    f["generation_kw"] = actual.generation_kw
    f["cost"] = f.grid_import_kw * actual.import_price * dt
    f["balance_error_kw"] = (
        f.generation_kw
        + f.grid_import_kw
        + f.discharge_kw
        + f.unserved_kw
        - f.facility_kw
        - f.charge_kw
        - f.curtailed_kw
    )
    final = float(f.battery_energy_kwh.iloc[-1])
    if abs(final - battery.initial_soc * battery.capacity_kwh) > 1e-6:
        raise ValueError("forecast replay must start from a plan with equal terminal SOC")
    return f
