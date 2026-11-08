"""Hand-calculated accounting, physical boundaries and reproducible exports."""

import json
from dataclasses import replace

import numpy as np
import pytest

from datacenter_simulator.analysis.infrastructure import (
    export_infrastructure_study,
    infrastructure_study,
)
from datacenter_simulator.methods.cooling import CoolingPlant
from datacenter_simulator.methods.infrastructure import (
    capital_breakdown,
    infrastructure_balance,
    size_modules,
    ups_energy_required,
)
from datacenter_simulator.models.infrastructure import CapitalScenario, ModularEquipment, UPSBattery
from datacenter_simulator.use_cases.infrastructure import (
    InfrastructureCase,
    infrastructure_cost_items,
    infrastructure_evidence,
)


def test_image_transcription_reconciles_all_twelve_rates():
    items = infrastructure_cost_items()
    assert len(items) == 12
    assert sum(item.million_usd_per_mw for item in items) == pytest.approx(42.7)
    table, result = capital_breakdown(items, CapitalScenario(20, 25))
    grouped = table.groupby("group").cost_usd.sum().to_dict()
    assert grouped == {"IT": 724e6, "Infrastructure": 102e6, "Services": 28e6}
    assert result["scenario_total_usd"] == 854e6
    assert table.set_index("id").loc["construction", "cost_usd"] == 18e6
    source = infrastructure_evidence()["source"]
    assert "unverified" in source["verification"].lower()
    assert "land" in source["unpriced_scope"]


def test_mw_boundary_allowances_and_sensitivity_do_not_double_count():
    items = infrastructure_cost_items()
    scenario = CapitalScenario(20, 25, contingency_fraction=0.1, unlisted_scope_usd=5e6)
    _, result = capital_breakdown(items, scenario)
    assert result["scenario_total_usd"] == 944.4e6
    _, facility = capital_breakdown(items, replace(scenario, mw_basis="facility"))
    assert facility["listed_subtotal_usd"] == 1067.5e6
    _, server = capital_breakdown(items, CapitalScenario(20, 25), multipliers={"servers": 1.2})
    assert server["listed_subtotal_usd"] == 979.6e6
    with pytest.raises(ValueError, match="unknown"):
        capital_breakdown(items, scenario, multipliers={"typo": 1})
    with pytest.raises(ValueError, match="unique"):
        capital_breakdown((*items, items[0]), scenario)
    with pytest.raises(ValueError):
        capital_breakdown(items, scenario, multipliers={"servers": float("nan")})


def test_hand_calculated_electrical_and_heat_balances():
    # 98 IT -> 100 UPS output -> 125 UPS input; cooling = 100/5 = 20.
    # (125 + 20 + 5 auxiliaries) / 0.75 main efficiency = 200 at meter.
    plant = CoolingPlant("idealized", 100, 5, liquid_fraction=1, fan_fraction=0, pump_fraction=0)
    r = infrastructure_balance(
        98,
        plant,
        ambient_c=30,
        downstream_efficiency=0.98,
        ups_efficiency=0.8,
        main_efficiency=0.75,
        auxiliary_kw=5,
    )
    assert r["facility_kw"] == pytest.approx(200)
    assert r["hall_heat_kw"] == pytest.approx(100)
    assert r["ups_loss_kw"] == pytest.approx(25)
    assert r["main_loss_kw"] == pytest.approx(50)
    assert r["rejected_heat_kw"] == pytest.approx(120)
    assert r["instantaneous_pue"] == pytest.approx(200 / 98)
    overloaded = infrastructure_balance(196, plant, ambient_c=30)
    assert overloaded["unmet_heat_kw"] == pytest.approx(100)
    assert overloaded["liquid_heat_kw"] + overloaded["air_heat_kw"] == 100
    idle = infrastructure_balance(0, plant, ambient_c=30)
    assert idle["facility_kw"] == 0
    assert np.isnan(idle["instantaneous_pue"])


@pytest.mark.parametrize("load,active,total", [(0, 0, 0), (2700, 1, 2), (2700.1, 2, 3)])
def test_discrete_sizing_at_the_capacity_boundary(load, active, total):
    r = size_modules(ModularEquipment("generator", 3000, derating=0.9), load)
    assert r["duty_units"] == active
    assert r["installed_units"] == total
    assert r["capacity_after_reserve_loss_kw"] >= load


