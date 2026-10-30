"""Visuals preserve model identities, routes and inert JSON embedding."""

import json
from dataclasses import replace

import pytest

from datacenter_simulator.analysis.engineering import resilience_study
from datacenter_simulator.models.facility import FacilityLayout
from datacenter_simulator.use_cases.engineering import (
    engineering_cooling,
    engineering_grid,
    engineering_layout,
)
from datacenter_simulator.utilities.engineering import dc_grid_single_line, write_engineering_lab


def test_route_geometry_is_reused_in_electrical_and_hydraulic_models():
    layout, grid, branches = engineering_layout(), engineering_grid(), engineering_cooling()
    routes = {c.id: c.route.length_m for c in layout.connections}
    for line in grid.lines:
        assert line.loop_resistance_ohm == pytest.approx(2 * 0.01724 * routes[line.id] / 120)
    for branch in branches:
        assert branch.pipe.length_m == pytest.approx(2 * routes[f"cdu:{branch.id}"])
    connected = layout.connected("rack-01")
    assert set(connected) == {"rack-01", "feed-A", "feed-B", "cdu", "switch"}
    with pytest.raises(ValueError):
        FacilityLayout(layout.assets, (replace(layout.connections[0], target="unknown"),))


def test_solved_single_line_and_offline_linked_lab(tmp_path):
    grid = engineering_grid()
    result = grid.solve({f"rack-{i + 1:02d}": 40 for i in range(4)})
    drawing = dc_grid_single_line(grid, result)
    assert len(drawing.layout.shapes) == len(grid.ids)
    path = write_engineering_lab(engineering_layout(), resilience_study(), tmp_path / "lab.html")
    source = path.read_text()
    assert "__DATA__" not in source and "__PLOTLY__" not in source
    start = source.index('<script id="lab-data" type="application/json">') + len(
        '<script id="lab-data" type="application/json">'
    )
    payload = json.loads(source[start : source.index("</script>", start)])
    assert set(payload["figures"]) == {"scene", "plan", "electrical", "cooling", "communications"}
    assert any("feed-A" in frame["failed"] for frame in payload["frames"])
    for figure in payload["figures"].values():
        assert any(
            "rack-01" in trace.get("meta", {}).get("equipment_ids", []) for trace in figure["data"]
        )
