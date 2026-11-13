"""Reproducible 800 VDC migration, backup and fault-energy sensitivity study."""

import argparse
import json
from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from pathlib import Path

import pandas as pd

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
    PowerStudyInputs,
)
from datacenter_simulator.use_cases.power_architecture import illustrative_power_architectures

# Independent illustrative fault domain, not scaled with the hall's IT demand.
FAULT_CLEARING_TIMES_S = (0.00005, 0.0005, 0.005, 0.020)
FAULT_ASSUMPTIONS: dict[str, float] = {
    "voltage_v": 800.0,
    "horizon_s": 0.020,
    "local_capacitance_f": 0.010,
    "local_loop_resistance_ohm": 0.050,
    "remote_capacitance_f": 0.030,
    "remote_loop_resistance_ohm": 0.100,
    "converter_current_limit_a": 2000.0,
    "storage_current_limit_a": 1000.0,
    "storage_available_energy_j": 100000.0,
}


@dataclass
class PowerArchitectureStudy:
    inputs: PowerStudyInputs
    architectures: pd.DataFrame
    stages: pd.DataFrame
    conductors: pd.DataFrame
    efficiency_sensitivity: pd.DataFrame
    faults: pd.DataFrame
    fault_contributions: pd.DataFrame
    backup: dict[str, float]


def power_architecture_study(inputs: PowerStudyInputs | None = None) -> PowerArchitectureStudy:
    """Keep conversion-only results separate from a 1 MW copper thought experiment.

    Fault timing uses a separate synthetic 800 V domain and fixed 20 ms
    observation window, with remote backfeed allowed or ideally blocked.
    """
    p = inputs or PowerStudyInputs()
    architectures = illustrative_power_architectures(p)
    baseline = evaluate_power_path(architectures[0], p.it_kw)
    rows, stages = [], []
    for architecture in architectures:
        result = evaluate_power_path(architecture, p.it_kw)
        saved_kw = baseline.input_kw - result.input_kw
        rows.append(
            {
                "architecture": architecture.id,
                "ac_dc_location": architecture.ac_dc_location,
                "backup_location": architecture.backup_location,
                "it_kw": p.it_kw,
                "input_kw": result.input_kw,
                "conversion_loss_kw": result.loss_kw,
                "efficiency": result.efficiency,
                "input_energy_kwh": result.input_kw * p.operating_hours,
                "input_energy_saving_kwh": saved_kw * p.operating_hours,
                "input_energy_saving_pct": 100 * saved_kw / baseline.input_kw,
                "energy_cost_saving": saved_kw * p.operating_hours * p.electricity_per_kwh,
                "balance_error_kw": result.balance_error_kw,
            }
        )
        stages.append(result.stages.assign(architecture=architecture.id))
    sensitivity = []
    for efficiency in (0.94, 0.95, 0.96, 0.975, 0.99):
        alternative = illustrative_power_architectures(replace(p, sst_efficiency=efficiency))[-1]
        result = evaluate_power_path(alternative, p.it_kw)
        sensitivity.append(
            {
                "sst_efficiency": efficiency,
                "input_kw": result.input_kw,
                "input_energy_saving_pct": 100
                * (baseline.input_kw - result.input_kw)
                / baseline.input_kw,
            }
        )
    faults, contributions = [], []
    f = FAULT_ASSUMPTIONS
    for clearing in FAULT_CLEARING_TIMES_S:
        for blocked in (False, True):
            # A local capacitor stays on the faulted side after upstream isolation.
            caps = [
                CapacitorPath(
                    "local_load_side",
                    f["local_capacitance_f"],
                    f["local_loop_resistance_ohm"],
                )
            ]
            if not blocked:
                caps.append(
                    CapacitorPath(
                        "remote_rack_backfeed",
                        f["remote_capacitance_f"],
                        f["remote_loop_resistance_ohm"],
                        clearing,
                    )
                )
            sources = [
                LimitedSourcePath("source_converter", f["converter_current_limit_a"], clearing),
                LimitedSourcePath(
                    "storage_dc_dc",
                    f["storage_current_limit_a"],
                    clearing,
                    f["storage_available_energy_j"],
                ),
            ]
            screen = fault_energy_screen(f["voltage_v"], f["horizon_s"], caps, sources)
            faults.append(
                {
                    "clearing_s": clearing,
                    "reverse_blocking": blocked,
                    "capacitor_released_j": screen.capacitor_released_j,
                    "source_envelope_j": screen.source_envelope_j,
                    "combined_screen_j": screen.combined_screen_j,
                    "capacitor_remaining_j": screen.capacitor_remaining_j,
                }
            )
            contributions.append(
                screen.contributions.assign(
                    clearing_s=clearing,
                    reverse_blocking=blocked,
                )
            )
    # DC bus must also supply the downstream DC/DC conversion loss.
    bus_kw = p.it_kw / p.rack_dc_dc_efficiency
    backup = dc_backup_requirements(
        bus_kw,
        p.backup_duration_s,
        discharge_efficiency=p.backup_efficiency,
        usable_soc_fraction=p.usable_soc_fraction,
    )
    backup["ideal_hold_up_capacitance_f"] = capacitor_hold_up_f(
        bus_kw,
        p.capacitor_hold_s,
        p.bus_voltage_v,
        p.minimum_bus_voltage_v,
    )
    backup["sst_break_even_efficiency"] = baseline.efficiency / p.rack_dc_dc_efficiency
    return PowerArchitectureStudy(
        p,
        pd.DataFrame(rows),
        pd.concat(stages, ignore_index=True),
        compare_dc_conductors(1000),
        pd.DataFrame(sensitivity),
        pd.DataFrame(faults),
        pd.concat(contributions, ignore_index=True),
        backup,
    )


