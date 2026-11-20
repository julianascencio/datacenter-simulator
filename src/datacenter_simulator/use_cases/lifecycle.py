"""Illustrative independently supplied halls on one campus, all values synthetic."""

from dataclasses import replace

from datacenter_simulator.methods.project_recovery import month_id, month_label
from datacenter_simulator.models.lifecycle import (
    BuildStage,
    Gate,
    LifecyclePlan,
    PowerDelivery,
    ServiceLife,
    StageWork,
    Withdrawal,
)


def reference_hall(name: str = "First hall", start: str = "2027-01") -> LifecyclePlan:
    """An illustrative 12 MW IT hall with its own budget and supply allocation."""

    def due(offset: int) -> str:
        return month_label(month_id(start) + offset)

    return LifecyclePlan(
        name=name,
        start=start,
        works=(
            StageWork(BuildStage.ORIGINATION, 2, 150_000),
            StageWork(BuildStage.SITE, 3, 450_000),
            StageWork(BuildStage.PERMITTING, 6, 900_000, (Gate("Land option", due(5)),)),
            StageWork(
                BuildStage.FINANCING,
                2,
                300_000,
                (Gate("Local planning and cooling-water approval", due(11)),),
            ),
            StageWork(
                BuildStage.DESIGN,
                4,
                4_000_000,
                (Gate("Anchor lease and financing signed", due(13)),),
            ),
            StageWork(
                BuildStage.CONSTRUCTION,
                12,
                83_000_000,
                (Gate("Design release and long-lead equipment order", due(17)),),
            ),
            StageWork(
                BuildStage.COMMISSIONING,
                2,
                1_200_000,
                (Gate("Diverse fiber live", due(28)),),
            ),
        ),
        service=ServiceLife(
            it_mw=12,
            pue=1.25,
            load_factor=0.8,
            ramp_months=4,
            service_months=120,
            refresh_every_months=48,
            refresh_cost_usd=5_000_000,
            refresh_unavailable_fraction=0.25,
            decommission_months=3,
            decommission_cost_usd=1_500_000,
        ),
        stall_cost_usd_per_month=125_000,
        power_deliveries=(PowerDelivery(due(29), 15),),
    )


def expansion_cases() -> dict[str, LifecyclePlan]:
    """Counterfactuals for a second hall. Exactly one joins the first hall in each case."""
    base = reference_hall("Expansion hall", "2028-01")
    pending_permit = replace(
        base.works[3], gates=(Gate("Local planning and cooling-water approval"),)
    )
    withdrawn = replace(
        base,
        works=(*base.works[:3], pending_permit, *base.works[4:]),
        withdrawal=Withdrawal("2029-02", "Sponsor withdrew after planning denial", 250_000),
    )
    return {
        "On time": base,
        "Power six months late": replace(
            base, power_deliveries=(PowerDelivery("2030-06", 9), PowerDelivery("2030-12", 6))
        ),
        "Power unresolved": replace(base, power_deliveries=(PowerDelivery("2030-06", 9),)),
        "Withdrawn": withdrawn,
    }
