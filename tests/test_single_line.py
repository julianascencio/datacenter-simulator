from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from datacenter_simulator.methods.electrical import DCBranch, DCBus, DCNetwork
from datacenter_simulator.utilities.single_line import dc_single_line, write_single_line_svg


def annotations(figure: object) -> str:
    return "\n".join(a.text for a in figure.layout.annotations)  # type: ignore[attr-defined]


def test_converter_input_output_and_vector_agree(tmp_path: Path) -> None:
    network = DCNetwork(
        [DCBus("s", 400), DCBus("l", 48)],
        [DCBranch("converter", "s", "l", efficiency=0.96, kind="converter")],
        "s",
    )
    result = network.solve({"l": 48})
    fig = dc_single_line(network, result)
    assert "I out 1000.0 / 1000 A rated" in annotations(fig)
    assert "48.00 kW out  /  ΔP 2.000 kW" in annotations(fig)
    assert "Input 125.00 A / output 1000.00 A" in fig.data[0].text[0]
    svg = write_single_line_svg(network, result, tmp_path / "circuit.svg")
    root = ET.fromstring(svg.read_text())
    text = " ".join(root.itertext())
    assert "I out 1000.0 / 1000 A rated" in text
    assert "Source 50.00 kW" in text
    assert "48.00 V / 48 V nominal" in text
    assert fig.layout.meta["overloaded_branches"] == []


def test_power_overload_with_current_below_rating() -> None:
    network = DCNetwork(
        [DCBus("s", 400), DCBus("l", 48)],
        [DCBranch("converter", "s", "l", kind="converter", rated_power_kw=2)],
        "s",
    )
    fig = dc_single_line(network, network.solve({"l": 3}))
    assert fig.layout.meta["overloaded_branches"] == ["converter"]
    assert "OVER POWER" in annotations(fig)
    assert "OVER CURRENT" not in annotations(fig)


def test_overcurrent_and_undervoltage_visible() -> None:
    network = DCNetwork(
        [DCBus("s", 48), DCBus("l", 48, 0.99)],
        [DCBranch("cable", "s", "l", 0.01, rated_current_a=5)],
        "s",
    )
    fig = dc_single_line(network, network.solve({"l": 4}))
    assert fig.layout.meta["undervoltage_buses"] == ["l"]
    assert "UNDERVOLTAGE" in annotations(fig)
    assert "OVER CURRENT" in annotations(fig)
    assert "R loop 10.000 mΩ" in annotations(fig)


def test_local_loads_at_source_intermediate_and_leaf_are_not_lost() -> None:
    network = DCNetwork(
        [DCBus(n, 400) for n in ["s", "mid", "end"]],
        [DCBranch("a", "s", "mid"), DCBranch("b", "mid", "end")],
        "s",
    )
    fig = dc_single_line(network, network.solve({"s": 1, "mid": 2, "end": 3}))
    text = annotations(fig)
    for label in ["LOAD<br>1.00 kW", "LOAD<br>2.00 kW", "LOAD<br>3.00 kW"]:
        assert label in text
    assert set(fig.layout.meta["bus_ids"]) == {"s", "mid", "end"}
    assert "Loads 6.00 kW" in text


@pytest.mark.parametrize("load", [0, 3])
def test_single_bus_and_no_branches(load: float) -> None:
    network = DCNetwork([DCBus("source", 400)], [], "source")
    fig = dc_single_line(network, network.solve({"source": load}))
    assert fig.layout.meta["branch_ids"] == []
    assert fig.layout.height > 0
    assert ("LOAD<br>3.00 kW" in annotations(fig)) == bool(load)


def test_reject_mismatched_result() -> None:
    network = DCNetwork([DCBus("s", 400), DCBus("l", 400)], [DCBranch("a", "s", "l")], "s")
    other = DCNetwork([DCBus("s", 800), DCBus("l", 800)], [DCBranch("a", "s", "l")], "s")
    with pytest.raises(ValueError, match="source voltage"):
        dc_single_line(network, other.solve({"l": 1}))
    result = network.solve({"l": 1})
    result.branches.at["a", "target"] = "wrong"
    with pytest.raises(ValueError, match="endpoints"):
        dc_single_line(network, result)
    result.buses = result.buses.drop("l")
    with pytest.raises(ValueError, match="exactly"):
        dc_single_line(network, result)


def test_svg_and_plot_labels_escape_identifiers(tmp_path: Path) -> None:
    name = '<script>alert("x")</script> & source'
    network = DCNetwork([DCBus(name, 400)], [], name)
    result = network.solve({})
    fig = dc_single_line(network, result)
    assert "<script>" not in annotations(fig)
    path = write_single_line_svg(network, result, tmp_path / "escaped.svg")
    root = ET.fromstring(path.read_text())
    assert name in " ".join(root.itertext())
    assert all(not element.tag.endswith("script") for element in root.iter())
