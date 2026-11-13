"""Inputs for an off-site storage procurement screen; all powers are AC."""

from dataclasses import dataclass
from math import sqrt

from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.models.devices import finite, fraction


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
    solar_ac_peak_mw: float = 525
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
