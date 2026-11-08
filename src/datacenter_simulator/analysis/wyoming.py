"""Run and export the Wyoming planning and operational grid-management exercise."""

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.grid_management import (
    GridManagementResult,
    contingency_screen,
    optimize_grid,
)
from datacenter_simulator.methods.project_recovery import (
    capacity_sensitivity,
    cost_screen,
    emissions,
    simulate_case,
    validate_recovery_inputs,
)
from datacenter_simulator.models.grid_management import GridPolicy
from datacenter_simulator.use_cases.wyoming import (
    wyoming_generators,
    wyoming_inputs,
    wyoming_outages,
    wyoming_profiles,
    wyoming_sources,
)


def recovery_study(cfg: dict[str, Any] | None = None) -> dict[str, pd.DataFrame]:
    """Reproduce four commissioning cases and the original carbon/cost sensitivities."""
    cfg = wyoming_inputs() if cfg is None else cfg
    validate_recovery_inputs(cfg)
    monthly, summary = [], []
    for name, staged, extra, delayed in [
        ("A_build_ahead", False, False, False),
        ("B_power_gated", True, False, False),
        ("C_power_gated_plus_firm", True, True, False),
        ("D_delayed_recovery", True, True, True),
    ]:
        rows, stats = simulate_case(cfg, name, staged, extra, delayed)
        monthly.extend(rows)
        summary.append(stats)
    carbon = []
    for name, fc, ccgt, penalty in [
        ("No_capture", 0, 0, 0),
        ("Fuel_cells_only", cfg["capture_fraction"], 0, cfg["fuel_cell_capture_energy_penalty"]),
        (
            "Fuel_cells_and_CCGT_optimistic",
            cfg["capture_fraction"],
            cfg["capture_fraction"],
            cfg["fuel_cell_capture_energy_penalty"],
        ),
    ]:
        carbon.append({"case": name, **emissions(cfg, fc, ccgt, penalty)})
    return {
        "monthly": pd.DataFrame(monthly),
        "summary": pd.DataFrame(summary),
        "emissions": pd.DataFrame(carbon),
        "capacity_sensitivity": pd.DataFrame(capacity_sensitivity(cfg)),
        "cost_sensitivity": pd.DataFrame(cost_screen(cfg)),
    }


def grid_management_study() -> dict[str, GridManagementResult]:
    """Compare a turbine trip with storage and utility/fuel common-mode failures.

    Start at steady dispatch to isolate the outage test from a cold-start test.
    The 1 GWh / 200 MW battery is hypothetical and is not a claimed project asset.
    """
    profiles = wyoming_profiles()
    generators = tuple(
        replace(g, initial_output_kw=min(g.net_capacity_kw, 100000)) for g in wyoming_generators()
    )
    battery = Battery(1_000_000, 200_000, 200_000, initial_soc=0.7)
    events = wyoming_outages(pd.DatetimeIndex(profiles.index))
    runs = {}
    for name in (
        "normal",
        "generator_trip",
        "trip_with_storage",
        "utility_path_loss",
        "common_gas_loss",
    ):
        event_name = "generator_trip" if name == "trip_with_storage" else name
        runs[name] = optimize_grid(
            profiles,
            generators,
            battery=battery if name not in {"normal", "generator_trip"} else None,
            outages=events[event_name],
            policy=GridPolicy(carbon_price_per_kg=0.05),
        )
    return runs


def export_wyoming_study(output: str | Path, cfg: dict[str, Any] | None = None) -> Path:
    """Export editable inputs, provenance, CSVs and an offline Plotly comparison.

    Custom inputs change the monthly planning study. The operational study explicitly
    remains the documented default fixture; its inputs are exported separately.
    """
    from datacenter_simulator.utilities.grid_management import write_grid_report

    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    inputs = wyoming_inputs() if cfg is None else cfg
    planning = recovery_study(inputs)
    runs = grid_management_study()
    for name, frame in planning.items():
        frame.to_csv(destination / f"recovery_{name}.csv", index=False)
    for name, result in runs.items():
        result.timeseries.to_csv(destination / f"grid_{name}.csv", index_label="timestamp")
        result.generators_kw.to_csv(destination / f"generation_{name}.csv", index_label="timestamp")
        result.available_kw.to_csv(
            destination / f"availability_{name}.csv", index_label="timestamp"
        )
    pd.DataFrame({name: result.summary for name, result in runs.items()}).T.to_csv(
        destination / "grid_summary.csv", index_label="case"
    )
    cfg_default = wyoming_inputs()
    contingency_screen(wyoming_generators(), 1_800_000, grid_limit_kw=26_000 * 0.95).to_csv(
        destination / "grid_contingencies.csv", index=False
    )
    wyoming_profiles().to_csv(destination / "grid_default_profiles.csv", index_label="timestamp")
    (destination / "recovery_inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    (destination / "grid_default_inputs.json").write_text(json.dumps(cfg_default, indent=2) + "\n")
    (destination / "sources.json").write_text(json.dumps(wyoming_sources(), indent=2) + "\n")
    (destination / "model_boundaries.json").write_text(
        json.dumps(
            {
                "status": "Illustrative scenarios; operational success is unproven",
                "planning": "MW/MWh; monthly, staged investment with perfect milestone knowledge",
                "operation": "kW/kWh; single-bus, perfect-foresight MILP; default case inputs",
                "storage": "Hypothetical 1 GWh / 200 MW; initial SOC 0.7; final SOC at least 0.7",
                "exclusions": [
                    "AC power flow",
                    "frequency/transient stability",
                    "unit startup and min-up/down",
                    "upstream methane",
                    "profit/IRR",
                    "forecast accuracy",
                    "actual hardware throughput",
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return write_grid_report(runs, planning, destination / "wyoming-grid-management.html")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/wyoming")
    parser.add_argument("--inputs", type=Path, help="Optional monthly planning inputs JSON")
    args = parser.parse_args(argv)
    cfg = json.loads(args.inputs.read_text()) if args.inputs is not None else None
    print(export_wyoming_study(args.output, cfg).resolve())


if __name__ == "__main__":
    main()
