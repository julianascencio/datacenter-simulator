"""Fluid communication sharing coupled to job phases, terminal power and rack heat."""

from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from datacenter_simulator.methods.communications import CommunicationNetwork
from datacenter_simulator.methods.cooling import ThermalZone
from datacenter_simulator.methods.resilience import FailureEvent
from datacenter_simulator.models.devices import Electrical, finite, fraction


@dataclass(frozen=True)
class JobPhase:
    kind: Literal["compute", "transfer"]
    amount: float
    source: str = ""
    target: str = ""
    utilization: float = 1

    def __post_init__(self) -> None:
        if self.kind not in {"compute", "transfer"}:
            raise ValueError("unknown job phase")
        finite("phase amount", self.amount, strict=True)
        fraction("utilization", self.utilization, positive=True)
        if self.kind == "transfer" and (
            not self.source or not self.target or self.source == self.target
        ):
            raise ValueError("transfer needs distinct endpoints")


@dataclass(frozen=True)
class Job:
    """Compute amounts are seconds at requested utilization; transfers are decimal GB."""

    id: str
    device_id: str
    phases: tuple[JobPhase, ...]
    release_s: float = 0
    deadline_s: float = 3600

    def __post_init__(self) -> None:
        if not self.id or not self.device_id or not self.phases:
            raise ValueError("job needs id, device and phases")
        finite("release_s", self.release_s)
        finite("deadline_s", self.deadline_s, self.release_s, strict=True)


@dataclass(frozen=True)
class ComputeDevice:
    id: str
    electrical: Electrical
    cooling_capacity_kw: float
    zone: ThermalZone = field(default_factory=ThermalZone)
    initial_temperature_c: float = 24
    throttle_c: float = 40
    throttle_slope_per_k: float = 0.1
    waiting_utilization: float = 0.05
    power_cap_kw: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("compute device needs an id")
        finite("cooling_capacity_kw", self.cooling_capacity_kw)
        finite("initial_temperature_c", self.initial_temperature_c, -50)
        finite("throttle_c", self.throttle_c, -50)
        finite("throttle_slope_per_k", self.throttle_slope_per_k)
        fraction("waiting_utilization", self.waiting_utilization)
        if self.power_cap_kw is not None:
            finite("power_cap_kw", self.power_cap_kw)


def shortest_paths(
    network: CommunicationNetwork,
    source: str,
    target: str,
    *,
    failed_links: frozenset[str] = frozenset(),
    failed_nodes: frozenset[str] = frozenset(),
    ecmp: bool = True,
    maximum_paths: int = 64,
) -> list[tuple[tuple[str, int], ...]]:
    """Enumerate equal-cost simple paths; ECMP is fluid splitting, not packet hashing."""
    if source not in network.nodes or target not in network.nodes or source == target:
        raise ValueError("invalid flow endpoints")
    if failed_links - {e.id for e in network.links} or failed_nodes - set(network.nodes):
        raise ValueError("unknown network failure")
    if source in failed_nodes or target in failed_nodes:
        return []
    adjacency: dict[str, list[tuple[str, str, int, float]]] = {node: [] for node in network.nodes}
    for link in network.links:
        if link.id in failed_links or {link.source, link.target} & failed_nodes:
            continue
        adjacency[link.source].append((link.target, link.id, 0, link.latency_ms))
        adjacency[link.target].append((link.source, link.id, 1, link.latency_ms))
    queue: list[tuple[float, str]] = [(0, target)]
    distances = dict.fromkeys(network.nodes, float("inf"))
    distances[target] = 0
    while queue:
        cost, node = heappop(queue)
        if cost > distances[node]:
            continue
        for neighbor, _, _, latency in adjacency[node]:
            alternative = cost + latency
            if alternative < distances[neighbor]:
                distances[neighbor] = alternative
                heappush(queue, (alternative, neighbor))
    if not np.isfinite(distances[source]):
        return []
    found: list[tuple[tuple[str, int], ...]] = []

    def visit(node: str, seen: frozenset[str], path: tuple[tuple[str, int], ...]) -> None:
        if node == target:
            found.append(path)
            if len(found) > maximum_paths:
                raise ValueError("ECMP path count exceeds maximum_paths")
            return
        for neighbor, name, direction, latency in sorted(adjacency[node]):
            if neighbor not in seen and abs(distances[node] - latency - distances[neighbor]) < 1e-9:
                visit(neighbor, seen | {neighbor}, path + ((name, direction),))
                if found and not ecmp:
                    return

    visit(source, frozenset({source}), ())
    return found


