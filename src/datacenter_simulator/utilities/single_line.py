"""Model-derived DC single-line schematics with interactive and vector output.

Symbols are explanatory, not an IEC/ANSI drawing-compliance claim. One line
represents the complete DC circuit; cable resistance includes the return path.
"""

from dataclasses import dataclass, field
from html import escape
from math import isclose
from pathlib import Path
from typing import cast

import pandas as pd
import plotly.graph_objects as go

from datacenter_simulator.methods.electrical import DCNetwork, ElectricalResult

INK = "#16324a"
CABLE = "#2563a6"
CONVERTER = "#a85c00"
LOAD = "#007e73"
ALARM = "#c62838"
MUTED = "#52687b"


@dataclass
class _Stroke:
    points: list[tuple[float, float]]
    color: str = INK
    width: float = 2
    fill: str = "none"


@dataclass
class _Label:
    x: float
    y: float
    lines: list[str]
    color: str = INK
    size: int = 13


@dataclass
class _Drawing:
    width: float
    height: float
    strokes: list[_Stroke] = field(default_factory=list)
    labels: list[_Label] = field(default_factory=list)
    hover: list[tuple[float, float, str]] = field(default_factory=list)
    overloaded: list[str] = field(default_factory=list)
    undervoltage: list[str] = field(default_factory=list)

    def line(self, points: list[tuple[float, float]], color: str = INK, width: float = 2) -> None:
        self.strokes.append(_Stroke(points, color, width))

    def box(self, x: float, y: float, w: float, h: float, color: str) -> None:
        self.strokes.append(
            _Stroke(
                [
                    (x - w / 2, y - h / 2),
                    (x + w / 2, y - h / 2),
                    (x + w / 2, y + h / 2),
                    (x - w / 2, y + h / 2),
                    (x - w / 2, y - h / 2),
                ],
                color,
                2,
                "#ffffff",
            )
        )

    def text(self, x: float, y: float, *lines: str, color: str = INK, size: int = 13) -> None:
        self.labels.append(_Label(x, y, list(lines), color, size))


def _number(frame: pd.DataFrame, key: str, column: str) -> float:
    # Keep pandas scalar typing out of the geometry code.
    return float(cast(float, frame.at[key, column]))


