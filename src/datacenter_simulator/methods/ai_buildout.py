"""Annual site commissioning, accelerator renewal and facility electricity."""

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class ComputePhase:
    """One fleet commissioned together, with like-for-like future replacements.

    package_kw excludes host/network IT. accelerator_usd includes the allocated
    node cost. brownfield_fraction is the share of IT MW with reusable space.
    """

    ready_year: int
    accelerators: int
    package_kw: float
    other_it_kw_per_accelerator: float
    accelerator_usd: float
    life_years: int
    brownfield_fraction: float = 0.0

    def __post_init__(self) -> None:
        for name in ("ready_year", "accelerators", "life_years"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        finite("package_kw", self.package_kw, strict=True)
        finite("other_it_kw_per_accelerator", self.other_it_kw_per_accelerator)
        finite("accelerator_usd", self.accelerator_usd)
        fraction("brownfield_fraction", self.brownfield_fraction)

    @property
    def it_mw(self) -> float:
        return self.accelerators * (self.package_kw + self.other_it_kw_per_accelerator) / 1000


def simulate_buildout(
    phases: Sequence[ComputePhase],
    *,
    start_year: int,
    end_year: int,
    power_ready_year: int,
    pue: float,
    it_load_factor: float,
    construction_usd_per_it_mw: float,
    new_power_fraction: float,
    power_usd_per_kw: float,
) -> pd.DataFrame:
    """Book each phase at the beginning of its first powered year.

    Rows cover the inclusive reporting window. Earlier cohorts carry in their
    load and replacement ages. A grid delay shifts commissioning, purchases and
    renewal clocks together. Output is undiscounted, constant-price USD. Annual
    energy uses a normalized 8760 hours and IT electrical load factor.
    """
    if any(type(y) is not int or y < 1 for y in (start_year, end_year, power_ready_year)):
        raise ValueError("calendar years must be positive integers")
    if end_year < start_year:
        raise ValueError("end_year precedes start_year")
    finite("pue", pue, 1)
    fraction("it_load_factor", it_load_factor)
    fraction("new_power_fraction", new_power_fraction)
    finite("construction_usd_per_it_mw", construction_usd_per_it_mw)
    finite("power_usd_per_kw", power_usd_per_kw)
    rows = []
    for year in range(start_year, end_year + 1):
        installed_it = new_it = greenfield_it = initial = refresh = 0.0
        for phase in phases:
            age = year - max(phase.ready_year, power_ready_year)
            if age < 0:
                continue
            installed_it += phase.it_mw
            purchase_usd = phase.accelerators * phase.accelerator_usd
            if age == 0:
                new_it += phase.it_mw
                greenfield_it += phase.it_mw * (1 - phase.brownfield_fraction)
                initial += purchase_usd
            elif age % phase.life_years == 0:
                refresh += purchase_usd
        facility_mw = installed_it * pue
        construction = greenfield_it * construction_usd_per_it_mw
        new_power_kw = new_it * 1000 * pue * new_power_fraction
        power = new_power_kw * power_usd_per_kw
        rows.append(
            {
                "year": year,
                "commissioned_it_mw": new_it,
                "installed_it_mw": installed_it,
                "facility_design_mw": facility_mw,
                "facility_mwh": facility_mw * it_load_factor * 8760,
                "initial_compute_usd": initial,
                "replacement_compute_usd": refresh,
                "construction_usd": construction,
                "new_power_kw": new_power_kw,
                "power_usd": power,
                "total_capex_usd": initial + refresh + construction + power,
            }
        )
    return pd.DataFrame(rows).set_index("year")
