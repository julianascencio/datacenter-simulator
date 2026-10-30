"""Linked equipment views, schematic layers and animated operational overlays."""

import html
import json
from pathlib import Path
from typing import Any, cast

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from datacenter_simulator.methods.dc_grid import DCGrid, DCGridResult
from datacenter_simulator.methods.resilience import ResilienceResult
from datacenter_simulator.models.facility import FacilityLayout
from datacenter_simulator.utilities.plotting import _box

COLORS = {"electrical": "#e9a23b", "cooling": "#32b6c7", "communications": "#9c8aff"}


def dc_grid_single_line(grid: DCGrid, result: DCGridResult) -> go.Figure:
    """Busbar/feeder schematic from the actual solved graph, including reverse power.

    Ports are labelled by control mode. No switch/protection apparatus is invented.
    Meshed ties are drawn directly and may cross; crossings are not junctions.
    """
    if set(result.buses.index) != set(grid.ids) or set(result.lines.index) != {
        e.id for e in grid.lines
    }:
        raise ValueError("solution does not match grid")
    positions = {
        bus: (0 if any(p.bus == bus for p in grid.ports) else 3, -i * 2)
        for i, bus in enumerate(grid.ids)
    }
    figure = go.Figure()
    for line in grid.lines:
        x1, y1 = positions[line.source]
        x2, y2 = positions[line.target]
        row: Any = result.lines.loc[line.id]
        color = "#f05b68" if float(row.loading_pu) > 1 else COLORS["electrical"]
        figure.add_trace(
            go.Scatter(
                x=[x1, (x1 + x2) / 2, (x1 + x2) / 2, x2],
                y=[y1, y1, y2, y2],
                mode="lines",
                line={"color": color, "width": 2},
                customdata=[line.target] * 4,
                name=line.id,
                hovertemplate=html.escape(line.id)
                + f"<br>{row.current_a:.1f} A<br>{row.loss_kw:.3f} kW loss<extra></extra>",
            )
        )
        figure.add_annotation(
            x=(x1 + x2) / 2,
            y=y2 + 0.3,
            text=f"{html.escape(line.id)} · {row.current_a:.1f} A",
            showarrow=False,
            font={"size": 10},
        )
    for bus, (x, y) in positions.items():
        figure.add_shape(
            type="line", x0=x, x1=x, y0=y - 0.5, y1=y + 0.5, line={"width": 7, "color": "#45d5b5"}
        )
        power = float(cast(float, result.buses.at[bus, "load_kw"]))
        voltage = float(cast(float, result.buses.at[bus, "voltage_v"]))
        ports = [p for p in grid.ports if p.bus == bus]
        detail = "<br>".join(
            f"{html.escape(p.id)} ({p.mode}): "
            f"{float(cast(float, result.ports.at[p.id, 'bus_kw'])):.1f} kW"
            for p in ports
        )
        figure.add_trace(
            go.Scatter(
                x=[x],
                y=[y],
                mode="markers+text",
                customdata=[bus],
                marker={"size": 14, "symbol": "square", "color": "#45d5b5"},
                text=[f"{html.escape(bus)}<br>{voltage:.1f} V · {power:.1f} kW load"],
                textposition="top right",
                name=bus,
                hovertemplate=detail + "<extra></extra>",
            )
        )
    figure.update_layout(
        template="plotly_dark",
        title="Solved DC single-line · signed feeder currents",
        height=max(450, len(grid.ids) * 100),
        showlegend=False,
        margin={"l": 40, "r": 180, "t": 60, "b": 40},
    )
    figure.update_xaxes(visible=False, range=[-1, 5])
    figure.update_yaxes(visible=False)
    return figure


