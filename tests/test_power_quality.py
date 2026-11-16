"""Independent circuit checks, physical limits and evidence contracts."""

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.analysis.power_quality import export_power_quality_study
from datacenter_simulator.connectors.power_quality import (
    read_power_profile,
    summarize_line_to_line_pst,
)
from datacenter_simulator.methods.power_quality import (
    ideal_source_benchmark,
    simulate_power_quality,
    sizing_sweep,
    solve_pcc,
    validate_power_profile,
)
from datacenter_simulator.models.power_quality import EStatcom, WeakGrid
from datacenter_simulator.use_cases.power_quality import synthetic_ai_load


def profile(p, q=None, dt=0.1):
    return pd.DataFrame(
        {
            "time_s": np.arange(len(p)) * dt,
            "load_mw": p,
            "load_mvar": np.zeros(len(p)) if q is None else q,
        }
    )


def test_grid_base_and_conditional_h_conversion():
    grid = WeakGrid()
    assert grid.short_circuit_mva == 800
    assert abs(grid.impedance_ohm) == pytest.approx(35**2 / 800)
    c = EStatcom()
    assert c.nominal_energy_kwh == pytest.approx(125.5555555556)
    assert c.usable_energy_mj == pytest.approx(361.6)


@pytest.mark.parametrize("p,q", [(0, 0), (180, 30), (100, -60), (-40, -5)])
def test_ac_circuit_kirchhoff_and_losses(p, q):
    grid = WeakGrid()
    r = solve_pcc(grid, p, q)
    s = complex(p, q) / grid.base_mva
    current = (s / r.voltage_pu).conjugate()
    assert r.voltage_pu + grid.impedance_pu * current == pytest.approx(grid.source_voltage_pu)
    source_s = grid.source_voltage_pu * current.conjugate() * grid.base_mva
    assert r.source_p_mw == pytest.approx(source_s.real)
    assert r.source_q_mvar == pytest.approx(source_s.imag)
    assert r.grid_loss_mw == pytest.approx(
        abs(current) ** 2 * grid.impedance_pu.real * grid.base_mva
    )


def test_resistive_circuit_matches_scalar_quadratic_and_collapse_raises():
    grid = WeakGrid(x_over_r=0, source_voltage_pu=1)
    v = (1 + np.sqrt(1 - 4 * 0.25 * 0.5)) / 2
    assert abs(solve_pcc(grid, 100, 0).voltage_pu) == pytest.approx(v)
    with pytest.raises(ValueError, match="solution"):
        solve_pcc(WeakGrid(scr=0.2), 200, 100)


def test_q_direction_on_rising_and_falling_voltage():
    grid = WeakGrid(source_voltage_pu=1)
    c = EStatcom(nominal_energy_mj=0)
    # Capacitive load raises V; droop absorbs. Inductive load lowers V; injects.
    result = simulate_power_quality(profile([0, 0], [-50, 50]), grid, c).timeseries
    assert result.support_q_mvar.iloc[0] < 0
    assert result.support_q_mvar.iloc[1] > 0
    assert result.voltage_pu.iloc[0] > 1
    assert result.voltage_pu.iloc[1] < 1
    # Load falls and bus rises: absorption increases (Q injection decreases).
    step = simulate_power_quality(profile([180, 80], [30, 10]), WeakGrid(), c).timeseries
    assert step.voltage_pu.iloc[1] > step.voltage_pu.iloc[0]
    assert step.support_q_mvar.iloc[1] < step.support_q_mvar.iloc[0]


def test_statcom_cannot_supply_active_energy():
    trace = synthetic_ai_load(duration_s=10)
    r = simulate_power_quality(trace, WeakGrid(), EStatcom(nominal_energy_mj=0))
    np.testing.assert_allclose(r.timeseries.pcc_p_mw, trace.load_mw)
    assert r.timeseries.support_p_mw.eq(0).all()
    assert r.timeseries.energy_end_mj.eq(0).all()


def test_storage_limits_losses_and_interval_energy_balance():
    trace = profile([80] * 10 + [180] * 50 + [20] * 50)
    c = EStatcom(
        rating_mva=25,
        active_limit_mw=25,
        nominal_energy_mj=10,
        smoothing_tau_s=20,
        charge_efficiency=0.9,
        discharge_efficiency=0.8,
    )
    r = simulate_power_quality(trace, WeakGrid(), c)
    f = r.timeseries
    assert f.energy_end_mj.min() >= c.minimum_soc * c.nominal_energy_mj - 1e-9
    assert f.energy_end_mj.max() <= c.maximum_soc * c.nominal_energy_mj + 1e-9
    assert f.converter_mva.max() <= c.rating_mva + 1e-8
    assert f.support_p_mw.abs().max() <= c.active_limit_mw
    assert f.p_limited.any() and f.q_limited.any()
    assert (f.support_p_mw > 0).any() and (f.support_p_mw < 0).any()
    assert f.converter_loss_mw.min() >= 0
    np.testing.assert_allclose(f.pcc_p_mw + f.support_p_mw, trace.load_mw)
    np.testing.assert_allclose(f.pcc_q_mvar + f.support_q_mvar, trace.load_mvar)
    assert r.summary["energy_balance_error_max_mj"] < 1e-12
    assert r.summary["initial_energy_mj"] - r.summary["terminal_energy_mj"] == pytest.approx(
        float((f.support_p_mw + f.converter_loss_mw).sum() * 0.1), abs=1e-10
    )


