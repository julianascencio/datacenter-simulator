"""Reusable Plotly design views and an offline scenario comparison workbench."""

import json
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.utils import PlotlyJSONEncoder

from datacenter_simulator.methods.facility_design import FacilityDesign
from datacenter_simulator.use_cases.design import design_evidence

if TYPE_CHECKING:
    from datacenter_simulator.analysis.design import DesignStudy

COLORS = ["#207c91", "#d99c35", "#7359a1", "#c96b4b", "#5e8b66", "#82909b"]


def _style(figure: go.Figure, title: str) -> go.Figure:
    figure.update_layout(
        title={"text": title, "font": {"size": 17}},
        template="plotly_white",
        font={"family": "Arial, sans-serif", "color": "#263e52"},
        margin={"l": 60, "r": 25, "t": 65, "b": 80},
        legend={"orientation": "h", "y": -0.2},
        height=430,
    )
    return figure


def design_power_flow(design: FacilityDesign) -> go.Figure:
    """Meter-to-end-use Sankey with conserved design electrical power."""
    keys = (
        "it_kw",
        "distribution_loss_kw",
        "ups_loss_kw",
        "cooling_kw",
        "auxiliary_kw",
        "main_loss_kw",
    )
    figure = go.Figure(
        go.Sankey(
            node={
                "label": [
                    "Facility meter",
                    "IT terminals",
                    "Hall distribution losses",
                    "UPS losses",
                    "Cooling",
                    "Site auxiliaries",
                    "Main losses",
                ],
                "color": ["#263e52", *COLORS],
                "pad": 20,
            },
            link={
                "source": [0] * 6,
                "target": list(range(1, 7)),
                "value": [design.balance[k] for k in keys],
            },
            valueformat=".1f",
            valuesuffix=" kW",
        )
    )
    return _style(figure, "Where the design power goes")


def design_capacity_chart(design: FacilityDesign) -> go.Figure:
    """Compare duty with installed and contingency capacity in each domain."""
    frame = design.equipment
    labels = [
        f"{row.equipment}<br>({'kWth' if row.domain == 'thermal' else 'kWe'})"
        for row in frame.itertuples()
    ]
    figure = go.Figure()
    for column, name, color in (
        ("duty_kw", "Required duty", COLORS[0]),
        ("installed_usable_kw", "Installed usable", "#b8cbd7"),
        ("remaining_kw", "After contingency", COLORS[1]),
    ):
        figure.add_bar(x=labels, y=frame[column].tolist(), name=name, marker_color=color)
    figure.update_layout(barmode="group", yaxis_title="kW (electrical or thermal as labelled)")
    return _style(figure, "Capacity before and after the specified loss")


def design_floor_plan(design: FacilityDesign, *, max_racks: int = 1000) -> go.Figure:
    """Dimensioned rack geometry with front faces alternating across cold aisles.

    Large exports show at most ``max_racks``; full geometry remains in racks.csv.
    This is placement geometry, not CFD or an egress drawing.
    """
    if type(max_racks) is not int or max_racks < 1:
        raise ValueError("max_racks must be a positive integer")
    racks = design.racks.head(max_racks)
    figure = go.Figure()
    for rack in racks.to_dict("records"):
        x, y, w, d = (float(rack[k]) for k in ("x_m", "y_m", "width_m", "depth_m"))
        figure.add_shape(
            type="rect",
            x0=x,
            x1=x + w,
            y0=y,
            y1=y + d,
            fillcolor=COLORS[0],
            line={"color": "white", "width": 1},
        )
        front = y + d if int(rack["row"]) % 2 else y
        figure.add_shape(
            type="line", x0=x, x1=x + w, y0=front, y1=front, line={"color": "#73d7eb", "width": 3}
        )
    figure.add_scatter(
        x=(racks.x_m + racks.width_m / 2).tolist(),
        y=(racks.y_m + racks.depth_m / 2).tolist(),
        mode="markers",
        marker={"size": 12, "color": COLORS[0]},
        text=[f"{r.rack}: {r.it_kw:.2f} kW" for r in racks.itertuples()],
        hovertemplate="%{text}<extra></extra>",
        showlegend=False,
    )
    figure.update_xaxes(title="Hall width (m)", range=[0, design.summary["hall_width_m"]])
    figure.update_yaxes(
        title="Hall depth (m)",
        range=[0, design.summary["hall_depth_m"]],
        scaleanchor="x",
        scaleratio=1,
    )
    return _style(figure, f"Rack plan · {len(racks)} of {len(design.racks)} racks · cyan = front")


