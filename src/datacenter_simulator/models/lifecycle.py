"""Inputs for monthly, deterministic data center project lifecycle scenarios."""

from dataclasses import dataclass
from enum import StrEnum

from datacenter_simulator.methods.project_recovery import month_id, month_label
from datacenter_simulator.models.devices import finite, fraction


class BuildStage(StrEnum):
    ORIGINATION = "demand definition"
    SITE = "site diligence"
    POWER = "power contracting"
    PERMITTING = "land entitlement"
    FINANCING = "commercial and financial close"
    DESIGN = "design"
    PROCUREMENT = "long-lead procurement"
    CONSTRUCTION = "construction and fit-out"
    COMMISSIONING = "commissioning"
    IT_INSTALLATION = "IT installation and acceptance"


def calendar_month(value: str) -> int:
    """Read a calendar month in YYYY-MM form."""
    index = month_id(value)
    if month_label(index) != value or not 1 <= index // 12 <= 9999:
        raise ValueError("month must have YYYY-MM format and a positive year")
    return index


def _months(name: str, value: int, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class Gate:
    """Prerequisite for starting a stage. None leaves it unresolved through the horizon."""

    requirement: str
    cleared_month: str | None = None

    def __post_init__(self) -> None:
        if not self.requirement.strip():
            raise ValueError("gate requirement is required")
        if self.cleared_month is not None:
            calendar_month(self.cleared_month)


@dataclass(frozen=True)
class PowerDelivery:
    """Additional firm facility MW allocated permanently to this tranche from a month."""

    month: str
    added_facility_mw: float

    def __post_init__(self) -> None:
        calendar_month(self.month)
        finite("added_facility_mw", self.added_facility_mw, strict=True)


@dataclass(frozen=True)
class StageWork:
    """Consecutive months of work, funded evenly once all entry gates clear."""

    stage: BuildStage
    months: int
    budget_usd: float
    gates: tuple[Gate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stage, BuildStage):
            raise ValueError("stage must be a BuildStage")
        _months("work months", self.months, 1)
        finite("budget_usd", self.budget_usd)


@dataclass(frozen=True)
class EquipmentDeposit:
    """Nonrefundable advance paid before service, excluded from remaining work budgets."""

    month: str
    amount_usd: float

    def __post_init__(self) -> None:
        calendar_month(self.month)
        finite("amount_usd", self.amount_usd, strict=True)


@dataclass(frozen=True)
class Cancellation:
    """Explicit terminal decision before service, effective at the start of a month."""

    month: str
    reason: str
    exit_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        calendar_month(self.month)
        if not self.reason.strip():
            raise ValueError("cancellation reason is required")
        finite("exit_cost_usd", self.exit_cost_usd)


@dataclass(frozen=True)
class ServiceLife:
    """Operating assumptions for one independently commissioned block of IT capacity."""

    it_mw: float
    pue: float
    load_factor: float
    ramp_months: int
    service_months: int
    decommission_months: int
    decommission_cost_usd: float
    refresh_every_months: int | None = None
    refresh_cost_usd: float = 0.0
    refresh_unavailable_fraction: float = 0.0

    def __post_init__(self) -> None:
        finite("it_mw", self.it_mw, strict=True)
        finite("pue", self.pue, 1)
        fraction("load_factor", self.load_factor)
        _months("service_months", self.service_months, 1)
        _months("ramp_months", self.ramp_months)
        _months("decommission_months", self.decommission_months, 1)
        if self.ramp_months > self.service_months:
            raise ValueError("ramp must fit within service life")
        finite("decommission_cost_usd", self.decommission_cost_usd)
        finite("refresh_cost_usd", self.refresh_cost_usd)
        fraction("refresh_unavailable_fraction", self.refresh_unavailable_fraction)
        if self.refresh_every_months is not None:
            _months("refresh_every_months", self.refresh_every_months, 1)
        elif self.refresh_cost_usd or self.refresh_unavailable_fraction:
            raise ValueError("refresh assumptions require a refresh interval")


@dataclass(frozen=True)
class LifecyclePlan:
    """One hall or tranche. Combine distinct, independently supplied tranches for a campus."""

    name: str
    start: str
    works: tuple[StageWork, ...]
    service: ServiceLife
    stall_cost_usd_per_month: float = 0.0
    cancellation: Cancellation | None = None
    power_deliveries: tuple[PowerDelivery, ...] | None = None
    equipment_deposit: EquipmentDeposit | None = None

    def __post_init__(self) -> None:
        start = calendar_month(self.start)
        if not self.name.strip():
            raise ValueError("plan name is required")
        if self.power_deliveries is not None:
            dates = [d.month for d in self.power_deliveries]
            if dates != sorted(set(dates)):
                raise ValueError("power delivery months must be unique and in order")
        if self.equipment_deposit and calendar_month(self.equipment_deposit.month) < start:
            raise ValueError("equipment deposit precedes project start")
        stages = [work.stage for work in self.works]
        if stages != [stage for stage in BuildStage if stage in stages]:
            raise ValueError("build stages must be unique and in lifecycle order")
        if not {BuildStage.CONSTRUCTION, BuildStage.COMMISSIONING} <= set(stages):
            raise ValueError("construction and commissioning are required")
        finite("stall_cost_usd_per_month", self.stall_cost_usd_per_month)
        if self.cancellation is not None and calendar_month(self.cancellation.month) < start:
            raise ValueError("cancellation precedes project start")