def _drawing(network: DCNetwork, result: ElectricalResult) -> _Drawing:
    if set(result.buses.index) != set(network.buses) or set(result.branches.index) != {
        edge.id for edge in network.branches
    }:
        raise ValueError(
            "single-line result must contain exactly this network's buses and branches"
        )
    if not result.buses.index.is_unique or not result.branches.index.is_unique:
        raise ValueError("single-line result indices must be unique")
    for edge in network.branches:
        row = result.branches.loc[edge.id]
        if row.source != edge.source or row.target != edge.target:
            raise ValueError("single-line result branch endpoints do not match the network")
    if not isclose(
        _number(result.buses, network.source_bus, "voltage_v"),
        network.buses[network.source_bus].nominal_voltage_v,
    ):
        raise ValueError("single-line result source voltage does not match the network")

    # Include local loads as explicit leaves, even at intermediate/source buses.
    # Depth-first order keeps each subtree contiguous and prevents crossed feeders.
    Node = tuple[str, str]
    root: Node = ("bus", network.source_bus)
    children: dict[Node, list[Node]] = {}
    for bus in network.order:
        nodes = [("bus", edge.target) for edge in network.children[bus]]
        if _number(result.buses, bus, "load_kw") > 0:
            nodes.append(("load", bus))
        children[("bus", bus)] = nodes
        children[("load", bus)] = []
    order, stack = [], [root]
    depth = {root: 0}
    while stack:
        node = stack.pop()
        order.append(node)
        for child in reversed(children[node]):
            depth[child] = depth[node] + 1
            stack.append(child)
    leaves = [node for node in order if not children[node]]
    y = {node: 210.0 + i * 175 for i, node in enumerate(leaves)}
    for node in reversed(order):
        if children[node]:
            y[node] = (y[children[node][0]] + y[children[node][-1]]) / 2
    x = {node: 255.0 + depth[node] * 320 for node in order}
    drawing = _Drawing(max(1000, max(x.values()) + 155), 410 + 175 * (len(leaves) - 1))
    drawing.text(drawing.width / 2, 34, "DC DISTRIBUTION / SINGLE-LINE", size=24)
    drawing.text(
        drawing.width / 2,
        68,
        f"Source {result.source_kw:.2f} kW   |   Loads {result.load_kw:.2f} kW"
        f"   |   Distribution losses {result.loss_kw:.3f} kW",
        size=15,
    )
    drawing.text(
        drawing.width / 2,
        101,
        "Blue: cables   /   Amber: regulated DC/DC   /   Teal: local loads"
        "   /   Red: rating or voltage violation",
        color=MUTED,
    )

    for edge in network.branches:
        start, end = ("bus", edge.source), ("bus", edge.target)
        x0, x1, yy = x[start], x[end], y[end]
        mid = (x0 + x1) / 2
        row = result.branches.loc[edge.id]
        current = _number(result.branches, edge.id, "current_a")
        power = _number(result.branches, edge.id, "receiving_kw")
        overcurrent = current > edge.rated_current_a
        overpower = edge.rated_power_kw is not None and power > edge.rated_power_kw
        alarm = overcurrent or overpower
        if alarm:
            drawing.overloaded.append(edge.id)
        color = ALARM if alarm else CONVERTER if edge.kind == "converter" else CABLE
        drawing.line([(x0, yy), (x1, yy)], color)
        drawing.line([(x1 - 26, yy - 5), (x1 - 18, yy), (x1 - 26, yy + 5)], color)
        if edge.kind == "converter":
            drawing.box(mid, yy, 76, 42, color)
            drawing.line([(mid - 38, yy + 21), (mid + 38, yy - 21)], color)
            drawing.text(mid - 19, yy - 8, "DC", color=color, size=11)
            drawing.text(mid + 19, yy + 8, "DC", color=color, size=11)
            spec = f"η {edge.efficiency:.1%}"
            if edge.rated_power_kw is not None:
                spec += f"  /  {edge.rated_power_kw:g} kW rated"
        else:
            spec = f"R loop {edge.resistance_ohm * 1000:.3f} mΩ"
        drawing.text(
            mid,
            yy - 65,
            edge.id,
            spec,
            f"I out {current:.1f} / {edge.rated_current_a:g} A rated",
            color=color,
        )
        status = (
            "OVER CURRENT + POWER"
            if overcurrent and overpower
            else ("OVER CURRENT" if overcurrent else "OVER POWER" if overpower else "")
        )
        drawing.text(
            mid,
            yy + 43,
            f"{power:.2f} kW out  /  ΔP {_number(result.branches, edge.id, 'loss_kw'):.3f} kW",
            status or f"Current loading {current / edge.rated_current_a:.1%}",
            color=color,
        )
        drawing.hover.append(
            (
                mid,
                yy,
                "<br>".join(
                    escape(v)
                    for v in [
                        edge.id,
                        f"{edge.source} → {edge.target}",
                        f"Input {_number(result.branches, edge.id, 'input_current_a'):.2f} A"
                        f" / output {current:.2f} A",
                        f"Sending {_number(result.branches, edge.id, 'sending_kw'):.3f} kW"
                        f" / receiving {power:.3f} kW",
                        f"Loss {_number(result.branches, edge.id, 'loss_kw'):.4f} kW",
                        status or "Within branch ratings",
                    ]
                ),
            )
        )

    for bus, model in network.buses.items():
        node = ("bus", bus)
        xx, yy = x[node], y[node]
        volts = _number(result.buses, bus, "voltage_v")
        pu = volts / model.nominal_voltage_v
        low = pu < model.minimum_voltage_pu
        if low:
            drawing.undervoltage.append(bus)
        color = ALARM if low else INK
        child_y = [y[c] for c in children[node]]
        top, bottom = (min(child_y), max(child_y)) if child_y else (yy, yy)
        drawing.line([(xx, top - 14), (xx, bottom + 14)], color, 5)
        # Bus IDs and voltage are below the receiving junction; feeder labels
        # are centered between buses, on a separate line.
        drawing.text(
            xx - 115 if len(child_y) > 1 else xx,
            yy + 100 if len(child_y) > 1 else yy + 85,
            bus,
            f"{volts:.2f} V / {model.nominal_voltage_v:g} V nominal",
            f"{pu:.4f} pu" + (" · UNDERVOLTAGE" if low else ""),
            color=color,
            size=12,
        )
        drawing.hover.append(
            (
                xx,
                yy,
                "<br>".join(
                    escape(v)
                    for v in [
                        bus,
                        f"Voltage {volts:.3f} V ({pu:.4f} pu)",
                        f"Minimum {model.minimum_voltage_pu:.3f} pu",
                        f"Local demand {_number(result.buses, bus, 'load_kw'):.3f} kW",
                    ]
                ),
            )
        )
        if bus == network.source_bus:
            drawing.box(xx - 72, yy, 76, 48, INK)
            drawing.line([(xx - 34, yy), (xx, yy)])
            drawing.text(xx - 72, yy, "DC", "SOURCE", size=11)
        load = ("load", bus)
        if load in x:
            lx, ly = x[load], y[load]
            drawing.line([(xx, ly), (lx - 61, ly)], LOAD)
            drawing.box(lx, ly, 122, 52, LOAD)
            drawing.text(
                lx, ly, "LOAD", f"{_number(result.buses, bus, 'load_kw'):.2f} kW", color=LOAD
            )
            drawing.text(lx, ly + 52, f"at {bus}", color=LOAD, size=12)

    drawing.text(
        drawing.width / 2,
        drawing.height - 55,
        "Single radial DC source. Arrows show source-to-load direction; currents are"
        " receiving/output-terminal values.",
        color=MUTED,
    )
    drawing.text(
        drawing.width / 2,
        drawing.height - 31,
        "Cable R includes outgoing + return. No protection coordination, grounding,"
        " fault currents or multi-source DC operation are represented.",
        color=MUTED,
    )
    return drawing