def _figure(layout: FacilityLayout, domain: str) -> go.Figure:
    figure = go.Figure()
    assets = {a.id: a for a in layout.assets}
    connections = [
        c for c in layout.connections if domain in {"plan", "scene"} or c.domain == domain
    ]
    present = (
        set(assets)
        if domain in {"plan", "scene"}
        else {v for c in connections for v in (c.source, c.target)}
    )
    if domain in COLORS:
        parents = sorted({c.source for c in connections})
        children = sorted(present - set(parents))
        positions = {name: (0.0, float(i * 2)) for i, name in enumerate(parents)}
        positions.update({name: (4.0, float(i * 1.5)) for i, name in enumerate(children)})
    else:
        positions = {name: (a.placement.x_m, a.placement.y_m) for name, a in assets.items()}
    for c in connections:
        color = COLORS[c.domain]
        if domain == "scene":
            x, y, z = zip(*c.route.points_m, strict=True)
            trace = go.Scatter3d(x=x, y=y, z=z, mode="lines", line={"color": color, "width": 4})
        else:
            if domain == "plan":
                x, y, _ = zip(*c.route.points_m, strict=True)
            else:
                start, end = positions[c.source], positions[c.target]
                middle = 1.5 + 0.4 * sorted({e.source for e in connections}).index(c.source)
                x, y = (start[0], middle, middle, end[0]), (start[1], start[1], end[1], end[1])
            trace = go.Scatter(x=x, y=y, mode="lines", line={"color": color, "width": 2})
        trace.update(
            name=c.id,
            customdata=[c.target] * len(x),
            meta={"equipment_ids": [c.source, c.target], "domain": c.domain, "role": "connection"},
            hovertemplate=(
                f"{html.escape(c.id)}<br>One-way route: {c.route.length_m:.2f} m<extra></extra>"
            ),
            showlegend=False,
        )
        figure.add_trace(trace)
    for name in sorted(present):
        a = assets[name]
        p = a.placement
        if domain == "scene":
            _box(figure, p.x_m, p.y_m, p.z_m, p.width_m, p.depth_m, p.height_m, "#45d5b5", name)
            figure.data[-1].update(
                customdata=[name] * 8, meta={"equipment_ids": [name], "role": "asset"}
            )
        else:
            node_x, node_y = positions[name]
            figure.add_trace(
                go.Scatter(
                    x=[node_x],
                    y=[node_y],
                    mode="markers+text",
                    name=name,
                    customdata=[name],
                    text=[html.escape(name)],
                    textposition="top center",
                    marker={"symbol": "square", "size": 22, "color": "#45d5b5"},
                    meta={"equipment_ids": [name], "role": "asset"},
                    showlegend=False,
                )
            )
    title = {
        "scene": "3D equipment and physical routes",
        "plan": "2D floor plan · metres",
        "electrical": "A/B DC feed schematic",
        "cooling": "CDU branch schematic",
        "communications": "Communication topology",
    }[domain]
    figure.update_layout(
        template="plotly_dark",
        title=title,
        height=440,
        paper_bgcolor="#102033",
        plot_bgcolor="#102033",
        margin={"l": 35, "r": 35, "t": 65, "b": 35},
        uirevision=domain,
    )
    if domain == "scene":
        figure.update_layout(
            scene={
                "aspectmode": "data",
                "xaxis_title": "X [m]",
                "yaxis_title": "Y [m]",
                "zaxis_title": "Z [m]",
                "camera": {"eye": {"x": 1.4, "y": -1.6, "z": 1.2}},
            }
        )
    else:
        figure.update_xaxes(visible=domain == "plan")
        figure.update_yaxes(visible=domain == "plan", scaleanchor="x" if domain == "plan" else None)
    return figure


def write_engineering_lab(
    layout: FacilityLayout, scenario: ResilienceResult, path: str | Path
) -> Path:
    """Self-contained linked views with rack selection and an event-time slider."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    domains = ["scene", "plan", "electrical", "cooling", "communications"]
    figures = {domain: json.loads(_figure(layout, domain).to_json()) for domain in domains}
    frames: list[dict[str, Any]] = []
    for row in scenario.timeline.to_dict("records"):
        rack_data = scenario.racks.loc[scenario.racks.time_s == row["time_s"]].to_dict("records")
        feed_data = scenario.feeds.loc[scenario.feeds.time_s == row["time_s"]].to_dict("records")
        frames.append(
            {
                "time_s": row["time_s"],
                "failed": list(row["failed"]),
                "racks": rack_data,
                "feeds": feed_data,
            }
        )
    payload = json.dumps(
        {"figures": figures, "frames": frames, "assets": [a.id for a in layout.assets]},
        allow_nan=False,
    ).replace("<", "\\u003c")
    template = Path(__file__).with_name("engineering.html").read_text()
    path.write_text(template.replace("__PLOTLY__", get_plotlyjs()).replace("__DATA__", payload))
    return path
