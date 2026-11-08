"""Offline Plotly report for the synthetic infrastructure study."""

import json
from dataclasses import asdict
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

import plotly.graph_objects as go

from datacenter_simulator.use_cases.infrastructure import infrastructure_evidence

if TYPE_CHECKING:
    from datacenter_simulator.analysis.infrastructure import InfrastructureStudy


def write_infrastructure_report(study: "InfrastructureStudy", path: str | Path) -> Path:
    """Bundle plots, boundary notes, exact cost rows and relative audit downloads."""
    totals, design, costs = study.summary, study.design, study.costs
    waterfall = go.Figure(
        go.Waterfall(
            x=[*costs.name, "Listed subtotal"],
            y=[*(costs.cost_usd / 1e6), 0],
            measure=[*(["relative"] * len(costs)), "total"],
            increasing={"marker": {"color": "#087f8c"}},
            totals={"marker": {"color": "#123354"}},
        )
    )
    waterfall.update_layout(title="The 12 image lines, scaled once", yaxis_title="USD million")
    flow = go.Figure(
        go.Sankey(
            node={
                "label": [
                    "Utility meter",
                    "IT terminals",
                    "Hall distribution losses",
                    "UPS losses (outside hall)",
                    "Cooling",
                    "Site auxiliaries",
                    "Main distribution losses",
                ],
                "color": "#087f8c",
            },
            link={
                "source": [0] * 6,
                "target": list(range(1, 7)),
                "value": [
                    design[k] / 1000
                    for k in (
                        "it_kw",
                        "distribution_loss_kw",
                        "ups_loss_kw",
                        "cooling_kw",
                        "auxiliary_kw",
                        "main_loss_kw",
                    )
                ],
            },
            valuesuffix=" MW",
        )
    )
    flow.update_layout(title="Design electrical power balance (not a wiring diagram)")
    timeline = go.Figure()
    for column, name in (("it_kw", "IT"), ("cooling_kw", "Cooling"), ("facility_kw", "Facility")):
        timeline.add_scatter(
            x=study.hourly.index, y=study.hourly[column] / 1000, name=name, mode="lines"
        )
    timeline.update_layout(title="48-hour synthetic operation", yaxis_title="MW")
    sensitivity = go.Figure(
        go.Bar(
            x=study.cost_sensitivity.scenario_total_usd / 1e6,
            y=study.cost_sensitivity.scenario,
            orientation="h",
            marker_color="#087f8c",
        )
    )
    sensitivity.update_layout(
        title="Isolated cost assumptions, not confidence intervals",
        xaxis_title="USD million",
        margin={"l": 260},
        height=420,
    )
    pieces = []
    for i, figure in enumerate((waterfall, flow, timeline, sensitivity)):
        figure.update_layout(template="plotly_white", font={"family": "Arial"}, autosize=True)
        pieces.append(
            figure.to_html(
                full_html=False,
                include_plotlyjs=True if i == 0 else False,
                config={"responsive": True, "displaylogo": False},
                div_id=f"infrastructure-chart-{i}",
            )
        )
    evidence = infrastructure_evidence()
    downloads = [
        *(
            f"{n}.csv"
            for n in (
                "costs",
                "sizing",
                "hourly",
                "cost_sensitivity",
                "cooling_sensitivity",
                "scale_sensitivity",
            )
        ),
        *(f"{n}.json" for n in ("assumptions", "evidence", "design", "summary")),
    ]
    links = " · ".join(f'<a href="{name}" download>{name}</a>' for name in downloads)
    groups = costs.groupby("group", sort=False).cost_usd.sum()
    groups_text = " · ".join(f"{name}: ${value / 1e6:,.1f}m" for name, value in groups.items())
    cost_table = costs[["name", "group", "million_usd_per_mw", "cost_usd", "vendors_as_shown"]]
    cooling_table = study.cooling_sensitivity[
        ["liquid_heat_fraction", "facility_kw", "cooling_kw", "instantaneous_pue"]
    ]
    input_json = escape(json.dumps(asdict(study.case), indent=2))
    command = (
        f"python -m datacenter_simulator.analysis.infrastructure --it-mw {study.case.it_mw:g}"
        " --output outputs/infrastructure"
    )
    text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Synthetic data center equipment study</title>
