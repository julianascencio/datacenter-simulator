"""Explicit contract assumptions for behind-the-meter BESS screening."""

from dataclasses import dataclass

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class BESSValuePolicy:
    """Reserve SOC is held in normal service and released only in outage replay.

    Peak rate applies ONCE to the complete input horizon, not per timestep or
    automatically per month. Wear is an assumed variable cost per AC kWh out.
    """

    grid_limit_kw: float
    reserve_soc: float = 0.1
    peak_eur_per_kw_period: float = 0
    wear_eur_per_kwh: float = 0.012

    def __post_init__(self) -> None:
        for name in ("grid_limit_kw", "peak_eur_per_kw_period", "wear_eur_per_kwh"):
            finite(name, getattr(self, name))
        fraction("reserve_soc", self.reserve_soc)
