"""Run separate mesh, time-step and physical-input sensitivity studies."""

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from datacenter_simulator.analysis.cfd import load_cfd_case
from datacenter_simulator.methods.cfd import simulate_cfd
from datacenter_simulator.methods.verification import richardson_gci
from datacenter_simulator.models.cfd import CFDCase
from datacenter_simulator.use_cases.cfd import reference_cfd_case


def accuracy_study(case: CFDCase, *, coarse: tuple[int, int, int] = (6, 4, 3)) -> dict[str, Any]:
    """Same physical case/time on 1x/2x/4x meshes and three time-step caps.

    Peak and volume-mean temperature rise are evaluated. Scalar GCI estimates
    are conditional on monotonic asymptotic convergence; no mesh-independent
    or measured-accuracy claim is made. Refine vents and rack shapes separately.
    """
    mesh, time_rows, sensitivity = [], [], []

    def row(solved: Any) -> dict[str, float]:
        return {
            "cells": solved.summary["cells"],
            "peak_rise_k": solved.summary["max_temperature_c"] - case.settings.supply_temperature_c,
            "mean_rise_k": solved.summary["mean_temperature_c"]
            - case.settings.supply_temperature_c,
            "actual_max_dt_s": float(solved.history.dt_s.max()),
            "final_change_k_s": solved.summary["final_temperature_change_k_s"],
            "energy_error_fraction": solved.summary["relative_energy_balance_error"],
        }

    for factor in (1, 2, 4):
        g = replace(case.grid, nx=coarse[0] * factor, ny=coarse[1] * factor, nz=coarse[2] * factor)
        solved = simulate_cfd(replace(case, grid=g))
        mesh.append({"spacing_m": float(np.cbrt(g.cell_volume_m3)), **row(solved)})
    # Use the middle mesh for time and physical-input sensitivity, keeping their roles distinct.
    grid = replace(case.grid, nx=coarse[0] * 2, ny=coarse[1] * 2, nz=coarse[2] * 2)
    middle = replace(case, grid=grid)
    for time_factor in (1, 0.5, 0.25):
        cap = case.settings.max_dt_s * time_factor
        solved = simulate_cfd(replace(middle, settings=replace(case.settings, max_dt_s=cap)))
        time_rows.append({"requested_max_dt_s": cap, **row(solved)})
    variations = {
        "heat -20%": replace(
            middle, sources=tuple(replace(s, heat_kw=0.8 * s.heat_kw) for s in case.sources)
        ),
        "heat +20%": replace(
            middle, sources=tuple(replace(s, heat_kw=1.2 * s.heat_kw) for s in case.sources)
        ),
        "airflow -20%": replace(
            middle,
            settings=replace(case.settings, supply_flow_m3_s=0.8 * case.settings.supply_flow_m3_s),
        ),
        "airflow +20%": replace(
            middle,
            settings=replace(case.settings, supply_flow_m3_s=1.2 * case.settings.supply_flow_m3_s),
        ),
        "mixing x0.5": replace(
            middle,
            settings=replace(
                case.settings,
                viscosity_m2_s=0.5 * case.settings.viscosity_m2_s,
                diffusivity_m2_s=0.5 * case.settings.diffusivity_m2_s,
            ),
        ),
        "mixing x2": replace(
            middle,
            settings=replace(
                case.settings,
                viscosity_m2_s=2 * case.settings.viscosity_m2_s,
                diffusivity_m2_s=2 * case.settings.diffusivity_m2_s,
            ),
        ),
    }
    for name, varied in variations.items():
        sensitivity.append({"case": name, **row(simulate_cfd(varied))})
    gci = {
        key: richardson_gci([r[key] for r in mesh], [r["spacing_m"] for r in mesh])
        for key in ("peak_rise_k", "mean_rise_k")
    }
    return {
        "duration_s": case.settings.duration_s,
        "thermal_scheme": case.settings.thermal_scheme,
        "mesh": mesh,
        "time_steps": time_rows,
        "input_sensitivity": sensitivity,
        "gci": gci,
        "time_caps_effective": all(
            np.isclose(r["actual_max_dt_s"], r["requested_max_dt_s"]) for r in time_rows
        ),
        "interpretation": "Discretization and input sensitivity only. No measured validation, "
        "steady-state or mesh-independence claim. GCI excludes model error.",
    }


def export_accuracy_study(output: str | Path, case: CFDCase | None = None) -> dict[str, Any]:
    if case is None:
        base = reference_cfd_case()
        case = replace(base, settings=replace(base.settings, duration_s=20, snapshot_interval_s=10))
    result = accuracy_study(case)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "accuracy.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    for key in ("mesh", "time_steps", "input_sensitivity"):
        pd.DataFrame(result[key]).to_csv(output / f"{key}.csv", index=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/cfd-accuracy")
    parser.add_argument("--inputs")
    args = parser.parse_args()
    result = export_accuracy_study(args.output, load_cfd_case(args.inputs) if args.inputs else None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
