"""Constrained BESS scheduling and independent outage/ramp stress tests."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from datacenter_simulator.connectors.generation import generation_from_series, validate_timeline
from datacenter_simulator.methods.energy import Battery, dispatch
from datacenter_simulator.models.bess_value import BESSValuePolicy
from datacenter_simulator.models.devices import finite


@dataclass
class BESSValueResult:
    timeseries: pd.DataFrame
    summary: dict[str, float]


def _inputs(demand: pd.Series, solar: pd.Series, dt_hours: float) -> tuple[np.ndarray, np.ndarray]:
    finite("dt_hours", dt_hours, strict=True)
    if not isinstance(demand.index, pd.DatetimeIndex):
        raise ValueError("demand needs a timezone-aware DatetimeIndex")
    validate_timeline(demand.index)
    if len(demand) > 1 and not np.allclose(
        (demand.index[1:] - demand.index[:-1]).total_seconds() / 3600, dt_hours, rtol=0, atol=1e-9
    ):
        raise ValueError("timeline spacing must equal dt_hours")
    return (
        generation_from_series(demand, demand.index).to_numpy(dtype=float),
        generation_from_series(solar, demand.index).to_numpy(dtype=float),
    )


def optimize_bess_value(
    demand_kw: pd.Series,
    solar_kw: pd.Series,
    import_eur_per_kwh: pd.Series,
    battery: Battery,
    policy: BESSValuePolicy,
    *,
    dt_hours: float = 1,
) -> BESSValueResult:
    """Perfect-foresight MILP: import energy + period peak + discharge wear.

    AC facility-bus powers; no exports or load shedding. Binary operating modes
    forbid simultaneous charging/discharging even with negative energy prices.
    Initial and terminal energy are equal: no free initial inventory. The
    constant reserve floor applies at every boundary. Solver failure/infeasible
    schedules raise, never become zero-cost solutions. This is an optimistic
    scheduling benchmark, not a real-time controller or market eligibility model.
    """
    load, solar = _inputs(demand_kw, solar_kw, dt_hours)
    if not import_eur_per_kwh.index.equals(demand_kw.index):
        raise ValueError("price timeline must exactly match demand")
    price = import_eur_per_kwh.to_numpy(dtype=float)
    if not np.isfinite(price).all():
        raise ValueError("prices must be finite")
    if not battery.minimum_soc <= policy.reserve_soc <= battery.initial_soc:
        raise ValueError("reserve must lie between physical minimum and initial SOC")
    n = len(load)
    # c, d, grid, curtail (n each), E (n+1), peak (1), charge-mode (n).
    energy_start, peak, mode_start = 4 * n, 5 * n + 1, 5 * n + 2
    size = 6 * n + 2
    lower, upper = np.zeros(size), np.full(size, np.inf)
    upper[:n] = battery.max_charge_kw
    upper[n : 2 * n] = battery.max_discharge_kw
    upper[2 * n : 3 * n] = policy.grid_limit_kw
    upper[3 * n : 4 * n] = solar
    lower[energy_start:peak] = policy.reserve_soc * battery.capacity_kwh
    upper[energy_start:peak] = battery.maximum_soc * battery.capacity_kwh
    initial = battery.initial_soc * battery.capacity_kwh
    lower[energy_start] = upper[energy_start] = initial
    lower[peak - 1] = upper[peak - 1] = initial
    upper[peak] = policy.grid_limit_kw
    upper[mode_start:] = 1
    objective = np.zeros(size)
    objective[n : 2 * n] = policy.wear_eur_per_kwh * dt_hours
    objective[2 * n : 3 * n] = price * dt_hours
    objective[peak] = policy.peak_eur_per_kw_period
    integrality = np.zeros(size)
    integrality[mode_start:] = 1
    matrix = lil_matrix((5 * n, size))
    lb, ub = np.full(5 * n, -np.inf), np.zeros(5 * n)
    for t in range(n):
        r = 5 * t
        matrix[r, [t, n + t, 2 * n + t, 3 * n + t]] = [-1, 1, 1, -1]
        lb[r] = ub[r] = load[t] - solar[t]
        matrix[r + 1, [energy_start + t + 1, energy_start + t, t, n + t]] = [
            1,
            -1,
            -battery.charge_efficiency * dt_hours,
            dt_hours / battery.discharge_efficiency,
        ]
        lb[r + 1] = ub[r + 1] = 0
        matrix[r + 2, [2 * n + t, peak]] = [1, -1]
        matrix[r + 3, [t, mode_start + t]] = [1, -battery.max_charge_kw]
        matrix[r + 4, [n + t, mode_start + t]] = [1, battery.max_discharge_kw]
        ub[r + 4] = battery.max_discharge_kw
    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(matrix.tocsr(), lb, ub),
        options={"time_limit": 60, "mip_rel_gap": 1e-8},
    )
    if not result.success or result.x is None:
        raise ValueError(f"BESS schedule not optimal/feasible: {result.message}")
    x = result.x
    charge, discharge = x[:n], x[n : 2 * n]
    grid, curtailed = x[2 * n : 3 * n], x[3 * n : 4 * n]
    energy = x[energy_start:peak]
    baseline = np.maximum(load - solar, 0)
    baseline_cost = float(np.dot(baseline, price) * dt_hours)
    baseline_peak_cost = float(baseline.max() * policy.peak_eur_per_kw_period)
    energy_cost = float(np.dot(grid, price) * dt_hours)
    peak_cost = float(grid.max() * policy.peak_eur_per_kw_period)
    wear = float(discharge.sum() * dt_hours * policy.wear_eur_per_kwh)
    loss = charge * (1 - battery.charge_efficiency) + discharge * (
        1 / battery.discharge_efficiency - 1
    )
    balance = solar + discharge + grid - load - charge - curtailed
    state_error = (
        np.diff(energy)
        - (charge * battery.charge_efficiency - discharge / battery.discharge_efficiency) * dt_hours
    )
    if max(abs(balance).max(), abs(state_error).max()) > 1e-5:
        raise RuntimeError("solver output violates conservation")
    frame = pd.DataFrame(
        {
            "demand_kw": load,
            "solar_kw": solar,
            "import_eur_per_kwh": price,
            "baseline_grid_kw": baseline,
            "grid_kw": grid,
            "charge_kw": charge,
            "discharge_kw": discharge,
            "curtailed_kw": curtailed,
            "energy_start_kwh": energy[:-1],
            "energy_end_kwh": energy[1:],
            "battery_loss_kw": loss,
            "balance_error_kw": balance,
        },
        index=demand_kw.index,
    )
    return BESSValueResult(
        frame,
        {
            "baseline_peak_kw": float(baseline.max()),
            "bess_peak_kw": float(grid.max()),
            "baseline_energy_cost_eur": baseline_cost,
            "baseline_peak_cost_eur": baseline_peak_cost,
            "bess_energy_cost_eur": energy_cost,
            "bess_peak_cost_eur": peak_cost,
            "wear_cost_eur": wear,
            "operating_saving_eur": baseline_cost
            + baseline_peak_cost
            - energy_cost
            - peak_cost
            - wear,
            "baseline_exceeds_connection": float(baseline.max() > policy.grid_limit_kw + 1e-7),
            "baseline_curtailed_kwh": float(np.maximum(solar - load, 0).sum() * dt_hours),
            "bess_curtailed_kwh": float(curtailed.sum() * dt_hours),
            "charge_kwh": float(charge.sum() * dt_hours),
            "discharge_kwh": float(discharge.sum() * dt_hours),
            "battery_loss_kwh": float(loss.sum() * dt_hours),
            "initial_energy_kwh": initial,
            "terminal_energy_kwh": float(energy[-1]),
        },
    )


def replay_outage(
    critical_demand_kw: pd.Series,
    solar_kw: pd.Series,
    battery: Battery,
    *,
    initial_energy_kwh: float,
    dt_hours: float = 1,
) -> BESSValueResult:
    """Unannounced grid outage using actual pre-outage SOC, physical minimum.

    Ideal islanding and available PV are assumed; no UPS transfer, fault, voltage,
    frequency, generator or grid-forming capability is established by this replay.
    """
    load, solar = _inputs(critical_demand_kw, solar_kw, dt_hours)
    energy = initial_energy_kwh
    rows = []
    for demand, pv in zip(load, solar, strict=True):
        step = dispatch(
            float(demand),
            float(pv),
            dt_hours,
            battery=battery,
            energy_kwh=energy,
            grid_import_limit_kw=0,
        )
        energy = float(
            np.clip(
                step.battery_energy_kwh,
                battery.minimum_soc * battery.capacity_kwh,
                battery.maximum_soc * battery.capacity_kwh,
            )
        )
        rows.append(
            {
                "demand_kw": demand,
                "solar_kw": pv,
                "discharge_kw": step.discharge_kw,
                "energy_end_kwh": energy,
                "unserved_kw": step.unserved_kw,
            }
        )
    frame = pd.DataFrame(rows, index=critical_demand_kw.index)
    return BESSValueResult(
        frame,
        {
            "unserved_kwh": float(frame.unserved_kw.sum() * dt_hours),
            "served_kwh": float((frame.demand_kw - frame.unserved_kw).sum() * dt_hours),
            "initial_energy_kwh": initial_energy_kwh,
            "terminal_energy_kwh": energy,
        },
    )


def ramp_buffer_requirement(
    demand_kw: pd.Series, *, grid_ramp_kw_per_s: float, dt_seconds: float
) -> dict[str, float]:
    """Ideal ramp-limited grid trace; signed residual is BESS discharge (+).

    Reports lossless minimum energy swing and power envelopes, not verified
    inverter dynamics. Initial grid equals first demand. No price/annual revenue
    is inferred from this subsecond/second-resolution sizing calculation.
    """
    values, _ = _inputs(demand_kw, demand_kw * 0, dt_seconds / 3600)
    finite("grid_ramp_kw_per_s", grid_ramp_kw_per_s, strict=True)
    grid = np.empty(len(values))
    grid[0] = values[0]
    for t in range(1, len(values)):
        delta = grid_ramp_kw_per_s * dt_seconds
        grid[t] = np.clip(values[t], grid[t - 1] - delta, grid[t - 1] + delta)
    residual = values - grid
    inventory = np.r_[0, np.cumsum(-residual * dt_seconds / 3600)]
    return {
        "required_discharge_kw": max(0.0, max(float(value) for value in residual)),
        "required_charge_kw": max(0.0, -min(float(value) for value in residual)),
        "minimum_lossless_energy_swing_kwh": float(np.ptp(inventory)),
        "initial_energy_above_minimum_kwh": float(-inventory.min()),
        "terminal_energy_change_kwh": float(inventory[-1]),
    }
