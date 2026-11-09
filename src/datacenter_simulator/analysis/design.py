"""Run a configurable facility design and export its offline comparison workbench."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from datacenter_simulator.methods.cooling import cooling_alternatives
from datacenter_simulator.methods.facility_design import (
    FacilityDesign,
    annual_design_energy,
    design_balance,
    design_facility,
)
from datacenter_simulator.models.design import CoolingTechnology, DesignInputs, OperatingBin
from datacenter_simulator.use_cases.design import design_evidence, illustrative_operating_bins


@dataclass
class DesignStudy:
    design: FacilityDesign
    bins: tuple[OperatingBin, ...]
    operating: pd.DataFrame
    summary: dict[str, float]
    load_sweep: pd.DataFrame


def design_study(
    inputs: DesignInputs | None = None, bins: Sequence[OperatingBin] | None = None
) -> DesignStudy:
    """Calculate peak sizing, annual energy and a fixed-plant load sensitivity."""
    design = design_facility(inputs)
    bins = tuple(illustrative_operating_bins() if bins is None else bins)
    operating, annual = annual_design_energy(design, bins)
    rows = []
    for load in np.linspace(0.1, 1, 19):
        power = design_balance(
            design.inputs,
            design.plant,
            design.summary["design_it_kw"] * float(load),
            design.inputs.design_ambient_c,
        )
        rows.append({"load_fraction": float(load), **power})
    return DesignStudy(design, bins, operating, {**design.summary, **annual}, pd.DataFrame(rows))


def compare_designs(study: DesignStudy) -> dict[str, DesignStudy]:
    """Five cooling presets × three capacity arrangements at identical IT demand.

    Keep the selected baseline first. Each variant is independently sized; the
    resulting annual differences are estimates from uncalibrated cooling curves.
    """
    case = study.design.inputs
    studies = {f"{case.cooling} / {case.redundancy}": study}
    for cooling in cooling_alternatives():
        for redundancy in ("N", "N+1", "2N"):
            label = f"{cooling} / {redundancy}"
            if label not in studies:
                # Dataclass validation verifies the names before any calculation.
                inputs = replace(
                    case, cooling=cast(CoolingTechnology, cooling), redundancy=redundancy
                )
                studies[label] = design_study(inputs, study.bins)
    return studies


def export_design_study(
    output: str | Path,
    inputs: DesignInputs | None = None,
    bins: Sequence[OperatingBin] | None = None,
) -> DesignStudy:
    """Export editable inputs, numerical audit files and an offline Plotly report."""
    from datacenter_simulator.utilities.design import write_design_report

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    study = design_study(inputs, bins)
    studies = compare_designs(study)
    comparison = pd.DataFrame([{"scenario": name, **s.summary} for name, s in studies.items()])
    for name, frame in (
        ("equipment", study.design.equipment),
        ("racks", study.design.racks),
        ("operating", study.operating),
        ("load_sweep", study.load_sweep),
        ("comparison", comparison),
    ):
        frame.to_csv(output / f"{name}.csv", index=False)
    scenarios = {
        name: {
            "inputs": asdict(s.design.inputs),
            "summary": s.summary,
            "balance": s.design.balance,
            "equipment": s.design.equipment.to_dict("records"),
        }
        for name, s in studies.items()
    }
    for name, data in (
        ("inputs", asdict(study.design.inputs)),
        ("bins", [asdict(b) for b in study.bins]),
        ("summary", study.summary),
        ("balance", study.design.balance),
        ("evidence", design_evidence()),
        ("scenarios", scenarios),
    ):
        (output / f"{name}.json").write_text(
            json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    write_design_report(studies, output / "design-workbench.html")
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/design"))
    parser.add_argument("--inputs", type=Path, help="JSON object of DesignInputs overrides")
    parser.add_argument("--bins", type=Path, help="JSON array of operating bins totaling 8760 h")
    parser.add_argument("--it-kw", type=float, help="Override current IT peak from inputs")
    args = parser.parse_args()
    values = {} if args.inputs is None else json.loads(args.inputs.read_text(encoding="utf-8"))
    if args.it_kw is not None:
        values["it_peak_kw"] = args.it_kw
    try:
        inputs = DesignInputs(**values)
        bins = (
            None
            if args.bins is None
            else [OperatingBin(**b) for b in json.loads(args.bins.read_text(encoding="utf-8"))]
        )
        study = export_design_study(args.output, inputs, bins)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(study.summary, indent=2))
    print(f"Report: {args.output / 'design-workbench.html'}")


if __name__ == "__main__":
    main()
