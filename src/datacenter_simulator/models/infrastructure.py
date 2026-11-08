"""Explicit assumptions for early equipment, capital and UPS screening studies."""

from dataclasses import dataclass
from typing import Literal

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class CostItem:
    """A quoted content rate, not a unit price for an individual machine.

    The selected MW basis applies to every line. Vendor labels are source
    annotations only, never performance specifications or procurement advice.
    """

    id: str
    name: str
    group: Literal["IT", "Infrastructure", "Services"]
    million_usd_per_mw: float
    vendors_as_shown: str
    source_id: str

    def __post_init__(self) -> None:
        if not self.id or not self.name or not self.source_id:
            raise ValueError("cost items require an id, name and provenance")
        if self.group not in {"IT", "Infrastructure", "Services"}:
            raise ValueError("unknown cost group")
        finite("million_usd_per_mw", self.million_usd_per_mw)


@dataclass(frozen=True)
class CapitalScenario:
    """Linear content scaling with an explicit denominator and separate allowances.

    ``facility_mw`` must be a design rating, not average operational demand.
    Contingency applies to the listed subtotal only. Unlisted scope is added
    separately; zero means unpriced, not absent. No automatic redundancy uplift.
    """

    it_mw: float
    facility_mw: float
    mw_basis: Literal["it", "facility"] = "it"
    contingency_fraction: float = 0
    unlisted_scope_usd: float = 0

    def __post_init__(self) -> None:
        finite("it_mw", self.it_mw, strict=True)
        finite("facility_mw", self.facility_mw, self.it_mw)
        if self.mw_basis not in {"it", "facility"}:
            raise ValueError("mw_basis must explicitly be it or facility")
        fraction("contingency_fraction", self.contingency_fraction)
        finite("unlisted_scope_usd", self.unlisted_scope_usd)


@dataclass(frozen=True)
class ModularEquipment:
    """Identical parallel modules, in explicitly declared kW or thermal kW.

    Reserve modules are installed but not needed to meet the design duty. This
    arithmetic is not a reliability probability, Tier certification or A/B design.
    """

    id: str
    rating_kw: float
    reserve_units: int = 1
    derating: float = 1
    domain: Literal["electrical", "thermal"] = "electrical"

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("equipment needs an id")
        finite("rating_kw", self.rating_kw, strict=True)
        fraction("derating", self.derating, positive=True)
        if type(self.reserve_units) is not int or self.reserve_units < 0:
            raise ValueError("reserve_units must be a nonnegative integer")
        if self.domain not in {"electrical", "thermal"}:
            raise ValueError("unknown capacity domain")


@dataclass(frozen=True)
class UPSBattery:
    """Constant-power battery energy approximation at the UPS output boundary.

    The energy reserve, ageing and inverter conversion are separate factors.
    Manufacturer discharge curves, temperature, transfer and recharge dynamics
    are not represented. A common battery bank is not made redundant by N+1 UPSs.
    """

    nominal_kwh: float
    rated_kw: float
    rated_kva: float
    inverter_efficiency: float = 0.95
    usable_fraction: float = 0.8
    end_of_life_fraction: float = 0.8

    def __post_init__(self) -> None:
        for name in ("nominal_kwh", "rated_kw", "rated_kva"):
            finite(name, getattr(self, name), strict=True)
        for name in ("inverter_efficiency", "usable_fraction", "end_of_life_fraction"):
            fraction(name, getattr(self, name), positive=True)

    def runtime_minutes(self, output_kw: float, *, load_power_factor: float = 1) -> float:
        """Reject both kW and kVA overload; return autonomy at a positive load."""
        finite("output_kw", output_kw, strict=True)
        fraction("load_power_factor", load_power_factor, positive=True)
        if output_kw > self.rated_kw or output_kw / load_power_factor > self.rated_kva:
            raise ValueError("UPS load exceeds kW or kVA rating")
        return (
            60
            * self.nominal_kwh
            * self.inverter_efficiency
            * self.usable_fraction
            * self.end_of_life_fraction
            / output_kw
        )