def max_min_rates(
    usage: NDArray[np.float64],
    capacities: NDArray[np.float64],
    limits: NDArray[np.float64] | None = None,
) -> NDArray[np.float64]:
    """Progressive filling with fixed route fractions; columns are flows, rows resources."""
    a, caps = np.asarray(usage, dtype=float), np.asarray(capacities, dtype=float)
    if (
        a.ndim != 2
        or caps.shape != (a.shape[0],)
        or not np.isfinite(a).all()
        or not np.isfinite(caps).all()
    ):
        raise ValueError("invalid resource matrix/capacities")
    if np.any(a < 0) or np.any(caps < 0):
        raise ValueError("resource use and capacity cannot be negative")
    n = a.shape[1]
    ceilings = np.full(n, np.inf) if limits is None else np.asarray(limits, dtype=float)
    if ceilings.shape != (n,) or np.any(ceilings < 0) or np.isnan(ceilings).any():
        raise ValueError("invalid flow limits")
    rates = np.zeros(n)
    active = {j for j in range(n) if np.any(a[:, j] > 0)}
    while active:
        ids = sorted(active)
        slopes = a[:, ids].sum(axis=1)
        residual = np.maximum(0, caps - a @ rates)
        candidates = np.divide(
            residual, slopes, out=np.full_like(residual, np.inf), where=slopes > 0
        )
        increment = min(min(map(float, candidates)), min(map(float, ceilings[ids] - rates[ids])))
        rates[ids] += increment
        saturated = (a @ rates >= caps - 1e-9) & (slopes > 0)
        frozen = {j for j in ids if rates[j] >= ceilings[j] - 1e-9 or np.any(a[saturated, j] > 0)}
        if not frozen:
            raise ValueError("bandwidth allocation failed to make progress")
        active -= frozen
    return rates


@dataclass
class WorkloadResult:
    jobs: pd.DataFrame
    devices: pd.DataFrame
    links: pd.DataFrame
    summary: dict[str, float]