def test_ups_energy_kva_and_ageing_are_distinct_constraints():
    # 600 kW for 10 min = 100 kWh AC; /0.8 inverter /0.5 usable /0.8 EOL.
    energy = ups_energy_required(
        600, 10, inverter_efficiency=0.8, usable_fraction=0.5, end_of_life_fraction=0.8
    )
    assert energy == pytest.approx(312.5)
    battery = UPSBattery(energy, 800, 800, 0.8, 0.5, 0.8)
    assert battery.runtime_minutes(600, load_power_factor=0.8) == pytest.approx(10)
    with pytest.raises(ValueError, match="kVA"):
        battery.runtime_minutes(600, load_power_factor=0.7)
    with pytest.raises(ValueError):
        battery.runtime_minutes(900)
    with pytest.raises(ValueError):
        battery.runtime_minutes(0)
    assert ups_energy_required(0, 10) == 0


def test_study_closes_each_hour_and_uses_energy_weighted_pue():
    study = infrastructure_study()
    frame = study.hourly
    components = frame[
        [
            "it_kw",
            "distribution_loss_kw",
            "ups_loss_kw",
            "cooling_kw",
            "auxiliary_kw",
            "main_loss_kw",
        ]
    ].sum(axis=1)
    np.testing.assert_allclose(components, frame.facility_kw, rtol=1e-12)
    np.testing.assert_allclose(frame.server_kw + frame.network_kw, frame.it_kw)
    np.testing.assert_allclose(
        frame.liquid_heat_kw + frame.air_heat_kw + frame.unmet_heat_kw, frame.hall_heat_kw
    )
    np.testing.assert_allclose(
        frame.hall_heat_kw - frame.unmet_heat_kw + frame.cooling_kw, frame.rejected_heat_kw
    )
    assert study.summary["period_energy_pue"] == pytest.approx(
        frame.facility_kw.sum() / frame.it_kw.sum()
    )
    assert study.summary["period_unmet_heat_kwh"] == 0
    assert (study.sizing.margin_after_reserve_loss_kw >= 0).all()
    assert study.summary["ups_runtime_minutes"] == pytest.approx(10)
    assert study.summary["listed_subtotal_usd"] == 854e6


def test_engineering_redundancy_and_cooling_do_not_reprice_source():
    normal = infrastructure_study()
    changed = infrastructure_study(InfrastructureCase(rack_kw=50, liquid_heat_fraction=0))
    assert changed.summary["listed_subtotal_usd"] == normal.summary["listed_subtotal_usd"]
    assert changed.design["cooling_kw"] > normal.design["cooling_kw"]
    assert changed.sizing.set_index("id").loc["IT racks", "installed_units"] == 400
    assert changed.sizing.set_index("id").loc["Liquid CDUs", "installed_units"] == 0
    almost_air = infrastructure_study(InfrastructureCase(liquid_heat_fraction=1e-9))
    assert almost_air.design["cooling_kw"] == pytest.approx(changed.design["cooling_kw"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"it_mw": 0},
        {"it_mw": float("inf")},
        {"ups_efficiency": 0},
        {"liquid_heat_fraction": 1.1},
        {"load_power_factor": -1},
        {"ups_autonomy_minutes": -10},
        {"electricity_usd_per_kwh": -1},
    ],
)
def test_invalid_case_inputs(kwargs):
    with pytest.raises(ValueError):
        InfrastructureCase(**kwargs)


@pytest.mark.parametrize("reserve", [-1, 1.5, True])
def test_reserve_is_a_nonnegative_integer(reserve):
    with pytest.raises(ValueError):
        ModularEquipment("test", 100, reserve_units=reserve)


def test_export_contains_offline_report_and_auditable_inputs(tmp_path):
    export_infrastructure_study(tmp_path)
    assert len(list(tmp_path.glob("*.csv"))) == 6
    for name in ("assumptions", "evidence", "design", "summary"):
        data = json.loads((tmp_path / f"{name}.json").read_text())
        assert data
    report = (tmp_path / "infrastructure-study.html").read_text()
    assert "plotly.js" in report
    assert "infrastructure-chart-3" in report
    assert 'href="evidence.json" download' in report
    assert "unverified" in report
    assert "not a quotation" in report
