"""3D staggered-grid pressure projection coupled to conservative thermal transport.

The native solver advances incompressible momentum and temperature, not a fitted
heat map. It is first-order in time and upwind advection, with centred diffusion.
Rack envelopes are permeable heat/resistance zones. See the CFD guide for the
equations, numerical verification and the distinction from measured validation.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu

from datacenter_simulator.models.cfd import CFDCase, CFDGrid

Field = NDArray[np.float64]
Velocity = tuple[Field, Field, Field]


def cell_coordinates(grid: CFDGrid) -> tuple[Field, Field, Field]:
    """One-dimensional arrays of cell-centre x, y and z coordinates."""
    return tuple((np.arange(n) + 0.5) * h for n, h in zip(grid.shape, grid.spacing, strict=True))  # type: ignore[return-value]


def cell_velocity(velocity: Velocity) -> Velocity:
    u, v, w = velocity
    return (u[:-1] + u[1:]) / 2, (v[:, :-1] + v[:, 1:]) / 2, (w[:, :, :-1] + w[:, :, 1:]) / 2


def divergence(velocity: Velocity, grid: CFDGrid) -> Field:
    """Conservative face-flux divergence in 1/s."""
    result = np.zeros(grid.shape)
    for i, a in enumerate(velocity):
        result += np.diff(a, axis=i) / grid.spacing[i]
    return result


def _faces(field: Field, axis: int) -> Field:
    pad = [(0, 0)] * 3
    pad[axis] = (1, 1)
    padded = np.pad(field, pad, mode="edge")
    a, b = [slice(None)] * 3, [slice(None)] * 3
    a[axis], b[axis] = slice(None, -1), slice(1, None)
    return (padded[tuple(a)] + padded[tuple(b)]) / 2


def source_fields(case: CFDCase) -> tuple[Field, Field, list[Field]]:
    """Volume-overlap rasterization conserves each source's declared watts.

    The overlap fractions also weight drag and rack-zone air-temperature probes.
    A rack narrower than a cell is included, but is explicitly under-resolved.
    """
    heat = np.zeros(case.grid.shape)
    drag = np.zeros(case.grid.shape)
    weights = []
    for source in case.sources:
        overlaps = []
        for n, h, start, size in zip(
            case.grid.shape,
            case.grid.spacing,
            (source.x_m, source.y_m, source.z_m),
            (source.width_m, source.depth_m, source.height_m),
            strict=True,
        ):
            low = np.arange(n) * h
            overlaps.append(
                np.maximum(0, np.minimum(low + h, start + size) - np.maximum(low, start))
            )
        volume = (
            overlaps[0][:, None, None] * overlaps[1][None, :, None] * overlaps[2][None, None, :]
        )
        fraction = volume / case.grid.cell_volume_m3
        heat += source.heat_kw * 1000 * fraction / float(volume.sum())
        drag += source.drag_per_s * fraction
        weights.append(volume / float(volume.sum()))
    return heat, drag, weights


class PressureProjection:
    """Factorized -div(grad p) with Neumann walls and p=0 on the return face.

    Pressure is kinematic (m2/s2) during projection. The outlet cell centre is a
    half cell from the pressure boundary. The same discrete gradient/divergence
    pair constructs the matrix and corrects face velocities.
    """

    def __init__(self, grid: CFDGrid):
        self.grid = grid
        count = int(np.prod(grid.shape))
        ids = np.arange(count).reshape(grid.shape)
        diagonal = np.zeros(count)
        rows: list[int] = []
        columns: list[int] = []
        values: list[float] = []
        for axis, h in enumerate(grid.spacing):
            lo, hi = [slice(None)] * 3, [slice(None)] * 3
            lo[axis], hi[axis] = slice(None, -1), slice(1, None)
            left, right = ids[tuple(lo)].ravel(), ids[tuple(hi)].ravel()
            coefficient = 1 / h**2
            diagonal[left] += coefficient
            diagonal[right] += coefficient
            rows.extend(left.tolist() + right.tolist())
            columns.extend(right.tolist() + left.tolist())
            values.extend([-coefficient] * (2 * len(left)))
        diagonal[ids[-1].ravel()] += 2 / grid.spacing[0] ** 2
        rows.extend(range(count))
        columns.extend(range(count))
        values.extend(diagonal.tolist())
        self.matrix = coo_matrix((values, (rows, columns)), shape=(count, count)).tocsc()
        self.factor = splu(self.matrix)

    def project(self, velocity: Velocity, dt_s: float) -> tuple[Velocity, Field, float]:
        """Return divergence-free velocities, kinematic pressure and linear residual."""
        if not np.isfinite(dt_s) or dt_s <= 0:
            raise ValueError("projection time step must be positive and finite")
        rhs = -divergence(velocity, self.grid).ravel() / dt_s
        pressure = self.factor.solve(rhs)
        residual = float(np.max(np.abs(self.matrix @ pressure - rhs)))
        p = pressure.reshape(self.grid.shape)
        u, v, w = (a.copy() for a in velocity)
        dx, dy, dz = self.grid.spacing
        u[1:-1] -= dt_s * np.diff(p, axis=0) / dx
        u[-1] += 2 * dt_s * p[-1] / dx
        v[:, 1:-1] -= dt_s * np.diff(p, axis=1) / dy
        w[:, :, 1:-1] -= dt_s * np.diff(p, axis=2) / dz
        return (u, v, w), p, residual


def _supply(case: CFDCase) -> Field:
    _, dy, dz = case.grid.spacing
    low = np.arange(case.grid.nz) * dz
    fractions = np.clip((case.settings.inlet_height_m - low) / dz, 0, 1)
    open_area = float(fractions.sum()) * dz * case.grid.width_m
    return np.broadcast_to(
        fractions[None, :] * case.settings.supply_flow_m3_s / open_area,
        (case.grid.ny, case.grid.nz),
    ).copy()


def _boundary(velocity: Velocity, case: CFDCase, *, predict: bool) -> None:
    u, v, w = velocity
    u[0] = _supply(case)
    if predict:
        u[-1] = u[-2]  # predictor zero normal gradient, corrected by return pressure
    v[:, 0] = v[:, -1] = 0
    w[:, :, 0] = w[:, :, -1] = 0


def _momentum_rhs(
    field: Field, advectors: Velocity, axis: int, grid: CFDGrid, viscosity: float
) -> Field:
    rhs = np.zeros_like(field)
    for direction, h in enumerate(grid.spacing):
        pad = [(0, 0)] * 3
        pad[direction] = (1, 1)
        padded = np.pad(field, pad, mode="edge")
        # Tangential wall values use odd reflection (no slip). The return uses
        # zero-gradient extrapolation, including return backflow.
        if direction != axis:
            low: list[slice | int] = [slice(None)] * 3
            high: list[slice | int] = [slice(None)] * 3
            low[direction], high[direction] = 0, -1
            padded[tuple(low)] *= -1
            if direction != 0:
                padded[tuple(high)] *= -1
        lo, hi = [slice(None)] * 3, [slice(None)] * 3
        lo[direction], hi[direction] = slice(None, -2), slice(2, None)
        left, right = padded[tuple(lo)], padded[tuple(hi)]
        speed = advectors[direction]
        rhs -= speed * np.where(speed >= 0, (field - left) / h, (right - field) / h)
        rhs += viscosity * (left - 2 * field + right) / h**2
    return rhs


def thermal_step(
    temperature_c: Field, velocity: Velocity, heat_w_m3: Field, case: CFDCase, dt_s: float
) -> tuple[Field, float]:
    """Conservative upwind advection + centred diffusion; returns net outward W.

    Walls are adiabatic. Inlet is prescribed temperature; the return has zero
    diffusive flux and uses supply temperature for any inward advective flux.
    The budget includes conduction through the inlet as well as advection.
    """
    settings, grid = case.settings, case.grid
    theta = temperature_c - settings.supply_temperature_c
    fluxes = []
    for axis, h in enumerate(grid.spacing):
        flux = np.zeros_like(velocity[axis])
        lo, hi, mid = [slice(None)] * 3, [slice(None)] * 3, [slice(None)] * 3
        lo[axis], hi[axis], mid[axis] = slice(None, -1), slice(1, None), slice(1, -1)
        left, right, speed = theta[tuple(lo)], theta[tuple(hi)], velocity[axis][tuple(mid)]
        flux[tuple(mid)] = speed * np.where(speed >= 0, left, right)
        flux[tuple(mid)] -= settings.diffusivity_m2_s * (right - left) / h
        if axis == 0:
            u = velocity[0]
            fractions = np.clip(
                (settings.inlet_height_m - np.arange(grid.nz) * grid.spacing[2]) / grid.spacing[2],
                0,
                1,
            )
            flux[0] = u[0] * np.where(u[0] >= 0, 0, theta[0])
            flux[0] -= 2 * settings.diffusivity_m2_s * fractions[None, :] * theta[0] / h
            flux[-1] = u[-1] * np.where(u[-1] >= 0, theta[-1], 0)
        fluxes.append(flux)
    rho_cp = settings.density_kg_m3 * settings.cp_j_kg_k
    tendency = np.subtract(heat_w_m3 / rho_cp, divergence(tuple(fluxes), grid))  # type: ignore[arg-type]
    updated = temperature_c + dt_s * tendency
    net_out = float(
        (fluxes[0][-1].sum() - fluxes[0][0].sum()) * grid.spacing[1] * grid.spacing[2] * rho_cp
    )
    return updated, net_out


@dataclass
class CFDSnapshot:
    time_s: float
    temperature_c: Field
    velocity_m_s: Velocity  # cell-centred for visualization and export
    pressure_pa: Field


@dataclass
class CFDResult:
    case: CFDCase
    snapshots: list[CFDSnapshot]
    history: pd.DataFrame
    rack_temperatures: pd.DataFrame
    summary: dict[str, Any]


def simulate_cfd(case: CFDCase) -> CFDResult:
    """Integrate momentum, pressure projection and heat to the requested final time.

    Adaptive dt obeys advective/diffusive limits and snapshot times exactly.
    Buoyancy is explicit and rack drag is semi-implicit. The returned pressure
    excludes the hydrostatic reference. Finite duration never implies steady state.
    """
    grid, settings = case.grid, case.settings
    heat, drag, weights = source_fields(case)
    shapes = [
        (grid.nx + 1, grid.ny, grid.nz),
        (grid.nx, grid.ny + 1, grid.nz),
        (grid.nx, grid.ny, grid.nz + 1),
    ]
    velocity: Velocity = tuple(np.zeros(s) for s in shapes)  # type: ignore[assignment]
    projector = PressureProjection(grid)
    _boundary(velocity, case, predict=True)
    velocity, p, _ = projector.project(velocity, 1.0)
    temperature = np.full(grid.shape, settings.supply_temperature_c, dtype=float)
    snapshots = [
        CFDSnapshot(0, temperature.copy(), cell_velocity(velocity), p * settings.density_kg_m3)
    ]
    history: list[dict[str, float]] = []
    rack_rows = []
    time, next_snapshot, cumulative_out = (
        0.0,
        min(settings.snapshot_interval_s, settings.duration_s),
        0.0,
    )
    rho_cp = settings.density_kg_m3 * settings.cp_j_kg_k
    power = float(heat.sum() * grid.cell_volume_m3)
    drag_faces = tuple(_faces(drag, i) for i in range(3))
    for _ in range(settings.max_steps):
        cc = cell_velocity(velocity)
        rhs = []
        for axis, field in enumerate(velocity):
            adv = tuple(field if j == axis else _faces(cc[j], axis) for j in range(3))
            rhs.append(_momentum_rhs(field, adv, axis, grid, settings.viscosity_m2_s))  # type: ignore[arg-type]
        buoyancy = (
            settings.gravity_m_s2
            * settings.expansion_per_k
            * (temperature - settings.supply_temperature_c)
        )
        rhs[2] += _faces(buoyancy, 2)
        inverse_dt = sum(
            float(np.max(np.abs(a))) / h for a, h in zip(velocity, grid.spacing, strict=True)
        )
        inverse_dt += (
            2
            * max(settings.viscosity_m2_s, settings.diffusivity_m2_s)
            * sum(1 / h**2 for h in grid.spacing)
        )
        # Source acceleration guard, including buoyancy, limits new speeds.
        acceleration = sum(
            float(np.max(np.abs(a))) / h for a, h in zip(rhs, grid.spacing, strict=True)
        )
        dt = min(
            settings.max_dt_s,
            settings.cfl / max(inverse_dt, 1e-12),
            np.sqrt(settings.cfl / max(acceleration, 1e-12)),
            next_snapshot - time,
        )
        predicted: Velocity = tuple(
            (a + dt * b) / (1 + dt * d) for a, b, d in zip(velocity, rhs, drag_faces, strict=True)
        )  # type: ignore[assignment]
        _boundary(predicted, case, predict=True)
        corrected, p, linear_residual = projector.project(predicted, dt)
        # Check the actual projected fluxes, which can exceed the predictor CFL.
        thermal_rate = sum(
            float(np.max(np.abs(a))) / h for a, h in zip(corrected, grid.spacing, strict=True)
        ) + 4 * settings.diffusivity_m2_s * sum(1 / h**2 for h in grid.spacing)
        if dt * thermal_rate > 0.95:
            raise RuntimeError("projected thermal CFL exceeded; reduce max_dt_s or cfl")
        updated, boundary_w = thermal_step(temperature, corrected, heat, case, dt)
        if not np.isfinite(updated).all() or any(not np.isfinite(a).all() for a in corrected):
            raise RuntimeError("non-finite CFD fields; inspect grid, time step and physical inputs")
        time += dt
        cumulative_out += boundary_w * dt
        stored = float(
            (updated - settings.supply_temperature_c).sum() * grid.cell_volume_m3 * rho_cp
        )
        div = float(np.max(np.abs(divergence(corrected, grid))))
        outlet_flow = float(corrected[0][-1].sum() * grid.spacing[1] * grid.spacing[2])
        history.append(
            {
                "time_s": time,
                "dt_s": dt,
                "max_temperature_c": float(np.max(updated)),
                "mean_temperature_c": float(updated.mean()),
                "max_temperature_change_k_s": float(np.max(np.abs(updated - temperature))) / dt,
                "max_divergence_per_s": div,
                "pressure_linear_residual": linear_residual,
                "outlet_flow_m3_s": outlet_flow,
                "mass_balance_error_m3_s": outlet_flow - settings.supply_flow_m3_s,
                "return_backflow_m3_s": float(
                    -np.minimum(corrected[0][-1], 0).sum() * grid.spacing[1] * grid.spacing[2]
                ),
                "heat_source_w": power,
                "boundary_heat_out_w": boundary_w,
                "stored_heat_j": stored,
                "cumulative_heat_out_j": cumulative_out,
                "energy_balance_error_j": stored + cumulative_out - power * time,
                "thermal_cfl": dt * thermal_rate,
            }
        )
        temperature, velocity = updated, corrected
        if time >= next_snapshot - 1e-9:
            snapshots.append(
                CFDSnapshot(
                    time, temperature.copy(), cell_velocity(velocity), p * settings.density_kg_m3
                )
            )
            for source, weight in zip(case.sources, weights, strict=True):
                rack_rows.append(
                    {
                        "time_s": time,
                        "rack": source.name,
                        "zone_mean_c": float((weight * temperature).sum()),
                        "zone_max_c": float(np.max(temperature[weight > 0])),
                    }
                )
            if time >= settings.duration_s - 1e-9:
                break
            next_snapshot = min(next_snapshot + settings.snapshot_interval_s, settings.duration_s)
    else:
        raise RuntimeError("CFD max_steps reached before final time; increase max_steps")
    table = pd.DataFrame(history)
    scale = max(power * time, 1)
    warnings = [
        "Research CFD: constant effective mixing coefficients; no calibrated turbulence closure.",
        "Rack-zone values are air temperatures, not server silicon or equipment surfaces.",
    ]
    if any(
        min(s.width_m / grid.spacing[0], s.depth_m / grid.spacing[1], s.height_m / grid.spacing[2])
        < 2
        for s in case.sources
    ):
        warnings.append(
            "At least one rack has fewer than two cells across a dimension; refine the mesh."
        )
    if (
        settings.expansion_per_k
        * float(np.max(np.abs(temperature - settings.supply_temperature_c)))
        > 0.1
    ):
        warnings.append(
            "Temperature excursion exceeds the 10% Boussinesq density-variation screening limit."
        )
    if table.return_backflow_m3_s.max() > 1e-8:
        warnings.append(
            "Return backflow occurred; its prescribed temperature equals the supply temperature."
        )
    summary: dict[str, Any] = {
        "solver": "3D incompressible Boussinesq staggered-grid pressure projection",
        "cells": int(np.prod(grid.shape)),
        "steps": len(history),
        "duration_s": time,
        "air_heat_kw": power / 1000,
        "supply_flow_m3_s": settings.supply_flow_m3_s,
        "max_temperature_c": float(np.max(temperature)),
        "mean_temperature_c": float(temperature.mean()),
        "max_divergence_per_s": float(table.max_divergence_per_s.max()),
        "max_mass_balance_error_m3_s": float(table.mass_balance_error_m3_s.abs().max()),
        "relative_energy_balance_error": float(table.energy_balance_error_j.abs().max() / scale),
        "final_temperature_change_k_s": float(table.max_temperature_change_k_s.iloc[-1]),
        "steady_state_claimed": False,
        "warnings": warnings,
    }
    return CFDResult(
        case,
        snapshots,
        table,
        pd.DataFrame(rack_rows, columns=["time_s", "rack", "zone_mean_c", "zone_max_c"]),
        summary,
    )