def simulate_workloads(
    network: CommunicationNetwork,
    devices: list[ComputeDevice],
    jobs: list[Job],
    *,
    duration_s: float = 3600,
    step_s: float = 1,
    scheduler: Literal["fifo", "edf"] = "edf",
    ecmp: bool = True,
    events: list[FailureEvent] | None = None,
    ambient_c: float = 25,
    setpoint_c: float = 24,
) -> WorkloadResult:
    """Nonpreemptive one-job/device execution with event-resolved phase completion.

    Transfer rate is max-min fair fluid bandwidth. No packet loss, TCP or latency
    percentile is inferred. Compute slows with explicit rack-zone throttling and
    power caps. All terminal electricity becomes heat. Simulation stops at last
    completion or duration_s; unfinished jobs remain explicit.
    """
    finite("duration_s", duration_s, strict=True)
    finite("step_s", step_s, strict=True)
    finite("ambient_c", ambient_c, -50)
    finite("setpoint_c", setpoint_c, -50)
    if scheduler not in {"fifo", "edf"}:
        raise ValueError("unknown scheduler")
    device_map, job_map = {d.id: d for d in devices}, {j.id: j for j in jobs}
    if not devices or not jobs or len(device_map) != len(devices) or len(job_map) != len(jobs):
        raise ValueError("nonempty devices/jobs need unique ids")
    if set(device_map) - set(network.nodes) or any(j.device_id not in device_map for j in jobs):
        raise ValueError("unknown device/network mapping")
    for job in jobs:
        for phase in job.phases:
            if phase.kind == "transfer" and {phase.source, phase.target} - set(network.nodes):
                raise ValueError("unknown transfer node")
    events = events or []
    if any(
        e.component not in set(network.nodes) | {link.id for link in network.links} for e in events
    ):
        raise ValueError("unknown failed network component")
    boundaries = sorted(
        {duration_s}
        | {j.release_s for j in jobs}
        | {v for e in events for v in (e.start_s, e.end_s)}
    )
    phases = dict.fromkeys(job_map, 0)
    remaining = {j.id: j.phases[0].amount for j in jobs}
    active: dict[str, str] = {}
    started: dict[str, float] = {}
    completed: dict[str, float] = {}
    energy = dict.fromkeys(job_map, 0.0)
    temperatures = {d.id: d.initial_temperature_c for d in devices}
    device_rows, link_rows = [], []
    t = 0.0
    while t < duration_s - 1e-9 and len(completed) < len(jobs):
        failed = {e.component for e in events if e.start_s <= t < e.end_s}
        offline = {
            d.id
            for d in devices
            if d.power_cap_kw is not None and d.power_cap_kw < d.electrical.power_kw(0)
        }
        failed_nodes = frozenset(failed.intersection(network.nodes) | offline)
        failed_links = frozenset(failed.intersection({link.id for link in network.links}))
        for device in devices:
            if device.id not in active:
                waiting = [
                    j
                    for j in jobs
                    if j.device_id == device.id and j.id not in started and j.release_s <= t + 1e-9
                ]
                if waiting:
                    chosen = min(
                        waiting,
                        key=lambda j: ((j.deadline_s if scheduler == "edf" else j.release_s), j.id),
                    )
                    active[device.id], started[chosen.id] = chosen.id, t
        transfers = [
            name
            for name in active.values()
            if job_map[name].phases[phases[name]].kind == "transfer"
        ]
        resources = [(e.id, direction) for e in network.links for direction in (0, 1)]
        resource_index = {key: i for i, key in enumerate(resources)}
        a = np.zeros((len(resources), len(transfers)))
        capacities = np.asarray(
            [
                e.capacity_gbps
                if e.id not in failed_links and not ({e.source, e.target} & failed_nodes)
                else 0
                for e in network.links
                for _ in (0, 1)
            ]
        )
        for k, name in enumerate(transfers):
            if job_map[name].device_id in failed_nodes:
                continue
            phase = job_map[name].phases[phases[name]]
            paths = shortest_paths(
                network,
                phase.source,
                phase.target,
                failed_links=failed_links,
                failed_nodes=failed_nodes,
                ecmp=ecmp,
            )
            for path in paths:
                for resource in path:
                    a[resource_index[resource], k] += 1 / len(paths)
        rates = max_min_rates(a, capacities) if transfers else np.zeros(0)
        progress = {name: float(rates[i] / 8) for i, name in enumerate(transfers)}
        powers, utils = {}, {}
        for d in devices:
            utilization = 0.0
            active_job = active.get(d.id)
            active_phase = job_map[active_job].phases[phases[active_job]] if active_job else None
            if active_phase is not None:
                utilization = (
                    active_phase.utilization
                    if active_phase.kind == "compute"
                    else d.waiting_utilization
                )
            throttle = max(
                0.05, 1 - max(0, temperatures[d.id] - d.throttle_c) * d.throttle_slope_per_k
            )
            utilization *= throttle
            if d.power_cap_kw is not None and d.id not in offline:
                if d.electrical.curve is not None:
                    cap_util = d.electrical.curve.utilization_at_power(d.power_cap_kw)
                else:
                    span = d.electrical.peak_kw - d.electrical.idle_kw
                    cap_util = (
                        min(1.0, max(0.0, (d.power_cap_kw - d.electrical.idle_kw) / span))
                        ** (1 / d.electrical.power_exponent)
                        if span
                        else 1.0
                    )
                utilization = min(utilization, cap_util)
            if d.id in failed_nodes:
                utilization = 0.0
            powers[d.id] = 0.0 if d.id in failed_nodes else d.electrical.power_kw(utilization)
            utils[d.id] = utilization
            if active_job and active_phase is not None and active_phase.kind == "compute":
                progress[active_job] = utilization / active_phase.utilization
        future = [v for v in boundaries if v > t + 1e-9]
        dt = min(step_s, duration_s - t, min(future) - t if future else duration_s - t)
        for name, rate in progress.items():
            if rate > 0:
                dt = min(dt, remaining[name] / rate)
        if dt < 1e-10:
            raise ValueError("workload event solver stalled")
        used = a @ rates
        for i, resource in enumerate(resources):
            link_rows.append(
                {
                    "time_s": t,
                    "duration_s": dt,
                    "link": resource[0],
                    "direction": resource[1],
                    "used_gbps": used[i],
                    "capacity_gbps": capacities[i],
                }
            )
        for d in devices:
            current_job = active.get(d.id)
            if current_job:
                energy[current_job] += powers[d.id] * dt / 3600
            removal = min(
                d.cooling_capacity_kw,
                max(
                    0,
                    powers[d.id]
                    + d.zone.conductance_kw_k * (ambient_c - setpoint_c)
                    + (temperatures[d.id] - setpoint_c) * d.zone.capacitance_kj_k / dt,
                ),
            )
            temperatures[d.id] = d.zone.advance(
                temperatures[d.id], ambient_c, powers[d.id], removal, dt / 3600
            )
            device_rows.append(
                {
                    "time_s": t,
                    "duration_s": dt,
                    "equipment_id": d.id,
                    "job": current_job or "",
                    "power_kw": powers[d.id],
                    "utilization": utils[d.id],
                    "temperature_c": temperatures[d.id],
                    "removed_heat_kw": removal,
                }
            )
        for name, rate in progress.items():
            remaining[name] -= rate * dt
            if remaining[name] <= 1e-8:
                phases[name] += 1
                if phases[name] == len(job_map[name].phases):
                    completed[name] = t + dt
                    del active[job_map[name].device_id]
                else:
                    remaining[name] = job_map[name].phases[phases[name]].amount
        t += dt
    rows = [
        {
            "job": j.id,
            "device_id": j.device_id,
            "release_s": j.release_s,
            "start_s": started.get(j.id, float("nan")),
            "completion_s": completed.get(j.id, float("nan")),
            "completed": j.id in completed,
            "deadline_s": j.deadline_s,
            "deadline_missed": (
                completed[j.id] > j.deadline_s if j.id in completed else t >= j.deadline_s
            ),
            "assigned_energy_kwh": energy[j.id],
        }
        for j in jobs
    ]
    frame = pd.DataFrame(device_rows)
    total_energy = float((frame.power_kw * frame.duration_s).sum() / 3600)
    return WorkloadResult(
        pd.DataFrame(rows).set_index("job"),
        frame,
        pd.DataFrame(link_rows),
        {
            "elapsed_s": t,
            "completed_jobs": float(len(completed)),
            "deadline_misses": float(sum(bool(r["deadline_missed"]) for r in rows)),
            "terminal_energy_kwh": total_energy,
            "energy_per_completed_job_kwh": total_energy / len(completed)
            if completed
            else float("nan"),
            "peak_temperature_c": float(frame.temperature_c.max()),
        },
    )


