"""Independent design arithmetic, boundary checks and exported audit consistency."""

import json
from dataclasses import replace
from math import sqrt

import numpy as np
import pytest

from datacenter_simulator.analysis.design import compare_designs, design_study, export_design_study
from datacenter_simulator.methods.facility_design import (
    annual_design_energy,
    design_facility,
    rack_layout,
    size_redundant_capacity,
    three_phase_current,
)
from datacenter_simulator.models.design import DesignInputs, OperatingBin
from datacenter_simulator.utilities.design import design_floor_plan, design_power_flow


def arithmetic_case():
    return DesignInputs(
        it_peak_kw=980,
        growth_fraction=0,
        rack_limit_kw=100,
        downstream_efficiency=0.98,
        ups_efficiency=0.8,
        main_efficiency=1,
        cooling="dx",
        cooling_module_kw_th=1000,
        cooling_margin_fraction=0,
        design_ambient_c=30,
        auxiliary_fraction=0,
        module_derating=1,
        ups_load_power_factor=0.8,
        grid_limit_kw=1500,
    )


def test_known_design_power_heat_capacity_and_battery():
    design = design_facility(arithmetic_case())
    # 980 IT / .98 = 1000 UPS output / .8 = 1250 UPS input.
    # DX: 1000/3.2 compressor + 1000*.045 fans = 357.5 kW.
    assert design.balance["hall_heat_kw"] == pytest.approx(1000)
    assert design.balance["facility_kw"] == pytest.approx(1607.5)
    assert design.summary["heat_rejection_kw"] == pytest.approx(1357.5)
    assert design.summary["grid_margin_kw"] == pytest.approx(-107.5)
    assert design.summary["battery_per_bank_kwh"] == pytest.approx(1000 / 6 / 0.95 / 0.8 / 0.8)
    # The 500 kVA rating at PF .8 restricts each UPS to 400 kW, requiring 3+1.
    ups = design.equipment.set_index("equipment").loc["UPS"]
    assert ups.installed_modules == 4
    assert ups.remaining_kw == 1200
    assert design.summary["rack_count"] == 10
    assert design.racks.it_kw.iloc[-1] == 80


@pytest.mark.parametrize(
    "topology,installed,remaining,passes",
    [("N", 2, 500, False), ("N+1", 3, 1000, True), ("2N", 4, 1000, True)],
)
def test_redundancy_exact_boundary_and_failure(topology, installed, remaining, passes):
    row = size_redundant_capacity("UPS", 1000, 500, redundancy=topology)
    assert row["installed_modules"] == installed
    assert row["remaining_kw"] == remaining
    assert row["contingency_pass"] == passes
    above = size_redundant_capacity("UPS", 1000.01, 500, redundancy=topology)
    assert above["duty_modules"] == 3
    empty = size_redundant_capacity("UPS", 0, 500, redundancy=topology)
    assert empty["installed_modules"] == 0


def test_2n_allocates_independent_banks_without_inventing_standby_losses():
    n = design_facility(replace(arithmetic_case(), redundancy="N"))
    n2 = design_facility(replace(arithmetic_case(), redundancy="2N"))
    np.testing.assert_allclose(n2.equipment.installed_modules, 2 * n.equipment.installed_modules)
    assert n2.summary["battery_total_kwh"] == 2 * n.summary["battery_total_kwh"]
    assert n2.summary["design_facility_kw"] == n.summary["design_facility_kw"]


def test_annual_pue_is_weighted_energy_and_grid_gap_is_reported():
    design = design_facility(arithmetic_case())
    bins = [OperatingBin(4380, 0.5, 30), OperatingBin(4380, 1, 30)]
    frame, summary = annual_design_energy(design, bins)
    # Half load: 625 UPS input + 500/3.2 + 45*(.2+.8*.5**3) cooling.
    assert frame.facility_kw.tolist() == pytest.approx([794.75, 1607.5])
    assert summary["annual_facility_kwh"] == pytest.approx((794.75 + 1607.5) * 4380)
    assert summary["annual_energy_pue"] == pytest.approx((794.75 + 1607.5) / (490 + 980))
    assert summary["annual_energy_pue"] != pytest.approx(frame.instantaneous_pue.mean())
    assert summary["annual_grid_exceedance_kwh"] == pytest.approx(107.5 * 4380)
    assert summary["annual_grid_exceedance_hours"] == 4380


