"""Two-boundary solar/storage matching, reusing the package battery dispatcher."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.generation import generation_from_series, validate_timeline
from datacenter_simulator.methods.energy import Battery, dispatch
from datacenter_simulator.models.devices import finite


@dataclass
class UtilityStorageResult:
    timeseries: pd.DataFrame
    summary: dict[str, float]


def match_utility_storage(
    demand_kw: pd.Series,
    solar_kw: pd.Series,
    *,
    battery: Battery | None = None,
    poi_export_limit_kw: float,
    dt_hours: float = 1,
) -> UtilityStorageResult:
    """Greedy solar-only charging and hourly matching across two separate meters.

    Match direct solar first, charge surplus, discharge into the hourly deficit,
    then export unmatched surplus or curtail. The shared generation-site POI
    limits ALL solar plus battery export, including unmatched energy. No grid
    charging or simultaneous charge/discharge is allowed. The customer still
    imports its full facility demand from the utility. Residual unmatched demand
    is an accounting quantity, never a behind-the-meter import or an outage.

    Usable initial storage must be empty to avoid attributing unknown initial
    energy to solar. Final inventory is reported, never credited as delivered.
    No transmission losses, REC certification or contract dispatch are inferred.
    """
    if not isinstance(demand_kw.index, pd.DatetimeIndex):
        raise ValueError("demand requires a DatetimeIndex")
    validate_timeline(demand_kw.index)
    finite("dt_hours", dt_hours, strict=True)
    finite("poi_export_limit_kw", poi_export_limit_kw)
    demand = generation_from_series(demand_kw, demand_kw.index).to_numpy(dtype=float)
    solar = generation_from_series(solar_kw, demand_kw.index).to_numpy(dtype=float)
    if len(demand) > 1 and not np.allclose(
        (demand_kw.index[1:] - demand_kw.index[:-1]).total_seconds() / 3600,
        dt_hours,
        rtol=0,
        atol=1e-9,
    ):
        raise ValueError("timeline spacing must equal dt_hours")
    if battery is not None and battery.initial_soc != battery.minimum_soc:
        raise ValueError("initial usable storage must be empty for solar attribution")
    energy = 0.0 if battery is None else battery.initial_soc * battery.capacity_kwh
    initial = energy
    rows = []
    for load, pv in zip(demand, solar, strict=True):
        # A virtual matching target at the generation site is capped by the POI.
        # dispatch.grid_import_kw fills only that virtual target; it is not a meter.
        target = min(load, poi_export_limit_kw)
        before = energy
        step = dispatch(
            target,
            pv,
            dt_hours,
            battery=battery,
            energy_kwh=energy,
            grid_import_limit_kw=target,
            grid_export_limit_kw=max(0, poi_export_limit_kw - target),
        )
        energy = step.battery_energy_kwh
        if battery is not None:
            floor = battery.minimum_soc * battery.capacity_kwh
            ceiling = battery.maximum_soc * battery.capacity_kwh
            bounded = min(ceiling, max(floor, energy))
            if abs(bounded - energy) > 1e-7:
                raise RuntimeError("dispatch violated the battery energy window")
            # Snap roundoff at the bounds before the next step's strict validation.
            energy = bounded
        direct = min(pv, target)
        matched = direct + step.discharge_kw
        exported = matched + step.grid_export_kw
        rows.append(
            {
                "facility_demand_kw": load,
                "facility_utility_import_kw": load,
                "solar_available_kw": pv,
                "direct_solar_matched_kw": direct,
                "charge_kw": step.charge_kw,
                "discharge_kw": step.discharge_kw,
                "matched_kw": matched,
                "residual_unmatched_kw": load - matched,
                "site_export_kw": exported,
                "unmatched_export_kw": step.grid_export_kw,
                "curtailed_kw": step.curtailed_kw,
                "battery_energy_kwh": energy,
                "battery_loss_kw": step.battery_loss_kw,
                "site_balance_error_kw": pv
                + step.discharge_kw
                - step.charge_kw
                - exported
                - step.curtailed_kw,
                "storage_balance_error_kwh": energy
                - before
                - dt_hours * (step.charge_kw - step.discharge_kw - step.battery_loss_kw),
            }
        )
    frame = pd.DataFrame(rows, index=demand_kw.index)
    total = float(frame.facility_demand_kw.sum() * dt_hours)
    delivered = float(frame.matched_kw.sum() * dt_hours)
    discharge = float(frame.discharge_kw.sum() * dt_hours)
    usable_ac = (
        0
        if battery is None
        else battery.capacity_kwh
        * (battery.maximum_soc - battery.minimum_soc)
        * battery.discharge_efficiency
    )
    summary = {
        "facility_energy_mwh": total / 1000,
        "matched_energy_mwh": delivered / 1000,
        "hourly_matched_fraction": delivered / total if total else 0,
        "fully_matched_hours": float(
            ((frame.residual_unmatched_kw <= 1e-7) & (frame.facility_demand_kw > 0)).sum()
            * dt_hours
        ),
        "residual_unmatched_mwh": (total - delivered) / 1000,
        "facility_meter_peak_mw": float(frame.facility_utility_import_kw.max() / 1000),
        "residual_unmatched_peak_mw": float(frame.residual_unmatched_kw.max() / 1000),
        "solar_available_mwh": float(frame.solar_available_kw.sum() * dt_hours / 1000),
        "battery_charge_mwh": float(frame.charge_kw.sum() * dt_hours / 1000),
        "battery_discharge_mwh": discharge / 1000,
        "battery_loss_mwh": float(frame.battery_loss_kw.sum() * dt_hours / 1000),
        "unmatched_export_mwh": float(frame.unmatched_export_kw.sum() * dt_hours / 1000),
        "curtailed_mwh": float(frame.curtailed_kw.sum() * dt_hours / 1000),
        "initial_internal_energy_mwh": initial / 1000,
        "final_internal_energy_mwh": energy / 1000,
        "equivalent_delivered_cycles": discharge / usable_ac if usable_ac else 0,
        "site_balance_max_abs_kw": float(frame.site_balance_error_kw.abs().max()),
        "storage_balance_max_abs_kwh": float(frame.storage_balance_error_kwh.abs().max()),
    }
    return UtilityStorageResult(frame, summary)