@dataclass
class WorkloadSchedule:
    jobs: tuple[Job, ...]
    plan: pd.DataFrame
    estimated_carbon_kg: float


def schedule_carbon_aware(
    jobs: list[Job],
    carbon_kg_kwh: list[float],
    power_kw: dict[str, float],
    *,
    slot_s: float = 60,
    estimated_transfer_gbps: float = 10,
) -> WorkloadSchedule:
    """Choose nonoverlapping start slots under release/deadline constraints.

    Duration estimates include compute and transfer time rounded UP to full slots.
    Transfer throughput and constant job power are declared planning assumptions.
    Re-execute the returned jobs through simulate_workloads to assess actual
    congestion and deadline performance; planning feasibility is not a guarantee.
    """
    from dataclasses import replace

    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix

    finite("slot_s", slot_s, strict=True)
    finite("estimated_transfer_gbps", estimated_transfer_gbps, strict=True)
    if not jobs or len({j.id for j in jobs}) != len(jobs) or not carbon_kg_kwh:
        raise ValueError("unique jobs and a nonempty carbon forecast required")
    carbon = np.asarray(carbon_kg_kwh, dtype=float)
    if not np.isfinite(carbon).all() or np.any(carbon < 0):
        raise ValueError("carbon factors must be finite and nonnegative")
    devices = sorted({job.device_id for job in jobs})
    for device in devices:
        if device not in power_kw:
            raise ValueError("each device needs a planning power")
        finite("planning power", power_kw[device], strict=True)
    candidates = []
    for i, job in enumerate(jobs):
        seconds = sum(
            p.amount if p.kind == "compute" else p.amount * 8 / estimated_transfer_gbps
            for p in job.phases
        )
        slots = int(np.ceil(seconds / slot_s))
        first = int(np.ceil(job.release_s / slot_s))
        last = min(len(carbon), int(np.floor(job.deadline_s / slot_s))) - slots
        if last < first:
            raise ValueError(f"job cannot fit its planning window: {job.id}")
        for start in range(first, last + 1):
            cost = float(
                carbon[start : start + slots].sum() * power_kw[job.device_id] * slot_s / 3600
            )
            candidates.append((i, start, slots, cost))
    count = len(candidates)
    rows = len(jobs) + len(devices) * len(carbon)
    a = lil_matrix((rows, count), dtype=float)
    lower, upper = np.zeros(rows), np.ones(rows)
    lower[: len(jobs)] = 1
    for k, (i, start, slots, _) in enumerate(candidates):
        a[i, k] = 1
        device_index = devices.index(jobs[i].device_id)
        for t in range(start, start + slots):
            a[len(jobs) + device_index * len(carbon) + t, k] = 1
    objective = np.asarray([c[3] for c in candidates])
    solution = milp(
        objective,
        integrality=np.ones(count),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(a.tocsc(), lower, upper),
        options={"time_limit": 60, "mip_rel_gap": 1e-8},
    )
    if not solution.success:
        raise ValueError("no feasible carbon-aware workload schedule")
    chosen, records = [], []
    for k, (i, start, slots, cost) in enumerate(candidates):
        if solution.x[k] > 0.5:
            job = jobs[i]
            chosen.append(replace(job, release_s=start * slot_s))
            records.append(
                {
                    "job": job.id,
                    "device_id": job.device_id,
                    "start_s": start * slot_s,
                    "reserved_end_s": (start + slots) * slot_s,
                    "estimated_carbon_kg": cost,
                }
            )
    return WorkloadSchedule(
        tuple(chosen), pd.DataFrame(records).set_index("job"), float(solution.fun)
    )


def workload_power_profile(
    result: WorkloadResult, start: pd.Timestamp, *, step_s: float = 60
) -> pd.DataFrame:
    """Energy-preserving regular DC-terminal profile from variable event intervals.

    The final output interval is padded with zero after the simulation ends;
    consumers must preserve that interval duration for exact energy accounting.
    """
    finite("step_s", step_s, strict=True)
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    devices = sorted(result.devices.equipment_id.unique())
    count = int(np.ceil(result.summary["elapsed_s"] / step_s))
    values = np.zeros((count, len(devices)))
    for row in result.devices.to_dict("records"):
        begin, end = float(row["time_s"]), float(row["time_s"] + row["duration_s"])
        column = devices.index(str(row["equipment_id"]))
        first, last = int(begin // step_s), min(count - 1, int(np.ceil(end / step_s) - 1))
        for slot in range(first, last + 1):
            overlap = max(0, min(end, (slot + 1) * step_s) - max(begin, slot * step_s))
            values[slot, column] += float(row["power_kw"]) * overlap / step_s
    return pd.DataFrame(
        values,
        columns=devices,
        index=pd.date_range(start, periods=count, freq=pd.Timedelta(seconds=step_s)),
    )
