"""Reproducible BMS/EPMS/DCIM incident studies and telemetry business cases.

Run ``python -m datacenter_simulator.analysis.telemetry --output outputs/telemetry``.
All values are synthetic assumptions; no database or hardware is contacted.
"""

import argparse
import json
from dataclasses import asdict, replace
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from datacenter_simulator.connectors.telemetry import (
    TelemetryHistory,
    line_protocol,
    sample_channel,
)
from datacenter_simulator.methods.cooling import CoolingPlant, ThermalZone
from datacenter_simulator.methods.scada import empty_asset
from datacenter_simulator.methods.telemetry import (
    capacity_plan,
    drain_time_s,
    evaluate_business_case,
    incident_timeline,
    potentially_affected_assets,
    rollup,
)
from datacenter_simulator.models.devices import Electrical
from datacenter_simulator.models.scada import validate_plant
from datacenter_simulator.models.scada_catalog import device_profiles
from datacenter_simulator.models.telemetry import (
    AssetContext,
    CollectorChannel,
    ContextHistory,
    StreamBudget,
    TelemetryBusinessCase,
    ThresholdRule,
    telemetry_schema,
)

START = "2026-01-01T00:00:00Z"
SCENARIOS = ("cooling_failure", "workload_step", "utility_sag")


def telemetry_evidence() -> dict[str, Any]:
    return json.loads(
        files("datacenter_simulator").joinpath("data/telemetry_evidence.json").read_text()
    )  # type: ignore[no-any-return]


def example_plant() -> tuple[list[dict[str, Any]], list[dict[str, str]], ContextHistory]:
    """Synthetic one-rack plant; contexts and relationships are snapshot-specific."""
    profiles = device_profiles()
    specifications = [
        ("hall", "room", None),
        ("utility", "grid_connection", "hall"),
        ("ups", "ups", "hall"),
        ("pdu", "rack_pdu", "hall"),
        ("pump", "pump", "hall"),
        ("cdu", "cdu", "hall"),
        ("rack", "rack", "hall"),
        ("server", "server", "rack"),
    ]
    assets = [empty_asset(profiles[p], i, parent_id=parent) for i, p, parent in specifications]
    for asset in assets:
        asset["location"] = {"site": "demo-site", "room": "hall"}
        asset["identity"] = {
            "owner": "demo-tenant" if asset["id"] in {"rack", "server"} else "operator"
        }
    relationships = [
        dict(source=s, target=t, kind=k)
        for s, t, k in [
            ("utility", "ups", "electrical_feed"),
            ("ups", "pdu", "electrical_feed"),
            ("pdu", "rack", "electrical_feed"),
            ("pump", "cdu", "cooling_supply"),
            ("cdu", "rack", "cooling_supply"),
        ]
    ]
    contexts = ContextHistory(
        [
            AssetContext(
                "demo-site",
                a["id"],
                a["profile"],
                START,
                owner=a["identity"]["owner"],
                rack_id="rack" if a["id"] in {"rack", "server"} else None,
            )
            for a in assets
        ]
    )
    validate_plant(assets, relationships, profiles)
    return assets, relationships, contexts


