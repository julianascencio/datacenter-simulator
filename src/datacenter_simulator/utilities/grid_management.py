"""Self-contained Plotly views from package simulation outputs; no model logic here."""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from datacenter_simulator.methods.grid_management import GridManagementResult


def write_grid_report(
    runs: dict[str, GridManagementResult],
    planning: dict[str, pd.DataFrame],
    path: str | Path,
) -> Path:
    """Write offline charts with source/status context and explicit units."""
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        subplot_titles=(
            "Served facility demand",
            "Unserved critical demand",
            "Stored battery energy",
        ),
    )
    for name, result in runs.items():
        ts = result.timeseries
        for row, column in (
            (1, "served_kw"),
            (2, "critical_unserved_kw"),
            (3, "battery_energy_kwh"),
        ):
            fig.add_trace(
                go.Scatter(
                    x=ts.index,
                    y=ts[column] / 1000,
                    name=name,
                    legendgroup=name,
                    showlegend=row == 1,
                ),
                row=row,
                col=1,
            )
    fig.update_yaxes(title_text="MW", row=1, col=1)
    fig.update_yaxes(title_text="MW", row=2, col=1)
    fig.update_yaxes(title_text="MWh", row=3, col=1)
    fig.update_layout(height=850, template="plotly_white", legend={"orientation": "h", "y": -0.08})
    deployment = go.Figure()
    monthly = planning["monthly"]
    for case_name, rows in monthly.groupby("case"):
        deployment.add_trace(
            go.Scatter(
                x=rows.month,
                y=rows.commissioned_it_mw,
                mode="lines",
                line_shape="hv",
                name=str(case_name),
            )
        )
    deployment.update_layout(
        title="Conditional commissioning scenarios",
        yaxis_title="Accepted IT MW",
        template="plotly_white",
        height=430,
        legend={"orientation": "h", "y": -0.2},
    )
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame({name: r.summary for name, r in runs.items()}).T.round(3)
    html = Path(__file__).with_suffix(".html").read_text(encoding="utf-8")
    html = html.replace(
        "__OPERATIONS__",
        fig.to_html(full_html=False, include_plotlyjs=True, config={"responsive": True}),
    )
    html = html.replace(
        "__DEPLOYMENT__",
        deployment.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True}),
    )
    html = html.replace("__SUMMARY__", table.to_html())
    dest.write_text(html, encoding="utf-8")
    return dest
