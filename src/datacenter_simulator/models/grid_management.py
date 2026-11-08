"""Campus supply models; power in kW, energy in kWh, money in declared currency."""

from dataclasses import dataclass

import pandas as pd

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class Generator:
    """Dispatchable block at a declared pre-capture electrical boundary.

    ``delivery_factor`` and ``capture_auxiliary_fraction`` reduce usable output.
    Heat rate uses HHV MMBtu per pre-capture kWh; emissions use kg/MMBtu.
    Capture availability is an annual-weighted accounting factor, not a sampled outage.
    Fuel groups identify shared supply failures. These are not unit-commitment models.
    """

    id: str
    capacity_kw: float
    fuel_group: str = ""
    heat_rate_mmbtu_per_kwh: float = 0.006
    fuel_price_per_mmbtu: float = 4.0
    variable_om_per_kwh: float = 0.01
    fuel_carbon_kg_per_mmbtu: float = 52.91
    capture_fraction: float = 0.0
    capture_availability: float = 1.0
    capture_auxiliary_fraction: float = 0.0
    capture_cost_per_tonne: float = 0.0
    delivery_factor: float = 1.0
    ramp_kw_per_hour: float | None = None
    initial_output_kw: float = 0.0
    commissioned_at: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("generator id must be nonempty")
        for name in (
            "capacity_kw",
            "heat_rate_mmbtu_per_kwh",
            "fuel_price_per_mmbtu",
            "variable_om_per_kwh",
            "fuel_carbon_kg_per_mmbtu",
            "capture_cost_per_tonne",
            "initial_output_kw",
        ):
            finite(name, getattr(self, name))
        for name in ("capture_fraction", "capture_availability", "capture_auxiliary_fraction"):
            fraction(name, getattr(self, name))
        fraction("delivery_factor", self.delivery_factor, positive=True)
        if self.capture_auxiliary_fraction >= 1:
            raise ValueError("capture auxiliaries must leave positive net output")
        if self.ramp_kw_per_hour is not None:
            finite("ramp_kw_per_hour", self.ramp_kw_per_hour, strict=True)
        if self.initial_output_kw > self.net_capacity_kw:
            raise ValueError("initial output exceeds net capacity")
        if self.commissioned_at is not None and (
            pd.isna(self.commissioned_at) or self.commissioned_at.tzinfo is None
        ):
            raise ValueError("commissioning timestamp must be valid and timezone-aware")

    @property
    def net_capacity_kw(self) -> float:
        return self.capacity_kw * self.delivery_factor * (1 - self.capture_auxiliary_fraction)

    @property
    def raw_carbon_kg_per_kwh(self) -> float:
        return (
            self.heat_rate_mmbtu_per_kwh
            * self.fuel_carbon_kg_per_mmbtu
            / (1 - self.capture_auxiliary_fraction)
        )

    @property
    def captured_kg_per_kwh(self) -> float:
        return self.raw_carbon_kg_per_kwh * self.capture_fraction * self.capture_availability

    @property
    def residual_kg_per_kwh(self) -> float:
        return self.raw_carbon_kg_per_kwh - self.captured_kg_per_kwh

    @property
    def marginal_cost_per_kwh(self) -> float:
        return (
            self.heat_rate_mmbtu_per_kwh * self.fuel_price_per_mmbtu + self.variable_om_per_kwh
        ) / (1 - self.capture_auxiliary_fraction) + (
            self.captured_kg_per_kwh * self.capture_cost_per_tonne / 1000
        )


@dataclass(frozen=True)
class SupplyOutage:
    """Half-open [start, end) loss of named assets, fuel groups, and/or grid import."""

    start: pd.Timestamp
    end: pd.Timestamp
    generator_ids: tuple[str, ...] = ()
    fuel_groups: tuple[str, ...] = ()
    grid: bool = False

    def __post_init__(self) -> None:
        if any(pd.isna(t) or t.tzinfo is None for t in (self.start, self.end)):
            raise ValueError("outages require valid timezone-aware timestamps")
        if self.end <= self.start or not (self.generator_ids or self.fuel_groups or self.grid):
            raise ValueError("outage needs a positive interval and at least one target")


@dataclass(frozen=True)
class GridPolicy:
    """Economic priority weights; demand charge applies once to the supplied horizon."""

    carbon_price_per_kg: float = 0.0
    demand_charge_per_kw: float = 0.0
    throughput_cost_per_kwh: float = 0.01
    critical_unserved_cost_per_kwh: float = 10000.0
    flexible_unserved_cost_per_kwh: float = 100.0
    terminal_soc: float | None = None
    require_critical_service: bool = False

    def __post_init__(self) -> None:
        for name in (
            "carbon_price_per_kg",
            "demand_charge_per_kw",
            "throughput_cost_per_kwh",
            "critical_unserved_cost_per_kwh",
            "flexible_unserved_cost_per_kwh",
        ):
            finite(name, getattr(self, name))
        if self.critical_unserved_cost_per_kwh <= self.flexible_unserved_cost_per_kwh:
            raise ValueError("critical load needs a higher unserved-energy penalty")
        if self.terminal_soc is not None:
            fraction("terminal_soc", self.terminal_soc)
