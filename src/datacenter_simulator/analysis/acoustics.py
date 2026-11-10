"""Run and export reproducible octave-band 3D acoustic studies."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from datacenter_simulator.methods.acoustics import (
    AcousticResult,
    simulate_noise,
    validate_noise_receivers,
)
from datacenter_simulator.methods.cfd import cell_coordinates
from datacenter_simulator.models.acoustics import (
    OCTAVE_HZ,
    AcousticCase,
    AcousticReceiver,
    AcousticSettings,
    AcousticSource,
)
from datacenter_simulator.models.cfd import CFDGrid
from datacenter_simulator.use_cases.acoustics import (
    acoustic_evidence,
    noise_scenarios,
    reference_noise_case,
)
from datacenter_simulator.utilities.acoustics import write_noise_report


def load_noise_case(path: str | Path) -> AcousticCase:
    raw = json.loads(Path(path).read_text())
    if set(raw) != {"grid", "settings", "sources", "receivers"}:
        raise ValueError("noise JSON requires grid, settings, sources, receivers")
    settings = raw["settings"]
    if "surface_absorption" in settings:
        settings["surface_absorption"] = tuple(tuple(row) for row in settings["surface_absorption"])
    if settings.get("background_db") is not None:
        settings["background_db"] = tuple(settings["background_db"])
    sources = []
    for source in raw["sources"]:
        source["sound_power_db"] = tuple(source["sound_power_db"])
        if "insertion_loss_db" in source:
            source["insertion_loss_db"] = tuple(source["insertion_loss_db"])
        sources.append(AcousticSource(**source))
    return AcousticCase(
        CFDGrid(**raw["grid"]),
        AcousticSettings(**settings),
        tuple(sources),
        tuple(AcousticReceiver(**row) for row in raw["receivers"]),
    )


def export_noise_study(
    output: str | Path,
    case: AcousticCase | None = None,
    *,
    compare: bool = True,
    samples: int = 2000,
) -> dict[str, AcousticResult]:
    case = reference_noise_case() if case is None else case
    cases = noise_scenarios(case) if compare else {"Baseline": case}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    results, downloads = {}, []
    for i, (name, inputs) in enumerate(cases.items()):
        result = simulate_noise(inputs, samples=samples)
        results[name] = result
        stem = f"noise-{i}"
        for suffix, data in (("inputs", asdict(inputs)), ("summary", result.summary)):
            filename = f"{stem}-{suffix}.json"
            (output / filename).write_text(json.dumps(data, indent=2, allow_nan=False))
            downloads.append(filename)
        for suffix, table in (
            ("receivers", result.receivers),
            ("sources", result.contributions),
            ("room", result.room),
        ):
            filename = f"{stem}-{suffix}.csv"
            table.to_csv(output / filename, index=False)
            downloads.append(filename)
        x, y, z = cell_coordinates(inputs.grid)
        np.savez_compressed(
            output / f"{stem}-fields.npz",
            x_m=x,
            y_m=y,
            z_m=z,
            frequency_hz=OCTAVE_HZ,
            band_spl_db=result.band_spl_db,
            laeq_dba=result.laeq_dba,
            valid=result.valid,
        )
        downloads.append(f"{stem}-fields.npz")
        gx, gy, gz = np.meshgrid(x, y, z, indexing="ij")
        cells = pd.DataFrame(
            {
                "x_m": gx.ravel(),
                "y_m": gy.ravel(),
                "z_m": gz.ravel(),
                "valid": result.valid.ravel(),
                "laeq_dba": result.laeq_dba.ravel(),
            }
        )
        for band, f in enumerate(OCTAVE_HZ):
            cells[f"lp_{f}_hz_db"] = result.band_spl_db[..., band].ravel()
        cells.to_csv(output / f"{stem}-cells.csv", index=False)
        downloads.append(f"{stem}-cells.csv")
        g = inputs.grid
        vtk = [
            "# vtk DataFile Version 3.0",
            "Octave-band acoustic energy model; excluded points are NaN",
            "ASCII",
            "DATASET STRUCTURED_POINTS",
            f"DIMENSIONS {g.nx} {g.ny} {g.nz}",
            f"ORIGIN {x[0]} {y[0]} {z[0]}",
            "SPACING " + " ".join(map(str, g.spacing)),
            f"POINT_DATA {g.nx * g.ny * g.nz}",
            "SCALARS LAeq_dBA float 1",
            "LOOKUP_TABLE default",
        ]
        vtk.extend(str(v) for v in result.laeq_dba.ravel(order="F"))
        vtk.extend(["SCALARS valid int 1", "LOOKUP_TABLE default"])
        vtk.extend(str(int(v)) for v in result.valid.ravel(order="F"))
        (output / f"{stem}-field.vtk").write_text("\n".join(vtk) + "\n")
        downloads.append(f"{stem}-field.vtk")
    (output / "acoustic-evidence.json").write_text(json.dumps(acoustic_evidence(), indent=2))
    downloads.append("acoustic-evidence.json")
    write_noise_report(results, output / "noise-3d.html", downloads)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/noise")
    parser.add_argument("--inputs")
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument(
        "--measurements", help="CSV with receiver,observed_dba for matched operation"
    )
    args = parser.parse_args()
    case = load_noise_case(args.inputs) if args.inputs else None
    results = export_noise_study(args.output, case, compare=not args.single, samples=args.samples)
    if args.measurements:
        table, metrics = validate_noise_receivers(
            results["Baseline"], pd.read_csv(args.measurements)
        )
        table.to_csv(Path(args.output) / "measurement-comparison.csv", index=False)
        (Path(args.output) / "measurement-metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({name: r.summary for name, r in results.items()}, indent=2))
    print(f"Report: {Path(args.output) / 'noise-3d.html'}")


if __name__ == "__main__":
    main()
