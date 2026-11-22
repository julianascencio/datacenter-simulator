"""November 2026 snapshot of the Better Data Center Project's US site estimates."""

import csv
from importlib.resources import files

from datacenter_simulator.methods.gas_exposure import GasSite


def anthropic_us_sites() -> tuple[GasSite, ...]:
    """Read the 19 US site estimates and regional factors from the packaged snapshot."""
    snapshot = files("datacenter_simulator").joinpath("data/anthropic_us_power_2026_11_19.csv")
    with snapshot.open("r", encoding="utf-8") as stream:
        return tuple(
            GasSite(
                name=row["site"],
                low_it_mw=float(row["capacity_low_mw"]),
                high_it_mw=float(row["capacity_high_mw"]),
                onsite_gas=row["supply"] == "On-site/BTM gas",
                regional_grid_gas_fraction=float(row["regional_gas_pct"]) / 100,
                study_gas_fraction=float(row["study_gas_pct"]) / 100,
                study_co2e_lb_per_mwh=float(row["study_co2e_lb_per_mwh"]),
                speculative_attribution=row["speculative_attribution"] == "true",
            )
            for row in csv.DictReader(stream)
        )
