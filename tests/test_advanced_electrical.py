"""Analytical, conservation and evidence-boundary tests for design extensions."""

from dataclasses import replace
from math import sqrt

import numpy as np
import pytest

from datacenter_simulator.connectors.performance import specpower_reference
from datacenter_simulator.methods.dc_grid import DCGrid, DCLine, DCPort
from datacenter_simulator.methods.design import Feeder, Route, feeder_sweep, solve_feeder
from datacenter_simulator.methods.electrical import DCBranch, DCBus, DCNetwork
from datacenter_simulator.methods.uncertainty import sample_study
from datacenter_simulator.models.devices import Electrical
from datacenter_simulator.models.performance import (
    ConverterMap,
    PowerCurve,
    Provenance,
    calibration_errors,
)


@pytest.fixture
def converter():
    return ConverterMap(
        100,
        (0, 0.5, 1),
        (20, 60),
        ((0.8, 0.95, 0.96), (0.75, 0.9, 0.92)),
        Provenance("test assumption", "100 kW converter"),
        0.1,
        (1, 0.8),
    )


def test_curve_boundary_and_held_out_points():
    measured = specpower_reference()
    assert measured.provenance.kind == "measured"
    assert measured.provenance.boundary == "ac_input"
    assert measured.evaluate(1) == 0.784
    with pytest.raises(ValueError, match="DC terminal"):
        Electrical(48, 0.129, 0.784, curve=measured)
    fitted = PowerCurve(measured.utilization[::2], measured.power_kw[::2], measured.provenance)
    errors = calibration_errors(
        fitted, list(zip(measured.utilization[1::2], measured.power_kw[1::2], strict=True))
    )
    assert 0 < errors["mae_kw"] < 0.02
    with pytest.raises(ValueError):
        measured.evaluate(1.1)
    dc = replace(
        measured,
        provenance=replace(measured.provenance, kind="illustrative", boundary="dc_terminal"),
    )
    assert Electrical(48, 0.1, 1, curve=dc).power_kw(0.5) == 0.5


def test_converter_interpolation_standby_and_derating(converter):
    assert converter.input_kw(0, 20) == 0.1
    assert converter.input_kw(50, 40) == pytest.approx(50 / 0.925 + 0.1)
    assert converter.capacity_kw(40) == 90
    with pytest.raises(ValueError, match="derated"):
        converter.input_kw(90, 60)
    with pytest.raises(ValueError):
        converter.input_kw(10, 10)
    network = DCNetwork(
        [DCBus("hv", 400), DCBus("lv", 48)],
        [DCBranch("converter", "hv", "lv", kind="converter", performance=converter)],
        "hv",
    )
    result = network.solve({"lv": 50})
    assert result.source_kw == pytest.approx(converter.input_kw(50))


def test_route_and_electrothermal_equilibrium():
    route = Route("feed", ((0, 0, 0), (0, 0, 3), (4, 0, 3)))
    assert route.length_m == 7
    feeder = Feeder(20, 120, 300, 0.02)
    result = solve_feeder(feeder, 400, 50)
    assert result.temperature_c == pytest.approx(30 + result.cable_loss_kw * 1000 * 0.02)
    assert result.cable_loss_kw == pytest.approx(
        result.current_a**2 * feeder.resistance_ohm(result.temperature_c) / 1000
    )
    assert result.source_kw == pytest.approx(50 + result.cable_loss_kw)
    assert result.copper_kg == pytest.approx(43.008)
    assert solve_feeder(feeder, 800, 50).cable_loss_kw < result.cable_loss_kw
    hot = solve_feeder(replace(feeder, maximum_temperature_c=31), 400, 50)
    assert not hot.feasible and "temperature" in hot.warnings
    frame = feeder_sweep([48, 400], [Feeder(100, 1, 1, 0.1)], 100)
    assert not frame.feasible.any()