def incident_study(scenario: str = "cooling_failure") -> dict[str, Any]:
    """Three-minute trace from existing terminal-power/cooling/thermal-zone models.

    A single mixed thermal zone represents the rack environment, not a measured
    rack hotspot. An assumed proportional recovery load restores temperature.
    The utility sag scenario assumes an ideal UPS masks the disturbance; no UPS
    transfer dynamics or ride-through certification is inferred.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    assets, relationships, contexts = example_plant()
    electrical = Electrical(800, 20, 100)
    cooling = CoolingPlant("Synthetic liquid plant", 120, 5, liquid_fraction=1, fan_fraction=0)
    zone = ThermalZone(capacitance_kj_k=500, conductance_kw_k=0)
    temperature = 24.0
    traces = []
    for second in range(180):
        disturbance = 60 <= second < 120
        failed = scenario == "cooling_failure" and disturbance
        utilization = 1.0 if scenario == "workload_step" and disturbance else 0.5
        power = electrical.power_kw(utilization)
        plant = replace(cooling, capacity_kw=20) if failed else cooling
        recovery = max(temperature - 24, 0) * zone.capacitance_kj_k / 30
        result = plant.evaluate(power + recovery, 30)
        traces.append(
            dict(
                second=second,
                rack_power_kw=power,
                inlet_temperature_c=temperature,
                removed_heat_kw=result.heat_removed_kw,
                cooling_power_kw=result.electric_kw,
                flow_l_min=result.liquid_flow_kg_s * 60,  # water density assumed 1 kg/L
                facility_power_kw=power + result.electric_kw,
                pump_power_kw=result.auxiliaries_kw,  # already included in plant electricity
                utility_voltage_v=195.0 if scenario == "utility_sag" and disturbance else 230.0,
                ups_source="battery" if scenario == "utility_sag" and disturbance else "normal",
            )
        )
        temperature = zone.advance(temperature, 24, power, result.heat_removed_kw, 1 / 3600)
    channels = [
        (CollectorChannel("rack", "rack", "active_power_kw", "EPMS", "epms-1", 1), "rack_power_kw"),
        (
            CollectorChannel("rack", "rack", "inlet_temperature_c", "BMS", "bms-1", 5),
            "inlet_temperature_c",
        ),
        (CollectorChannel("cdu", "cdu", "secondary_flow_l_min", "BMS", "bms-1", 5), "flow_l_min"),
        (CollectorChannel("pump", "pump", "active_power_kw", "BMS", "bms-1", 5), "pump_power_kw"),
        (
            CollectorChannel("utility", "grid_connection", "voltage_l1_n_v", "EPMS", "epms-1", 1),
            "utility_voltage_v",
        ),
        (
            CollectorChannel("hall", "room", "facility_power_kw", "EPMS", "epms-1", 1),
            "facility_power_kw",
        ),
        (CollectorChannel("ups", "ups", "output_source", "EPMS", "epms-1", 5), "ups_source"),
        (
            CollectorChannel("server", "server", "inlet_temperature_c", "DCIM", "dcim-1", 15, 3),
            "inlet_temperature_c",
        ),
    ]
    history = TelemetryHistory()
    for channel, key in channels:
        asset = next(a for a in assets if a["id"] == channel.asset_id)
        asset["supported_points"].append(channel.point_key)
        for record in sample_channel(
            channel, [row[key] for row in traces], site_id="demo-site", start=START
        ):
            history.append(record)
    rules = [
        ThresholdRule("rack", "inlet_temperature_c", "BMS", "bms-1", 28),
        ThresholdRule("rack", "active_power_kw", "EPMS", "epms-1", 90),
        ThresholdRule("pump", "active_power_kw", "BMS", "bms-1", 0.25, "below"),
        ThresholdRule("utility", "voltage_l1_n_v", "EPMS", "epms-1", 207, "below"),
    ]
    origin = {"cooling_failure": "pump", "workload_step": "rack", "utility_sag": "utility"}[
        scenario
    ]
    return dict(
        scenario=scenario,
        assets=assets,
        relationships=relationships,
        contexts=contexts,
        history=history,
        traces=pd.DataFrame(traces),
        channels=[asdict(c) for c, _ in channels],
        rules=[asdict(r) for r in rules],
        model_inputs=dict(
            electrical=asdict(electrical), cooling=asdict(cooling), zone=asdict(zone)
        ),
        timeline=incident_timeline(
            history, contexts, rules, site_id="demo-site", start=START, end="2026-01-01T00:03:00Z"
        ),
        potentially_affected=potentially_affected_assets(assets, relationships, origin),
        topology_valid_at=START,
    )


def business_sensitivity() -> list[dict[str, Any]]:
    """Nine assumption combinations, including a labor-only downside scenario."""
    result = []
    for incidents in (4, 12, 36):
        for fraction in (0.0, 0.25, 0.5):
            evaluation = evaluate_business_case(
                TelemetryBusinessCase(
                    incidents_per_year=incidents, downtime_realization_fraction=fraction
                )
            )
            result.append({**evaluation.pop("assumptions"), **evaluation})
    return result


def sampling_comparison() -> list[dict[str, Any]]:
    """A phase-sensitive 10-second pulse can disappear under sparse sampling."""
    values = [100.0 if 11 <= t < 21 else 60.0 for t in range(120)]
    rows = []
    for period in (1, 5, 15, 30, 60):
        samples = values[::period]
        rows.append(
            dict(
                interval_s=period,
                samples=len(samples),
                observed_max_kw=max(samples),
                true_max_kw=max(values),
                phase_offset_s=0,
            )
        )
    return rows


def export_telemetry_study(output: str | Path) -> dict[str, Any]:
    """Export CSV/JSONL, device schemas, replay inputs and a standalone Plotly report."""
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    evidence = telemetry_evidence()
    (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    profiles = device_profiles()
    schema_dir = root / "schemas"
    schema_dir.mkdir(exist_ok=True)
    for profile in profiles.values():
        (schema_dir / f"{profile.key}.json").write_text(
            json.dumps(telemetry_schema(profile), indent=2) + "\n"
        )
    figures = []
    summaries = []
    for scenario in SCENARIOS:
        study = incident_study(scenario)
        path = root / scenario
        path.mkdir(exist_ok=True)
        history = study["history"]
        history.write_jsonl(path / "telemetry.jsonl")
        (path / "telemetry.lp").write_text(line_protocol(history), encoding="utf-8")
        pd.DataFrame(history.frame(study["contexts"])).to_csv(path / "telemetry.csv", index=False)
        pd.DataFrame(rollup(history)).to_csv(path / "rollup-60s.csv", index=False)
        study["traces"].to_csv(path / "physical-trace.csv", index=False)
        manifest = {k: v for k, v in study.items() if k not in {"history", "contexts", "traces"}}
        manifest["contexts"] = [asdict(c) for c in study["contexts"].contexts]
        (path / "incident.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
        summaries.append(
            {
                "scenario": scenario,
                "observations": len(history.records()),
                "potentially_affected": study["potentially_affected"],
                "timeline": study["timeline"],
            }
        )
        df = study["traces"]
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            subplot_titles=("Power", "Thermal response", "Utility voltage"),
        )
        for key, plot_row in (
            ("rack_power_kw", 1),
            ("cooling_power_kw", 1),
            ("inlet_temperature_c", 2),
            ("utility_voltage_v", 3),
        ):
            fig.add_trace(go.Scatter(x=df.second, y=df[key], name=key), row=plot_row, col=1)
        for plot_row, unit in enumerate(("kW", "°C", "V RMS L1-N"), 1):
            fig.update_yaxes(title_text=unit, row=plot_row, col=1)
        fig.update_xaxes(title_text="Elapsed seconds", row=3, col=1)
        fig.update_layout(
            title=f"Synthetic scenario: {scenario.replace('_', ' ')}",
            height=650,
            template="plotly_white",
        )
        figures.append(fig)
    economics = business_sensitivity()
    pd.DataFrame(economics).to_csv(root / "business-sensitivity.csv", index=False)
    budgets = [
        StreamBudget(10000, interval, 100, 7, 60, 365, 160, 2) for interval in (1, 5, 30, 60)
    ]
    sizing = []
    for budget in budgets:
        row = {
            **asdict(budget),
            **capacity_plan([budget], outage_s=600, buffer_observations=100000),
        }
        row["drain_time_s_at_20000_writes_per_s"] = drain_time_s(
            row["buffered_observations"],
            ingest_rate=row["observations_per_second"],
            write_rate=20000,
        )
        sizing.append(row)
    pd.DataFrame(sizing).to_csv(root / "capacity-sensitivity.csv", index=False)
    pd.DataFrame(sampling_comparison()).to_csv(root / "sampling-comparison.csv", index=False)
    fig = go.Figure()
    for fraction in (0.0, 0.25, 0.5):
        selected = [r for r in economics if r["downtime_realization_fraction"] == fraction]
        fig.add_trace(
            go.Bar(
                name=f"Assumed downtime realization: {fraction:.0%}",
                x=[r["incidents_per_year"] for r in selected],
                y=[r["npv"] for r in selected],
            )
        )
    fig.update_layout(
        title="Five-year NPV sensitivity (synthetic EUR assumptions)",
        xaxis_title="Incidents/year",
        yaxis_title="NPV (EUR)",
        template="plotly_white",
    )
    figures.append(fig)
    # Static shell plus self-contained Plotly scripts; no external assets or service calls.
    body = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unified facility telemetry</title><style>
body{font:16px system-ui;margin:24px auto;padding:0 20px;max-width:1150px;color:#18314b}
h1{font-size:2rem}p{line-height:1.6}a{color:#006d77}.plotly-graph-div{max-width:100%}
.table-scroll{overflow-x:auto}table{border-collapse:collapse;font-size:.85rem;min-width:650px}
td,th{padding:8px;border-bottom:1px solid #d4e1eb;text-align:left}th{background:#eef4f7}
</style><h1>Unified facility telemetry</h1>
<p>Three synthetic scenarios link BMS cooling, EPMS electrical signals and DCIM asset context.
Threshold order is evidence for investigation, not proof of causation.
Topology identifies possible exposure, not actual customer downtime.</p>
<p>The supplied source has four pages only. Model coefficients, thresholds, collector settings
and all economic values are engineering assumptions. DCIM remains the source of asset context;
this offline replay does not operate equipment.</p>
<p><a href="business-sensitivity.csv">Business assumptions and NPV CSV</a> ·
<a href="capacity-sensitivity.csv">Storage and buffering CSV</a> ·
<a href="sampling-comparison.csv">Sampling comparison CSV</a> ·
<a href="evidence.json">Evidence ledger</a></p>"""
    for index, fig in enumerate(figures):
        body += fig.to_html(
            full_html=False,
            include_plotlyjs=True if index == 0 else False,
            config={"responsive": True},
        )
        if index < len(summaries):
            summary = summaries[index]
            body += "<h2>Observed event timeline</h2><p>Potential dependency exposure: "
            body += escape(", ".join(summary["potentially_affected"]) or "No downstream asset")
            body += ". These are dependency links, not confirmed outages.</p>"
            columns = ("time", "source_system", "asset_id", "point_key", "state", "owner")
            body += '<div class="table-scroll"><table><thead><tr>'
            body += "".join(f"<th>{escape(column.replace('_', ' '))}</th>" for column in columns)
            body += "</tr></thead><tbody>"
            for event in summary["timeline"]:
                body += (
                    "<tr>"
                    + "".join(
                        f"<td>{escape(str(event.get(column) or 'unknown'))}</td>"
                        for column in columns
                    )
                    + "</tr>"
                )
            body += "</tbody></table></div>"
    body += "<h2>Replay inputs</h2><ul>"
    for scenario in SCENARIOS:
        body += (
            f'<li>{scenario}: <a href="{scenario}/telemetry.jsonl">canonical observations</a> · '
            f'<a href="{scenario}/incident.json">models, devices, context and timeline</a> · '
            f'<a href="{scenario}/telemetry.csv">CSV</a> · '
            f'<a href="{scenario}/telemetry.lp">line protocol</a></li>'
        )
    body += (
        "</ul><p>Negative NPV and unavailable payback are retained. Storage estimates depend "
        "on assumed bytes per observation and exclude measured database performance. "
        "No telemetry product license prices are supplied.</p></html>"
    )
    (root / "telemetry.html").write_text(body, encoding="utf-8")
    return dict(scenarios=summaries, economics=economics, sizing=sizing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/telemetry"))
    args = parser.parse_args()
    result = export_telemetry_study(args.output)
    print(
        json.dumps(
            {
                "report": str(args.output / "telemetry.html"),
                "scenarios": len(result["scenarios"]),
                "schemas": len(device_profiles()),
            }
        )
    )


if __name__ == "__main__":
    main()
