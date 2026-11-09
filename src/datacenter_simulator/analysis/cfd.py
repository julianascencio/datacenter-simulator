"""Run, compare and export native 3D room airflow/heat simulations."""

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from datacenter_simulator.methods.cfd import CFDResult, cell_coordinates, simulate_cfd
from datacenter_simulator.models.cfd import CFDCase, CFDGrid, CFDSettings, CFDSource
from datacenter_simulator.use_cases.cfd import airflow_scenarios, cfd_evidence, reference_cfd_case


def load_cfd_case(path: str | Path) -> CFDCase:
    """Load the exact exported JSON schema; dataclasses reject invalid inputs."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(raw) != {"grid", "settings", "sources"}:
        raise ValueError("CFD inputs require exactly grid, settings and sources")
    return CFDCase(
        CFDGrid(**raw["grid"]),
        CFDSettings(**raw["settings"]),
        tuple(CFDSource(**s) for s in raw["sources"]),
    )


def mesh_sensitivity(result: CFDResult) -> pd.DataFrame:
    """Same physical inputs/time on approximately 0.5x, 1x and 1.5x cell counts.

    This reports sensitivity, not a convergence-order or mesh-independence claim.
    Each mesh resolves the inlet and source overlaps conservatively.
    """
    rows = []
    for factor in (0.5, 1.0, 1.5):
        counts = tuple(max(3, round(n * factor)) for n in result.case.grid.shape)
        grid = replace(result.case.grid, nx=counts[0], ny=counts[1], nz=counts[2])
        case = replace(result.case, grid=grid)
        solved = result if factor == 1 else simulate_cfd(case)
        rows.append(
            {
                "nx": grid.nx,
                "ny": grid.ny,
                "nz": grid.nz,
                "cells": solved.summary["cells"],
                "max_temperature_c": solved.summary["max_temperature_c"],
                "mean_temperature_c": solved.summary["mean_temperature_c"],
                "final_temperature_change_k_s": solved.summary["final_temperature_change_k_s"],
                "energy_error_fraction": solved.summary["relative_energy_balance_error"],
            }
        )
    return pd.DataFrame(rows)


def write_vtk(result: CFDResult, path: str | Path) -> Path:
    """Export final cell centres as a legacy VTK structured-point dataset.

    ParaView/VTK point ordering has x varying fastest, so arrays are flattened
    in Fortran order. Temperature and pressure retain physical units.
    """
    grid = result.case.grid
    final = result.snapshots[-1]
    h = grid.spacing
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        stream.write("# vtk DataFile Version 3.0\nData center CFD cell centres\nASCII\n")
        stream.write(f"DATASET STRUCTURED_POINTS\nDIMENSIONS {grid.nx} {grid.ny} {grid.nz}\n")
        stream.write(f"ORIGIN {h[0] / 2} {h[1] / 2} {h[2] / 2}\nSPACING {h[0]} {h[1]} {h[2]}\n")
        stream.write(f"POINT_DATA {np.prod(grid.shape)}\n")
        for name, field in (
            ("temperature_c", final.temperature_c),
            ("pressure_pa", final.pressure_pa),
        ):
            stream.write(f"SCALARS {name} double 1\nLOOKUP_TABLE default\n")
            np.savetxt(stream, field.ravel(order="F"), fmt="%.10g")
        stream.write("VECTORS velocity_m_s double\n")
        np.savetxt(
            stream, np.column_stack([v.ravel(order="F") for v in final.velocity_m_s]), fmt="%.10g"
        )
    return path


def export_cfd_study(
    output: str | Path,
    case: CFDCase | None = None,
    *,
    compare_airflow: bool = True,
    check_mesh: bool = False,
) -> dict[str, CFDResult]:
    """Write offline 3D report, full transient NPZ, final VTK/CSV and audit tables."""
    from datacenter_simulator.utilities.cfd import write_cfd_report

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    case = reference_cfd_case() if case is None else case
    cases = airflow_scenarios(case) if compare_airflow else {"Normal airflow": case}
    results = {name: simulate_cfd(spec) for name, spec in cases.items()}
    downloads = []
    for index, result in enumerate(results.values()):
        stem = f"case-{index}"
        coords = cell_coordinates(result.case.grid)
        xyz = np.meshgrid(*coords, indexing="ij")
        final = result.snapshots[-1]
        for suffix, value in (("inputs", asdict(result.case)), ("summary", result.summary)):
            filename = f"{stem}-{suffix}.json"
            (output / filename).write_text(
                json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
            downloads.append(filename)
        for suffix, frame in (("history", result.history), ("rack-air", result.rack_temperatures)):
            filename = f"{stem}-{suffix}.csv"
            frame.to_csv(output / filename, index=False)
            downloads.append(filename)
        data = {k: a.ravel() for k, a in zip(("x_m", "y_m", "z_m"), xyz, strict=True)}
        data.update(
            {"temperature_c": final.temperature_c.ravel(), "pressure_pa": final.pressure_pa.ravel()}
        )
        data.update(
            {
                k: a.ravel()
                for k, a in zip(("u_m_s", "v_m_s", "w_m_s"), final.velocity_m_s, strict=True)
            }
        )
        pd.DataFrame(data).to_csv(output / f"{stem}-cells.csv", index=False)
        downloads.append(f"{stem}-cells.csv")
        np.savez_compressed(
            output / f"{stem}-fields.npz",
            x_m=coords[0],
            y_m=coords[1],
            z_m=coords[2],
            time_s=[s.time_s for s in result.snapshots],
            temperature_c=np.stack([s.temperature_c for s in result.snapshots]),
            pressure_pa=np.stack([s.pressure_pa for s in result.snapshots]),
            velocity_m_s=np.stack([s.velocity_m_s for s in result.snapshots]),
        )
        downloads.append(f"{stem}-fields.npz")
        write_vtk(result, output / f"{stem}-final.vtk")
        downloads.append(f"{stem}-final.vtk")
    comparison = pd.DataFrame(
        [
            {"scenario": name, **{k: v for k, v in r.summary.items() if k != "warnings"}}
            for name, r in results.items()
        ]
    )
    comparison.to_csv(output / "comparison.csv", index=False)
    downloads.append("comparison.csv")
    mesh = mesh_sensitivity(next(iter(results.values()))) if check_mesh else pd.DataFrame()
    if check_mesh:
        mesh.to_csv(output / "mesh-sensitivity.csv", index=False)
        downloads.append("mesh-sensitivity.csv")
    (output / "evidence.json").write_text(
        json.dumps(cfd_evidence(), indent=2) + "\n", encoding="utf-8"
    )
    downloads.append("evidence.json")
    write_cfd_report(results, output / "cfd-3d.html", downloads=downloads, mesh=mesh)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/cfd"))
    parser.add_argument("--inputs", type=Path, help="Exported case inputs JSON")
    parser.add_argument("--seconds", type=float, help="Simulation duration")
    parser.add_argument("--flow", type=float, help="Supply volume flow in m3/s")
    parser.add_argument("--grid", type=int, nargs=3, metavar=("NX", "NY", "NZ"))
    parser.add_argument(
        "--mesh-study", action="store_true", help="Run coarse/base/fine sensitivity"
    )
    parser.add_argument("--single", action="store_true", help="Skip half-airflow comparison")
    args = parser.parse_args()
    try:
        case = reference_cfd_case() if args.inputs is None else load_cfd_case(args.inputs)
        if args.seconds is not None:
            case = replace(case, settings=replace(case.settings, duration_s=args.seconds))
        if args.flow is not None:
            case = replace(case, settings=replace(case.settings, supply_flow_m3_s=args.flow))
        if args.grid is not None:
            case = replace(
                case, grid=replace(case.grid, nx=args.grid[0], ny=args.grid[1], nz=args.grid[2])
            )
        results = export_cfd_study(
            args.output, case, compare_airflow=not args.single, check_mesh=args.mesh_study
        )
    except (TypeError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps({name: r.summary for name, r in results.items()}, indent=2))
    print(f"Report: {args.output / 'cfd-3d.html'}")


if __name__ == "__main__":
    main()
