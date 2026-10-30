"""Single-phase rack branches, variable-speed pumps and a finite-UA CDU."""

from dataclasses import dataclass
from math import exp, log10, pi

import pandas as pd
from scipy.optimize import brentq

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class Fluid:
    density_kg_m3: float = 997
    cp_kj_kgk: float = 4.18
    viscosity_pa_s: float = 0.00089

    def __post_init__(self) -> None:
        for name in ("density_kg_m3", "cp_kj_kgk", "viscosity_pa_s"):
            finite(name, getattr(self, name), strict=True)


DEFAULT_FLUID = Fluid()


@dataclass(frozen=True)
class Pipe:
    """Total supply+return length; Darcy-Weisbach with laminar/Swamee-Jain friction."""

    length_m: float
    diameter_m: float
    roughness_m: float = 1.5e-6
    minor_loss_k: float = 0

    def __post_init__(self) -> None:
        for name in ("length_m", "diameter_m"):
            finite(name, getattr(self, name), strict=True)
        for name in ("roughness_m", "minor_loss_k"):
            finite(name, getattr(self, name))
        if self.roughness_m >= self.diameter_m:
            raise ValueError("roughness must be smaller than diameter")

    def pressure_drop_pa(self, flow_l_s: float, fluid: Fluid = DEFAULT_FLUID) -> float:
        finite("flow_l_s", flow_l_s)
        if flow_l_s == 0:
            return 0.0
        velocity = flow_l_s / 1000 / (pi * self.diameter_m**2 / 4)
        reynolds = fluid.density_kg_m3 * velocity * self.diameter_m / fluid.viscosity_pa_s
        laminar = 64 / reynolds
        turbulent = (
            0.25 / log10(self.roughness_m / (3.7 * self.diameter_m) + 5.74 / reynolds**0.9) ** 2
        )
        blend = max(0.0, min(1.0, (reynolds - 2300) / 1700))
        friction = (1 - blend) * laminar + blend * turbulent
        return (friction * self.length_m / self.diameter_m + self.minor_loss_k) * (
            fluid.density_kg_m3 * velocity**2 / 2
        )


@dataclass(frozen=True)
class CoolingBranch:
    """Rack branch: pipe plus cold-plate/valve Δp=k·flow², with k in Pa/(L/s)²."""

    id: str
    pipe: Pipe
    resistance_pa_per_l_s2: float
    heat_kw: float
    thermal_resistance_k_kw: float = 0.05
    maximum_component_c: float = 85

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("branch needs an equipment id")
        for name in ("resistance_pa_per_l_s2", "heat_kw", "thermal_resistance_k_kw"):
            finite(name, getattr(self, name))
        finite("maximum_component_c", self.maximum_component_c, -50)

    def pressure_drop_pa(self, flow_l_s: float, fluid: Fluid) -> float:
        return (
            self.pipe.pressure_drop_pa(flow_l_s, fluid) + self.resistance_pa_per_l_s2 * flow_l_s**2
        )

    def flow_l_s(self, head_pa: float, fluid: Fluid) -> float:
        if head_pa <= 0:
            return 0.0
        high = 1.0
        while self.pressure_drop_pa(high, fluid) < head_pa:
            high *= 2
        return float(brentq(lambda q: self.pressure_drop_pa(q, fluid) - head_pa, 0, high))


@dataclass(frozen=True)
class Pump:
    """Head = shutoff·speed² - curve·(total_flow/parallel_units)²."""

    shutoff_pa: float = 150000
    curve_pa_per_l_s2: float = 2500
    efficiency: float = 0.65
    parallel_units: int = 1

    def __post_init__(self) -> None:
        for name in ("shutoff_pa", "curve_pa_per_l_s2"):
            finite(name, getattr(self, name), strict=True)
        fraction("efficiency", self.efficiency, positive=True)
        if not isinstance(self.parallel_units, int) or self.parallel_units < 1:
            raise ValueError("parallel_units must be a positive integer")

    def head_pa(self, flow_l_s: float, speed: float) -> float:
        finite("flow_l_s", flow_l_s)
        fraction("speed", speed)
        return max(
            0.0,
            self.shutoff_pa * speed**2
            - self.curve_pa_per_l_s2 * (flow_l_s / self.parallel_units) ** 2,
        )


def counterflow_effectiveness(
    ua_kw_k: float, hot_capacity_kw_k: float, cold_capacity_kw_k: float
) -> float:
    """Counterflow ε-NTU effectiveness, including the equal-capacity limit."""
    for name, value in (
        ("UA", ua_kw_k),
        ("hot capacity", hot_capacity_kw_k),
        ("cold capacity", cold_capacity_kw_k),
    ):
        finite(name, value)
    cmin, cmax = (
        min(hot_capacity_kw_k, cold_capacity_kw_k),
        max(hot_capacity_kw_k, cold_capacity_kw_k),
    )
    if cmin == 0 or ua_kw_k == 0:
        return 0.0
    ratio, ntu = cmin / cmax, ua_kw_k / cmin
    if abs(ratio - 1) < 1e-9:
        return ntu / (1 + ntu)
    exponent = exp(-ntu * (1 - ratio))
    return (1 - exponent) / (1 - ratio * exponent)


