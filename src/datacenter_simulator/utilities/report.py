"""Offline HTML report composed from reusable plotting functions."""

import html
import json
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from datacenter_simulator.methods.communications import Traffic
from datacenter_simulator.simulation import DataCenter, SimulationResult
from datacenter_simulator.utilities.plotting import (
    communications_diagram,
    cooling_comparison,
    cooling_schema,
    electrical_diagram,
    equipment_3d,
    floor_plan,
    power_timeseries,
)


def write_report(
    center: DataCenter,
    result: SimulationResult,
    path: str | Path,
    *,
    comparisons: dict[str, SimulationResult] | None = None,
    utilization: float = 0.7,
    ambient_c: float = 25,
    traffic: list[Traffic] | None = None,
) -> Path:
    """Write a self-contained report and CSV/JSON companion exports.

    Topology/thermal snapshots use the explicitly labelled utilization and ambient.
    Time plots and KPI cards summarize the supplied simulation result.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    electrical = center.electrical.solve(center.bus_loads(utilization))
    comm = center.communications.evaluate(traffic or [])
    heat = electrical.load_kw + electrical.loss_kw * center.conditioned_loss_fraction
    figures: list[tuple[str, go.Figure]] = [
        ("3D hall", equipment_3d(center, utilization)),
        ("2D layout", floor_plan(center, utilization)),
        ("DC single-line", electrical_diagram(center, electrical)),
        ("Communications", communications_diagram(center, comm)),
        ("Cooling flow", cooling_schema(center, heat, ambient_c)),
        ("Power & generation", power_timeseries(result)),
    ]
    if comparisons:
        figures.append(("Compare HVAC", cooling_comparison(comparisons)))
    nav, panels = [], []
    for number, (label, figure) in enumerate(figures):
        nav.append(
            f'<button id="tab-{number}" class="tab {"active" if number == 0 else ""}" '
            f'role="tab" aria-controls="panel-{number}" '
            f'aria-selected="{"true" if number == 0 else "false"}" '
            f'onclick="showTab({number})">{label}</button>'
        )
        plot = figure.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id=f"plot-{number}",
            config={
                "responsive": True,
                "displaylogo": False,
                "toImageButtonOptions": {"format": "png", "scale": 2},
            },
        )
        panels.append(
            f'<section id="panel-{number}" class="panel" role="tabpanel" '
            f'aria-labelledby="tab-{number}" {"hidden" if number else ""}>'
            f"{plot}</section>"
        )
    s = result.summary
    metrics = [
        ("IT ENERGY", f"{s['it_kwh'] / 1000:.2f}", "MWh"),
        ("FACILITY PUE", f"{s['pue']:.3f}", "energy ratio"),
        ("PEAK DEMAND", f"{s['peak_facility_kw']:.1f}", "kW"),
        ("GRID IMPORT", f"{s['grid_import_kwh'] / 1000:.2f}", "MWh"),
        ("COOLING ENERGY", f"{s['cooling_kwh'] / 1000:.2f}", "MWh"),
    ]
    cards = "".join(
        f'<div class="metric"><small>{title}</small><strong>{value}</strong>'
        f"<span>{unit}</span></div>"
        for title, value, unit in metrics
    )
    warnings = sorted(set(result.warnings + electrical.warnings + comm.warnings))
    notices = "".join(f"<li>{html.escape(warning)}</li>" for warning in warnings)
    notices = (
        f'<details open class="alerts"><summary>Model flags</summary><ul>{notices}</ul></details>'
        if warnings
        else '<div class="checks">● No capacity or balance flags in this run</div>'
    )
    csv_name, json_name = target.stem + ".csv", target.stem + ".json"
    result.timeseries.to_csv(target.with_suffix(".csv"), index_label="timestamp")
    # JSON has no NaN literals: absent PUE for zero IT demand is represented as null.
    clean = {key: value if value == value else None for key, value in s.items()}
    target.with_suffix(".json").write_text(json.dumps(clean, indent=2, allow_nan=False) + "\n")
    document = Path(__file__).with_name("report.html").read_text(encoding="utf-8")
    for placeholder, value in {
        "__PLOTLY__": get_plotlyjs(),
        "__CARDS__": cards,
        "__NAV__": "".join(nav),
        "__PANELS__": "".join(panels),
        "__NOTICES__": notices,
        "__SNAPSHOT__": f"{utilization:.0%} utilization, {ambient_c:g} °C ambient",
        "__PERIOD__": f"{len(result.timeseries)} intervals, starting {result.timeseries.index[0]}",
        "__CENTER__": html.escape(center.name + " / " + center.cooling.name),
        "__CSV__": html.escape(csv_name, quote=True),
        "__JSON__": html.escape(json_name, quote=True),
    }.items():
        document = document.replace(placeholder, value)
    target.write_text(document, encoding="utf-8")
    return target