def dc_single_line(network: DCNetwork, result: ElectricalResult) -> go.Figure:
    """Draw busbars, feeders, DC/DC converters and local loads from a solved network.

    Red marks both current/power overloads and undervoltage. Hover distinguishes
    converter input/output current. Pan and zoom preserve all individual circuits.
    The diagram has a minimum readable width for use in a scrolling report panel.
    """
    drawing = _drawing(network, result)
    fig = go.Figure()
    for stroke in drawing.strokes:
        path = "M " + " L ".join(f"{xx},{yy}" for xx, yy in stroke.points)
        fig.add_shape(
            type="path",
            path=path,
            line=dict(color=stroke.color, width=stroke.width),
            fillcolor=stroke.fill if stroke.fill != "none" else "rgba(0,0,0,0)",
        )
    for label in drawing.labels:
        fig.add_annotation(
            x=label.x,
            y=label.y,
            text="<br>".join(escape(v) for v in label.lines),
            showarrow=False,
            font=dict(size=label.size, color=label.color),
            xanchor="center",
            yanchor="middle",
            align="center",
        )
    fig.add_trace(
        go.Scatter(
            x=[point[0] for point in drawing.hover],
            y=[point[1] for point in drawing.hover],
            mode="markers",
            marker=dict(size=38, color="rgba(0,0,0,0)"),
            text=[point[2] for point in drawing.hover],
            hovertemplate="%{text}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        title=dict(text=""),
        template="plotly_white",
        font=dict(family="Arial, sans-serif"),
        width=drawing.width,
        height=drawing.height,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
        dragmode="pan",
        hovermode="closest",
        meta=dict(
            diagram="dc-single-line",
            minimum_width=drawing.width,
            bus_ids=list(network.buses),
            branch_ids=[e.id for e in network.branches],
            overloaded_branches=drawing.overloaded,
            undervoltage_buses=drawing.undervoltage,
        ),
    )
    fig.update_xaxes(visible=False, range=[0, drawing.width])
    fig.update_yaxes(visible=False, range=[drawing.height, 0])
    return fig


def write_single_line_svg(network: DCNetwork, result: ElectricalResult, path: str | Path) -> Path:
    """Export a standalone, scalable schematic without a browser or Kaleido.

    Uses the same geometry and values as :func:`dc_single_line`. SVG text is
    escaped and contains no scripts, external resources, or user-supplied markup.
    """
    drawing = _drawing(network, result)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{drawing.width:g}" '
        f'height="{drawing.height:g}" viewBox="0 0 {drawing.width:g} {drawing.height:g}" '
        'role="img" aria-labelledby="title description">',
        '<title id="title">DC distribution single-line diagram</title>',
        '<desc id="description">Solved radial DC circuit with bus voltages, cable loop '
        "resistance, converter ratings, output currents, losses and local loads.</desc>",
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for stroke in drawing.strokes:
        points = " ".join(f"{xx:g},{yy:g}" for xx, yy in stroke.points)
        parts.append(
            f'<polyline points="{points}" fill="{stroke.fill}" stroke="{stroke.color}" '
            f'stroke-width="{stroke.width:g}" stroke-linejoin="round"/>'
        )
    for label in drawing.labels:
        start = label.y - (len(label.lines) - 1) * label.size * 0.65
        parts.append(
            f'<text text-anchor="middle" font-family="Arial,sans-serif" '
            f'font-size="{label.size}" fill="{label.color}">'
        )
        for i, line in enumerate(label.lines):
            parts.append(
                f'<tspan x="{label.x:g}" y="{start + i * label.size * 1.3:g}" '
                f'dominant-baseline="middle">{escape(line)}</tspan>'
            )
        parts.append("</text>")
    parts.append("</svg>")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return target