@dataclass
class CDUResult:
    branches: pd.DataFrame
    flow_l_s: float
    head_pa: float
    pump_kw: float
    heat_removed_kw: float
    unmet_heat_kw: float
    rejected_heat_kw: float
    secondary_supply_c: float
    secondary_return_c: float
    primary_return_c: float
    effectiveness: float
    warnings: tuple[str, ...]


def solve_cdu(
    branches: list[CoolingBranch],
    pump: Pump,
    *,
    speed: float = 1,
    primary_supply_c: float = 25,
    primary_flow_kg_s: float = 10,
    ua_kw_k: float = 50,
    maximum_return_c: float = 55,
    fluid: Fluid = DEFAULT_FLUID,
    failed_branches: frozenset[str] = frozenset(),
) -> CDUResult:
    """Solve parallel branch hydraulics then a finite-UA secondary/primary balance.

    Pump electricity enters the secondary coolant as heat. Removal is limited by
    return-temperature capacity; unattainable component temperatures remain flags.
    Blocked branches have zero flow and all their heat is unmet. No two-phase physics.
    """
    ids = [b.id for b in branches]
    if not branches or len(set(ids)) != len(ids) or failed_branches - set(ids):
        raise ValueError("branches must be unique and failures must refer to known branches")
    fraction("speed", speed)
    finite("primary_supply_c", primary_supply_c, -30)
    finite("maximum_return_c", maximum_return_c, primary_supply_c, strict=True)
    finite("primary_flow_kg_s", primary_flow_kg_s, strict=True)
    finite("ua_kw_k", ua_kw_k, strict=True)
    active = [b for b in branches if b.id not in failed_branches]

    def flows(head: float) -> dict[str, float]:
        return {b.id: b.flow_l_s(head, fluid) for b in active}

    head = (
        0.0
        if not active or speed == 0
        else float(
            brentq(
                lambda h: h - pump.head_pa(sum(flows(h).values()), speed),
                0,
                pump.shutoff_pa * speed**2,
            )
        )
    )
    rates = flows(head)
    total = sum(rates.values())
    pump_kw = head * total / 1e6 / pump.efficiency
    secondary_capacity = total / 1000 * fluid.density_kg_m3 * fluid.cp_kj_kgk
    primary_capacity = primary_flow_kg_s * fluid.cp_kj_kgk
    effectiveness = counterflow_effectiveness(ua_kw_k, secondary_capacity, primary_capacity)
    conductance = effectiveness * min(secondary_capacity, primary_capacity)
    available = max(0.0, conductance * (maximum_return_c - primary_supply_c) - pump_kw)
    requested = sum(b.heat_kw for b in active)
    removed = min(requested, available)
    ratio = removed / requested if requested else 1.0
    rejected = removed + pump_kw
    secondary_return = (
        primary_supply_c + rejected / conductance if conductance else primary_supply_c
    )
    secondary_supply = (
        secondary_return - rejected / secondary_capacity if secondary_capacity else primary_supply_c
    )
    primary_return = primary_supply_c + rejected / primary_capacity
    rows, warnings = [], []
    for b in branches:
        flow = rates.get(b.id, 0.0)
        heat = b.heat_kw * ratio if flow else 0.0
        capacity = flow / 1000 * fluid.density_kg_m3 * fluid.cp_kj_kgk
        outlet = secondary_supply + heat / capacity if capacity else float("nan")
        component = (
            (secondary_supply + (outlet - secondary_supply) / 2 + heat * b.thermal_resistance_k_kw)
            if capacity
            else float("nan")
        )
        if heat < b.heat_kw - 1e-8:
            warnings.append(f"unmet heat: {b.id}")
        if component > b.maximum_component_c:
            warnings.append(f"component overtemperature: {b.id}")
        rows.append(
            {
                "equipment_id": b.id,
                "flow_l_s": flow,
                "pressure_drop_pa": head if flow else 0,
                "heat_removed_kw": heat,
                "unmet_heat_kw": b.heat_kw - heat,
                "outlet_c": outlet,
                "component_c": component,
            }
        )
    return CDUResult(
        pd.DataFrame(rows).set_index("equipment_id"),
        total,
        head,
        pump_kw,
        removed,
        sum(b.heat_kw for b in branches) - removed,
        rejected,
        secondary_supply,
        secondary_return,
        primary_return,
        effectiveness,
        tuple(warnings),
    )
