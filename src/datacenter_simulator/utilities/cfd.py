"""Interactive field views for calculated CFD arrays, with no browser-side solver."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from datacenter_simulator.methods.cfd import CFDResult, cell_coordinates, source_fields
from datacenter_simulator.use_cases.cfd import cfd_evidence


def temperature_slice(result: CFDResult, *, frame: int = -1, height_m: float = 1.2) -> go.Figure:
    """Return a reusable Plotly horizontal temperature slice at the nearest centre."""
    x, y, z = cell_coordinates(result.case.grid)
    if not np.isfinite(height_m) or not 0 <= height_m <= result.case.grid.height_m:
        raise ValueError("height_m must lie within the room")
    k = int(np.argmin(np.abs(z - height_m)))
    snap = result.snapshots[frame]
    figure = go.Figure(
        go.Heatmap(
            x=x.tolist(),
            y=y.tolist(),
            z=snap.temperature_c[:, :, k].T.tolist(),
            colorscale="Turbo",
            colorbar={"title": "°C"},
        )
    )
    figure.update_layout(
        title=f"Air temperature at z={z[k]:.2f} m, t={snap.time_s:g} s",
        xaxis_title="x (m)",
        yaxis_title="y (m)",
        template="plotly_white",
    )
    figure.update_yaxes(scaleanchor="x", scaleratio=1)
    return figure


def write_cfd_report(
    results: Mapping[str, CFDResult],
    path: str | Path,
    *,
    downloads: Sequence[str] = (),
    mesh: pd.DataFrame | None = None,
) -> Path:
    """Embed time-dependent 3D fields, slice selectors, vectors and numerical audits."""
    if not results:
        raise ValueError("CFD report requires at least one result")
    cases = {}
    low, high = float("inf"), -float("inf")
    for name, result in results.items():
        x, y, z = cell_coordinates(result.case.grid)
        _, _, weights = source_fields(result.case)
        frames = []
        for snap in result.snapshots:
            speed = np.sqrt(sum(a * a for a in snap.velocity_m_s))
            low = min(low, float(np.min(snap.temperature_c)))
            high = max(high, float(np.max(snap.temperature_c)))
            frames.append(
                {
                    "time": snap.time_s,
                    "temperature": snap.temperature_c.ravel().tolist(),
                    "pressure": snap.pressure_pa.ravel().tolist(),
                    "speed": speed.ravel().tolist(),
                    "u": snap.velocity_m_s[0].ravel().tolist(),
                    "v": snap.velocity_m_s[1].ravel().tolist(),
                    "w": snap.velocity_m_s[2].ravel().tolist(),
                    "max_temperature": float(np.max(snap.temperature_c)),
                    "max_speed": float(speed.max()),
                    "racks": [
                        {
                            "name": s.name,
                            "mean": float((snap.temperature_c * weight).sum()),
                            "max": float(np.max(snap.temperature_c[weight > 0])),
                        }
                        for s, weight in zip(result.case.sources, weights, strict=True)
                    ],
                }
            )
        cases[name] = {
            "inputs": asdict(result.case),
            "summary": result.summary,
            "x": x.tolist(),
            "y": y.tolist(),
            "z": z.tolist(),
            "frames": frames,
            "history": result.history.to_dict("list"),
        }
    payload = {"cases": cases, "temperature_min": low, "temperature_max": max(high, low + 0.1)}
    data = (
        json.dumps(payload, allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = Path(__file__).with_name("cfd.html").read_text(encoding="utf-8")
    links = " · ".join(
        f'<a download href="{escape(f, quote=True)}">{escape(f)}</a>' for f in downloads
    )
    mesh_html = "Not run for this export. Use --mesh-study to compare coarse, base and fine grids."
    if mesh is not None and not mesh.empty:
        mesh_html = mesh.to_html(index=False, float_format=lambda value: f"{value:.5g}")
    options = "".join(f"<option>{escape(name)}</option>" for name in results)
    html = (
        template.replace("__PLOTLY__", get_plotlyjs())
        .replace("__DATA__", data)
        .replace("__OPTIONS__", options)
        .replace("__LINKS__", links)
        .replace("__MESH__", mesh_html)
        .replace("__EVIDENCE__", escape(json.dumps(cfd_evidence(), indent=2)))
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
