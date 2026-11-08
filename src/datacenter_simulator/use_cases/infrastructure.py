"""Editable, deliberately synthetic 20 MW IT equipment-content example."""

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from datacenter_simulator.methods.cooling import CoolingPlant
from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.infrastructure import CostItem


@dataclass(frozen=True)
class InfrastructureCase:
    """Planning assumptions invented for the tutorial, not inferred from the image.

    IT MW includes servers and networking; rack density is a total IT envelope.
    Cooling auxiliaries are already included by CoolingPlant. UPS/main losses
    and site auxiliary heat are assumed outside the conditioned hall.
    """

    it_mw: float = 20
    rack_kw: float = 100
    network_power_fraction: float = 0.04
    liquid_heat_fraction: float = 0.85
    design_ambient_c: float = 35
    cooling_margin_fraction: float = 0.15
    mechanical_cop: float = 6
    residual_air_cop: float = 3.2
    downstream_efficiency: float = 0.98
    ups_efficiency: float = 0.97
    main_efficiency: float = 0.99
    auxiliary_fraction_of_it_rating: float = 0.01
    ups_autonomy_minutes: float = 10
    battery_inverter_efficiency: float = 0.95
    battery_usable_fraction: float = 0.8
    battery_end_of_life_fraction: float = 0.8
    load_power_factor: float = 0.95
    electricity_usd_per_kwh: float = 0.10

    def __post_init__(self) -> None:
        for name in (
            "it_mw",
            "rack_kw",
            "mechanical_cop",
            "residual_air_cop",
            "ups_autonomy_minutes",
        ):
            finite(name, getattr(self, name), strict=True)
        for name in (
            "network_power_fraction",
            "liquid_heat_fraction",
            "cooling_margin_fraction",
            "auxiliary_fraction_of_it_rating",
        ):
            fraction(name, getattr(self, name))
        for name in (
            "downstream_efficiency",
            "ups_efficiency",
            "main_efficiency",
            "battery_inverter_efficiency",
            "battery_usable_fraction",
            "battery_end_of_life_fraction",
            "load_power_factor",
        ):
            fraction(name, getattr(self, name), positive=True)
        finite("design_ambient_c", self.design_ambient_c, -30)
        finite("electricity_usd_per_kwh", self.electricity_usd_per_kwh)

    def cooling_plant(self) -> CoolingPlant:
        """Use the existing mechanical air/liquid model with economizer disabled.

        Capacity is sized for hall heat plus margin, not the facility meter MW.
        No vendor curve, water consumption or weather-year performance is claimed.
        """
        return CoolingPlant(
            name="Synthetic mechanical air + liquid cooling",
            capacity_kw=self.it_mw
            * 1000
            / self.downstream_efficiency
            * (1 + self.cooling_margin_fraction),
            # CoolingPlant uses its main COP for an air-only plant. Preserve the
            # same air-path COP at the zero-liquid endpoint of the sensitivity.
            cop=self.residual_air_cop if self.liquid_heat_fraction == 0 else self.mechanical_cop,
            liquid_fraction=self.liquid_heat_fraction,
            economizer=False,
            fan_fraction=0.015,
            pump_fraction=0.01,
            residual_air_cop=self.residual_air_cop,
        )


def infrastructure_evidence() -> dict[str, Any]:
    """Fresh packaged source transcription and verification/exclusion annotations."""
    result: dict[str, Any] = json.loads(
        files("datacenter_simulator")
        .joinpath("data/infrastructure_content_2026.json")
        .read_text(encoding="utf-8")
    )
    return result


def infrastructure_cost_items() -> tuple[CostItem, ...]:
    """The twelve image rates; do not treat this as a validated cost database."""
    return tuple(CostItem(**row) for row in infrastructure_evidence()["items"])
