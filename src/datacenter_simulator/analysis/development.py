"""Run a replayable offline development-risk business case."""

import argparse
import csv
import json
from dataclasses import asdict, replace
from pathlib import Path

import plotly.graph_objects as go

from datacenter_simulator.methods.development import evaluate_development
from datacenter_simulator.models.development import DevelopmentScenario
from datacenter_simulator.use_cases.development import SOURCE_CONTEXT, development_scenarios


def run_study(output: Path, scenarios: list[DevelopmentScenario]) -> None:
    """Write assumptions, source context, branch values and probability/delay heatmap."""
    if not scenarios:
        raise ValueError("at least one scenario is required")
    output.mkdir(parents=True, exist_ok=True)
    (output / "inputs.json").write_text(json.dumps([asdict(s) for s in scenarios], indent=2))
    (output / "source_context.json").write_text(json.dumps(SOURCE_CONTEXT, indent=2))
    rows = [{"name": s.name, **asdict(evaluate_development(s))} for s in scenarios]
    with (output / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    probabilities = [i / 10 for i in range(11)]
    delays = list(range(0, 37, 3))
    z = [
        [
            evaluate_development(
                replace(scenarios[0], cancellation_probability=p, delay_months=d)
            ).expected_npv_usd
            / 1e6
            for d in delays
        ]
        for p in probabilities
    ]
    fig = go.Figure(
        go.Heatmap(
            x=delays,
            y=probabilities,
            z=z,
            colorbar={"title": "Expected NPV ($m)"},
            colorscale="RdBu",
            zmid=0,
        )
    )
    fig.update_layout(
        title="Synthetic development risk — assumptions, not forecasts",
        xaxis_title="Additional delay (months)",
        yaxis_title="Cancellation probability",
    )
    fig.write_html(output / "development-risk.html", include_plotlyjs=True)
    (output / "sensitivity.json").write_text(
        json.dumps(
            {"delay_months": delays, "cancellation_probability": probabilities, "npv_musd": z},
            indent=2,
        )
    )


def main() -> None:
    """CLI with JSON replay."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/development"))
    parser.add_argument("--inputs", type=Path)
    args = parser.parse_args()
    scenarios = (
        [DevelopmentScenario(**row) for row in json.loads(args.inputs.read_text())]
        if args.inputs
        else development_scenarios()
    )
    run_study(args.output, scenarios)


if __name__ == "__main__":
    main()
