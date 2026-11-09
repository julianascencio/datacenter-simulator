"""Analytical transport limits, projection identities and coupled CFD conservation."""

from dataclasses import replace

import numpy as np
import pytest

from datacenter_simulator.analysis.cfd import export_cfd_study, load_cfd_case, write_vtk
from datacenter_simulator.methods.cfd import (
    PressureProjection,
    cell_coordinates,
    divergence,
    simulate_cfd,
    source_fields,
    thermal_step,
)
from datacenter_simulator.methods.facility_design import design_facility
from datacenter_simulator.models.cfd import CFDCase, CFDGrid, CFDSettings, CFDSource
from datacenter_simulator.models.design import DesignInputs
from datacenter_simulator.use_cases.cfd import cfd_from_design, reference_cfd_case
from datacenter_simulator.utilities.cfd import temperature_slice


def small_case():
    base = reference_cfd_case()
    return replace(
        base,
        grid=replace(base.grid, nx=10, ny=8, nz=6),
        settings=replace(base.settings, duration_s=4, snapshot_interval_s=2),
    )


def zero_velocity(grid):
    return (
        np.zeros((grid.nx + 1, grid.ny, grid.nz)),
        np.zeros((grid.nx, grid.ny + 1, grid.nz)),
        np.zeros((grid.nx, grid.ny, grid.nz + 1)),
    )


def test_projection_recovers_manufactured_pressure_and_removes_gradient():
    grid = CFDGrid(2, 3, 1, 7, 6, 5)
    x, y, z = np.meshgrid(*cell_coordinates(grid), indexing="ij")
    pressure = np.cos(np.pi * x / 4) * np.cos(np.pi * y / 3) * np.cos(np.pi * z)
    u, v, w = zero_velocity(grid)
    dt = 0.2
    dx, dy, dz = grid.spacing
    u[1:-1] = dt * np.diff(pressure, axis=0) / dx
    u[-1] = -2 * dt * pressure[-1] / dx
    v[:, 1:-1] = dt * np.diff(pressure, axis=1) / dy
    w[:, :, 1:-1] = dt * np.diff(pressure, axis=2) / dz
    corrected, solved, residual = PressureProjection(grid).project((u, v, w), dt)
    np.testing.assert_allclose(solved, pressure, atol=1e-12)
    assert max(float(np.abs(a).max()) for a in corrected) < 1e-12
    assert np.abs(divergence(corrected, grid)).max() < 1e-11
    assert residual < 1e-10


def test_heat_sources_conserve_watts_with_subcell_geometry():
    grid = CFDGrid(1, 1, 1, 5, 4, 3)
    rack = CFDSource("thin rack", 0.12, 0.13, 0.14, 0.04, 0.07, 0.1, 2.5, 0.8)
    case = CFDCase(grid, CFDSettings(inlet_height_m=1), (rack,))
    heat, drag, weights = source_fields(case)
    assert heat.sum() * grid.cell_volume_m3 == pytest.approx(2500)
    assert drag.sum() * grid.cell_volume_m3 == pytest.approx(0.04 * 0.07 * 0.1 * 0.8)
    assert weights[0].sum() == pytest.approx(1)


def test_unheated_room_keeps_uniform_temperature_and_balances_flow():
    case = replace(small_case(), sources=())
    result = simulate_cfd(case)
    np.testing.assert_allclose(
        result.snapshots[-1].temperature_c, case.settings.supply_temperature_c
    )
    assert result.summary["max_divergence_per_s"] < 1e-10
    assert result.summary["max_mass_balance_error_m3_s"] < 1e-10
    assert result.snapshots[-1].time_s == case.settings.duration_s


def test_closed_adiabatic_uniform_heating_matches_exact_storage():
    grid = CFDGrid(2, 3, 4, 4, 4, 4)
    settings = CFDSettings(
        supply_flow_m3_s=0,
        viscosity_m2_s=0,
        diffusivity_m2_s=0,
        gravity_m_s2=0,
        duration_s=2,
        snapshot_interval_s=1,
    )
    case = CFDCase(grid, settings, (CFDSource("all air", 0, 0, 0, 2, 3, 4, 2, 0),))
    result = simulate_cfd(case)
    expected = 20 + 2000 * 2 / (1.2 * 1006 * 24)
    np.testing.assert_allclose(result.snapshots[-1].temperature_c, expected, atol=1e-12)
    assert result.history.stored_heat_j.iloc[-1] == pytest.approx(4000)
    assert result.history.cumulative_heat_out_j.iloc[-1] == 0


def test_ventilated_heat_pickup_matches_mass_flow_heat_capacity():
    grid = CFDGrid(1, 1, 1, 6, 3, 3)
    settings = CFDSettings(
        supply_flow_m3_s=1,
        inlet_height_m=1,
        density_kg_m3=1,
        cp_j_kg_k=1,
        viscosity_m2_s=0,
        diffusivity_m2_s=0,
        gravity_m_s2=0,
        duration_s=10,
        max_dt_s=0.02,
        snapshot_interval_s=5,
    )
    case = CFDCase(grid, settings, (CFDSource("uniform", 0, 0, 0, 1, 1, 1, 0.001, 0),))
    result = simulate_cfd(case)
    # 1 watt / (1 kg/m3 * 1 m3/s * 1 J/kg/K) = exactly 1 K return rise.
    np.testing.assert_allclose(result.snapshots[-1].temperature_c[-1], 21, atol=1e-6)
    assert result.history.boundary_heat_out_w.iloc[-1] == pytest.approx(1, abs=1e-6)


