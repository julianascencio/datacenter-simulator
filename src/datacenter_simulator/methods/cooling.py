"""Transparent lumped cooling alternatives; coefficients are illustrative, configurable."""

from dataclasses import dataclass
from math import exp

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class CoolingResult:
    heat_removed_kw: float
    unmet_heat_kw: float
    electric_kw: float
    compressor_kw: float
    auxiliaries_kw: float
    rejected_heat_kw: float
    liquid_heat_kw: float
    air_heat_kw: float
    liquid_flow_kg_s: float
    air_flow_m3_s: float
    economizer_active: bool
    effective_cop: float


@dataclass(frozen=True)
class CoolingPlant:
    """Aggregate heat-removal model with a liquid loop and residual air cooling.

    COP is mechanical cooling COP at 30°C outdoors, excluding fan/pump auxiliaries.
    Capacity is thermal kW; parasitics are fractions of rated thermal capacity.
    Economizer is an idealized dry cooler with an approach temperature (no water use).
    """

    name: str
    capacity_kw: float
    cop: float
    liquid_fraction: float = 0
    supply_c: float = 18
    approach_k: float = 5
    economizer: bool = False
    fan_fraction: float = 0.035
    pump_fraction: float = 0.01
    liquid_delta_k: float = 10
    air_delta_k: float = 12
    residual_air_cop: float = 3.2
    cop_ambient_slope: float = 0.02
    coolant_cp_kj_kgk: float = 4.18

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("cooling plant needs a name")
        for name in (
            "capacity_kw",
            "cop",
            "liquid_delta_k",
            "air_delta_k",
            "residual_air_cop",
            "coolant_cp_kj_kgk",
        ):
            finite(name, getattr(self, name), strict=True)
        for name in ("approach_k", "fan_fraction", "pump_fraction", "cop_ambient_slope"):
            finite(name, getattr(self, name))
        finite("supply_c", self.supply_c, -100)
        fraction("liquid_fraction", self.liquid_fraction)
        if self.economizer and self.liquid_fraction == 0:
            raise ValueError("dry-cooler economizer requires a liquid circuit")

    def evaluate(self, heat_kw: float, ambient_c: float) -> CoolingResult:
        finite("heat_kw", heat_kw)
        finite("ambient_c", ambient_c, -100)
        removed = min(heat_kw, self.capacity_kw)
        liquid = removed * self.liquid_fraction
        air = removed - liquid
        free = bool(self.economizer and ambient_c + self.approach_k <= self.supply_c)
        adjustment = max(0.25, 1 - self.cop_ambient_slope * (ambient_c - 30))
        mechanical_cop = max(1.0, self.cop * adjustment)
        air_cop = (
            mechanical_cop
            if self.liquid_fraction == 0
            else max(1.0, self.residual_air_cop * adjustment)
        )
        compressor = (0 if free else liquid / mechanical_cop) + air / air_cop
        # Cubic affinity law plus a 20% auxiliary floor while operating.
        ratio = removed / self.capacity_kw
        auxiliaries = (
            0.0
            if removed == 0
            else self.capacity_kw
            * (self.fan_fraction + self.pump_fraction)
            * (0.2 + 0.8 * ratio**3)
        )
        electric = compressor + auxiliaries
        return CoolingResult(
            removed,
            heat_kw - removed,
            electric,
            compressor,
            auxiliaries,
            removed + electric,
            liquid,
            air,
            liquid / (self.coolant_cp_kj_kgk * self.liquid_delta_k),
            air / (1.2 * 1.006 * self.air_delta_k),
            free and liquid > 0,
            removed / electric if electric else float("nan"),
        )


def cooling_alternatives(capacity_kw: float = 500) -> dict[str, CoolingPlant]:
    """Uncalibrated comparison presets; these are not vendor specifications.

    Liquid fractions include facility-level capture (CRAH coil for chilled water).
    Immersion uses an illustrative dielectric-fluid cp, not water's heat capacity.
    """
    return {
        "dx": CoolingPlant("DX / CRAC", capacity_kw, 3.2, fan_fraction=0.045, pump_fraction=0),
        "chilled_water": CoolingPlant(
            "Chilled water / CRAH", capacity_kw, 5.5, 1, 18, economizer=True, fan_fraction=0.035
        ),
        "rear_door": CoolingPlant(
            "Rear-door heat exchanger",
            capacity_kw,
            5.5,
            0.75,
            24,
            economizer=True,
            fan_fraction=0.025,
        ),
        "direct_to_chip": CoolingPlant(
            "Direct-to-chip + CDU", capacity_kw, 6, 0.85, 35, economizer=True, fan_fraction=0.015
        ),
        "immersion": CoolingPlant(
            "Single-phase immersion",
            capacity_kw,
            6.5,
            0.98,
            40,
            economizer=True,
            fan_fraction=0.008,
            pump_fraction=0.015,
            coolant_cp_kj_kgk=2.0,
        ),
    }


@dataclass(frozen=True)
class ThermalZone:
    """Single well-mixed thermal mass; does not predict rack hotspots or airflow."""

    capacitance_kj_k: float = 100_000
    conductance_kw_k: float = 0.5

    def __post_init__(self) -> None:
        finite("capacitance_kj_k", self.capacitance_kj_k, strict=True)
        finite("conductance_kw_k", self.conductance_kw_k)

    def advance(
        self,
        temperature_c: float,
        ambient_c: float,
        internal_heat_kw: float,
        removed_heat_kw: float,
        dt_hours: float,
    ) -> float:
        for name, val in (("temperature_c", temperature_c), ("ambient_c", ambient_c)):
            finite(name, val, -100)
        finite("internal_heat_kw", internal_heat_kw)
        finite("removed_heat_kw", removed_heat_kw)
        finite("dt_hours", dt_hours, strict=True)
        net = internal_heat_kw - removed_heat_kw
        if self.conductance_kw_k == 0:
            return temperature_c + net * dt_hours * 3600 / self.capacitance_kj_k
        equilibrium = ambient_c + net / self.conductance_kw_k
        return equilibrium + (temperature_c - equilibrium) * exp(
            -self.conductance_kw_k * dt_hours * 3600 / self.capacitance_kj_k
        )
