"""Transport accuracy, actuator physics and honest verification eligibility."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.methods.cfd import (
    cell_coordinates,
    rack_momentum_terms,
    return_open_fraction,
    simulate_cfd,
    thermal_step,
)
from datacenter_simulator.methods.verification import richardson_gci, validate_temperature_probes
from datacenter_simulator.models.cfd import CFDCase, CFDGrid, CFDSettings, CFDSource


def test_muscl_reduces_gaussian_advection_error_without_new_extrema():
    grid = CFDGrid(2, 1, 1, 80, 3, 3)
    x, _, _ = cell_coordinates(grid)
    initial = 20 + np.exp(-(((x - 0.6) / 0.12) ** 2))
    u = np.full((81, 3, 3), 0.4)
    v, w = np.zeros((80, 4, 3)), np.zeros((80, 3, 4))
    exact = 20 + np.exp(-(((x - 0.8) / 0.12) ** 2))
    errors = []
    for scheme in ("upwind", "muscl"):
        case = CFDCase(
            grid, CFDSettings(inlet_height_m=1, diffusivity_m2_s=0, thermal_scheme=scheme)
        )
        temperature = np.broadcast_to(initial[:, None, None], grid.shape).copy()
        for _ in range(100):
            temperature, _ = thermal_step(temperature, (u, v, w), np.zeros(grid.shape), case, 0.005)
        errors.append(np.mean(np.abs(temperature[:, 1, 1] - exact)))
        assert temperature.min() >= 20 - 1e-10
        assert temperature.max() <= initial.max() + 1e-10
    assert errors[1] < errors[0] / 4


def test_quadratic_fan_pressure_force_and_forchheimer_drag():
    grid = CFDGrid(2, 2, 2, 8, 8, 8)
    rack = CFDSource(
        "fan",
        0.5,
        0.5,
        0,
        0.5,
        1,
        1,
        0,
        inertial_drag_per_m=2,
        fan_pressure_pa=20,
        fan_free_speed_m_s=2,
    )
    case = CFDCase(grid, CFDSettings(), (rack,))
    still = tuple(np.zeros(grid.shape) for _ in range(3))
    force, drag = rack_momentum_terms(case, still)
    assert force[0].sum() * grid.cell_volume_m3 == pytest.approx(20 * 1 * 1 / 1.2)
    assert not drag.any()
    axial = (np.ones(grid.shape), still[1], still[2])
    force, drag = rack_momentum_terms(case, axial)
    assert force[0].sum() * grid.cell_volume_m3 == pytest.approx(15 / 1.2)
    assert drag.sum() * grid.cell_volume_m3 == pytest.approx(2 * 0.5)
    stopped, _ = rack_momentum_terms(case, (2 * axial[0], axial[1], axial[2]))
    assert not stopped[0].any()


def test_return_backflow_temperature_enters_conservative_energy_budget():
    g = CFDGrid(1, 1, 1, 5, 3, 3)
    case = CFDCase(g, CFDSettings(inlet_height_m=1, diffusivity_m2_s=0, return_temperature_c=30))
    velocity = (np.full((6, 3, 3), -0.1), np.zeros((5, 4, 3)), np.zeros((5, 3, 4)))
    result, flux = thermal_step(np.full(g.shape, 20.0), velocity, np.zeros(g.shape), case, 0.01)
    assert result[-1].min() > 20
    stored = (result - 20).sum() * g.cell_volume_m3 * 1.2 * 1006
    assert stored == pytest.approx(-flux * 0.01, abs=1e-10)


def test_gci_recovers_known_second_order_error_and_refuses_oscillation():
    result = richardson_gci([12, 10.5, 10.125], [1, 0.5, 0.25])
    assert result["eligible"] and result["order"] == pytest.approx(2)
    assert result["extrapolated"] == pytest.approx(10)
    assert result["fine_gci_absolute"] == pytest.approx(0.125 * 1.25)
    assert not richardson_gci([10, 12, 11], [1, 0.5, 0.25])["eligible"]
    assert not richardson_gci([10, 10, 10], [1, 0.5, 0.25])["eligible"]
    with pytest.raises(ValueError):
        richardson_gci([12, 11, 10], [1, 0.5, 0.3])


def test_probe_interpolation_and_metrics_reject_extrapolation():
    g = CFDGrid(2, 2, 2, 4, 4, 4)
    case = CFDCase(
        g,
        CFDSettings(
            duration_s=1,
            snapshot_interval_s=0.5,
            supply_flow_m3_s=0,
            gravity_m_s2=0,
            diffusivity_m2_s=0,
        ),
        (CFDSource("uniform", 0, 0, 0, 2, 2, 2, 1),),
    )
    result = simulate_cfd(case)
    expected = 20 + 1000 * 0.25 / (1.2 * 1006 * 8)
    probes = pd.DataFrame(
        [
            dict(
                time_s=0.25,
                x_m=1,
                y_m=1,
                z_m=1,
                observed_c=expected - 0.2,
                standard_uncertainty_c=0.1,
            )
        ]
    )
    table, metrics = validate_temperature_probes(result, probes)
    assert metrics["bias"] == pytest.approx(0.2)
    assert metrics["rmse"] == pytest.approx(0.2)
    assert table.residual_over_measurement_sigma.iloc[0] == pytest.approx(2)
    with pytest.raises(ValueError):
        validate_temperature_probes(result, probes.assign(time_s=2))
    with pytest.raises(ValueError):
        replace(case.settings, thermal_scheme="fake")
    with pytest.raises(ValueError):
        replace(case.sources[0], fan_direction=0)


def test_partial_return_aperture_conserves_area_and_coupled_mass():
    from datacenter_simulator.use_cases.cfd import reference_cfd_case

    base = reference_cfd_case()
    case = replace(
        base,
        grid=replace(base.grid, nx=10, ny=8, nz=6),
        settings=replace(base.settings, duration_s=2, snapshot_interval_s=1),
    )
    aperture = return_open_fraction(case)
    assert aperture.sum() * case.grid.spacing[1] * case.grid.spacing[2] == pytest.approx(1.8)
    assert np.any(aperture == 0)
    result = simulate_cfd(case)
    assert result.summary["max_mass_balance_error_m3_s"] < 1e-10
    assert result.summary["max_divergence_per_s"] < 1e-10
    assert result.summary["relative_energy_balance_error"] < 1e-10
    with pytest.raises(ValueError):
        replace(case, settings=replace(case.settings, return_z_m=3))