def export_power_architecture_study(
    output: str | Path,
    inputs: PowerStudyInputs | None = None,
) -> PowerArchitectureStudy:
    """Export CSVs, replayable JSON, evidence and a self-contained HTML chart."""
    from plotly import graph_objects as go
    from plotly.subplots import make_subplots

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    study = power_architecture_study(inputs)
    for name in (
        "architectures",
        "stages",
        "conductors",
        "efficiency_sensitivity",
        "faults",
        "fault_contributions",
    ):
        getattr(study, name).to_csv(output / f"{name}.csv", index=False)
    for name, value in (
        ("inputs", asdict(study.inputs)),
        ("backup", study.backup),
        ("fault_assumptions", {**FAULT_ASSUMPTIONS, "clearing_times_s": FAULT_CLEARING_TIMES_S}),
        ("architectures", [asdict(a) for a in illustrative_power_architectures(study.inputs)]),
        (
            "scope",
            {
                "parameter_status": "illustrative",
                "power_boundary": "source to common low-voltage IT DC terminal; conversion only",
                "excluded": [
                    "cable/cooling/standby losses from architecture totals",
                    "PUE/TCO",
                    "transient network solution",
                    "arc flash/PPE/certification",
                ],
                "conductor_scenario": (
                    "Independent 1 MW receiving load, 2 m one-way, "
                    "1000 mm2 per pole, 20 C, 2000 A rating"
                ),
                "fault_scenario": (
                    "Independent 800 V fault domain; fixed 20 ms horizon; "
                    "ideal isolation; no inductance"
                ),
                "randomness": "none; deterministic algebra and existing DCNetwork solver",
            },
        ),
    ):
        (output / f"{name}.json").write_text(
            json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    evidence = files("datacenter_simulator").joinpath("data/power_architecture_sources.json")
    (output / "evidence.json").write_text(evidence.read_text(encoding="utf-8"), encoding="utf-8")
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Conversion loss at fixed IT demand",
            "Same 1 MW DC conductor geometry",
            "SST efficiency sensitivity",
            "Fault energy screen — not arc energy",
        ),
        vertical_spacing=0.22,
        horizontal_spacing=0.14,
    )
    fig.add_trace(
        go.Bar(
            x=study.architectures.architecture,
            y=study.architectures.conversion_loss_kw,
            name="Loss [kW]",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=study.conductors.voltage_v.astype(str),
            y=study.conductors.current_a,
            name="Conductor current [A]",
        ),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Scatter(
            x=study.efficiency_sensitivity.sst_efficiency * 100,
            y=study.efficiency_sensitivity.input_energy_saving_pct,
            name="Input saving [%]",
            mode="lines+markers",
        ),
        row=2,
        col=1,
    )
    for blocked, frame in study.faults.groupby("reverse_blocking"):
        fig.add_trace(
            go.Scatter(
                x=frame.clearing_s * 1000,
                y=frame.combined_screen_j / 1000,
                name=f"Remote backfeed {'blocked' if blocked else 'allowed'}",
                mode="lines+markers",
            ),
            row=2,
            col=2,
        )
    fig.update_yaxes(title_text="kW", row=1, col=1)
    fig.update_yaxes(title_text="A", row=1, col=2)
    fig.update_xaxes(title_text="DC voltage [V]", row=1, col=2)
    fig.update_xaxes(title_text="SST efficiency [%]", row=2, col=1)
    fig.update_yaxes(title_text="Input energy saving [%]", row=2, col=1)
    fig.update_xaxes(
        title_text="Isolation time [ms]",
        type="log",
        tickmode="array",
        tickvals=[0.05, 0.5, 5, 20],
        ticktext=["0.05", "0.5", "5", "20"],
        row=2,
        col=2,
    )
    fig.update_yaxes(title_text="Screen index [kJ]", row=2, col=2)
    fig.update_layout(
        title="800 VDC architecture study — illustrative assumptions",
        height=850,
        template="plotly_white",
        legend={"orientation": "h", "y": -0.22},
    )
    description = (
        "<h1>800 VDC migration study</h1><p>Illustrative, deterministic scenarios. "
        "Conversion totals exclude cables, cooling and standby. Conductor and fault studies "
        "are separate domains. Local capacitor energy persists after upstream isolation. "
        "The fault screen is not arc-flash incident energy, a protection design or a "
        "certification assessment.</p><p>Inputs, equations, evidence and all contributions "
        "are available in the companion JSON and CSV files.</p>"
        "<p>The fixed-geometry conductor comparison retains overload flags in conductors.csv; "
        "it is not a cable selection.</p>"
        "<h2>DC backup minima</h2>"
        f"<p>Bus power: <strong>{study.backup['bus_load_kw']:,.1f} kW</strong>; "
        f"duration: <strong>{study.inputs.backup_duration_s:g} s</strong>; "
        f"nominal storage energy: <strong>{study.backup['minimum_nominal_kwh']:,.2f} kWh</strong>. "
        f"Separate {study.inputs.capacitor_hold_s * 1000:g} ms ideal hold-up: "
        f"<strong>{study.backup['ideal_hold_up_capacitance_f']:.3f} F</strong> "
        f"from {study.inputs.bus_voltage_v:g} to {study.inputs.minimum_bus_voltage_v:g} V. "
        "These are separate sizing minima, not a simulated hybrid-storage controller.</p>"
    )
    html = fig.to_html(include_plotlyjs=True, full_html=True)
    html = html.replace(
        "</head>",
        "<style>body{font-family:system-ui,sans-serif;"
        "line-height:1.5;color:#19354a;max-width:1440px;margin:24px auto;"
        "padding:0 20px}h1,h2{line-height:1.2}</style></head>",
    )
    (output / "power-architecture.html").write_text(
        html.replace("<body>", "<body>" + description),
        encoding="utf-8",
    )
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/power-architecture"))
    parser.add_argument("--inputs", type=Path, help="JSON object of PowerStudyInputs overrides")
    args = parser.parse_args()
    try:
        values = {} if args.inputs is None else json.loads(args.inputs.read_text(encoding="utf-8"))
        study = export_power_architecture_study(args.output, PowerStudyInputs(**values))
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    print(
        study.architectures[["architecture", "input_kw", "input_energy_saving_pct"]].to_string(
            index=False,
        )
    )
    print("Assumptions: illustrative; conversion-only comparison; no arc-flash assessment.")
    print(f"Report: {args.output / 'power-architecture.html'}")


if __name__ == "__main__":
    main()
