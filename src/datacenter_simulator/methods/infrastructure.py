"""Cost accounting, discrete sizing and a coupled planning-boundary power balance."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from math import ceil

import pandas as pd

from datacenter_simulator.methods.cooling import CoolingPlant
from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.infrastructure import CapitalScenario, CostItem, ModularEquipment


def capital_breakdown(
    items: Sequence[CostItem],
    scenario: CapitalScenario,
    *,
    multipliers: Mapping[str, float] | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Scale every listed rate once; fees remain absolute rates, not percentages.

    Multipliers express deliberate sensitivity assumptions. Unknown keys and
    duplicate items are errors. The source subtotal, contingency and unlisted
    allowances stay distinct; none of these implies a complete project budget.
    """
    ids = {item.id for item in items}
    if not items or len(ids) != len(items):
        raise ValueError("a nonempty catalogue with unique ids is required")
    factors = {} if multipliers is None else dict(multipliers)
    if set(factors) - ids:
        raise ValueError("multiplier refers to an unknown cost item")
    for factor in factors.values():
        finite("cost multiplier", factor)
    capacity = scenario.it_mw if scenario.mw_basis == "it" else scenario.facility_mw
    rows = []
    for item in items:
        factor = factors.get(item.id, 1.0)
        rows.append(
            {
                **asdict(item),
                "mw_basis": scenario.mw_basis,
                "basis_mw": capacity,
                "multiplier": factor,
                "cost_usd": item.million_usd_per_mw * 1e6 * capacity * factor,
            }
        )
    frame = pd.DataFrame(rows)
    subtotal = float(frame.cost_usd.sum())
    contingency = subtotal * scenario.contingency_fraction
    return frame, {
        "listed_subtotal_usd": subtotal,
        "contingency_usd": contingency,
        "unlisted_scope_usd": scenario.unlisted_scope_usd,
        "scenario_total_usd": subtotal + contingency + scenario.unlisted_scope_usd,
        "listed_usd_per_it_mw": subtotal / scenario.it_mw,
    }


def size_modules(equipment: ModularEquipment, duty_kw: float) -> dict[str, str | int | float]:
    """Ceiling of duty / usable unit capacity, plus the requested spare modules.

    A zero duty installs no units. Capacity after losing the specified reserve
    count is reported explicitly and must still cover duty. No cost is inferred.
    """
    finite("duty_kw", duty_kw)
    usable = equipment.rating_kw * equipment.derating
    duty_units = ceil(duty_kw / usable)
    reserve = equipment.reserve_units if duty_units else 0
    installed = duty_units + reserve
    return {
        "id": equipment.id,
        "domain": equipment.domain,
        "duty_kw": duty_kw,
        "unit_nameplate_kw": equipment.rating_kw,
        "derating": equipment.derating,
        "duty_units": duty_units,
        "reserve_units": reserve,
        "installed_units": installed,
        "installed_nameplate_kw": installed * equipment.rating_kw,
        "capacity_after_reserve_loss_kw": duty_units * usable,
        "margin_after_reserve_loss_kw": duty_units * usable - duty_kw,
    }


def ups_energy_required(
    output_kw: float,
    minutes: float,
    *,
    inverter_efficiency: float = 0.95,
    usable_fraction: float = 0.8,
    end_of_life_fraction: float = 0.8,
) -> float:
    """Nominal kWh = output kW × hours / (efficiency × usable × ageing factors)."""
    finite("output_kw", output_kw)
    finite("minutes", minutes)
    for name, value in (
        ("inverter_efficiency", inverter_efficiency),
        ("usable_fraction", usable_fraction),
        ("end_of_life_fraction", end_of_life_fraction),
    ):
        fraction(name, value, positive=True)
    return output_kw * minutes / 60 / inverter_efficiency / usable_fraction / end_of_life_fraction


def infrastructure_balance(
    it_kw: float,
    plant: CoolingPlant,
    *,
    ambient_c: float,
    downstream_efficiency: float = 0.98,
    ups_efficiency: float = 0.97,
    main_efficiency: float = 0.99,
    auxiliary_kw: float = 0,
) -> dict[str, float]:
    """IT terminals <- distribution <- UPS <- main distribution <- utility meter.

    IT includes servers AND networking. Downstream distribution losses heat the
    hall; UPS/main losses and site auxiliaries dissipate outside the hall. The
    cooling plant sits outside the UPS branch. UPS protects IT only, not cooling.
    Power ratios are instantaneous, not measured annual PUE. Unmet cooling is
    reported rather than silently resizing the plant or claiming serviceability.
    """
    finite("it_kw", it_kw)
    finite("auxiliary_kw", auxiliary_kw)
    for name, value in (
        ("downstream_efficiency", downstream_efficiency),
        ("ups_efficiency", ups_efficiency),
        ("main_efficiency", main_efficiency),
    ):
        fraction(name, value, positive=True)
    ups_output = it_kw / downstream_efficiency
    ups_input = ups_output / ups_efficiency
    cooled = plant.evaluate(ups_output, ambient_c)
    before_main = ups_input + cooled.electric_kw + auxiliary_kw
    meter = before_main / main_efficiency
    return {
        "it_kw": it_kw,
        "distribution_loss_kw": ups_output - it_kw,
        "ups_output_kw": ups_output,
        "ups_input_kw": ups_input,
        "ups_loss_kw": ups_input - ups_output,
        "hall_heat_kw": ups_output,
        "liquid_heat_kw": cooled.liquid_heat_kw,
        "air_heat_kw": cooled.air_heat_kw,
        "cooling_kw": cooled.electric_kw,
        "compressor_kw": cooled.compressor_kw,
        "cooling_auxiliary_kw": cooled.auxiliaries_kw,
        "rejected_heat_kw": cooled.rejected_heat_kw,
        "unmet_heat_kw": cooled.unmet_heat_kw,
        "liquid_flow_kg_s": cooled.liquid_flow_kg_s,
        "air_flow_m3_s": cooled.air_flow_m3_s,
        "auxiliary_kw": auxiliary_kw,
        "main_loss_kw": meter - before_main,
        "facility_kw": meter,
        "instantaneous_pue": meter / it_kw if it_kw else float("nan"),
    }