def test_finite_impedance_ideal_source_has_explicit_energy_and_current_sharing():
    trace = synthetic_ai_load(duration_s=10)
    grid = WeakGrid()
    r = ideal_source_benchmark(trace, grid)
    f = r.timeseries
    np.testing.assert_allclose(f.pcc_p_mw, trace.load_mw / 2)
    np.testing.assert_allclose(f.pcc_p_mw + f.auxiliary_p_mw, trace.load_mw)
    total = solve_pcc(replace(grid, scr=8), trace.load_mw.iloc[0], trace.load_mvar.iloc[0])
    current = (grid.source_voltage_pu - total.voltage_pu) / grid.impedance_pu
    assert (total.voltage_pu * current.conjugate()).real * grid.base_mva == pytest.approx(
        f.pcc_p_mw.iloc[0]
    )
    assert r.summary["auxiliary_delivered_mwh"] > 0


def test_smoothing_improves_pulses_but_not_sustained_mean_and_timestep_converges():
    grid, c = WeakGrid(), EStatcom()
    trace = synthetic_ai_load(duration_s=30)
    base = simulate_power_quality(trace, grid)
    result = simulate_power_quality(trace, grid, c)
    assert result.summary["pcc_active_swing_mw"] < base.summary["pcc_active_swing_mw"]
    assert result.summary["voltage_excursion_pu"] < base.summary["voltage_excursion_pu"]
    stress = simulate_power_quality(synthetic_ai_load(duration_s=120, shape="sustained"), grid, c)
    assert stress.timeseries.pcc_p_mw.iloc[-1] > 175
    coarse = simulate_power_quality(synthetic_ai_load(duration_s=10, dt_s=0.02), grid, c)
    fine = simulate_power_quality(synthetic_ai_load(duration_s=10, dt_s=0.01), grid, c)
    assert abs(coarse.summary["pcc_active_swing_mw"] - fine.summary["pcc_active_swing_mw"]) < 1


def test_sizing_retains_failed_cases_and_requires_whole_envelope():
    traces = {"pulse": synthetic_ai_load(duration_s=5)}
    result = sizing_sweep(
        traces,
        (WeakGrid(), WeakGrid(scr=0.05)),
        (EStatcom(),),
        maximum_swing_mw=100,
        maximum_voltage_excursion_pu=1,
    )
    assert result.screen_pass.tolist() == [True, False]
    assert not result.passes_all_tested_cases.any()
    assert result.status.iloc[1] != "solved"


@pytest.mark.parametrize(
    "changes",
    [
        {"rating_mva": 0},
        {"nominal_energy_mj": -1},
        {"charge_efficiency": 0},
        {"initial_soc": 0},
        {"minimum_soc": 0.9},
        {"recovery_tau_s": float("nan")},
        {"rating_mva": 20, "active_limit_mw": 21},
    ],
)
def test_invalid_compensator(changes):
    with pytest.raises(ValueError):
        EStatcom(**changes)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.assign(time_s=[0, 0, 1]),
        lambda p: p.assign(time_s=[0, 1, 3]),
        lambda p: p.assign(load_mw=[1, -1, 1]),
        lambda p: p.assign(load_mvar=[0, float("nan"), 0]),
        lambda p: p.iloc[:1],
    ],
)
def test_invalid_profiles(mutate):
    with pytest.raises(ValueError):
        validate_power_profile(mutate(profile([1, 1, 1])))


def external_pst():
    return pd.DataFrame(
        {
            "case": ["external"] * 3,
            "window_start_s": [0] * 3,
            "duration_s": [600] * 3,
            "channel": ["AB", "BC", "CA"],
            "pst": [1.2, 3.4, 2.3],
            "meter": ["validated-meter/version"] * 3,
            "waveform_reference": ["waveforms.csv#sha256=example"] * 3,
        }
    )


def test_pst_is_max_of_all_line_to_line_channels_not_positive_sequence():
    summary = summarize_line_to_line_pst(external_pst())
    assert summary.pst_max.iloc[0] == 3.4
    assert summary.worst_channel.iloc[0] == "BC"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.iloc[:2],
        lambda p: p.assign(channel=["positive_sequence", "BC", "CA"]),
        lambda p: p.assign(channel=["AB", "AB", "CA"]),
        lambda p: p.assign(duration_s=120),
        lambda p: p.assign(pst=[-1, 2, 3]),
        lambda p: p.assign(meter=""),
        lambda p: p.assign(pst=[float("inf"), 2, 3]),
    ],
)
def test_invalid_flicker_evidence(mutate):
    with pytest.raises(ValueError):
        summarize_line_to_line_pst(mutate(external_pst()))


def test_export_replay_and_evidence_separation(tmp_path):
    study = export_power_quality_study(
        tmp_path, profile=synthetic_ai_load(duration_s=5), flicker=external_pst()
    )
    replay = simulate_power_quality(
        read_power_profile(tmp_path / "profile_input.csv"), WeakGrid(), EStatcom()
    )
    pd.testing.assert_frame_equal(study.cases["estatcom"].timeseries, replay.timeseries, atol=1e-9)
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["reported_case"]["verification_status"] == "reported_only_not_reproduced"
    assert not any("pst" in key for key in replay.summary)
    html = (tmp_path / "power-quality.html").read_text()
    assert "plotly" in html and "not Pst" in html
    assert (tmp_path / "external_pst_summary.csv").exists()
    assert len(study.sizing) == 54