<style>
body{{margin:0;background:#f0f4f7;color:#123354;font:16px/1.6 Arial,sans-serif}}
main{{max-width:1200px;margin:auto;padding:28px}}h1{{font-size:clamp(26px,4vw,42px);line-height:1.15}}
h2{{margin-top:34px}}.eyebrow{{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#087f8c}}
.notice{{border-left:5px solid #d68a28;background:#fff7e8;padding:16px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
gap:14px;margin:24px 0}}
.card,.chart{{background:white;padding:18px;border-radius:12px;min-width:0}}
.card b{{display:block;font-size:28px}}.chart{{margin:18px 0;overflow:hidden}}
.table{{overflow:auto;background:white;border-radius:12px}}table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{padding:10px;text-align:left;border-bottom:1px solid #dce5eb;white-space:nowrap}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:18px;border-radius:12px}}
a{{color:#086c83;overflow-wrap:anywhere}}.audit{{line-height:2}}@media(max-width:600px){{main{{padding:14px}}.chart{{padding:0}}}}
</style></head><body><main>
<p class="eyebrow">ASVA Consulting · Reproducible synthetic example</p>
<h1>From equipment content to a {study.case.it_mw:g} MW IT design</h1>
<p>Trace each image rate, reconcile the power boundary, size the modules and test the
assumptions.</p>
<p class="notice"><b>Illustration, not a quotation.</b> The screenshot is unverified and its MW
denominator is unspecified. This baseline assumes IT MW. The listed subtotal is incomplete project
scope; vendor names do not supply performance data. All engineering inputs are invented.</p>
<div class="cards">
<div class="card">Listed subtotal<b>${totals["listed_subtotal_usd"] / 1e6:,.1f}m</b>USD, IT MW
basis</div>
<div class="card">Facility design demand<b>{totals["design_facility_mw"]:.2f} MW</b>IT plus
losses and cooling</div>
<div class="card">48-hour energy PUE<b>{totals["period_energy_pue"]:.3f}</b>Simulated; not
annual measured PUE</div>
<div class="card">UPS battery energy<b>{totals["ups_nominal_battery_kwh"] / 1000:.2f} MWh</b>
Nominal, {study.case.ups_autonomy_minutes:g}-minute IT-only support</div></div>
<h2>1. Reproduce the image's listed content</h2><p>{groups_text}</p>{pieces[0]}
<div class="table">{cost_table.to_html(index=False, escape=True)}</div>
<h2>2. Close the electrical and thermal balances</h2>
<p>Networking is part of IT demand. The hall cooling load includes downstream distribution losses.
UPS and main losses are outside the conditioned hall. The cooling plant is outside the UPS branch.
Only the IT branch receives battery support; UPS autonomy does not prove a safe facility
outage.</p>{pieces[1]}
<h2>3. Size equipment independently of the cost rates</h2>
<p>N+1 means one spare module per listed bank, except racks. Unit ratings are synthetic capacity
envelopes; shared feeds, pipes, fuel supplies and battery banks can still fail. Thermal kW and
electrical kW are distinct. No spare-unit multiplier is applied to the infographic costs.</p>
<div class="table">{study.sizing.to_html(index=False, escape=True)}</div>
<h2>4. Run a declared 48-hour operating profile</h2>
<p>Facility energy: {totals["period_facility_kwh"] / 1000:,.1f} MWh. Electricity-only cost:
${totals["period_electricity_usd"]:,.0f} at the assumed ${study.case.electricity_usd_per_kwh:g}/kWh.
Unmet hall heat: {totals["period_unmet_heat_kwh"]:,.1f} kWh. These are not annual
forecasts.</p>{pieces[2]}
<h2>5. Test the uncertain inputs</h2>{pieces[3]}
<p>Alternative MW basis changes every cost line together. Other scenarios change one assumption
at a time. Cooling mix below changes the physics only; no vendor price saving is inferred.</p>
<div class="table">{cooling_table.to_html(index=False, escape=True)}</div>
<h2>6. Inspect the assumptions and reproduce</h2>
<pre>{command}</pre>
<details><summary>Engineering inputs</summary><pre>{input_json}</pre></details>
<p><b>Unpriced scope:</b> {escape("; ".join(evidence["source"]["unpriced_scope"]))}.</p>
<p>{escape(evidence["source"]["scope_note"])}</p>
<p>Source: <a href="{escape(evidence["source"]["url"])}">user-supplied LinkedIn link</a>.
The screenshot was transcribed; the linked post was inaccessible. Original image is not
redistributed.</p>
<p class="audit">Audit downloads: {links}</p>
<p>Models omit detailed battery discharge, protection coordination, water use, CFD, construction
schedule, revenue, financing and lifetime replacement. Unit-count checks are not availability
claims.</p>
</main></body></html>"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
