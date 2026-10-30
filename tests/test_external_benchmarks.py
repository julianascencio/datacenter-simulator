"""Optional independent package comparisons (run in the benchmarks CI job)."""

import numpy as np
import pytest

from datacenter_simulator.connectors.solar import pv_from_weather
from datacenter_simulator.connectors.weather import bundled_weather
from datacenter_simulator.methods.dc_grid import DCGrid, DCLine, DCPort


def test_pypsa_nonlinear_resistive_grid_matches():
    pypsa = pytest.importorskip("pypsa")
    # SI conversions are explicit: PyPSA bus voltage kV, power MW, resistance ohm.
    reference = pypsa.Network()
    for bus in ("source", "a", "b"):
        # PyPSA builds Y for AC-labelled buses; zero reactance and zero Q reduce
        # its nonlinear equations to the resistive DC special case.
        reference.add("Bus", bus, v_nom=0.4)
    lines = [("sa", "source", "a", 0.05), ("sb", "source", "b", 0.08), ("ab", "a", "b", 0.1)]
    for name, source, target, resistance in lines:
        reference.add("Line", name, bus0=source, bus1=target, r=resistance, x=0, s_nom=1)
    reference.add("Generator", "grid", bus="source", control="Slack", p_nom=1)
    reference.add("Load", "a", bus="a", p_set=0.04)
    reference.add("Load", "b", bus="b", p_set=0.06)
    outcome = reference.pf(x_tol=1e-10)
    assert outcome["converged"].to_numpy().all()
    own = DCGrid(
        dict.fromkeys(("source", "a", "b"), 400),
        [DCLine(*line) for line in lines],
        [DCPort("grid", "source")],
    ).solve({"a": 40, "b": 60})
    assert np.abs(reference.buses_t.v_ang.to_numpy()).max() < 1e-8
    expected = reference.buses_t.v_mag_pu.iloc[0].reindex(own.buses.index).to_numpy() * 400
    assert np.allclose(own.buses.voltage_v, expected, atol=1e-5, rtol=0)
    expected_losses = (reference.lines_t.p0.iloc[0] + reference.lines_t.p1.iloc[0]).sum() * 1000
    assert own.cable_loss_kw == pytest.approx(expected_losses, abs=1e-6)


def test_pvlib_adapter_scales_dc_and_separates_conversion_boundary():
    pytest.importorskip("pvlib")
    weather = bundled_weather("tenerife").loc["2021-06-15"]
    first = pv_from_weather(weather, latitude=28.46, longitude=-16.25, dc_rating_kw=100)
    second = pv_from_weather(weather, latitude=28.46, longitude=-16.25, dc_rating_kw=200)
    assert np.allclose(second.pv_dc_kw, first.pv_dc_kw * 2)
    assert (first.pv_ac_kw <= first.pv_dc_kw + 1e-9).all()
    assert first.pv_dc_kw.max() > 50
    assert first.index.equals(weather.index)
