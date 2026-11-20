"""Closed-form spending, energy and date checks for deterministic project paths."""

import json
import sys
from dataclasses import replace

import pandas as pd
import pytest

from datacenter_simulator.analysis.lifecycle import lifecycle_summary, main
from datacenter_simulator.methods.lifecycle import simulate_lifecycle
from datacenter_simulator.models.lifecycle import (
    BuildStage,
    Gate,
    LifecyclePlan,
    PowerDelivery,
    ServiceLife,
    StageWork,
    Withdrawal,
)
from datacenter_simulator.use_cases.lifecycle import expansion_cases, reference_hall


def small_hall():
    return LifecyclePlan(
        "Test",
        "2027-12",
        (StageWork(BuildStage.CONSTRUCTION, 1, 100), StageWork(BuildStage.COMMISSIONING, 1, 20)),
        ServiceLife(10, 1.2, 0.8, 2, 4, 2, 10, 2, 30, 0.25),
        3,
    )


def test_leap_year_ramp_refresh_and_retirement():
    ledger = simulate_lifecycle(small_hall(), "2028-08").set_index("month")
    assert ledger.phase.tolist() == [
        "construction and fit-out",
        "commissioning",
        "ramp-up",
        "ramp-up",
        "refresh",
        "operations",
        "decommissioning",
        "decommissioning",
        "retired",
    ]
    assert ledger.commissioned_it_mw.tolist() == [0, 0, 10, 10, 10, 10, 0, 0, 0]
    assert ledger.average_it_mw.tolist() == [0, 0, 2, 6, 6, 8, 0, 0, 0]
    assert ledger.loc["2028-02", "facility_mwh"] == pytest.approx(2 * 29 * 24 * 1.2)
    assert ledger.spend_usd.tolist() == [100, 20, 0, 0, 30, 0, 5, 5, 0]


def test_parallel_clearances_and_unresolved_gate():
    plan = small_hall()
    gates = (Gate("Firm power", "2028-03"), Gate("Fiber", "2028-02"))
    works = (plan.works[0], replace(plan.works[1], gates=gates))
    frame = simulate_lifecycle(replace(plan, works=works), "2028-04").set_index("month")
    assert frame.reason.tolist() == ["", "Firm power, Fiber", "Firm power", "", ""]
    assert frame.holding_usd.tolist() == [0, 3, 3, 0, 0]
    assert frame.work_usd.tolist() == [100, 0, 0, 20, 0]
    assert frame.loc["2028-04", "status"] == "in service"
    unresolved = replace(works[1], gates=(Gate("Firm power"),))
    frame = simulate_lifecycle(replace(plan, works=(works[0], unresolved)), "2029-12")
    assert frame.iloc[-1].status == "stalled"
    assert frame.holding_usd.sum() == 24 * 3
    assert frame.work_usd.sum() == 100
    assert frame.facility_mwh.sum() == 0
    assert lifecycle_summary(frame)["first_service_month"] is None


def test_mid_construction_withdrawal_stops_work_and_books_exit_once():
    plan = small_hall()
    works = (replace(plan.works[0], months=4), plan.works[1])
    canceled = replace(plan, works=works, withdrawal=Withdrawal("2028-02", "Sponsor exit", 5))
    frame = simulate_lifecycle(canceled, "2029-12")
    assert frame.work_usd.sum() == 50
    assert frame.spend_usd.sum() == 55
    assert frame.facility_mwh.sum() == frame.commissioned_it_mw.sum() == 0
    assert set(frame.iloc[2:].reason) == {"Sponsor exit"}
    assert set(frame.iloc[2:].status) == {"cancelled"}
    pd.testing.assert_frame_equal(frame.iloc[:2], simulate_lifecycle(canceled, "2028-01"))


def test_expansion_counterfactuals_leave_first_hall_independent():
    first = simulate_lifecycle(reference_hall(), "2031-12").set_index("month")
    results = {
        label: simulate_lifecycle(plan, "2031-12") for label, plan in expansion_cases().items()
    }
    on_time, late, stalled, withdrawn = (lifecycle_summary(f) for f in results.values())
    assert on_time["first_service_month"] == "2030-08"
    assert late["first_service_month"] == "2031-02"
    assert late["months_stalled"] == 6
    assert late["spend_usd"] == 90_000_000 + 6 * 125_000
    assert stalled["spend_usd"] == 88_800_000 + 19 * 125_000
    assert withdrawn["spend_usd"] == 1_500_000 + 2 * 125_000 + 250_000
    assert on_time["facility_mwh"] == pytest.approx(131_544)
    assert late["facility_mwh"] == pytest.approx(79_200)
    for label in ("Power unresolved", "Withdrawn"):
        expansion = results[label].set_index("month")
        combined = first.commissioned_it_mw.add(expansion.commissioned_it_mw, fill_value=0)
        pd.testing.assert_series_equal(combined, first.commissioned_it_mw.astype(float))


def test_study_replays_json_and_cutoff(tmp_path, monkeypatch):
    output, replay = tmp_path / "out", tmp_path / "replay"
    monkeypatch.setattr(sys, "argv", ["lifecycle", "--through", "2031-12", "--output", str(output)])
    main()
    monkeypatch.setattr(
        sys, "argv", ["lifecycle", "--inputs", str(output / "inputs.json"), "--output", str(replay)]
    )
    main()
    for name in ("inputs.json", "monthly.csv", "summary.json"):
        assert (output / name).read_bytes() == (replay / name).read_bytes()
    assert json.loads((replay / "summary.json").read_text())["through"] == "2031-12"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ramp_months": 5},
        {"service_months": -1},
        {"it_mw": float("nan")},
        {"refresh_unavailable_fraction": 1.1},
        {"pue": 0.9},
        {"decommission_months": True},
        {"refresh_every_months": None},
    ],
)
def test_invalid_service_inputs(kwargs):
    with pytest.raises(ValueError):
        replace(small_hall().service, **kwargs)


def test_stage_sequence_and_month_boundaries():
    plan = small_hall()
    for works in (plan.works[:1], plan.works[::-1], plan.works + plan.works[1:]):
        with pytest.raises(ValueError):
            replace(plan, works=works)
    for bad_month in ("2028-00", "2028-1", "0000-01", "2027-11"):
        with pytest.raises(ValueError):
            simulate_lifecycle(plan, bad_month)
    with pytest.raises(ValueError, match="before service"):
        simulate_lifecycle(replace(plan, withdrawal=Withdrawal("2028-03", "Too late")), "2028-04")


def test_power_gate_uses_nameplate_and_facility_boundary():
    plan = small_hall()
    steps = (PowerDelivery("2027-12", 10), PowerDelivery("2028-03", 2))
    frame = simulate_lifecycle(replace(plan, power_deliveries=steps), "2028-04")
    assert frame.status.tolist() == ["active", "stalled", "stalled", "active", "in service"]
    assert "12 facility MW" in frame.iloc[2].reason
    assert simulate_lifecycle(replace(plan, power_deliveries=()), "2029-01").facility_mwh.sum() == 0
    with pytest.raises(ValueError, match="in order"):
        replace(plan, power_deliveries=steps[::-1])
