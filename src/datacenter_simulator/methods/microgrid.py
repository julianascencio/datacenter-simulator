"""Quasi-static direct-DC PV/storage coupling with distribution-loss feedback."""

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.generation import generation_from_series, validate_timeline
from datacenter_simulator.methods.dc_grid import DCGrid, DCGridResult, DCPort
from datacenter_simulator.methods.energy import Battery, dispatch
from datacenter_simulator.models.devices import finite, fraction


@dataclass
class MicrogridResult:
    timeseries: pd.DataFrame
    snapshots: list[DCGridResult | None]
    summary: dict[str, float]


def simulate_dc_microgrid(
    grid: DCGrid,
    loads_kw: pd.DataFrame,
    pv_dc_kw: pd.Series,
    *,
    battery: Battery | None = None,
    dt_hours: float = 1,
    grid_limit_ac_kw: pd.Series | None = None,
    pv_coupling: Literal["dc", "ac"] = "dc",
    pv_converter_efficiency: float = 0.98,
    inverter_efficiency: float = 0.96,
    rectifier_efficiency: float = 0.97,
    pv_converter_rating_kw: float = 1e6,
) -> MicrogridResult:
    """PV at array DC output; loads at DC terminals; grid at AC meter.

    Battery remains DC-connected in both PV-coupling cases. The reference bus is
    regulated by grid, battery or curtaillable PV. Deficits shed terminal demand
    uniformly with feeder-loss feedback. This is a steady-state sequence, not
    an islanding transient or an AC cooling-plant simulation.
    """
    if not isinstance(loads_kw.index, pd.DatetimeIndex):
        raise ValueError("loads need a DatetimeIndex")
    validate_timeline(loads_kw.index)
    finite("dt_hours", dt_hours, strict=True)
    finite("pv_converter_rating_kw", pv_converter_rating_kw, strict=True)
    if len(loads_kw) > 1 and not np.allclose(
        (loads_kw.index[1:] - loads_kw.index[:-1]).total_seconds(), dt_hours * 3600
    ):
        raise ValueError("load intervals must match dt_hours")
    if (
        set(loads_kw) - set(grid.ids)
        or not np.isfinite(loads_kw.to_numpy()).all()
        or (loads_kw < 0).any().any()
    ):
        raise ValueError("loads must be nonnegative finite values on known buses")
    if len(grid.ports) != 1 or grid.ports[0].mode != "voltage":
        raise ValueError(
            "microgrid template needs one regulated root; use DCGrid for custom sharing"
        )
    if pv_coupling not in {"ac", "dc"}:
        raise ValueError("unknown PV coupling")
    for name, value in (
        ("pv_converter_efficiency", pv_converter_efficiency),
        ("inverter_efficiency", inverter_efficiency),
        ("rectifier_efficiency", rectifier_efficiency),
    ):
        fraction(name, value, positive=True)
    pv = generation_from_series(pv_dc_kw, loads_kw.index)
    limits = (
        pd.Series(1e6, index=loads_kw.index)
        if grid_limit_ac_kw is None
        else generation_from_series(grid_limit_ac_kw, loads_kw.index)
    )
    efficiency = (
        pv_converter_efficiency
        if pv_coupling == "dc"
        else inverter_efficiency * rectifier_efficiency
    )
    root = grid.ports[0]
    template = DCGrid(
        grid.nominal_v,
        grid.lines,
        [
            DCPort(
                "reference",
                root.bus,
                voltage_v=root.voltage_v,
                max_source_kw=1e9,
                max_current_a=1e12,
                efficiency=1,
            )
        ],
    )
    energy = battery.capacity_kwh * battery.initial_soc if battery else 0.0
    rows, snapshots = [], []
    for t, (_, sample) in enumerate(loads_kw.iterrows()):
        demand = {str(k): float(v) for k, v in sample.items()}
        available_pv = min(float(pv.iloc[t]) * efficiency, pv_converter_rating_kw)
        grid_cap = min(
            float(limits.iloc[t]) * rectifier_efficiency,
            root.max_source_kw,
            root.max_current_a * root.voltage_v / 1000,
        )
        available_battery = (
            0.0
            if battery is None
            else min(
                battery.max_discharge_kw,
                max(0, energy - battery.minimum_soc * battery.capacity_kwh)
                * battery.discharge_efficiency
                / dt_hours,
            )
        )
        if available_battery < 1e-8:
            available_battery = 0.0
        available = available_pv + grid_cap + available_battery

        def requirement(scale: float, demand: dict[str, float] = demand) -> DCGridResult:
            return template.solve({bus: power * scale for bus, power in demand.items()})

        scale = 1.0
        try:
            solved = requirement(scale)
            feasible = float(solved.ports.bus_kw.sum()) <= available + 1e-8
        except ValueError:
            feasible = False
        if not feasible:
            low, high = 0.0, 1.0
            solved = requirement(0)
            for _ in range(40):
                mid = (low + high) / 2
                try:
                    candidate = requirement(mid)
                    ok = float(candidate.ports.bus_kw.sum()) <= available
                except ValueError:
                    ok = False
                if ok:
                    low, solved = mid, candidate
                else:
                    high = mid
            scale = low
        needed = max(0.0, float(solved.ports.bus_kw.sum()))
        balance = dispatch(
            needed,
            available_pv,
            dt_hours,
            battery=battery,
            energy_kwh=energy,
            grid_import_limit_kw=grid_cap,
        )
        energy = balance.battery_energy_kwh
        used_pv = max(0.0, available_pv - balance.curtailed_kw)
        battery_power = balance.discharge_kw - balance.charge_kw
        actual_ports = []
        if grid_cap > 0:
            actual_ports.append(
                DCPort(
                    "grid",
                    root.bus,
                    voltage_v=root.voltage_v,
                    max_source_kw=grid_cap,
                    max_current_a=1e12,
                    efficiency=rectifier_efficiency,
                )
            )
            if battery is not None:
                actual_ports.append(
                    DCPort(
                        "battery",
                        root.bus,
                        "power",
                        root.voltage_v,
                        battery_power,
                        battery.max_discharge_kw,
                        battery.max_charge_kw,
                        max_current_a=1e12,
                        efficiency=1,
                    )
                )
            actual_ports.append(
                DCPort(
                    "pv",
                    root.bus,
                    "power",
                    root.voltage_v,
                    used_pv,
                    max_source_kw=pv_converter_rating_kw,
                    max_current_a=1e12,
                    efficiency=efficiency,
                )
            )
        elif battery is not None and (available_battery > 0 or balance.charge_kw > 0):
            actual_ports.append(
                DCPort(
                    "battery",
                    root.bus,
                    voltage_v=root.voltage_v,
                    max_source_kw=available_battery,
                    max_sink_kw=battery.max_charge_kw,
                    max_current_a=1e12,
                    efficiency=1,
                )
            )
            actual_ports.append(
                DCPort(
                    "pv",
                    root.bus,
                    "power",
                    root.voltage_v,
                    used_pv,
                    max_source_kw=pv_converter_rating_kw,
                    max_current_a=1e12,
                    efficiency=efficiency,
                )
            )
        elif used_pv > 0:
            actual_ports.append(
                DCPort(
                    "pv",
                    root.bus,
                    voltage_v=root.voltage_v,
                    max_source_kw=used_pv,
                    max_current_a=1e12,
                    efficiency=efficiency,
                )
            )
        snapshot = (
            DCGrid(grid.nominal_v, grid.lines, actual_ports).solve(
                {bus: power * scale for bus, power in demand.items()}
            )
            if actual_ports
            else None
        )
        snapshots.append(snapshot)
        served = sum(demand.values()) * scale
        rows.append(
            {
                **asdict(balance),
                "requested_terminal_kw": sum(demand.values()),
                "served_terminal_kw": served,
                "unserved_terminal_kw": sum(demand.values()) - served,
                "served_fraction": scale,
                "dc_loss_kw": solved.cable_loss_kw,
                "grid_import_ac_kw": balance.grid_import_kw / rectifier_efficiency,
                "rectifier_loss_kw": balance.grid_import_kw * (1 / rectifier_efficiency - 1),
                "pv_available_dc_kw": float(pv.iloc[t]),
                "pv_bus_kw": used_pv,
                "pv_loss_kw": used_pv * (1 / efficiency - 1),
                "pv_curtailed_dc_kw": max(0, float(pv.iloc[t]) - used_pv / efficiency),
                "minimum_voltage_v": 0.0
                if snapshot is None
                else float(snapshot.buses.voltage_v.min()),
                "grid_connected": grid_cap > 0,
            }
        )
    frame = pd.DataFrame(rows, index=loads_kw.index)
    return MicrogridResult(
        frame,
        snapshots,
        {
            "grid_import_ac_kwh": float(frame.grid_import_ac_kw.sum() * dt_hours),
            "unserved_terminal_kwh": float(frame.unserved_terminal_kw.sum() * dt_hours),
            "conversion_loss_kwh": float(
                (frame.rectifier_loss_kw + frame.pv_loss_kw + frame.battery_loss_kw).sum()
                * dt_hours
            ),
            "dc_loss_kwh": float(frame.dc_loss_kw.sum() * dt_hours),
            "max_balance_error_kw": float(frame.balance_error_kw.abs().max()),
        },
    )
