"""Annual facility electricity, gas burn and fuel-price exposure at leased sites."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class GasSite:
    """One site's capacity bounds, supply classification and attribution factors.

    The regional fraction applies to imported electricity. The study fraction
    and CO2e factor apply to the whole site's electricity under the source
    study's dispatch assumptions.
    """

    name: str
    low_it_mw: float
    high_it_mw: float
    onsite_gas: bool
    regional_grid_gas_fraction: float
    study_gas_fraction: float
    study_co2e_lb_per_mwh: float
    speculative_attribution: bool = False

    def __post_init__(self) -> None:
        finite("low_it_mw", self.low_it_mw)
        finite("high_it_mw", self.high_it_mw, minimum=self.low_it_mw)
        fraction("regional_grid_gas_fraction", self.regional_grid_gas_fraction)
        fraction("study_gas_fraction", self.study_gas_fraction)
        finite("study_co2e_lb_per_mwh", self.study_co2e_lb_per_mwh)
        if self.onsite_gas and self.study_gas_fraction != 1:
            raise ValueError("an exclusively on-site gas supply requires a study gas fraction of 1")


def annual_gas_exposure(
    sites: Sequence[GasSite],
    *,
    capacity: Literal["low", "high"] = "high",
    it_load_fraction: float = 0.70,
    pue: float = 1.15,
    onsite_heat_rate_mmbtu_per_mwh: float = 9.0,
    grid_heat_rate_mmbtu_per_mwh: float = 7.754,
    onsite_price_usd_per_mmbtu: float = 4.0,
) -> pd.DataFrame:
    """Return site-level flows for an 8,760-hour year at constant average IT load.

    All sites share the load fraction and PUE. Each site runs either entirely
    on gas behind the meter or entirely on grid imports. The regional and study
    columns are alternative allocations of the same grid imports. Both heat
    rates use higher heating value. Only on-site fuel incurs a direct charge
    under the scenario's full commodity pass-through assumption.
    """
    if capacity not in ("low", "high"):
        raise ValueError("capacity must be 'low' or 'high'")
    if not sites or len({site.name for site in sites}) != len(sites):
        raise ValueError("provide at least one site and a unique name for each site")
    fraction("it_load_fraction", it_load_fraction)
    finite("pue", pue, minimum=1)
    finite("onsite_heat_rate_mmbtu_per_mwh", onsite_heat_rate_mmbtu_per_mwh, strict=True)
    finite("grid_heat_rate_mmbtu_per_mwh", grid_heat_rate_mmbtu_per_mwh, strict=True)
    finite("onsite_price_usd_per_mmbtu", onsite_price_usd_per_mmbtu)

    rows = []
    for site in sites:
        it_mw = site.low_it_mw if capacity == "low" else site.high_it_mw
        it_mwh = it_mw * it_load_fraction * 8760
        facility_mwh = it_mwh * pue
        onsite_mwh = facility_mwh if site.onsite_gas else 0.0
        grid_mwh = facility_mwh - onsite_mwh
        regional_grid_gas = grid_mwh * site.regional_grid_gas_fraction
        study_grid_gas = grid_mwh * site.study_gas_fraction
        onsite_fuel = onsite_mwh * onsite_heat_rate_mmbtu_per_mwh
        rows.append(
            {
                "site": site.name,
                "it_capacity_mw": it_mw,
                "it_mwh": it_mwh,
                "facility_mwh": facility_mwh,
                "onsite_gas_mwh": onsite_mwh,
                "grid_mwh": grid_mwh,
                "regional_grid_gas_mwh": regional_grid_gas,
                "study_grid_gas_mwh": study_grid_gas,
                "onsite_fuel_mmbtu": onsite_fuel,
                "regional_grid_fuel_mmbtu": regional_grid_gas * grid_heat_rate_mmbtu_per_mwh,
                "study_grid_fuel_mmbtu": study_grid_gas * grid_heat_rate_mmbtu_per_mwh,
                "onsite_fuel_cost_usd": onsite_fuel * onsite_price_usd_per_mmbtu,
                "study_co2e_tonnes": facility_mwh * site.study_co2e_lb_per_mwh * 0.00045359237,
            }
        )
    return pd.DataFrame(rows).set_index("site")
