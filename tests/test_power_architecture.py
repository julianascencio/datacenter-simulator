"""Analytical checks, conservation, adverse cases and reproducible study exports."""

import json
import subprocess
import sys
from dataclasses import replace
from math import exp, sqrt
from pathlib import Path

import pandas as pd
import pytest

from datacenter_simulator.analysis.power_architecture import (
    export_power_architecture_study,
    power_architecture_study,
)
from datacenter_simulator.methods.energy import Battery, dispatch
from datacenter_simulator.methods.power_architecture import (
    capacitor_hold_up_f,
    compare_dc_conductors,
    dc_backup_requirements,
    evaluate_power_path,
    fault_energy_screen,
)
from datacenter_simulator.models.power_architecture import (
    CapacitorPath,
    LimitedSourcePath,
    PowerArchitecture,
    PowerStage,
    PowerStudyInputs,
)
from datacenter_simulator.use_cases.power_architecture import illustrative_power_architectures


def test_power_cascade_conservation_and_zero_load() -> None:
    architecture = PowerArchitecture(
        "analytical", (PowerStage("one", 0.8), PowerStage("two", 0.5)), "test", "test"
    )
    result = evaluate_power_path(architecture, 100)
    assert result.input_kw == pytest.approx(250)
    assert result.loss_kw == pytest.approx(150)
    assert result.efficiency == pytest.approx(0.4)
    assert result.balance_error_kw == pytest.approx(0, abs=1e-10)
    assert list(result.stages.loss_kw) == pytest.approx([50, 100])
    assert list(result.stages.input_kw)[1] == result.stages.output_kw.iloc[0]
    assert evaluate_power_path(architecture, 0).input_kw == 0
    with pytest.raises(ValueError):
        evaluate_power_path(architecture, -1)


def test_presets_preserve_ups_and_backup_boundary() -> None:
    ac, sidecar, row, central = illustrative_power_architectures()
    assert any("UPS" in s.name for s in ac.stages)
    for architecture in (sidecar, row):
        assert any("UPS" in s.name for s in architecture.stages)
        assert any("transformer" in s.name for s in architecture.stages)
    assert all("UPS" not in s.name for s in central.stages)
    assert "storage" in central.backup_location
    assert central.stages[-1] == sidecar.stages[-1]


def test_dc_feeder_matches_quadratic_and_retains_overload() -> None:
    frame = compare_dc_conductors(1000).set_index("voltage_v")
    assert frame.loc[54, "ideal_current_a"] == pytest.approx(18518.5185185)
    assert frame.loc[800, "ideal_current_a"] == 1250
    for voltage, row in frame.iterrows():
        resistance = row.loop_resistance_ohm
        # High-voltage root of Vr² - Vs*Vr + P*R = 0, independent of iterative solver.
        receiving = (float(voltage) + sqrt(float(voltage) ** 2 - 4e6 * resistance)) / 2
        assert row.receiving_voltage_v == pytest.approx(receiving, abs=1e-7)
        assert row.current_a == pytest.approx(1e6 / receiving)
        assert row.loss_kw == pytest.approx((1e6 / receiving) ** 2 * resistance / 1000)
        assert abs(row.balance_error_kw) < 1e-6
    assert frame.loc[54, "overloaded"]
    assert not frame.loc[800, "overloaded"]
    assert frame.loc[54, "loss_kw"] > frame.loc[800, "loss_kw"]
    with pytest.raises(ValueError):
        compare_dc_conductors(1, ())
    with pytest.raises(ValueError):
        compare_dc_conductors(1000, (0,))


def test_backup_minimum_replays_in_existing_dispatch() -> None:
    sizing = dc_backup_requirements(1000, 60, discharge_efficiency=0.95, usable_soc_fraction=0.8)
    battery = Battery(
        sizing["minimum_nominal_kwh"],
        0,
        1000,
        discharge_efficiency=0.95,
        initial_soc=0.9,
        minimum_soc=0.1,
        maximum_soc=0.9,
    )
    result = dispatch(
        1000,
        0,
        60 / 3600,
        battery=battery,
        energy_kwh=0.9 * battery.capacity_kwh,
        grid_import_limit_kw=0,
    )
    assert result.unserved_kw == pytest.approx(0, abs=1e-9)
    assert result.battery_energy_kwh == pytest.approx(0.1 * battery.capacity_kwh)
    undersized = replace(battery, capacity_kwh=battery.capacity_kwh / 2)
    result = dispatch(
        1000,
        0,
        60 / 3600,
        battery=undersized,
        energy_kwh=0.9 * undersized.capacity_kwh,
        grid_import_limit_kw=0,
    )
    assert result.unserved_kw == pytest.approx(500)
    assert dc_backup_requirements(1000, 0)["minimum_nominal_kwh"] == 0


def test_capacitor_hold_up_conserves_energy() -> None:
    capacitance = capacitor_hold_up_f(1000, 0.02, 800, 720)
    final_v = sqrt(800**2 - 2 * 1e6 * 0.02 / capacitance)
    assert final_v == pytest.approx(720)
    assert capacitor_hold_up_f(0, 0.02, 800, 720) == 0
    with pytest.raises(ValueError):
        capacitor_hold_up_f(1000, 0.02, 800, 800)


