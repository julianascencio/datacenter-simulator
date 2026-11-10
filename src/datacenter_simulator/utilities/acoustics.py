"""Offline 3D acoustic field explorer; calculations remain in the Python engine."""

import json
from dataclasses import asdict
from html import escape
from pathlib import Path
from typing import Any

import numpy as np
from plotly.offline import get_plotlyjs

from datacenter_simulator.methods.acoustics import AcousticResult
from datacenter_simulator.methods.cfd import cell_coordinates
from datacenter_simulator.models.acoustics import OCTAVE_HZ


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_noise_report(
    results: dict[str, AcousticResult], path: str | Path, downloads: list[str]
) -> Path:
    cases = {}
    for name, r in results.items():
        coordinates = cell_coordinates(r.case.grid)
        cases[name] = {
            "inputs": asdict(r.case),
            "summary": r.summary,
            "coordinates": [c.tolist() for c in coordinates],
            "fields": {
                "A": r.laeq_dba.ravel().tolist(),
                **{str(f): r.band_spl_db[..., i].ravel().tolist() for i, f in enumerate(OCTAVE_HZ)},
            },
            "receivers": r.receivers.to_dict("records"),
            "contributions": r.contributions.to_dict("records"),
            "room": r.room.to_dict("records"),
        }
    data = json.dumps(_finite({"cases": cases, "frequencies": OCTAVE_HZ}), allow_nan=False)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("acoustics.html").read_text()
    html = template.replace("__PLOTLY__", get_plotlyjs()).replace("__DATA__", data)
    html = html.replace(
        "__DOWNLOADS__",
        " · ".join(
            f'<a download href="{escape(f, quote=True)}">{escape(f)}</a>' for f in downloads
        ),
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    return path
