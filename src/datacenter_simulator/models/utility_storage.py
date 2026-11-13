"""Reported project metadata and separate off-site storage simulation inputs."""

from dataclasses import dataclass
from math import sqrt

from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class FaradayProjectMetadata:
    """Reported project facts; unknown operating values stay None, not scenario defaults.

    Source IDs resolve in data/faraday_sources.json. Area, construction duration,
    future expansion and property-tax expectations retain their reported qualifiers.
    The source's solar capacity basis and contract energy measurement boundary
    are unresolved; numerical interpretations belong in FaradayInputs/SCOPE.
    """

    project_name: str = "Faraday BESS"
    owner_operator: str = "Lydian Energy"
    battery_location: str = "Utah County, Utah, USA"
    customer: str = "Meta"
    data_center: str = "Eagle Mountain data center"
    utility_counterparty: str = "PacifiCorp"
    utility_utah_unit: str = "Rocky Mountain Power"
    tariff_schedule: int = 34
    operating_status: str = "commercial operation"
    commercial_operation_date: str = "2026-09-18"
    configuration: str = "standalone"
    chemistry: str = "LFP"
    battery_power_mw: float = 150
    contracted_storage_mwh: float = 600
    reported_duration_hours: float = 4
    adjacent_solar_name: str = "Faraday solar plant"
    adjacent_solar_reported_mw: float = 525
    solar_capacity_ac_dc_basis: str | None = None
    shared_substation_and_interconnection: bool = True
    approximate_battery_area_acres: float = 8
    approximate_mobilization_to_operation_months: float = 10
    projected_lifetime_property_tax_usd: float = 9_000_000
    proposed_phase2_max_mw: float = 375
    proposed_phase2_max_mwh: float = 1500
    proposed_phase2_target: str = "Q4 2028"
    proposed_phase2_status: str = "in development"
    earlier_reported_phase1_mwh: float = 733
    earlier_energy_rating_reconciliation: str | None = None
    portfolio_financing_usd: float = 689_000_000
    financing_scope: str = "Faraday BESS, AC Ranch 1 and Yellow Viking; not BESS-only CAPEX"
    actual_data_center_it_mw: float | None = None
    actual_data_center_facility_mw: float | None = None
    actual_data_center_pue: float | None = None
    actual_poi_export_limit_mw: float | None = None
    actual_solar_allocation_fraction: float | None = None
    actual_battery_round_trip_efficiency: float | None = None
    news_publication_date: str = "2026-11-12"
    facts_checked_on: str = "2026-11-13"
    source_ids: tuple[str, ...] = (
        "lydian_cod_2026_11_10",
        "lydian_financing_2026_02_17",
        "meta_eagle_mountain_2026_09_14",
        "rmp_schedule34",
        "user_supplied_news",
    )


REPORTED_FARADAY = FaradayProjectMetadata()


def contracted_storage(
    power_mw: float, deliverable_mwh: float, round_trip_efficiency: float = 0.9
) -> Battery:
    """Map an AC deliverable energy window to the existing internal-energy model.

    The internal window is E_AC / eta_discharge. It is NOT installed cell
    nameplate capacity. A full window delivers E_AC, avoiding a second derating
    of a contracted AC rating. The initial usable window is empty.
    """
    finite("power_mw", power_mw, strict=True)
    finite("deliverable_mwh", deliverable_mwh, strict=True)
    fraction("round_trip_efficiency", round_trip_efficiency, positive=True)
    eta = sqrt(round_trip_efficiency)
    return Battery(
        capacity_kwh=deliverable_mwh * 1000 / eta,
        max_charge_kw=power_mw * 1000,
        max_discharge_kw=power_mw * 1000,
        charge_efficiency=eta,
        discharge_efficiency=eta,
        minimum_soc=0,
        maximum_soc=1,
        initial_soc=0,
    )


@dataclass(frozen=True)
class FaradayInputs:
    """Synthetic demand/resource assumptions, distinct from reported asset facts.

    The reported 525 MW solar figure has no verified AC/DC basis. Treating it
    as an available AC peak and allocating it all to this study are assumptions.
    PUE is a constant multiplier including all facility overhead in this screen.
    """

    hours: int = 168
    it_mw: float = 160
    pue: float = 1.25
    solar_ac_peak_mw: float = REPORTED_FARADAY.adjacent_solar_reported_mw
    poi_export_mw: float = 525
    round_trip_efficiency: float = 0.9

    def __post_init__(self) -> None:
        if isinstance(self.hours, bool) or not isinstance(self.hours, int) or self.hours < 1:
            raise ValueError("hours must be a positive integer")
        finite("it_mw", self.it_mw, strict=True)
        finite("pue", self.pue, minimum=1)
        finite("solar_ac_peak_mw", self.solar_ac_peak_mw)
        finite("poi_export_mw", self.poi_export_mw)
        fraction("round_trip_efficiency", self.round_trip_efficiency, positive=True)
