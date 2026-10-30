"""MILP storage dispatch and rolling-horizon execution with actual-power recourse."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from datacenter_simulator.connectors.generation import validate_timeline
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.models.devices import finite, fraction


@dataclass
class OptimizedDispatch:
    timeseries: pd.DataFrame
    objective: float
    summary: dict[str, float]


def _profiles(frame: pd.DataFrame, dt_hours: float) -> None:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("dispatch requires a DatetimeIndex")
    validate_timeline(frame.index)
    finite("dt_hours", dt_hours, strict=True)
    required = {"demand_kw", "generation_kw", "import_price"}
    if not required <= set(frame):
        raise ValueError("dispatch needs demand_kw, generation_kw and import_price")
    if not np.isfinite(frame.select_dtypes(include="number").to_numpy()).all():
        raise ValueError("dispatch inputs must be finite")
    for column in ("demand_kw", "generation_kw", "carbon_kg_kwh", "grid_limit_kw"):
        if column in frame and (frame[column] < 0).any():
            raise ValueError(f"{column} must be nonnegative")
    if len(frame) > 1 and not np.allclose(
        (frame.index[1:] - frame.index[:-1]).total_seconds(), dt_hours * 3600
    ):
        raise ValueError("dispatch timeline does not match dt_hours")


def optimize_dispatch(
    profiles: pd.DataFrame,
    battery: Battery,
    *,
    dt_hours: float = 1,
    initial_energy_kwh: float | None = None,
    terminal_soc: float | None = None,
    reserve_soc: float | None = None,
    grid_limit_kw: float = 1000,
    export_limit_kw: float = 0,
    demand_charge_per_kw: float = 0,
    carbon_price_per_kg: float = 0,
    throughput_cost_per_kwh: float = 0.01,
    unserved_cost_per_kwh: float = 1e6,
) -> OptimizedDispatch:
    """Optimize a declared common-bus boundary with mutually exclusive flow directions.

    Optional columns: export_price, carbon_kg_kwh, grid_limit_kw. Demand charges
    apply once to this horizon, not automatically to a calendar billing month.
    Unserved load is penalized explicitly; always inspect it before interpreting cost.
    """
    _profiles(profiles, dt_hours)
    for name, value in (
        ("grid_limit_kw", grid_limit_kw),
        ("export_limit_kw", export_limit_kw),
        ("demand_charge_per_kw", demand_charge_per_kw),
        ("carbon_price_per_kg", carbon_price_per_kg),
        ("throughput_cost_per_kwh", throughput_cost_per_kwh),
    ):
        finite(name, value)
    finite("unserved_cost_per_kwh", unserved_cost_per_kwh, strict=True)
    terminal = battery.initial_soc if terminal_soc is None else terminal_soc
    reserve = battery.minimum_soc if reserve_soc is None else reserve_soc
    for name, value in (("terminal_soc", terminal), ("reserve_soc", reserve)):
        fraction(name, value)
        if not battery.minimum_soc <= value <= battery.maximum_soc:
            raise ValueError(f"{name} outside battery bounds")
    initial = (
        battery.initial_soc * battery.capacity_kwh
        if initial_energy_kwh is None
        else initial_energy_kwh
    )
    finite("initial energy", initial, battery.minimum_soc * battery.capacity_kwh)
    if initial > battery.maximum_soc * battery.capacity_kwh:
        raise ValueError("initial energy exceeds battery capacity")
    n = len(profiles)
    demand = profiles.demand_kw.to_numpy(dtype=float)
    generation = profiles.generation_kw.to_numpy(dtype=float)
    prices = profiles.import_price.to_numpy(dtype=float)
    exports = profiles.get("export_price", pd.Series(0, index=profiles.index)).to_numpy(dtype=float)
    carbon = profiles.get("carbon_kg_kwh", pd.Series(0, index=profiles.index)).to_numpy(dtype=float)
    limits = profiles.get("grid_limit_kw", pd.Series(grid_limit_kw, index=profiles.index)).to_numpy(
        dtype=float
    )
    # Blocks: import/export, charge/discharge, energy, curtail/unserved, two direction modes.
    size, peak = 9 * n + 1, 9 * n
    lower, upper, cost = np.zeros(size), np.full(size, np.inf), np.zeros(size)
    integrality = np.zeros(size)
    upper[:n], upper[n : 2 * n] = limits, export_limit_kw
    upper[2 * n : 3 * n], upper[3 * n : 4 * n] = battery.max_charge_kw, battery.max_discharge_kw
    lower[4 * n : 5 * n], upper[4 * n : 5 * n] = (
        reserve * battery.capacity_kwh,
        battery.maximum_soc * battery.capacity_kwh,
    )
    lower[5 * n - 1] = max(lower[5 * n - 1], terminal * battery.capacity_kwh)
    upper[5 * n : 6 * n], upper[6 * n : 7 * n] = generation, demand
    upper[7 * n : 9 * n], integrality[7 * n : 9 * n] = 1, 1
    cost[:n] = dt_hours * (prices + carbon_price_per_kg * carbon)
    cost[n : 2 * n] = -dt_hours * exports
    cost[2 * n : 4 * n] = dt_hours * throughput_cost_per_kwh
    cost[6 * n : 7 * n] = dt_hours * unserved_cost_per_kwh
    cost[peak] = demand_charge_per_kw
    a = lil_matrix((7 * n, size), dtype=float)
    lo, hi = np.full(7 * n, -np.inf), np.full(7 * n, np.inf)
    for t in range(n):
        a[t, [t, n + t, 2 * n + t, 3 * n + t, 5 * n + t, 6 * n + t]] = [1, -1, -1, 1, -1, 1]
        lo[t] = hi[t] = demand[t] - generation[t]
        a[n + t, [4 * n + t, 2 * n + t, 3 * n + t]] = [
            1,
            -battery.charge_efficiency * dt_hours,
            dt_hours / battery.discharge_efficiency,
        ]
        if t:
            a[n + t, 4 * n + t - 1] = -1
            lo[n + t] = hi[n + t] = 0
        else:
            lo[n + t] = hi[n + t] = initial
        a[2 * n + t, [2 * n + t, 7 * n + t]] = [1, -battery.max_charge_kw]
        hi[2 * n + t] = 0
        a[3 * n + t, [3 * n + t, 7 * n + t]] = [1, battery.max_discharge_kw]
        hi[3 * n + t] = battery.max_discharge_kw
        a[4 * n + t, [t, 8 * n + t]] = [1, -limits[t]]
        hi[4 * n + t] = 0
        a[5 * n + t, [n + t, 8 * n + t]] = [1, export_limit_kw]
        hi[5 * n + t] = export_limit_kw
        a[6 * n + t, [t, peak]] = [1, -1]
        hi[6 * n + t] = 0
    solution = milp(
        cost,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(a.tocsc(), lo, hi),
        options={"time_limit": 60, "mip_rel_gap": 1e-8},
    )
    if not solution.success or solution.x is None:
        raise ValueError(f"dispatch optimization failed: {solution.message}")
    x = solution.x
    frame = pd.DataFrame(
        {
            "demand_kw": demand,
            "generation_kw": generation,
            "grid_import_kw": x[:n],
            "grid_export_kw": x[n : 2 * n],
            "charge_kw": x[2 * n : 3 * n],
            "discharge_kw": x[3 * n : 4 * n],
            "battery_energy_kwh": x[4 * n : 5 * n],
            "curtailed_kw": x[5 * n : 6 * n],
            "unserved_kw": x[6 * n : 7 * n],
        },
        index=profiles.index,
    )
    frame["balance_error_kw"] = (
        frame.generation_kw
        + frame.grid_import_kw
        + frame.discharge_kw
        + frame.unserved_kw
        - frame.demand_kw
        - frame.charge_kw
        - frame.grid_export_kw
        - frame.curtailed_kw
    )
    frame["battery_loss_kw"] = frame.charge_kw * (
        1 - battery.charge_efficiency
    ) + frame.discharge_kw * (1 / battery.discharge_efficiency - 1)
    return OptimizedDispatch(
        frame,
        float(solution.fun),
        {
            "energy_cost": float(dt_hours * (x[:n] @ prices - x[n : 2 * n] @ exports)),
            "carbon_kg": float(dt_hours * (x[:n] @ carbon)),
            "peak_import_kw": float(x[:n].max()),
            "throughput_kwh": float(dt_hours * (x[2 * n : 3 * n].sum() + x[3 * n : 4 * n].sum())),
            "unserved_kwh": float(dt_hours * x[6 * n : 7 * n].sum()),
        },
    )


def rolling_dispatch(
    actual: pd.DataFrame,
    forecasts: pd.DataFrame,
    battery: Battery,
    *,
    horizon: int = 24,
    dt_hours: float = 1,
    reserve_soc: float | None = None,
    carbon_price_per_kg: float = 0,
) -> pd.DataFrame:
    """Replan each step, execute only its first target, then reconcile actual power.

    Forecasts are a fixed input trace of predictions, not perfect-foresight actuals.
    Recourse cancels infeasible charging, then uses available battery energy for
    deficits. Grid limits are physical actual limits. No export is assumed here.
    """
    _profiles(actual, dt_hours)
    _profiles(forecasts, dt_hours)
    if not actual.index.equals(forecasts.index) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("matching forecast timestamps and a positive horizon are required")
    energy = battery.initial_soc * battery.capacity_kwh
    floor = battery.minimum_soc * battery.capacity_kwh
    ceiling = battery.maximum_soc * battery.capacity_kwh
    rows = []
    for t in range(len(actual)):
        window = forecasts.iloc[t : t + horizon]
        plan = optimize_dispatch(
            window,
            battery,
            dt_hours=dt_hours,
            initial_energy_kwh=energy,
            terminal_soc=battery.minimum_soc if reserve_soc is None else reserve_soc,
            carbon_price_per_kg=carbon_price_per_kg,
        )
        target = float(plan.timeseries.discharge_kw.iloc[0] - plan.timeseries.charge_kw.iloc[0])
        row = actual.iloc[t]
        demand, generation = float(row.demand_kw), float(row.generation_kw)
        limit = float(row.get("grid_limit_kw", 1000))
        max_discharge = min(
            battery.max_discharge_kw,
            max(0, energy - floor) * battery.discharge_efficiency / dt_hours,
        )
        max_charge = min(
            battery.max_charge_kw, max(0, ceiling - energy) / battery.charge_efficiency / dt_hours
        )
        # Ensure charging never consumes power needed to serve actual demand.
        charge = min(max(0, -target), max_charge, max(0, generation + limit - demand))
        discharge = min(
            max(0, target, demand - generation - limit), max_discharge, max(0, demand - generation)
        )
        if discharge:
            charge = 0.0
        imported = min(limit, max(0, demand + charge - generation - discharge))
        unserved = max(0, demand + charge - generation - discharge - imported)
        curtailed = max(0, generation + discharge + imported - demand - charge)
        energy += dt_hours * (
            charge * battery.charge_efficiency - discharge / battery.discharge_efficiency
        )
        energy = min(ceiling, max(floor, energy))
        rows.append(
            {
                "target_battery_kw": target,
                "charge_kw": charge,
                "discharge_kw": discharge,
                "grid_import_kw": imported,
                "unserved_kw": unserved,
                "curtailed_kw": curtailed,
                "battery_energy_kwh": energy,
                "balance_error_kw": generation
                + discharge
                + imported
                + unserved
                - demand
                - charge
                - curtailed,
            }
        )
    return pd.DataFrame(rows, index=actual.index)
