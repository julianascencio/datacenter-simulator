"""Two-branch discounted cash-flow screening; no probability inference."""

from dataclasses import dataclass

from datacenter_simulator.models.development import DevelopmentScenario


@dataclass(frozen=True)
class DevelopmentResult:
    """Branch and expected present values in USD at the decision date."""

    approved_npv_usd: float
    canceled_npv_usd: float
    expected_npv_usd: float
    expected_cancellation_loss_usd: float
    holding_pv_usd: float
    approval_month: int


def evaluate_development(s: DevelopmentScenario) -> DevelopmentResult:
    """Discount monthly holding costs and annual post-approval operating cash flows.

    The entire operating life shifts with approval (no fixed terminal calendar
    date). Construction time is abstracted into permit_months; remaining capex
    is a lump sum. Cancellation receives no operating cash flows or remaining
    capex. Mitigation is paid in both branches and has no automatic risk effect.
    """
    months = s.permit_months + s.delay_months

    def discount(month: int) -> float:
        return (1 + s.annual_discount_rate) ** (-month / 12)

    upfront = s.predevelopment_usd + s.mitigation_usd
    holding = sum(s.monthly_holding_usd * discount(m) for m in range(1, months + 1))
    approved = -upfront - holding - (s.planned_capex_usd - s.predevelopment_usd) * discount(months)
    approved += sum(
        s.annual_operating_cashflow_usd * discount(months + 12 * year)
        for year in range(1, s.operating_years + 1)
    )
    canceled = -upfront - holding + (s.recovery_usd - s.cancellation_exit_usd) * discount(months)
    probability = s.cancellation_probability
    return DevelopmentResult(
        approved,
        canceled,
        (1 - probability) * approved + probability * canceled,
        probability * -canceled,
        holding,
        months,
    )