def test_analytical_diffusion_mode_improves_under_mesh_refinement():
    errors = []
    alpha, duration = 0.1, 0.2
    for nx in (8, 16, 32):
        grid = CFDGrid(1, 1, 1, nx, 3, 3)
        case = CFDCase(
            grid,
            CFDSettings(
                supply_flow_m3_s=0, inlet_height_m=1, diffusivity_m2_s=alpha, gravity_m_s2=0
            ),
        )
        x, _, _ = cell_coordinates(grid)
        mode = np.broadcast_to(np.sin(np.pi * x[:, None, None] / 2), grid.shape)
        temperature = 20 + mode.copy()
        dt = 0.02 * grid.spacing[0] ** 2 / alpha
        count = int(np.ceil(duration / dt))
        dt = duration / count
        for _ in range(count):
            temperature, _ = thermal_step(
                temperature, zero_velocity(grid), np.zeros(grid.shape), case, dt
            )
        exact = 20 + mode * np.exp(-alpha * (np.pi / 2) ** 2 * duration)
        errors.append(float(np.max(np.abs(temperature - exact))))
    assert errors[1] < errors[0] / 3.5
    assert errors[2] < errors[1] / 3.5


def test_buoyancy_changes_3d_airflow_and_coupled_energy_closes():
    case = small_case()
    result = simulate_cfd(case)
    no_gravity = simulate_cfd(replace(case, settings=replace(case.settings, gravity_m_s2=0)))
    assert (
        np.max(
            np.abs(result.snapshots[-1].velocity_m_s[2] - no_gravity.snapshots[-1].velocity_m_s[2])
        )
        > 0.01
    )
    assert result.summary["max_temperature_c"] > case.settings.supply_temperature_c + 1
    assert result.summary["max_divergence_per_s"] < 1e-10
    assert result.summary["relative_energy_balance_error"] < 1e-10
    assert result.history.thermal_cfl.max() <= 0.95
    assert not result.summary["steady_state_claimed"]
    assert len(result.rack_temperatures) == 8
    assert np.ptp(result.snapshots[-1].temperature_c, axis=2).max() > 0.1


def test_design_bridge_requires_explicit_heat_boundary():
    design = design_facility(
        DesignInputs(it_peak_kw=120, growth_fraction=0, rack_limit_kw=30, racks_per_row=2)
    )
    case = cfd_from_design(design, air_heat_fraction=0.15)
    assert sum(s.heat_kw for s in case.sources) == pytest.approx(18)
    assert case.grid.length_m == design.summary["hall_width_m"]
    assert len(case.sources) == 4
    with pytest.raises(ValueError):
        cfd_from_design(design, air_heat_fraction=1.1)


@pytest.mark.parametrize(
    "kwargs", [{"nx": 2}, {"nx": True}, {"width_m": 0}, {"nx": 100, "ny": 100, "nz": 100}]
)
def test_invalid_grids(kwargs):
    with pytest.raises(ValueError):
        CFDGrid(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_dt_s": 0},
        {"supply_flow_m3_s": -1},
        {"diffusivity_m2_s": float("nan")},
        {"cfl": 0.6},
        {"max_steps": True},
        {"supply_temperature_c": -273.15},
    ],
)
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        CFDSettings(**kwargs)


def test_bad_geometry_and_step_limit_fail_explicitly():
    base = small_case()
    with pytest.raises(ValueError, match="overlap"):
        replace(base, sources=(base.sources[0], replace(base.sources[0], name="duplicate")))
    with pytest.raises(ValueError, match="boundaries"):
        replace(base, sources=(replace(base.sources[0], x_m=100),))
    with pytest.raises(RuntimeError, match="max_steps"):
        simulate_cfd(replace(base, settings=replace(base.settings, max_steps=1)))


def test_exports_preserve_arrays_units_and_vtk_order(tmp_path):
    case = small_case()
    results = export_cfd_study(tmp_path, case, compare_airflow=False)
    result = results["Normal airflow"]
    assert load_cfd_case(tmp_path / "case-0-inputs.json") == case
    with np.load(tmp_path / "case-0-fields.npz") as arrays:
        np.testing.assert_array_equal(
            arrays["temperature_c"][-1], result.snapshots[-1].temperature_c
        )
        assert arrays["velocity_m_s"].shape == (3, 3, *case.grid.shape)
    vtk = write_vtk(result, tmp_path / "test.vtk").read_text().splitlines()
    start = vtk.index("LOOKUP_TABLE default") + 1
    count = np.prod(case.grid.shape)
    saved = np.array([float(v) for v in vtk[start : start + count]])
    np.testing.assert_allclose(saved, result.snapshots[-1].temperature_c.ravel(order="F"))
    figure = temperature_slice(result, height_m=1.1)
    assert np.asarray(figure.data[0].z).shape == (case.grid.ny, case.grid.nx)
    assert "__DATA__" not in (tmp_path / "cfd-3d.html").read_text()
