from math import sqrt

import pytest

from datacenter_simulator.methods.electrical import DCBranch, DCBus, DCNetwork
from datacenter_simulator.use_cases import reference_center


def test_two_bus_against_analytical_high_voltage_solution() -> None:
    network = DCNetwork(
        [DCBus("source", 400), DCBus("load", 400)],
        [DCBranch("cable", "source", "load", 0.1)],
        "source",
    )
    result = network.solve({"load": 100})
    voltage = (400 + sqrt(400**2 - 4 * 0.1 * 100_000)) / 2
    assert result.buses.loc["load", "voltage_v"] == pytest.approx(voltage, abs=1e-7)
    assert result.branches.loc["cable", "current_a"] == pytest.approx(100_000 / voltage)
    assert result.source_kw == pytest.approx(400 * 100 / voltage)
    assert result.source_kw == pytest.approx(result.load_kw + result.loss_kw)


def test_converter_conserves_power_not_current() -> None:
    network = DCNetwork(
        [DCBus("s", 400), DCBus("l", 48)],
        [DCBranch("dc-dc", "s", "l", efficiency=0.96, kind="converter")],
        "s",
    )
    result = network.solve({"l": 48})
    assert result.source_kw == pytest.approx(50)
    assert result.branches.loc["dc-dc", "input_current_a"] == pytest.approx(125)
    assert result.branches.loc["dc-dc", "current_a"] == pytest.approx(1000)


@pytest.mark.parametrize("voltage", [380, 400, 800])
def test_reference_voltage_options(voltage: float) -> None:
    center = reference_center(bus_voltage_v=voltage)
    r = center.electrical.solve(center.bus_loads(1))
    assert r.source_kw == pytest.approx(r.load_kw + r.loss_kw, abs=1e-8)
    assert not r.warnings
    assert (r.buses.voltage_v > 0).all()


def test_voltage_and_ampacity_flags() -> None:
    network = DCNetwork(
        [DCBus("s", 48), DCBus("l", 48, 0.99)],
        [DCBranch("e", "s", "l", 0.01, rated_current_a=5)],
        "s",
    )
    r = network.solve({"l": 4})
    assert any("Undervoltage" in w for w in r.warnings)
    assert any("overload" in w for w in r.warnings)


def test_voltage_collapse_is_not_silent() -> None:
    network = DCNetwork([DCBus("s", 48), DCBus("l", 48)], [DCBranch("e", "s", "l", 1)], "s")
    with pytest.raises(ValueError, match="collapsed|converge"):
        network.solve({"l": 10})


def test_disconnected_cycle_rejected() -> None:
    with pytest.raises(ValueError, match="disconnected|cycle"):
        DCNetwork(
            [DCBus(n, 48) for n in ["s", "a", "b"]],
            [DCBranch("a-b", "a", "b"), DCBranch("b-a", "b", "a")],
            "s",
        )


def test_voltage_change_requires_converter() -> None:
    with pytest.raises(ValueError, match="converter"):
        DCNetwork([DCBus("s", 400), DCBus("l", 48)], [DCBranch("e", "s", "l")], "s")


@pytest.mark.parametrize("load", [-1, float("nan"), float("inf")])
def test_invalid_load(load: float) -> None:
    network = DCNetwork([DCBus("s", 400)], [], "s")
    with pytest.raises(ValueError):
        network.solve({"s": load})


def test_zero_load_and_single_source() -> None:
    r = DCNetwork([DCBus("s", 400)], [], "s").solve({})
    assert r.source_kw == 0
    assert r.branches.empty


def test_copper_cable_round_trip_and_temperature() -> None:
    a = DCBranch.copper_cable("a", "s", "l", 10, 100, 200)
    b = DCBranch.copper_cable("b", "s", "l", 10, 100, 200, temperature_c=70)
    assert a.resistance_ohm == pytest.approx(0.003448)
    assert b.resistance_ohm > a.resistance_ohm
