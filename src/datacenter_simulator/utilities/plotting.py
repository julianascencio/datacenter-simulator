"""Interactive 2D/3D equipment layouts, single-line diagrams and result plots."""

import html

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from datacenter_simulator.methods.communications import CommunicationResult
from datacenter_simulator.methods.electrical import ElectricalResult
from datacenter_simulator.simulation import DataCenter, SimulationResult
from datacenter_simulator.utilities.single_line import dc_single_line

PALETTE = ["#50dfbd", "#5bbcff", "#ffbd69", "#b69cff", "#ff7489", "#e4eaef"]
BACKGROUND = "#101b2b"


def _style(fig: go.Figure, title: str, height: int = 620) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        title=dict(text=title, x=0.03),
        paper_bgcolor=BACKGROUND,
        plot_bgcolor=BACKGROUND,
        font=dict(family="Arial, sans-serif", color="#dce8f2"),
        colorway=PALETTE,
        height=height,
        margin=dict(l=45, r=30, t=70, b=45),
        legend=dict(orientation="h", y=-0.12),
    )
    return fig


def floor_plan(center: DataCenter, utilization: float = 0.7) -> go.Figure:
    """True-scale floor plan with equipment footprints, labels and terminal powers."""
    fig = go.Figure()
    for device in center.devices:
        p = device.placement
        color = PALETTE[0] if "rack" in device.kind else PALETTE[3]
        fig.add_trace(
            go.Scatter(
                x=[p.x_m, p.x_m + p.width_m, p.x_m + p.width_m, p.x_m, p.x_m],
                y=[p.y_m, p.y_m, p.y_m + p.depth_m, p.y_m + p.depth_m, p.y_m],
                mode="lines",
                fill="toself",
                fillcolor=color,
                opacity=0.75,
                line=dict(color=color),
                name=device.id,
                hovertemplate=f"{html.escape(device.id)}<br>{html.escape(device.kind)}"
                f"<br>{device.power_kw(utilization):.1f} kW"
                f"<br>{p.width_m} × {p.depth_m} × {p.height_m} m<extra></extra>",
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=p.x_m + p.width_m / 2,
            y=p.y_m + p.depth_m + 0.25,
            text=html.escape(device.id),
            showarrow=False,
            font=dict(size=11),
        )
    fig.update_xaxes(title="X [m]", zeroline=False, gridcolor="#223148")
    fig.update_yaxes(title="Y [m]", scaleanchor="x", scaleratio=1, gridcolor="#223148")
    return _style(fig, "02 / Equipment floor plan · terminal power on hover")


def _box(
    fig: go.Figure,
    x: float,
    y: float,
    z: float,
    width: float,
    depth: float,
    height: float,
    color: str,
    name: str,
    opacity: float = 1,
) -> None:
    fig.add_trace(
        go.Mesh3d(
            x=[x, x + width, x + width, x, x, x + width, x + width, x],
            y=[y, y, y + depth, y + depth, y, y, y + depth, y + depth],
            z=[z, z, z, z, z + height, z + height, z + height, z + height],
            i=[0, 0, 4, 4, 0, 0, 1, 1, 2, 2, 3, 3],
            j=[1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 0, 4],
            k=[2, 3, 6, 7, 5, 4, 6, 5, 7, 6, 4, 7],
            color=color,
            opacity=opacity,
            flatshading=True,
            name=name,
            showlegend=False,
            lighting=dict(ambient=0.55, diffuse=0.9, specular=0.4, roughness=0.4),
            lightposition=dict(x=0, y=-10, z=15),
            hovertemplate=html.escape(name) + "<extra></extra>",
        )
    )


def equipment_3d(center: DataCenter, utilization: float = 0.7) -> go.Figure:
    """Dimensioned rack scene with server fronts and illustrative support routing.

    Equipment locations come from the device model. Support trays and cooling plant
    placement are generated for presentation, not an installation routing solution.
    """
    fig = go.Figure()
    xmax = max(d.placement.x_m + d.placement.width_m for d in center.devices) + 3
    ymax = max(d.placement.y_m + d.placement.depth_m for d in center.devices) + 1
    _box(fig, -0.3, -0.3, -0.12, xmax + 1, ymax + 1, 0.1, "#27364a", "Equipment hall floor")
    for device in center.devices:
        p = device.placement
        power = device.power_kw(utilization)
        _box(
            fig,
            p.x_m,
            p.y_m,
            p.z_m,
            p.width_m,
            p.depth_m,
            p.height_m,
            "#283c51",
            f"{device.id} | {power:.1f} kW | {device.electrical.nominal_voltage_v:g} V",
        )
        for level in np.linspace(0.12, p.height_m - 0.15, 10):
            _box(
                fig,
                p.x_m + 0.035,
                p.y_m - 0.015,
                p.z_m + float(level),
                p.width_m - 0.07,
                0.025,
                0.075,
                "#60748b",
                f"{device.id} • illustrative server face",
            )
        _box(
            fig,
            p.x_m + 0.04,
            p.y_m - 0.035,
            p.z_m + 0.10,
            0.02,
            0.02,
            p.height_m - 0.2,
            PALETTE[0],
            f"{device.id} • status strip",
        )
        # Trace from common overhead tray to rack; color marks network layer.
        fig.add_trace(
            go.Scatter3d(
                x=[0.2, p.x_m + p.width_m / 2, p.x_m + p.width_m / 2],
                y=[p.y_m + 0.5] * 3,
                z=[2.8, 2.8, p.z_m + p.height_m],
                mode="lines",
                line=dict(color=PALETTE[2], width=4),
                showlegend=False,
                hovertemplate="Illustrative DC cable route<extra></extra>",
            )
        )
        if "rack" in device.kind:
            fig.add_trace(
                go.Scatter3d(
                    x=[xmax - 0.5, p.x_m + p.width_m / 2, p.x_m + p.width_m / 2],
                    y=[p.y_m + p.depth_m + 0.2] * 3,
                    z=[0.15, 0.15, 1.6],
                    mode="lines",
                    line=dict(color=PALETTE[1], width=4),
                    showlegend=False,
                    hovertemplate="Illustrative coolant supply<extra></extra>",
                )
            )
    _box(fig, xmax - 0.8, 3.5, 0, 0.8, 1.4, 1.7, "#397b8b", "Cooling plant / CDU (schematic)")
    fig.add_trace(
        go.Scatter3d(
            x=[xmax - 0.4],
            y=[4.2],
            z=[2],
            mode="text",
            text=["Cooling / CDU"],
            showlegend=False,
        )
    )
    fig.update_layout(
        scene=dict(
            xaxis_title="X [m]",
            yaxis_title="Y [m]",
            zaxis_title="Z [m]",
            aspectmode="data",
            bgcolor=BACKGROUND,
            camera=dict(eye=dict(x=1.5, y=-1.6, z=1.1)),
        )
    )
    return _style(fig, "01 / Data hall · drag to orbit, scroll to zoom", 740)


def electrical_diagram(center: DataCenter, result: ElectricalResult) -> go.Figure:
    """DC single-line with busbars, converter symbols, ratings and solved results.

    Compatibility wrapper around :func:`.single_line.dc_single_line`.
    """
    return dc_single_line(center.electrical, result)


def communications_diagram(center: DataCenter, result: CommunicationResult) -> go.Figure:
    fig = go.Figure()
    positions = {d.id: (d.placement.x_m, d.placement.y_m) for d in center.devices}
    for link in center.communications.links:
        rows = result.links[result.links.link == link.id]
        loading = float(rows.utilization.max())
        available = bool(rows.available.all())
        color = "#586475" if not available else PALETTE[4] if loading > 1 else PALETTE[1]
        fig.add_trace(
            go.Scatter(
                x=[positions[link.source][0], positions[link.target][0]],
                y=[positions[link.source][1], positions[link.target][1]],
                mode="lines",
                line=dict(
                    color=color, width=2 + min(loading, 2) * 3, dash="solid" if available else "dot"
                ),
                showlegend=False,
                hovertemplate=f"{html.escape(link.id)}<br>{link.capacity_gbps:g} Gbps"
                f"<br>Peak directional loading {loading:.1%}"
                f"<br>Available: {available}<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[positions[n][0] for n in center.communications.nodes],
            y=[positions[n][1] for n in center.communications.nodes],
            mode="markers+text",
            text=[html.escape(n) for n in center.communications.nodes],
            textposition="top center",
            marker=dict(size=18, color=PALETTE[0]),
            showlegend=False,
        )
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _style(fig, "04 / Communication topology · line width = offered traffic")


def cooling_schema(center: DataCenter, heat_kw: float, ambient_c: float) -> go.Figure:
    """Heat/electricity Sankey for the selected HVAC model, including unmet heat."""
    c = center.cooling.evaluate(heat_kw, ambient_c)
    return _style(
        go.Figure(
            go.Sankey(
                arrangement="snap",
                node=dict(
                    label=[
                        "IT + indoor distribution heat",
                        "Cooling electricity",
                        "Liquid loop",
                        "Residual air loop",
                        "Heat rejection",
                        "Ambient",
                        "Unmet heat",
                    ],
                    color=[
                        PALETTE[2],
                        PALETTE[3],
                        PALETTE[1],
                        PALETTE[0],
                        PALETTE[4],
                        "#7a92a9",
                        "#ff4f68",
                    ],
                    pad=24,
                    thickness=20,
                ),
                link=dict(
                    source=[0, 0, 0, 2, 3, 1, 4],
                    target=[2, 3, 6, 4, 4, 4, 5],
                    value=[
                        c.liquid_heat_kw,
                        c.air_heat_kw,
                        c.unmet_heat_kw,
                        c.liquid_heat_kw,
                        c.air_heat_kw,
                        c.electric_kw,
                        c.rejected_heat_kw,
                    ],
                ),
                valueformat=".1f",
                valuesuffix=" kW",
            )
        ),
        f"05 / Thermal balance · {html.escape(center.cooling.name)} · {ambient_c:g} °C",
    )


def power_timeseries(result: SimulationResult) -> go.Figure:
    frame = result.timeseries
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12, row_heights=[0.65, 0.35]
    )
    for column, name in [
        ("it_kw", "IT equipment"),
        ("dc_loss_kw", "DC distribution losses"),
        ("rectifier_loss_kw", "Rectifier losses"),
        ("cooling_kw", "Cooling"),
        ("auxiliary_kw", "Other auxiliaries"),
    ]:
        fig.add_trace(
            go.Scatter(x=frame.index, y=frame[column], name=name, stackgroup="demand"), row=1, col=1
        )
    for column, name, dash in [
        ("generation_kw", "Available generation", "dash"),
        ("grid_import_kw", "Grid import", "solid"),
    ]:
        fig.add_trace(
            go.Scatter(x=frame.index, y=frame[column], name=name, line=dict(dash=dash, width=2)),
            row=1,
            col=1,
        )
    fig.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame.battery_energy_kwh,
            name="Battery energy",
            line=dict(color=PALETTE[3]),
        ),
        row=2,
        col=1,
    )
    fig.update_yaxes(title_text="Power [kW]", row=1, col=1)
    fig.update_yaxes(title_text="Stored [kWh]", row=2, col=1)
    fig.update_xaxes(title_text="UTC · interval start", row=2, col=1)
    fig.update_layout(hovermode="x unified")
    return _style(fig, "06 / Facility demand, generation and storage", 680)


def cooling_comparison(results: dict[str, SimulationResult]) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Cooling energy [kWh]", "Energy-based PUE"))
    names = list(results)
    for column, key in [(1, "cooling_kwh"), (2, "pue")]:
        fig.add_trace(
            go.Bar(
                x=names,
                y=[results[n].summary[key] for n in names],
                marker_color=PALETTE[: len(names)],
                showlegend=False,
            ),
            row=1,
            col=column,
        )
    return _style(fig, "07 / HVAC alternatives · identical IT demand and weather", 540)