def test_two_bus_matches_independent_quadratic():
    grid = DCGrid(
        {"source": 400, "load": 400}, [DCLine("c", "source", "load", 0.1)], [DCPort("s", "source")]
    )
    result = grid.solve({"load": 100})
    expected = (400 + sqrt(400**2 - 4 * 0.1 * 100000)) / 2
    assert result.buses.loc["load", "voltage_v"] == pytest.approx(expected, abs=1e-7)
    assert abs(result.balance_error_kw) < 1e-8
    assert result.maximum_kcl_error_a < 1e-6


def test_meshed_bidirectional_flow_and_islands():
    lines = [DCLine("ab", "a", "b", 0.1), DCLine("ac", "a", "c", 0.1), DCLine("bc", "b", "c", 0.1)]
    grid = DCGrid(
        dict.fromkeys("abc", 400),
        lines,
        [DCPort("grid", "a", max_sink_kw=200), DCPort("pv", "c", "power", power_kw=100)],
    )
    result = grid.solve({"b": 10})
    assert result.ports.loc["grid", "bus_kw"] < 0
    assert result.lines.loc["ac", "current_a"] < 0
    assert abs(result.balance_error_kw) < 1e-7
    assert result.converter_loss_kw > 0
    with pytest.raises(ValueError, match="island"):
        DCGrid(dict.fromkeys("ab", 400), [], [DCPort("s", "a")])
    with pytest.raises(ValueError, match="only one"):
        DCGrid({"a": 400}, [], [DCPort("s1", "a"), DCPort("s2", "a")])


def test_droop_sharing_saturation_and_explicit_shedding():
    sources = [
        DCPort("a", "bus", "droop", droop_ohm=0.1),
        DCPort("b", "bus", "droop", droop_ohm=0.1),
    ]
    result = DCGrid({"bus": 400}, [], sources).solve({"bus": 100})
    assert result.ports.loc["a", "bus_kw"] == pytest.approx(50)
    assert result.buses.loc["bus", "voltage_v"] < 400
    limited = DCGrid({"bus": 400}, [], [replace(sources[0], max_source_kw=20), sources[1]])
    result = limited.solve({"bus": 100})
    assert result.ports.loc["a", "bus_kw"] == pytest.approx(20, abs=1e-5)
    grid = DCGrid({"bus": 400}, [], [DCPort("s", "bus", max_source_kw=50)])
    with pytest.raises(ValueError, match="capacity"):
        grid.solve({"bus": 100})
    result = grid.solve_with_shedding({"bus": 100})
    assert result.served_fraction == pytest.approx(0.5, abs=1e-6)
    assert result.unserved_kw == pytest.approx(50, abs=1e-6)


def test_collapse_and_invalid_inputs_are_explicit():
    grid = DCGrid({"a": 400, "b": 400}, [DCLine("line", "a", "b", 1)], [DCPort("s", "a")])
    with pytest.raises(ValueError, match="infeasible"):
        grid.solve({"b": 1000})
    with pytest.raises(ValueError):
        grid.solve({"unknown": 1})
    with pytest.raises(ValueError):
        grid.solve({"b": np.nan})
    with pytest.raises(ValueError):
        ConverterMap(100, (0, 1), (20, 40), ((1.01, 1), (1, 1)), Provenance("x", "y"))


def test_uncertainty_is_reproducible_and_retains_failures():
    def evaluate(p):
        if p["x"] < 0.5:
            raise ValueError("infeasible")
        return p["x"] ** 2

    a = sample_study({"x": (0, 1)}, evaluate, seed=8)
    b = sample_study({"x": (0, 1)}, evaluate, seed=8)
    assert a.equals(b)
    assert 0 < a.feasible.sum() < len(a)


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf")])
def test_shedding_does_not_hide_invalid_load_inputs(invalid):
    grid = DCGrid({"bus": 400}, [], [DCPort("source", "bus")])
    with pytest.raises(ValueError):
        grid.solve_with_shedding({"bus": invalid})