def test_balanced_ac_current_and_rack_geometry():
    assert three_phase_current(sqrt(3) * 0.4 * 0.8, 400, 0.8) == pytest.approx(1)
    inputs = replace(arithmetic_case(), racks_per_row=3)
    racks, area = rack_layout(inputs)
    assert len(racks) == 10
    assert racks.groupby("row").size().tolist() == [3, 3, 3, 1]
    assert area["hall_width_m"] == pytest.approx(3 * 0.6 + 2 * 1.5)
    assert area["hall_depth_m"] == pytest.approx(4 * 1.2 + 2 * 1.2 + 1 + 3)
    assert racks.it_kw.sum() == pytest.approx(980)
    assert (racks.x_m + racks.width_m <= area["hall_width_m"]).all()
    assert (racks.y_m + racks.depth_m <= area["hall_depth_m"]).all()
    # Each pair of boxes must be disjoint (touching rack sides is allowed).
    for i, a in enumerate(racks.itertuples()):
        for b in list(racks.itertuples())[i + 1 :]:
            assert (
                a.x_m + a.width_m <= b.x_m + 1e-9
                or b.x_m + b.width_m <= a.x_m + 1e-9
                or a.y_m + a.depth_m <= b.y_m + 1e-9
                or b.y_m + b.depth_m <= a.y_m + 1e-9
            )


def test_all_fifteen_variants_conserve_power_and_cooling():
    studies = compare_designs(design_study())
    assert len(studies) == 15
    for study in studies.values():
        d = study.design
        components = (
            "it_kw",
            "distribution_loss_kw",
            "ups_loss_kw",
            "cooling_kw",
            "auxiliary_kw",
            "main_loss_kw",
        )
        assert sum(d.balance[k] for k in components) == pytest.approx(d.balance["facility_kw"])
        assert d.balance["liquid_heat_kw"] + d.balance["air_heat_kw"] == pytest.approx(
            d.balance["hall_heat_kw"]
        )
        assert d.balance["unmet_heat_kw"] == 0
        assert sum(design_power_flow(d).data[0].link.value) == pytest.approx(
            d.balance["facility_kw"]
        )
        if d.inputs.redundancy != "N":
            assert d.equipment.contingency_pass.all()


@pytest.mark.parametrize(
    "overrides",
    [
        {"it_peak_kw": 0},
        {"it_peak_kw": float("nan")},
        {"growth_fraction": -1},
        {"rack_limit_kw": 0},
        {"racks_per_row": True},
        {"racks_per_row": 1.5},
        {"module_derating": 0},
        {"ups_load_power_factor": 1.1},
        {"main_efficiency": 0},
        {"redundancy": "Tier IV"},
        {"cooling": "unknown"},
        {"service_voltage_v": 0},
        {"grid_limit_kw": -1},
        {"cold_aisle_m": 0},
        {"support_area_fraction": -1},
        {"battery_end_of_life_fraction": 0},
        {"design_ambient_c": float("inf")},
    ],
)
def test_bad_inputs_fail_before_calculations(overrides):
    with pytest.raises(ValueError):
        DesignInputs(**overrides)


@pytest.mark.parametrize("bins", [[], [OperatingBin(8759, 0.5, 20)]])
def test_annual_hours_required(bins):
    with pytest.raises(ValueError, match="8760"):
        annual_design_energy(design_facility(), bins)


@pytest.mark.parametrize(
    "values", [(0, 0.5, 20), (8760, 0, 20), (8760, 1.1, 20), (8760, 0.5, float("nan"))]
)
def test_invalid_operating_bins(values):
    with pytest.raises(ValueError):
        OperatingBin(*values)


def test_export_roundtrip_and_large_layout_preview(tmp_path):
    study = export_design_study(tmp_path, arithmetic_case(), [OperatingBin(8760, 0.8, 30)])
    restored = DesignInputs(**json.loads((tmp_path / "inputs.json").read_text()))
    bins = [OperatingBin(**b) for b in json.loads((tmp_path / "bins.json").read_text())]
    assert design_study(restored, bins).summary == study.summary
    assert len(json.loads((tmp_path / "scenarios.json").read_text())) == 15
    assert len(list(tmp_path.glob("*.csv"))) == 5
    assert len(list(tmp_path.glob("*.json"))) == 6
    html = (tmp_path / "design-workbench.html").read_text()
    assert "plotly.js" in html and "__DATA__" not in html
    assert 'href="inputs.json" download' in html
    assert len(design_floor_plan(study.design, max_racks=2).data[0].x) == 2
