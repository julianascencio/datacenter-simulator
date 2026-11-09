"""Reusable facility sizing, geometry and annual energy calculations."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, isclose, sqrt
from typing import Literal

import pandas as pd

from datacenter_simulator.methods.cooling import CoolingPlant, cooling_alternatives
from datacenter_simulator.methods.infrastructure import (
    infrastructure_balance,
    size_modules,
    ups_energy_required,
)
from datacenter_simulator.models.design import DesignInputs, OperatingBin, Redundancy
from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.infrastructure import ModularEquipment


def size_redundant_capacity(
    name: str,
    duty_kw: float,
    module_kw: float,
    *,
    redundancy: Redundancy = "N+1",
    derating: float = 1,
    domain: Literal["electrical", "thermal"] = "electrical",
) -> dict[str, str | float | int | bool]:
    """Size N, N+1 or two independent full-duty N trains using ``size_modules``.

    Reports loss of one module for N/N+1 and one entire train for 2N. Zero duty
    installs nothing. Ratings are effective kW after any kVA/PF limit, before
    derating. A passing arithmetic check is not a Tier or reliability claim.
    """
    if redundancy not in {"N", "N+1", "2N"}:
        raise ValueError("redundancy must be N, N+1 or 2N")
    base = size_modules(
        ModularEquipment(name, module_kw, int(redundancy == "N+1"), derating, domain), duty_kw
    )
    n = int(base["duty_units"])
    installed = 2 * n if redundancy == "2N" else int(base["installed_units"])
    lost = n if redundancy == "2N" else min(1, installed)
    usable = module_kw * derating
    remaining = (installed - lost) * usable
    return {
        "equipment": name,
        "domain": domain,
        "redundancy": redundancy,
        "duty_kw": duty_kw,
        "effective_module_kw": module_kw,
        "module_derating": derating,
        "duty_modules": n,
        "installed_modules": installed,
        "installed_usable_kw": installed * usable,
        "contingency": "one train" if redundancy == "2N" else "one module",
        "lost_modules": lost,
        "remaining_kw": remaining,
        "remaining_margin_kw": remaining - duty_kw,
        "contingency_pass": remaining >= duty_kw - 1e-9,
    }


def three_phase_current(power_kw: float, voltage_v: float, power_factor: float) -> float:
    """Balanced three-phase RMS current: kW * 1000 / (sqrt(3) * V_LL * PF)."""
    finite("power_kw", power_kw)
    finite("voltage_v", voltage_v, strict=True)
    fraction("power_factor", power_factor, positive=True)
    return power_kw * 1000 / (sqrt(3) * voltage_v * power_factor)


def rack_layout(inputs: DesignInputs) -> tuple[pd.DataFrame, dict[str, float]]:
    """Place racks with alternating cold/hot aisles and perimeter clearance.

    The final rack carries the remainder. Floor area is geometric, excludes
    structural/egress/code checks, and applies the declared support allowance.
    """
    demand = inputs.it_peak_kw * (1 + inputs.growth_fraction)
    count = ceil(demand / inputs.rack_limit_kw)
    rows = ceil(count / inputs.racks_per_row)
    row_y = [inputs.perimeter_m]
    for row in range(1, rows):
        aisle = inputs.cold_aisle_m if row % 2 else inputs.hot_aisle_m
        row_y.append(row_y[-1] + inputs.rack_depth_m + aisle)
    records = []
    for i in range(count):
        row, column = divmod(i, inputs.racks_per_row)
        records.append(
            {
                "rack": f"R{i + 1:04d}",
                "row": row + 1,
                "x_m": inputs.perimeter_m + column * inputs.rack_width_m,
                "y_m": row_y[row],
                "width_m": inputs.rack_width_m,
                "depth_m": inputs.rack_depth_m,
                "height_m": inputs.rack_height_m,
                "it_kw": min(inputs.rack_limit_kw, demand - i * inputs.rack_limit_kw),
            }
        )
    width = min(count, inputs.racks_per_row) * inputs.rack_width_m + 2 * inputs.perimeter_m
    depth = row_y[-1] + inputs.rack_depth_m + inputs.perimeter_m
    area = width * depth
    return pd.DataFrame(records), {
        "rack_count": float(count),
        "rack_rows": float(rows),
        "hall_width_m": width,
        "hall_depth_m": depth,
        "white_space_m2": area,
        "total_planning_area_m2": area * (1 + inputs.support_area_fraction),
        "white_space_kw_per_m2": demand / area,
    }


@dataclass
class FacilityDesign:
    """Calculated peak design and selected duty plant, ready for operating studies."""

    inputs: DesignInputs
    plant: CoolingPlant
    balance: dict[str, float]
    equipment: pd.DataFrame
    racks: pd.DataFrame
    summary: dict[str, float]


def design_balance(
    inputs: DesignInputs, plant: CoolingPlant, it_kw: float, ambient_c: float
) -> dict[str, float]:
    """Reuse the package power/heat balance with fixed site auxiliaries."""
    return infrastructure_balance(
        it_kw,
        plant,
        ambient_c=ambient_c,
        downstream_efficiency=inputs.downstream_efficiency,
        ups_efficiency=inputs.ups_efficiency,
        main_efficiency=inputs.main_efficiency,
        auxiliary_kw=inputs.it_peak_kw * (1 + inputs.growth_fraction) * inputs.auxiliary_fraction,
    )


def design_facility(inputs: DesignInputs | None = None) -> FacilityDesign:
    """Size cooling first, then electrical capacity using its calculated demand.

    Only the duty cooling modules operate; spare/trailing train standby power
    is excluded. The UPS protects IT and downstream distribution, not cooling.
    2N requires two independent battery banks, each sized for the full load.
    """
    inputs = DesignInputs() if inputs is None else inputs
    it_kw = inputs.it_peak_kw * (1 + inputs.growth_fraction)
    heat = it_kw / inputs.downstream_efficiency
    cooling = size_redundant_capacity(
        "Cooling plant",
        heat * (1 + inputs.cooling_margin_fraction),
        inputs.cooling_module_kw_th,
        redundancy=inputs.redundancy,
        derating=inputs.module_derating,
        domain="thermal",
    )
    duty_capacity = float(cooling["duty_modules"]) * inputs.cooling_module_kw_th
    plant = cooling_alternatives(duty_capacity * inputs.module_derating)[inputs.cooling]
    balance = design_balance(inputs, plant, it_kw, inputs.design_ambient_c)
    specifications = (
        (
            "UPS",
            balance["ups_output_kw"],
            min(inputs.ups_module_kw, inputs.ups_module_kva * inputs.ups_load_power_factor),
        ),
        (
            "Transformers",
            balance["facility_kw"],
            inputs.transformer_module_kva * inputs.facility_power_factor,
        ),
        (
            "Generators",
            balance["facility_kw"],
            min(
                inputs.generator_module_kw,
                inputs.generator_module_kva * inputs.facility_power_factor,
            ),
        ),
    )
    equipment = pd.DataFrame(
        [
            size_redundant_capacity(
                name, duty, rating, redundancy=inputs.redundancy, derating=inputs.module_derating
            )
            for name, duty, rating in specifications
        ]
        + [cooling]
    )
    racks, geometry = rack_layout(inputs)
    battery = ups_energy_required(
        balance["ups_output_kw"],
        inputs.ups_autonomy_minutes,
        inverter_efficiency=inputs.battery_inverter_efficiency,
        usable_fraction=inputs.battery_usable_fraction,
        end_of_life_fraction=inputs.battery_end_of_life_fraction,
    )
    banks = 2 if inputs.redundancy == "2N" else 1
    summary = {
        **geometry,
        "design_it_kw": it_kw,
        "design_facility_kw": balance["facility_kw"],
        "design_power_ratio": balance["instantaneous_pue"],
        "service_kva": balance["facility_kw"] / inputs.facility_power_factor,
        "service_current_a": three_phase_current(
            balance["facility_kw"], inputs.service_voltage_v, inputs.facility_power_factor
        ),
        "grid_margin_kw": inputs.grid_limit_kw - balance["facility_kw"],
        "battery_per_bank_kwh": battery,
        "battery_bank_count": float(banks),
        "battery_total_kwh": battery * banks,
        "battery_output_rating_required_kw": balance["ups_output_kw"],
        "battery_output_rating_required_kva": balance["ups_output_kw"]
        / inputs.ups_load_power_factor,
        "liquid_flow_kg_s": balance["liquid_flow_kg_s"],
        "air_flow_m3_s": balance["air_flow_m3_s"],
        "heat_rejection_kw": balance["rejected_heat_kw"],
    }
    return FacilityDesign(inputs, plant, balance, equipment, racks, summary)


def annual_design_energy(
    design: FacilityDesign, bins: Sequence[OperatingBin]
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Evaluate a frozen design over a non-leap-year load/weather histogram.

    PUE is the ratio of summed energies, never the mean of power ratios. No
    dispatch, dynamic failures, generation, tariff escalation or hourly carbon
    matching is modelled. Reject cooling overload instead of reporting an
    apparently efficient but thermally infeasible annual case.
    """
    if not bins or not isclose(sum(b.hours for b in bins), 8760, rel_tol=0, abs_tol=1e-6):
        raise ValueError("annual operating bins must sum to 8760 hours")
    rows = []
    for b in bins:
        power = design_balance(
            design.inputs,
            design.plant,
            design.summary["design_it_kw"] * b.load_fraction,
            b.ambient_c,
        )
        if power["unmet_heat_kw"] > 1e-8:
            raise ValueError("annual bin exceeds installed duty cooling capacity")
        rows.append(
            {"hours": b.hours, "load_fraction": b.load_fraction, "ambient_c": b.ambient_c, **power}
        )
    frame = pd.DataFrame(rows)
    it_energy = float((frame.it_kw * frame.hours).sum())
    energy = float((frame.facility_kw * frame.hours).sum())
    grid_gap = (frame.facility_kw - design.inputs.grid_limit_kw).clip(lower=0)
    return frame, {
        "annual_it_kwh": it_energy,
        "annual_facility_kwh": energy,
        "annual_energy_pue": energy / it_energy,
        "annual_electricity_eur": energy * design.inputs.electricity_eur_per_kwh,
        "annual_grid_t_co2e": energy * design.inputs.grid_kg_co2e_per_kwh / 1000,
        "annual_grid_exceedance_kwh": float((grid_gap * frame.hours).sum()),
        "annual_grid_exceedance_hours": float(frame.loc[grid_gap > 1e-9, "hours"].sum()),
    }