def design_rack_scene(design: FacilityDesign, *, max_racks: int = 1000) -> go.Figure:
    """Single-mesh 3D rack envelopes with demand hover labels."""
    if type(max_racks) is not int or max_racks < 1:
        raise ValueError("max_racks must be a positive integer")
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    ii: list[int] = []
    jj: list[int] = []
    kk: list[int] = []
    labels: list[str] = []
    faces = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    racks = design.racks.head(max_racks)
    for rack in racks.to_dict("records"):
        start = len(xs)
        x, y, w, d, h = (float(rack[k]) for k in ("x_m", "y_m", "width_m", "depth_m", "height_m"))
        xs.extend([x, x + w, x + w, x, x, x + w, x + w, x])
        ys.extend([y, y, y + d, y + d, y, y, y + d, y + d])
        zs.extend([0, 0, 0, 0, h, h, h, h])
        labels.extend([f"{rack['rack']}: {rack['it_kw']:.2f} kW"] * 8)
        for a, b, c in faces:
            ii.append(start + a)
            jj.append(start + b)
            kk.append(start + c)
    figure = go.Figure(
        go.Mesh3d(
            x=xs,
            y=ys,
            z=zs,
            i=ii,
            j=jj,
            k=kk,
            color=COLORS[0],
            flatshading=True,
            text=labels,
            hovertemplate="%{text}<extra></extra>",
        )
    )
    figure.update_layout(
        scene={
            "xaxis": {"title": "Width (m)", "range": [0, design.summary["hall_width_m"]]},
            "yaxis": {"title": "Depth (m)", "range": [0, design.summary["hall_depth_m"]]},
            "zaxis": {"title": "Height (m)"},
            "aspectmode": "data",
        }
    )
    return _style(figure, f"3D rack envelopes · {len(racks)} of {len(design.racks)} racks")


def design_load_chart(study: "DesignStudy") -> go.Figure:
    """Fixed installed duty plant across IT demand at the design ambient."""
    frame = study.load_sweep
    figure = go.Figure()
    for key, name in (
        ("it_kw", "IT demand"),
        ("facility_kw", "Facility demand"),
        ("cooling_kw", "Cooling electricity"),
    ):
        figure.add_scatter(
            x=(frame.load_fraction * 100).tolist(), y=frame[key].tolist(), name=name, mode="lines"
        )
    figure.add_hline(
        y=study.design.inputs.grid_limit_kw,
        line_dash="dash",
        annotation_text="Grid limit",
        annotation_position="top left",
    )
    figure.update_layout(xaxis_title="Design IT demand (%)", yaxis_title="Electrical power (kW)")
    return _style(figure, "Load sensitivity at the design outdoor temperature")


def design_energy_chart(study: "DesignStudy") -> go.Figure:
    """Weighted operating bins, not a time series or an arithmetic PUE average."""
    frame = study.operating
    labels = [
        f"{r.load_fraction:.0%} load / {r.ambient_c:g}°C<br>{r.hours:g} h"
        for r in frame.itertuples()
    ]
    figure = go.Figure()
    figure.add_bar(x=labels, y=(frame.it_kw * frame.hours / 1000).tolist(), name="IT")
    figure.add_bar(
        x=labels,
        y=((frame.facility_kw - frame.it_kw) * frame.hours / 1000).tolist(),
        name="Facility overhead",
    )
    figure.update_layout(barmode="stack", yaxis_title="Annual energy contribution (MWh)")
    return _style(figure, "8760-hour load and weather bins")


def write_design_report(studies: Mapping[str, "DesignStudy"], path: str | Path) -> Path:
    """Write an offline selector with Python-calculated charts and audit downloads.

    The first study is the exported baseline. Inputs are changed through the
    Python/JSON interface; the report selects precomputed comparison scenarios.
    """
    if not studies:
        raise ValueError("at least one design study is required")
    baseline = next(iter(studies.values()))
    payload = {}
    for name, study in studies.items():
        payload[name] = {
            "summary": study.summary,
            "equipment": study.design.equipment.to_dict("records"),
            "figures": [
                f.to_plotly_json()
                for f in (
                    design_power_flow(study.design),
                    design_capacity_chart(study.design),
                    design_load_chart(study),
                    design_energy_chart(study),
                )
            ],
        }
    geometry = [
        f.to_plotly_json()
        for f in (design_floor_plan(baseline.design), design_rack_scene(baseline.design))
    ]
    data = json.dumps({"scenarios": payload, "geometry": geometry}, cls=PlotlyJSONEncoder)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    options = "".join(f'<option value="{escape(name)}">{escape(name)}</option>' for name in studies)
    files = [
        "inputs.json",
        "bins.json",
        "summary.json",
        "balance.json",
        "equipment.csv",
        "racks.csv",
        "operating.csv",
        "load_sweep.csv",
        "comparison.csv",
        "scenarios.json",
        "evidence.json",
    ]
    downloads = " · ".join(f'<a href="{f}" download>{f}</a>' for f in files)
    evidence = design_evidence()
    template = Path(__file__).with_name("design.html").read_text(encoding="utf-8")
    html = (
        template.replace("__PLOTLY__", get_plotlyjs())
        .replace("__DATA__", data)
        .replace("__COUNT__", str(len(studies)))
        .replace("__OPTIONS__", options)
        .replace("__DOWNLOADS__", downloads)
        .replace("__EVIDENCE__", escape(json.dumps(evidence, indent=2)))
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
