"""Hydraulic/thermal conservation, psychrometrics and attributed climate inputs."""

from dataclasses import replace
from math import pi

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.connectors.weather import bundled_weather, validate_weather
from datacenter_simulator.methods.hydraulics import (
    CoolingBranch,
    Fluid,
    Pipe,
    Pump,
    counterflow_effectiveness,
    solve_cdu,
)
from datacenter_simulator.methods.weather_cooling import (
    HeatRecovery,
    dewpoint_c,
    evaluate_weather_cooling,
    wetbulb_c,
)


def test_pipe_matches_laminar_poiseuille():
    fluid = Fluid(viscosity_pa_s=0.01)
    pipe = Pipe(10, 0.02, roughness_m=0)
    flow = 0.001
    expected = (
        128 * fluid.viscosity_pa_s * pipe.length_m * (flow / 1000) / (pi * pipe.diameter_m**4)
    )
    assert pipe.pressure_drop_pa(flow, fluid) == pytest.approx(expected)
    assert pipe.pressure_drop_pa(0) == 0


def test_heat_exchanger_equal_capacity_analytic_limit():
    assert counterflow_effectiveness(10, 10, 10) == 0.5
    assert counterflow_effectiveness(0, 10, 10) == 0
    assert counterflow_effectiveness(100, 10, 20) < 1


def test_parallel_flow_pump_operating_point_and_heat_conservation():
    branches = [CoolingBranch(name, Pipe(20, 0.04), 10000, 100) for name in ("rack-a", "rack-b")]
    pump = Pump()
    result = solve_cdu(branches, pump)
    assert result.branches.flow_l_s.iloc[0] == pytest.approx(result.branches.flow_l_s.iloc[1])
    assert pump.head_pa(result.flow_l_s, 1) == pytest.approx(result.head_pa)
    assert result.rejected_heat_kw == pytest.approx(result.heat_removed_kw + result.pump_kw)
    c_primary = 10 * 4.18
    assert c_primary * (result.primary_return_c - 25) == pytest.approx(result.rejected_heat_kw)
    c_secondary = result.flow_l_s / 1000 * 997 * 4.18
    assert c_secondary * (result.secondary_return_c - result.secondary_supply_c) == pytest.approx(
        result.rejected_heat_kw
    )
    assert solve_cdu(branches, pump, speed=0.6).flow_l_s < result.flow_l_s
    blocked = solve_cdu(branches, pump, failed_branches=frozenset({"rack-a"}))
    assert blocked.branches.loc["rack-a", "flow_l_s"] == 0
    assert blocked.branches.loc["rack-a", "unmet_heat_kw"] == 100
    assert blocked.branches.loc["rack-b", "flow_l_s"] > result.branches.loc["rack-b", "flow_l_s"]
    off = solve_cdu(branches, pump, speed=0)
    assert off.unmet_heat_kw == 200 and off.pump_kw == 0
    limited = solve_cdu(branches, pump, ua_kw_k=1)
    assert limited.unmet_heat_kw > 0
    assert limited.secondary_return_c == pytest.approx(55)
    assert solve_cdu(branches, replace(pump, parallel_units=2)).flow_l_s > result.flow_l_s


@pytest.mark.parametrize("temperature,rh", [(30, 0.5), (10, 0.9), (-5, 0.5), (40, 0.1), (20, 1)])
def test_psychrometric_order_and_saturation(temperature, rh):
    dew, wet = dewpoint_c(temperature, rh), wetbulb_c(temperature, rh)
    assert dew - 1e-8 <= wet <= temperature + 1e-8
    if rh == 1:
        assert wet == pytest.approx(temperature)
        assert dew == pytest.approx(temperature)


def test_water_and_heat_recovery_boundaries():
    dry = evaluate_weather_cooling(200, 35, 0.4, mode="dry")
    wet = evaluate_weather_cooling(200, 35, 0.4, mode="evaporative")
    assert dry.makeup_l_h == 0
    assert wet.makeup_l_h == pytest.approx(wet.evaporation_l_h + wet.drift_l_h + wet.blowdown_l_h)
    assert wet.makeup_l_h == pytest.approx(wet.evaporation_l_h * 4 / 3)
    recovered = evaluate_weather_cooling(200, 35, 0.4, recovery=HeatRecovery(80, supply_c=40))
    assert recovered.useful_heat_kw == 80
    assert recovered.rejected_heat_kw + recovered.useful_heat_kw == pytest.approx(
        200 + recovered.electric_kw
    )
    heatpump = evaluate_weather_cooling(
        200, 35, 0.4, recovery=HeatRecovery(80, supply_c=70, heat_pump_cop=4)
    )
    assert heatpump.heat_pump_kw == 20
    assert heatpump.recovered_source_heat_kw == 60
    assert heatpump.rejected_heat_kw + heatpump.useful_heat_kw == pytest.approx(
        200 + heatpump.electric_kw
    )
    idle = evaluate_weather_cooling(0, 35, 0.4, mode="evaporative")
    assert idle.makeup_l_h == 0 and idle.electric_kw == 0
    humid = evaluate_weather_cooling(200, 30, 0.5, supply_c=18, indoor_c=28, indoor_rh=0.9)
    assert humid.condensation_margin_k >= 2 - 1e-8


@pytest.mark.parametrize("name", ["tenerife", "frankfurt", "seville"])
def test_offline_tmy_is_complete_and_rejects_bad_data(name):
    frame = bundled_weather(name)
    assert len(frame) == 8760 and frame.index.tz is not None
    assert "source_timestamp" in frame
    assert frame.index[0] == pd.Timestamp("2021-01-01", tz="UTC")
    broken = frame.iloc[:4].copy()
    broken.iloc[0, broken.columns.get_loc("relative_humidity")] = 50
    with pytest.raises(ValueError, match="humidity"):
        validate_weather(broken)
    broken.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        validate_weather(broken)


def test_cold_dry_air_wetbulb_can_fall_below_drybulb_input_range():
    from datacenter_simulator.methods.weather_cooling import dewpoint_c, wetbulb_c

    assert dewpoint_c(-30, 0.2) < wetbulb_c(-30, 0.2) < -30
