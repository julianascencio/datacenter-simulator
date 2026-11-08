"""Reproduce the evidence-separated case through installed package methods."""

import json

import numpy as np
import pytest

from datacenter_simulator.analysis.wyoming import recovery_study
from datacenter_simulator.methods.project_recovery import (
    emissions,
    firm_capacity,
    hours_in_month,
    month_id,
)
from datacenter_simulator.use_cases.wyoming import wyoming_inputs, wyoming_sources


def test_recovery_matches_original_exercise_and_keeps_capital_separate():
    study = recovery_study()
    table = study["summary"].set_index("case")
    assert list(table.final_commissioned_it_mw) == [1400, 1400, 1500, 1500]
    assert table.loc["C_power_gated_plus_firm", "first_full_target_month"] == "2030-01"
    assert table.loc["D_delayed_recovery", "first_full_target_month"] == "2030-07"
    assert table.loc["A_build_ahead", "firm_it_energy_twh"] == pytest.approx(24.4224)
    assert table.loc["B_power_gated", "firm_it_energy_twh"] == pytest.approx(24.4224)
    assert (
        table.loc["B_power_gated", "idle_capital_carry_usd"]
        < table.loc["A_build_ahead", "idle_capital_carry_usd"]
    )
    assert np.all(
        study["monthly"].commissioned_it_mw * 1.2 <= study["monthly"].firm_facility_mw + 1e-7
    )


def test_carbon_energy_balance_and_capture_penalty():
    cfg = wyoming_inputs()
    none = emissions(cfg, 0, 0, 0)
    capture = emissions(cfg, 0.9, 0, 0.05)
    assert none["residual_mt_year"] == pytest.approx(5.2167138309)
    assert capture["residual_mt_year"] == pytest.approx(3.6379725668)
    assert capture["gas_million_mmbtu_year"] > none["gas_million_mmbtu_year"]
    assert capture["fuel_cell_net_mw"] + capture["ccgt_mw"] + capture[
        "black_hills_mw"
    ] == pytest.approx(1800)


def test_inputs_are_fresh_packaged_and_have_provenance():
    cfg = wyoming_inputs()
    cfg["pue"] = 9
    assert wyoming_inputs()["pue"] == 1.2
    sources = wyoming_sources()
    assert len(sources) >= 15
    assert all(s["url"].startswith("https://") for s in sources)
    json.dumps(sources)


def test_months_and_firm_capacity_edge_cases():
    assert hours_in_month(month_id("2028-02")) == 696
    assert firm_capacity([], 1) == 0
    assert firm_capacity([100], 1) == 0
    with pytest.raises(ValueError):
        month_id("2028-13")
    with pytest.raises(ValueError):
        firm_capacity([-1], 1)
    with pytest.raises(ValueError):
        firm_capacity([1], 1.5)


@pytest.mark.parametrize(
    "key,value",
    [
        ("pue", 0.9),
        ("delivery_factor", 1.1),
        ("fuel_cell_capture_energy_penalty", 1),
        ("building_lead_months", -1),
        ("end", "2027-01"),
    ],
)
def test_bad_planning_inputs_rejected(key, value):
    cfg = wyoming_inputs()
    cfg[key] = value
    with pytest.raises(ValueError):
        recovery_study(cfg)
