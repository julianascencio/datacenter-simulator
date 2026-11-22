"""Illustrative independently supplied halls on one campus, all values synthetic."""

from dataclasses import replace

from datacenter_simulator.methods.project_recovery import month_id, month_label
from datacenter_simulator.models.lifecycle import (
    BuildStage,
    Cancellation,
    EquipmentDeposit,
    Gate,
    LifecyclePlan,
    PowerDelivery,
    ServiceLife,
    StageWork,
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
            StageWork(BuildStage.POWER, 3, 450_000, (Gate("Land option", due(5)),)),
            StageWork(BuildStage.PERMITTING, 3, 450_000),
            StageWork(
                BuildStage.FINANCING,
                2,
                300_000,
                (Gate("Local planning and cooling-water approval", due(11)),),
            ),
            StageWork(
                BuildStage.DESIGN,
                2,
                1_000_000,
                (
                    Gate("Anchor tenant or owner commitment", due(11)),
                    Gate("Executed power service agreement", due(10)),
                    Gate("Construction financing closed", due(13)),
                ),
            ),
            StageWork(BuildStage.PROCUREMENT, 2, 2_000_000, (Gate("Design release", due(15)),)),
            StageWork(
                BuildStage.CONSTRUCTION,
                12,
                83_000_000,
                (Gate("Long-lead equipment release", due(17)),),
            ),
            StageWork(BuildStage.COMMISSIONING, 1, 700_000, (Gate("Diverse fiber live", due(28)),)),
            StageWork(
                BuildStage.IT_INSTALLATION,
                1,
                48_500_000,
                (
                    Gate("Factory acceptance", due(26)),
                    Gate("Installation inspection", due(28)),
                    Gate("System startup", due(29)),
                    Gate("Functional tests", due(30)),
                    Gate("Integrated systems acceptance", due(30)),
                ),
            ),
        ),
        equipment_deposit=EquipmentDeposit(due(7), 1_000_000),
        service=ServiceLife(
            it_mw=12,
            pue=1.25,
            load_factor=0.8,
            ramp_months=4,
            service_months=192,
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

    def change_gates(stage: BuildStage, gates: tuple[Gate, ...]) -> LifecyclePlan:
        works = tuple(
            replace(work, gates=gates) if work.stage == stage else work for work in base.works
        )
        return replace(base, works=works)

    pending_permit = change_gates(
        BuildStage.FINANCING, (Gate("Local planning and cooling-water approval"),)
    )
    denied = replace(
        pending_permit,
        cancellation=Cancellation("2029-02", "Rezoning denied; project ended", 250_000),
    )
    commercial_hold = change_gates(
        BuildStage.DESIGN,
        (
            Gate("Unconditional tenant commitment"),
            Gate("Executed power service agreement", "2028-11"),
            Gate("Construction financing closed"),
        ),
    )

    def power_case(final_month: str | None) -> LifecyclePlan:
        # Factory/installation checks can precede power. Live system tests require energization.
        next_month = month_label(month_id(final_month) + 1) if final_month else None
        acceptance = (
            *base.works[-1].gates[:2],
            Gate("System startup", final_month),
            Gate("Functional tests", next_month),
            Gate("Integrated systems acceptance", next_month),
        )
        deliveries: tuple[PowerDelivery, ...] = (PowerDelivery("2030-06", 9),)
        if final_month:
            deliveries += (PowerDelivery(final_month, 6),)
        return replace(
            change_gates(BuildStage.IT_INSTALLATION, acceptance), power_deliveries=deliveries
        )

    return {
        "On time": base,
        "Power six months late": power_case("2030-12"),
        "Power unresolved": power_case(None),
        "Tenant and financing unresolved": commercial_hold,
        "Rezoning denied": denied,
    }
