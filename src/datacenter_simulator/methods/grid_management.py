"""Chronological fleet dispatch, shared outages and static contingency screening.

The optimization is a single facility-bus MILP, not AC transmission power flow,
dynamic islanding, or automatic N-1 security-constrained dispatch.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from datacenter_simulator.connectors.generation import validate_timeline
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.models.devices import finite
from datacenter_simulator.models.grid_management import Generator, GridPolicy, SupplyOutage


@dataclass
class GridManagementResult:
    timeseries: pd.DataFrame
    generators_kw: pd.DataFrame
    available_kw: pd.DataFrame
    summary: dict[str, float]
    solver_message: str


def _validate_profiles(profiles: pd.DataFrame, dt_hours: float) -> None:
    if not isinstance(profiles.index, pd.DatetimeIndex):
        raise ValueError("grid profiles require a DatetimeIndex")
    validate_timeline(profiles.index)
    finite("dt_hours", dt_hours, strict=True)
    required = {
        "demand_kw",
        "critical_demand_kw",
        "renewable_kw",
        "grid_limit_kw",
        "import_price_per_kwh",
        "grid_carbon_kg_per_kwh",
    }
    if not required <= set(profiles) or profiles.columns.has_duplicates:
        raise ValueError(f"grid profiles require unique columns including {sorted(required)}")
    try:
        values = profiles[list(required)].to_numpy(dtype=float)
    except (ValueError, TypeError) as error:
        raise ValueError("grid profiles must be numeric") from error
    if not np.isfinite(values).all():
        raise ValueError("grid profiles must be finite")
    if (profiles[list(required - {"import_price_per_kwh"})] < 0).any().any():
        raise ValueError("power and carbon profiles must be nonnegative")
    if (profiles.critical_demand_kw > profiles.demand_kw).any():
        raise ValueError("critical demand cannot exceed total demand")
    if len(profiles) > 1 and not np.allclose(
        (profiles.index[1:] - profiles.index[:-1]).total_seconds(), dt_hours * 3600
    ):
        raise ValueError("profile intervals must match dt_hours")


def supply_availability(
    profiles: pd.DataFrame,
    generators: tuple[Generator, ...],
    *,
    outages: tuple[SupplyOutage, ...] = (),
    availability: pd.DataFrame | None = None,
    dt_hours: float = 1.0,
) -> tuple[pd.DataFrame, pd.Series]:
    """Apply commissioning, supplied 0..1 availability and correlated outage groups.

    Event boundaries inside the horizon must align to interval boundaries. Outages
    outside the horizon are harmless, but unknown targets are always rejected.
    """
    _validate_profiles(profiles, dt_hours)
    ids = [g.id for g in generators]
    if len(set(ids)) != len(ids):
        raise ValueError("generator ids must be unique")
    index = profiles.index
    if availability is not None:
        if not availability.index.equals(index) or list(availability.columns) != ids:
            raise ValueError("availability must exactly match timestamps and generator order")
        values = availability.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
            raise ValueError("generator availability must be finite and within 0..1")
    cap = pd.DataFrame({g.id: g.net_capacity_kw for g in generators}, index=index)
    if availability is not None:
        cap *= availability
    last = index[-1] + pd.Timedelta(hours=dt_hours)

    def aligned(stamp: pd.Timestamp) -> None:
        if index[0] <= stamp <= last and not np.isclose(
            (stamp - index[0]).total_seconds() / (dt_hours * 3600) % 1, 0
        ):
            raise ValueError("supply events must align with interval boundaries")

    for g in generators:
        if g.commissioned_at is not None:
            aligned(g.commissioned_at)
            cap.loc[index < g.commissioned_at, g.id] = 0
            if g.commissioned_at > index[0] and g.initial_output_kw:
                raise ValueError("uncommissioned generator cannot have initial output")
    limits = profiles.grid_limit_kw.copy().astype(float)
    groups = {g.fuel_group for g in generators if g.fuel_group}
    for event in outages:
        if set(event.generator_ids) - set(ids) or set(event.fuel_groups) - groups:
            raise ValueError("outage refers to an unknown generator or fuel group")
        aligned(event.start)
        aligned(event.end)
        mask = (index >= event.start) & (index < event.end)
        affected = [
            g.id
            for g in generators
            if g.id in event.generator_ids or g.fuel_group in event.fuel_groups
        ]
        cap.loc[mask, affected] = 0
        if event.grid:
            limits.loc[mask] = 0
    return cap, limits


def contingency_screen(
    generators: tuple[Generator, ...],
    demand_kw: float,
    *,
    grid_limit_kw: float = 0,
    firm_extra_kw: float = 0,
) -> pd.DataFrame:
    """Full-built static capacity, individual/group outages; no battery permanence credit.

    Extra supply must already be net of its own contingencies. This screen ignores
    ramping and dates; chronological adequacy is checked with ``optimize_grid``.
    """
    for name, value in (
        ("demand_kw", demand_kw),
        ("grid_limit_kw", grid_limit_kw),
        ("firm_extra_kw", firm_extra_kw),
    ):
        finite(name, value)
    if len({g.id for g in generators}) != len(generators):
        raise ValueError("generator ids must be unique")
    total = sum(g.net_capacity_kw for g in generators) + grid_limit_kw + firm_extra_kw
    losses = [("no_outage", 0.0), ("grid_path", grid_limit_kw)]
    losses += [(f"generator:{g.id}", g.net_capacity_kw) for g in generators]
    losses += [
        (f"fuel_group:{group}", sum(g.net_capacity_kw for g in generators if g.fuel_group == group))
        for group in sorted({g.fuel_group for g in generators if g.fuel_group})
    ]
    return pd.DataFrame(
        [
            {
                "contingency": name,
                "lost_kw": loss,
                "remaining_kw": total - loss,
                "shortfall_kw": max(0.0, demand_kw - total + loss),
                "margin_kw": total - loss - demand_kw,
            }
            for name, loss in losses
        ]
    )


def optimize_grid(
    profiles: pd.DataFrame,
    generators: tuple[Generator, ...] = (),
    *,
    battery: Battery | None = None,
    outages: tuple[SupplyOutage, ...] = (),
    availability: pd.DataFrame | None = None,
    policy: GridPolicy | None = None,
    dt_hours: float = 1.0,
) -> GridManagementResult:
    """Perfect-foresight mixed-integer fleet/storage schedule at a common facility bus.

    Includes ramp limits, grid import caps, binary battery direction, finite SOC,
    terminal reserve, priority-weighted shedding, carbon and peak-import costs.
    Flexible shedding is lost load, NOT automatically rescheduled useful work.
    Abrupt capacity loss permits a forced trip; restoration obeys ramp-up limits.
    No exports, minimum up/down time, start fuel, voltage or frequency dynamics.
    """
    policy = GridPolicy() if policy is None else policy
    cap, limits = supply_availability(
        profiles, generators, outages=outages, availability=availability, dt_hours=dt_hours
    )
    n, m = len(profiles), len(generators)
    # n-length blocks: import, charge, discharge, end energy, renewable curtailment,
    # critical shed, flexible shed, battery direction, dispatchable spill; then fleet and peak.
    peak, size = (9 + m) * n, (9 + m) * n + 1
    lower, upper, cost = np.zeros(size), np.full(size, np.inf), np.zeros(size)
    integer = np.zeros(size)
    demand = profiles.demand_kw.to_numpy(dtype=float)
    critical = profiles.critical_demand_kw.to_numpy(dtype=float)
    renewable = profiles.renewable_kw.to_numpy(dtype=float)
    price = profiles.import_price_per_kwh.to_numpy(dtype=float)
    grid_carbon = profiles.grid_carbon_kg_per_kwh.to_numpy(dtype=float)
    limit = limits.to_numpy(dtype=float)
    capacities = cap.to_numpy(dtype=float)
    upper[:n] = limit
    upper[4 * n : 5 * n] = renewable
    upper[5 * n : 6 * n] = 0 if policy.require_critical_service else critical
    upper[6 * n : 7 * n] = demand - critical
    upper[7 * n : 8 * n], integer[7 * n : 8 * n] = 1, 1
    cost[:n] = dt_hours * (price + grid_carbon * policy.carbon_price_per_kg)
    cost[n : 3 * n] = dt_hours * policy.throughput_cost_per_kwh
    cost[5 * n : 6 * n] = dt_hours * policy.critical_unserved_cost_per_kwh
    cost[6 * n : 7 * n] = dt_hours * policy.flexible_unserved_cost_per_kwh
    cost[8 * n : 9 * n] = dt_hours * 1e-6
    cost[peak] = policy.demand_charge_per_kw
    initial = 0.0
    eta_c = eta_d = 1.0
    charge_cap = discharge_cap = 0.0
    if battery is None:
        if policy.terminal_soc is not None:
            raise ValueError("terminal SOC requires a battery")
        upper[n : 4 * n] = 0
        upper[7 * n : 8 * n] = 0
    else:
        terminal = battery.initial_soc if policy.terminal_soc is None else policy.terminal_soc
        if not battery.minimum_soc <= terminal <= battery.maximum_soc:
            raise ValueError("terminal SOC outside battery bounds")
        initial = battery.initial_soc * battery.capacity_kwh
        eta_c, eta_d = battery.charge_efficiency, battery.discharge_efficiency
        charge_cap, discharge_cap = battery.max_charge_kw, battery.max_discharge_kw
        upper[n : 2 * n], upper[2 * n : 3 * n] = charge_cap, discharge_cap
        lower[3 * n : 4 * n] = battery.minimum_soc * battery.capacity_kwh
        upper[3 * n : 4 * n] = battery.maximum_soc * battery.capacity_kwh
        lower[4 * n - 1] = terminal * battery.capacity_kwh
    for j, g in enumerate(generators):
        upper[(9 + j) * n : (10 + j) * n] = capacities[:, j]
        cost[(9 + j) * n : (10 + j) * n] = dt_hours * (
            g.marginal_cost_per_kwh + policy.carbon_price_per_kg * g.residual_kg_per_kwh
        )
    rows = (6 + 2 * m) * n
    a = lil_matrix((rows, size), dtype=float)
    lo, hi = np.full(rows, -np.inf), np.full(rows, np.inf)
    for t in range(n):
        a[t, [t, n + t, 2 * n + t, 4 * n + t, 5 * n + t, 6 * n + t, 8 * n + t]] = [
            1,
            -1,
            1,
            -1,
            1,
            1,
            -1,
        ]
        lo[t] = hi[t] = demand[t] - renewable[t]
        a[n + t, [3 * n + t, n + t, 2 * n + t]] = [1, -eta_c * dt_hours, dt_hours / eta_d]
        if t:
            a[n + t, 3 * n + t - 1] = -1
            lo[n + t] = hi[n + t] = 0
        else:
            lo[n + t] = hi[n + t] = initial
        a[2 * n + t, [n + t, 7 * n + t]] = [1, -charge_cap]
        hi[2 * n + t] = 0
        a[3 * n + t, [2 * n + t, 7 * n + t]] = [1, discharge_cap]
        hi[3 * n + t] = discharge_cap
        a[4 * n + t, [t, peak]] = [1, -1]
        hi[4 * n + t] = 0
        a[5 * n + t, 8 * n + t] = 1
        hi[5 * n + t] = 0
        for j, g in enumerate(generators):
            col = (9 + j) * n + t
            a[t, col], a[5 * n + t, col] = 1, -1
            if g.ramp_kw_per_hour is None:
                continue
            up, down = (6 + 2 * j) * n + t, (7 + 2 * j) * n + t
            a[up, col], a[down, col] = 1, -1
            previous_cap = capacities[t - 1, j] if t else g.net_capacity_kw
            forced_trip = max(0.0, previous_cap - capacities[t, j])
            ramp = g.ramp_kw_per_hour * dt_hours
            if t:
                a[up, col - 1], a[down, col - 1] = -1, 1
                hi[up], hi[down] = ramp, ramp + forced_trip
            else:
                hi[up] = g.initial_output_kw + ramp
                hi[down] = ramp + forced_trip - g.initial_output_kw
    solved = milp(
        cost,
        integrality=integer,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(a.tocsc(), lo, hi),
        options={"time_limit": 60, "mip_rel_gap": 1e-8},
    )
    if not solved.success or solved.x is None:
        raise ValueError(f"grid optimization failed: {solved.message}")
    x = solved.x
    fleet = pd.DataFrame(
        {g.id: x[(9 + j) * n : (10 + j) * n] for j, g in enumerate(generators)},
        index=profiles.index,
    )
    frame = profiles.copy()
    for name, block in (
        ("grid_import_kw", 0),
        ("charge_kw", 1),
        ("discharge_kw", 2),
        ("battery_energy_kwh", 3),
        ("curtailed_kw", 4),
        ("critical_unserved_kw", 5),
        ("flexible_unserved_kw", 6),
        ("spilled_kw", 8),
    ):
        frame[name] = x[block * n : (block + 1) * n]
    frame["grid_limit_kw"] = limits
    frame["generator_kw"] = fleet.sum(axis=1)
    frame["served_kw"] = demand - frame.critical_unserved_kw - frame.flexible_unserved_kw
    frame["balance_error_kw"] = (
        frame.generator_kw
        + frame.grid_import_kw
        + renewable
        - frame.curtailed_kw
        + frame.discharge_kw
        - frame.charge_kw
        - frame.served_kw
        - frame.spilled_kw
    )
    frame["battery_loss_kw"] = frame.charge_kw * (1 - eta_c) + frame.discharge_kw * (1 / eta_d - 1)
    frame["residual_carbon_kg"] = dt_hours * (
        frame.grid_import_kw * grid_carbon
        + sum(
            (fleet[g.id] * g.residual_kg_per_kwh for g in generators),
            start=pd.Series(0.0, index=frame.index),
        )
    )
    frame["captured_carbon_kg"] = dt_hours * sum(
        (fleet[g.id] * g.captured_kg_per_kwh for g in generators),
        start=pd.Series(0.0, index=frame.index),
    )
    operating = dt_hours * float(
        frame.grid_import_kw @ price
        + sum(fleet[g.id].sum() * g.marginal_cost_per_kwh for g in generators)
    )
    summary = {
        "operating_cost": operating,
        "objective_cost": float(solved.fun),
        "peak_import_kw": float(frame.grid_import_kw.max()),
        "demand_charge": float(frame.grid_import_kw.max()) * policy.demand_charge_per_kw,
        "served_kwh": float(frame.served_kw.sum()) * dt_hours,
        "critical_unserved_kwh": float(frame.critical_unserved_kw.sum()) * dt_hours,
        "flexible_unserved_kwh": float(frame.flexible_unserved_kw.sum()) * dt_hours,
        "residual_carbon_kg": float(frame.residual_carbon_kg.sum()),
        "captured_carbon_kg": float(frame.captured_carbon_kg.sum()),
        "maximum_balance_error_kw": float(frame.balance_error_kw.abs().max()),
    }
    return GridManagementResult(frame, fleet, cap, summary, str(solved.message))
