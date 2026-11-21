"""Calendar-month lifecycle ledger for an independently deliverable data hall."""

from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from itertools import islice, repeat
from math import isclose

import pandas as pd

from datacenter_simulator.methods.project_recovery import hours_in_month, month_label
from datacenter_simulator.models.lifecycle import (
    BuildStage,
    Gate,
    LifecyclePlan,
    ServiceLife,
    calendar_month,
)


@dataclass(frozen=True)
class _Month:
    phase: str
    status: str
    reason: str = ""
    work_usd: float = 0
    holding_usd: float = 0
    deposit_usd: float = 0
    exit_usd: float = 0
    refresh_usd: float = 0
    decommission_usd: float = 0
    commissioned_it_mw: float = 0
    average_it_mw: float = 0


def _power_gate(plan: LifecyclePlan) -> Gate:
    required = plan.service.it_mw * plan.service.pue
    requirement = f"Firm power for commissioning ({required:g} facility MW)"
    allocated = 0.0
    for delivery in plan.power_deliveries or ():
        allocated += delivery.added_facility_mw
        if allocated >= required or isclose(allocated, required, rel_tol=1e-12):
            return Gate(requirement, delivery.month)
    return Gate(requirement)


def _development(plan: LifecyclePlan, start: int) -> Iterator[_Month]:
    month = start
    for work in plan.works:
        requirements = work.gates
        if work.stage == BuildStage.COMMISSIONING and plan.power_deliveries is not None:
            requirements = (*requirements, _power_gate(plan))
        gates = [
            (g.requirement, calendar_month(g.cleared_month) if g.cleared_month else None)
            for g in requirements
        ]
        while blockers := [name for name, date in gates if date is None or date > month]:
            yield _Month(
                work.stage.value,
                "stalled",
                ", ".join(blockers),
                holding_usd=plan.stall_cost_usd_per_month,
            )
            month += 1
        for _ in range(work.months):
            yield _Month(work.stage.value, "active", work_usd=work.budget_usd / work.months)
            month += 1


def _in_service(service: ServiceLife) -> Iterator[_Month]:
    for age in range(service.service_months):
        ramp = (age + 0.5) / service.ramp_months if age < service.ramp_months else 1.0
        interval = service.refresh_every_months
        refresh = interval is not None and age > 0 and age % interval == 0
        availability = 1 - service.refresh_unavailable_fraction if refresh else 1.0
        phase = "ramp-up" if age < service.ramp_months else "operations"
        if refresh:
            phase = "refresh"
        yield _Month(
            phase,
            "in service",
            refresh_usd=service.refresh_cost_usd if refresh else 0,
            commissioned_it_mw=service.it_mw,
            average_it_mw=service.it_mw * service.load_factor * ramp * availability,
        )
    for _ in range(service.decommission_months):
        yield _Month(
            "decommissioning",
            "active",
            decommission_usd=service.decommission_cost_usd / service.decommission_months,
        )
    yield from repeat(_Month("retired", "retired"))


def _timeline(plan: LifecyclePlan, start: int) -> Iterator[_Month]:
    cancellation = plan.cancellation
    decision = calendar_month(cancellation.month) if cancellation else None
    deposit = plan.equipment_deposit
    deposit_due = calendar_month(deposit.month) if deposit else None
    for month, row in enumerate(_development(plan, start), start):
        if cancellation is not None and month == decision:
            yield _Month(
                row.phase, "cancelled", cancellation.reason, exit_usd=cancellation.exit_cost_usd
            )
            yield from repeat(_Month(row.phase, "cancelled", cancellation.reason))
            return
        if deposit is not None and month == deposit_due:
            row = replace(row, deposit_usd=deposit.amount_usd)
            deposit_due = None
        yield row
    if cancellation is not None:
        raise ValueError("cancellation must occur before service begins")
    if deposit_due is not None:
        raise ValueError("equipment deposit must occur before service begins")
    yield from _in_service(plan.service)


def simulate_lifecycle(plan: LifecyclePlan, through: str) -> pd.DataFrame:
    """Emit one row per month from project start through the inclusive reporting cutoff.

    Gates and cancellations are effective at the start of their calendar month.
    A cancellation stops pre-service work immediately, with one exit charge. A
    later cancellation of an already operating block is an inconsistent input.
    Construction and load-bank test energy are outside the facility MWh boundary.
    """
    start, end = calendar_month(plan.start), calendar_month(through)
    if end < start:
        raise ValueError("reporting cutoff precedes project start")
    rows = []
    for month, row in enumerate(islice(_timeline(plan, start), end - start + 1), start):
        it_mwh = row.average_it_mw * hours_in_month(month)
        rows.append(
            {
                "month": month_label(month),
                "project": plan.name,
                "planned_it_mw": plan.service.it_mw,
                **asdict(row),
                "it_mwh": it_mwh,
                "facility_mwh": it_mwh * plan.service.pue,
                "spend_usd": row.work_usd
                + row.deposit_usd
                + row.holding_usd
                + row.exit_usd
                + row.refresh_usd
                + row.decommission_usd,
            }
        )
    return pd.DataFrame(rows)
