from pathlib import Path

from datacenter_simulator.cli import generate_reference
from datacenter_simulator.use_cases import reference_center
from datacenter_simulator.utilities.plotting import electrical_diagram, equipment_3d


def test_geometry_and_single_line_use_model() -> None:
    center = reference_center()
    scene = equipment_3d(center)
    assert len([trace for trace in scene.data if trace.type == "mesh3d"]) >= len(center.devices)
    result = center.electrical.solve(center.bus_loads(0.7))
    diagram = electrical_diagram(center, result)
    assert set(diagram.layout.meta["branch_ids"]) == {e.id for e in center.electrical.branches}
    assert set(diagram.layout.meta["bus_ids"]) == set(center.electrical.buses)


def test_report_is_offline_with_exports(tmp_path: Path) -> None:
    target = generate_reference(tmp_path, hours=4)
    content = target.read_text()
    assert "__PLOTLY__" not in content
    assert 'id="panel-6"' in content
    assert '<script src="https://' not in content
    assert target.with_suffix(".csv").exists()
    assert target.with_suffix(".json").exists()
    svg = target.with_name(target.stem + "-single-line.svg")
    assert svg.exists()
    assert svg.name in content
    assert "__SLD__" not in content
