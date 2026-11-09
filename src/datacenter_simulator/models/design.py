"""Validated inputs for concept-stage facility sizing; powers are electrical kW.

Defaults are illustrative engineering assumptions, not vendor specifications.
IT demand includes networking at the equipment terminals. Growth is a one-time
uplift to peak demand, not an annual growth rate or a CPU utilization factor.
"""

from dataclasses import dataclass
from typing import Literal

from datacenter_simulator.models.devices import finite, fraction

Redundancy = Literal["N", "N+1", "2N"]
CoolingTechnology = Literal["dx", "chilled_water", "rear_door", "direct_to_chip", "immersion"]


@dataclass(frozen=True)
class DesignInputs:
    """Sizing, geometry and operating assumptions for one facility.

    ``module_derating`` applies to UPS, transformers, generators and cooling
    modules. Separate input/output power factors prevent applying IT power
    factor to the whole facility. Redundancy counts cover independent identical
    modules/trains only, without claims about topology or availability.
    """

    it_peak_kw: float = 1000
    growth_fraction: float = 0.25
    rack_limit_kw: float = 30
    redundancy: Redundancy = "N+1"
    cooling: CoolingTechnology = "direct_to_chip"
    design_ambient_c: float = 35
    downstream_efficiency: float = 0.98
    ups_efficiency: float = 0.97
    main_efficiency: float = 0.99
    auxiliary_fraction: float = 0.02
    module_derating: float = 0.9
    ups_module_kw: float = 500
    ups_module_kva: float = 500
    ups_load_power_factor: float = 0.95
    transformer_module_kva: float = 2000
    facility_power_factor: float = 0.95
    generator_module_kw: float = 1500
    generator_module_kva: float = 1875
    cooling_module_kw_th: float = 500
    cooling_margin_fraction: float = 0.1
    ups_autonomy_minutes: float = 10
    battery_inverter_efficiency: float = 0.95
    battery_usable_fraction: float = 0.8
    battery_end_of_life_fraction: float = 0.8
    service_voltage_v: float = 11000
    grid_limit_kw: float = 2000
    racks_per_row: int = 12
    rack_width_m: float = 0.6
    rack_depth_m: float = 1.2
    rack_height_m: float = 2.2
    cold_aisle_m: float = 1.2
    hot_aisle_m: float = 1.0
    perimeter_m: float = 1.5
    support_area_fraction: float = 0.5
    electricity_eur_per_kwh: float = 0.15
    grid_kg_co2e_per_kwh: float = 0.2

    def __post_init__(self) -> None:
        for name in (
            "it_peak_kw",
            "rack_limit_kw",
            "ups_module_kw",
            "ups_module_kva",
            "transformer_module_kva",
            "generator_module_kw",
            "generator_module_kva",
            "cooling_module_kw_th",
            "ups_autonomy_minutes",
            "service_voltage_v",
            "rack_width_m",
            "rack_depth_m",
            "rack_height_m",
            "cold_aisle_m",
            "hot_aisle_m",
            "perimeter_m",
        ):
            finite(name, getattr(self, name), strict=True)
        for name in (
            "growth_fraction",
            "auxiliary_fraction",
            "cooling_margin_fraction",
            "grid_limit_kw",
            "support_area_fraction",
            "electricity_eur_per_kwh",
            "grid_kg_co2e_per_kwh",
        ):
            finite(name, getattr(self, name))
        for name in (
            "downstream_efficiency",
            "ups_efficiency",
            "main_efficiency",
            "module_derating",
            "ups_load_power_factor",
            "facility_power_factor",
            "battery_inverter_efficiency",
            "battery_usable_fraction",
            "battery_end_of_life_fraction",
        ):
            fraction(name, getattr(self, name), positive=True)
        finite("design_ambient_c", self.design_ambient_c, -100)
        if type(self.racks_per_row) is not int or self.racks_per_row < 1:
            raise ValueError("racks_per_row must be a positive integer")
        if self.redundancy not in {"N", "N+1", "2N"}:
            raise ValueError("redundancy must be N, N+1 or 2N")
        if self.cooling not in {"dx", "chilled_water", "rear_door", "direct_to_chip", "immersion"}:
            raise ValueError("unknown cooling technology")


@dataclass(frozen=True)
class OperatingBin:
    """Hours at a fraction of future design IT demand and outdoor temperature.

    Fractions describe electrical demand, not compute utilization. Bins must
    total 8760 h for the annual study; no time sequence or dispatch is implied.
    """

    hours: float
    load_fraction: float
    ambient_c: float

    def __post_init__(self) -> None:
        finite("hours", self.hours, strict=True)
        fraction("load_fraction", self.load_fraction, positive=True)
        finite("ambient_c", self.ambient_c, -100)
