"""Explicit, uncalibrated development-risk scenario inputs (USD, months)."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class DevelopmentScenario:
    """Decision at month zero; cancellation resolved at the permit decision.

    Predevelopment and mitigation are paid now. Remaining capex is paid only
    on approval. Annual operating cash flow is net of operating costs, before
    financing/tax. Delay is additional to the baseline permitting duration.
    """

    name: str
    planned_capex_usd: float
    predevelopment_usd: float
    mitigation_usd: float
    cancellation_probability: float
    permit_months: int
    delay_months: int
    monthly_holding_usd: float
    cancellation_exit_usd: float
    recovery_usd: float
    annual_operating_cashflow_usd: float
    operating_years: int
    annual_discount_rate: float
    assumption_basis: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.assumption_basis.strip():
            raise ValueError("name and assumption_basis are required")
        for key in ("permit_months", "delay_months", "operating_years"):
            value = getattr(self, key)
            if type(value) is not int or value < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
        if self.operating_years == 0:
            raise ValueError("operating_years must be positive")
        for key in (
            "planned_capex_usd",
            "predevelopment_usd",
            "mitigation_usd",
            "monthly_holding_usd",
            "cancellation_exit_usd",
            "recovery_usd",
            "annual_discount_rate",
        ):
            value = getattr(self, key)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        if not isfinite(self.annual_operating_cashflow_usd):
            raise ValueError("cash flow must be finite")
        if (
            not isfinite(self.cancellation_probability)
            or not 0 <= self.cancellation_probability <= 1
        ):
            raise ValueError("cancellation_probability must be in [0, 1]")
        if self.predevelopment_usd > self.planned_capex_usd:
            raise ValueError("predevelopment cannot exceed planned capex")
        if self.recovery_usd > self.predevelopment_usd:
            raise ValueError("recovery cannot exceed predevelopment spending")
