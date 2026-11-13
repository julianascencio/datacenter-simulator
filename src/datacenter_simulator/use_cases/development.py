"""Synthetic scenarios inspired by a user-supplied Heatmap excerpt."""

from dataclasses import replace

from datacenter_simulator.models.development import DevelopmentScenario

SOURCE_CONTEXT = {
    "publisher": "Heatmap",
    "author": "Robinson Meyer",
    "date": "2026-10-06",
    "title": "Exclusive: Data Center Cancellations Top $260 Billion in 2026",
    "provenance": (
        "User-supplied excerpt; underlying Heatmap Pro records not independently verified"
    ),
    "reported_canceled_planned_investment_usd_at_least": 260e9,
    "reported_q3_canceled_planned_investment_usd_approximately": 130e9,
    "reported_opposed_planned_investment_usd_approximately": 1e12,
    "reported_investment_disclosure_fraction_approximately": 0.60,
    "reported_canceled_fraction_of_opposed_projects_approximately": 0.50,
    "boundary": "Investment announcements are not realized losses. Conditional project counts "
    "are not dollar-weighted risks or site-level forecasts. No extrapolation for "
    "missing investment disclosures; no legal or moratorium status asserted.",
}


def development_scenarios() -> list[DevelopmentScenario]:
    """Return illustrative alternatives; risk changes are assumptions, not effects."""
    base = DevelopmentScenario(
        name="Baseline",
        planned_capex_usd=500e6,
        predevelopment_usd=20e6,
        mitigation_usd=0,
        cancellation_probability=0.30,
        permit_months=12,
        delay_months=12,
        monthly_holding_usd=250_000,
        cancellation_exit_usd=3e6,
        recovery_usd=5e6,
        annual_operating_cashflow_usd=85e6,
        operating_years=15,
        annual_discount_rate=0.09,
        assumption_basis="All inputs synthetic; no calibration to Heatmap aggregate statistics.",
    )
    return [
        base,
        replace(
            base,
            name="Mitigation assumption",
            mitigation_usd=8e6,
            cancellation_probability=0.20,
            delay_months=6,
        ),
        replace(
            base,
            name="Relocation assumption",
            mitigation_usd=15e6,
            cancellation_probability=0.10,
            delay_months=3,
        ),
        replace(base, name="Mitigation without risk benefit", mitigation_usd=8e6),
    ]
