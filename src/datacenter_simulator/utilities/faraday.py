"""Offline interactive views of the two-meter storage study."""

from pathlib import Path
from typing import TYPE_CHECKING

import plotly.graph_objects as go
from plotly.subplots import make_subplots

if TYPE_CHECKING:
    from datacenter_simulator.analysis.faraday import FaradayStudy


def write_faraday_report(study: "FaradayStudy", path: str | Path) -> None:
    """Render selectable scenarios, inventories, hourly matching and sensitivity."""
    fig = make_subplots(
        rows=3,
        cols=1,
        vertical_spacing=0.08,
        subplot_titles=(
            "Separate customer meter and matched supply",
            "Solar storage operation",
            "Internal usable energy inventory (not AC-deliverable MWh)",
        ),
    )
    specs = (
        ("facility_utility_import_kw", "Customer meter import", 1, "#243449"),
        ("matched_kw", "Matched supply", 1, "#009c8c"),
        ("residual_unmatched_kw", "Unmatched demand", 1, "#d36c44"),
        ("solar_available_kw", "Available solar", 2, "#d7a000"),
        ("charge_kw", "Battery charge", 2, "#4879bd"),
        ("discharge_kw", "Battery discharge", 2, "#009c8c"),
        ("battery_energy_kwh", "Internal inventory", 3, "#855bb1"),
    )
    names = list(study.results)
    for i, result in enumerate(study.results.values()):
        for column, label, row, color in specs:
            fig.add_trace(
                go.Scatter(
                    x=result.timeseries.index,
                    y=result.timeseries[column] / 1000,
                    name=label,
                    line={"color": color},
                    visible=i == 2,
                ),
                row=row,
                col=1,
            )
    buttons = [
        {
            "label": name,
            "method": "update",
            "args": [{"visible": [j // len(specs) == i for j in range(len(specs) * len(names))]}],
        }
        for i, name in enumerate(names)
    ]
    fig.update_layout(
        height=1000,
        template="plotly_white",
        margin={"t": 100, "l": 65, "r": 20},
        updatemenus=[{"buttons": buttons, "x": 0, "y": 1.10, "active": 2}],
        legend={"orientation": "h", "y": -0.1},
    )
    for row in (1, 2):
        fig.update_yaxes(title_text="MW", row=row, col=1)
    fig.update_yaxes(title_text="MWh", row=3, col=1)
    comparison = go.Figure(
        go.Bar(
            x=study.comparison.scenario,
            y=study.comparison.hourly_matched_fraction * 100,
            marker_color="#009c8c",
        )
    )
    comparison.update_layout(
        title="Energy-weighted hourly matching — synthetic scenarios",
        yaxis_title="Matched facility demand [%]",
        template="plotly_white",
        height=480,
        margin={"b": 160},
        yaxis_range=[0, 100],
    )
    heat = study.sensitivity.pivot(
        index="load_multiplier", columns="poi_export_mw", values="hourly_matched_fraction"
    )
    sensitivity = go.Figure(
        go.Heatmap(
            x=heat.columns,
            y=heat.index,
            z=heat.to_numpy() * 100,
            colorscale="Teal",
            zmin=0,
            zmax=100,
            colorbar={"title": "%"},
        )
    )
    sensitivity.update_layout(
        title="150 MW / 600 MWh: load and shared POI sensitivity",
        xaxis_title="Assumed shared POI limit [MW]",
        yaxis_title="Load multiplier",
        template="plotly_white",
        height=450,
    )
    p = study.inputs
    description = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Faraday | Utility storage case</title><style>
body{{font:16px/1.6 system-ui,sans-serif;color:#243449;background:#f4f7f9;margin:0}}
main{{max-width:1180px;margin:0 auto;padding:24px}}h1{{font-size:clamp(28px,5vw,46px)}}
section{{background:white;border-radius:14px;padding:18px;margin:20px 0;overflow:hidden}}
.note{{border-left:4px solid #009c8c;padding:12px;background:#e6f5f2}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;font-size:14px}}
td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:right}}a{{color:#006e76}}
</style></head><body><main><p>ASVA CONSULTING · REPRODUCIBLE RESEARCH</p>
<h1>Faraday: storage through the utility</h1>
<p>Operating phase: 150 MW / 600 MWh. Proposed addition: up to 375 MW / 1,500 MWh,
targeting Q4 2028. The combined 525 MW / 2,100 MWh case is hypothetical.</p>
<p class="note">Two separate meters: solar + battery export to the utility;
the data center imports its full demand from the utility. Hourly matched energy
does not establish a private wire, on-site backup, bill savings or certified clean energy.</p>
<section><h2>Active inputs</h2><p>Profile facility demand:
{study.profiles.demand_kw.mean() / 1000:g} MW mean,
{study.profiles.demand_kw.max() / 1000:g} MW peak.
Synthetic generator settings (overridden by supplied CSV): {p.it_mw:g} MW IT × {p.pue:g} PUE;
{p.solar_ac_peak_mw:g} MW assumed solar AC peak; {p.poi_export_mw:g} MW shared POI;
{p.round_trip_efficiency:.0%} round-trip efficiency. Profiles: {len(study.profiles):,} hours.
Actual site load, PV allocation and POI rating are undisclosed. Full solar allocation
is assumed. The 733 MWh sensitivity does not explain the historical rating difference.</p>
<p>Surplus solar charges storage; discharge fills later hourly deficits.
The usable battery window starts empty. Final inventory and excess exports are
excluded from matched energy. The low-solar case scales solar to 25% throughout.</p></section>
<section><h2>Scenario comparison</h2>"""
    table = study.comparison[
        [
            "scenario",
            "matched_energy_mwh",
            "hourly_matched_fraction",
            "battery_loss_mwh",
            "facility_meter_peak_mw",
        ]
    ].to_html(index=False, float_format=lambda x: f"{x:,.3f}", border=0)
    html = description + comparison.to_html(full_html=False, include_plotlyjs=True)
    html += '<div class="scroll">' + table + "</div></section>"
    html += "<section><h2>Explore hourly operation</h2>"
    html += fig.to_html(full_html=False, include_plotlyjs=False) + "</section><section>"
    html += sensitivity.to_html(full_html=False, include_plotlyjs=False)
    html += """</section><section><h2>Replay and inspect</h2><p>
<a href="inputs.json">Inputs</a> · <a href="profiles.csv">Hourly profiles</a> ·
<a href="comparison.csv">Comparison</a> · <a href="sensitivity.csv">Sensitivity</a> ·
<a href="evidence.json">Source ledger</a> · <a href="scope.json">Model boundaries</a></p>
<p>Schedule 34 has customer-specific approved terms. No contract price is public
in the source material used here. The $689 million portfolio financing is not
the battery's construction cost. This report does not calculate a tariff bill.</p>
</section></main></body></html>"""
    Path(path).write_text(html, encoding="utf-8")