def test_rc_discharge_analytical_energy_and_isolation() -> None:
    cap = CapacitorPath("cap", 0.01, 0.05)
    horizon = cap.resistance_ohm * cap.capacitance_f
    result = fault_energy_screen(800, horizon, [cap])
    initial = 3200
    expected = initial * (1 - exp(-2))
    assert result.capacitor_released_j == pytest.approx(expected)
    assert result.capacitor_released_j + result.capacitor_remaining_j == pytest.approx(initial)
    isolated = fault_energy_screen(800, 1, [replace(cap, disconnect_after_s=horizon)])
    assert isolated.capacitor_released_j == pytest.approx(expected)
    assert fault_energy_screen(800, 0, [cap]).combined_screen_j == 0
    assert fault_energy_screen(800, 10, [cap]).capacitor_released_j == initial
    assert fault_energy_screen(800, 1).combined_screen_j == 0


def test_source_cutoff_energy_limit_and_local_energy_floor() -> None:
    source = LimitedSourcePath("bess", 1000, 0.001, available_energy_j=100)
    assert fault_energy_screen(800, 0.02, sources=[source]).source_envelope_j == 100
    assert fault_energy_screen(800, 0.00001, sources=[source]).source_envelope_j == 8
    assert (
        fault_energy_screen(
            800, 1, sources=[replace(source, disconnect_after_s=0)]
        ).source_envelope_j
        == 0
    )
    local = CapacitorPath("local", 0.01, 0.05)
    # An instantaneous upstream trip leaves the entire local RC contribution.
    result = fault_energy_screen(800, 0.02, [local], [replace(source, disconnect_after_s=0)])
    assert result.combined_screen_j == pytest.approx(3200)
    with pytest.raises(ValueError):
        fault_energy_screen(800, 1, [local, local])


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_invalid_inputs(bad: float) -> None:
    for field in ("it_kw", "operating_hours", "sst_efficiency", "backup_duration_s"):
        with pytest.raises(ValueError):
            PowerStudyInputs(**{field: bad})
    with pytest.raises(ValueError):
        PowerStage("bad", bad)
    with pytest.raises(ValueError):
        CapacitorPath("bad", 0.01, bad)
    with pytest.raises(ValueError):
        LimitedSourcePath("bad", 100, bad)
    with pytest.raises(ValueError):
        fault_energy_screen(800, bad)
    with pytest.raises(ValueError):
        dc_backup_requirements(100, bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sst_efficiency", 1.01),
        ("sst_efficiency", 0),
        ("it_kw", 0),
        ("usable_soc_fraction", 0),
        ("operating_hours", 9000),
        ("minimum_bus_voltage_v", 801),
    ],
)
def test_input_boundaries(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        PowerStudyInputs(**{field: value})


def test_study_does_not_guarantee_savings_or_remove_local_energy() -> None:
    study = power_architecture_study()
    comparison = study.architectures.set_index("architecture")
    assert comparison.loc["sidecar_800v", "input_energy_saving_pct"] < 0
    assert comparison.loc["central_sst_800v", "input_energy_saving_pct"] > 0
    assert study.efficiency_sensitivity.input_energy_saving_pct.min() < 0
    threshold = study.backup["sst_break_even_efficiency"]
    break_even = power_architecture_study(PowerStudyInputs(sst_efficiency=threshold))
    assert break_even.architectures.input_energy_saving_pct.iloc[-1] == pytest.approx(0, abs=1e-10)
    assert study.backup["bus_load_kw"] == pytest.approx(5000 / 0.975)
    local = study.fault_contributions.query("path == 'local_load_side'")
    assert local.screen_energy_j.to_list() == pytest.approx([3200] * len(local))
    for _, frame in study.faults.groupby("reverse_blocking"):
        assert frame.combined_screen_j.is_monotonic_increasing
    pivot = study.faults.pivot(
        index="clearing_s", columns="reverse_blocking", values="combined_screen_j"
    )
    assert all(pivot[False] > pivot[True])
    zero_hours = power_architecture_study(PowerStudyInputs(operating_hours=0))
    assert all(zero_hours.architectures.energy_cost_saving == 0)


def test_export_replay_and_offline_report(tmp_path: Path) -> None:
    export_power_architecture_study(tmp_path, PowerStudyInputs(it_kw=2000))
    values = json.loads((tmp_path / "inputs.json").read_text())
    replay = power_architecture_study(PowerStudyInputs(**values))
    pd.testing.assert_frame_equal(pd.read_csv(tmp_path / "architectures.csv"), replay.architectures)
    assert json.loads((tmp_path / "evidence.json").read_text())["sources"]
    html = (tmp_path / "power-architecture.html").read_text()
    assert "plotly.js" in html and "not arc-flash incident energy" in html
    assert '<script src="https://' not in html
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "datacenter_simulator.analysis.power_architecture",
            "--inputs",
            str(tmp_path / "inputs.json"),
            "--output",
            str(tmp_path / "replay"),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "central_sst_800v" in command.stdout
    assert (tmp_path / "architectures.csv").read_bytes() == (
        tmp_path / "replay" / "architectures.csv"
    ).read_bytes()
