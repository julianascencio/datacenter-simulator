"""Analytical fleet-dispatch cases and physical/accounting invariants."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.grid_management import (
    contingency_screen,
    optimize_grid,
    supply_availability,
)
from datacenter_simulator.models.grid_management import Generator, GridPolicy, SupplyOutage


def profiles(n=4, demand=100, grid=0):
    return pd.DataFrame(
        {
            "demand_kw": float(demand),
            "critical_demand_kw": float(demand),
            "renewable_kw": 0.0,
            "grid_limit_kw": float(grid),
            "import_price_per_kwh": 0.20,
            "grid_carbon_kg_per_kwh": 0.4,
        },
        index=pd.date_range("2030-01-01", periods=n, freq="h", tz="UTC"),
    )


def unit(name="gas", capacity=100, cost=0.05, **kwargs):
    return Generator(name, capacity, heat_rate_mmbtu_per_kwh=0, variable_om_per_kwh=cost, **kwargs)


def test_merit_order_matches_hand_calculation():
    frame = profiles(demand=120, grid=100)
    result = optimize_grid(frame, (unit(capacity=80),))
    assert np.allclose(result.generators_kw.gas, 80)
    assert np.allclose(result.timeseries.grid_import_kw, 40)
    assert result.summary["operating_cost"] == pytest.approx(4 * (80 * 0.05 + 40 * 0.2))
    assert result.summary["maximum_balance_error_kw"] < 1e-7


def test_priority_shedding_and_hard_service_constraint():
    frame = profiles(demand=100)
    frame["critical_demand_kw"] = 60.0
    result = optimize_grid(frame, (unit(capacity=70),))
    assert result.summary["critical_unserved_kwh"] == pytest.approx(0)
    assert result.summary["flexible_unserved_kwh"] == pytest.approx(120)
    with pytest.raises(ValueError, match="optimization failed"):
        optimize_grid(frame, (unit(capacity=50),), policy=GridPolicy(require_critical_service=True))


def test_battery_duration_conservation_and_end_reserve():
    frame = profiles(n=4, demand=10)
    battery = Battery(
        20,
        10,
        10,
        charge_efficiency=1,
        discharge_efficiency=1,
        minimum_soc=0,
        maximum_soc=1,
        initial_soc=1,
    )
    result = optimize_grid(frame, battery=battery, policy=GridPolicy(terminal_soc=0))
    assert result.summary["served_kwh"] == pytest.approx(20)
    assert result.summary["critical_unserved_kwh"] == pytest.approx(20)
    assert result.timeseries.battery_energy_kwh.iloc[-1] == pytest.approx(0)
    reserved = optimize_grid(frame, battery=battery)
    assert reserved.summary["served_kwh"] == pytest.approx(0)


def test_battery_efficiency_and_negative_price_no_simultaneous_flows():
    frame = profiles(n=8, demand=10, grid=100)
    frame["import_price_per_kwh"] = [-1, -1, 1, 1, 1, 1, -1, -1]
    battery = Battery(
        40,
        20,
        20,
        charge_efficiency=0.8,
        discharge_efficiency=0.9,
        minimum_soc=0,
        maximum_soc=1,
        initial_soc=0.5,
    )
    run = optimize_grid(frame, battery=battery)
    ts = run.timeseries
    assert (np.minimum(ts.charge_kw, ts.discharge_kw) < 1e-7).all()
    expected = 20 + (ts.charge_kw * 0.8 - ts.discharge_kw / 0.9).cumsum()
    assert np.allclose(ts.battery_energy_kwh, expected)
    assert ts.spilled_kw.abs().max() < 1e-7  # Cannot dump paid imports without a generator.
    assert run.summary["maximum_balance_error_kw"] < 1e-7


def test_ramps_trip_and_restoration():
    frame = profiles(n=5)
    g = unit(ramp_kw_per_hour=25, initial_output_kw=100)
    event = SupplyOutage(frame.index[1], frame.index[2], generator_ids=("gas",))
    run = optimize_grid(frame, (g,), outages=(event,))
    assert np.allclose(run.generators_kw.gas, [100, 0, 25, 50, 75])


def test_shared_gas_outage_and_utility_outage_apply_to_correct_paths():
    frame = profiles(n=4, grid=30)
    gs = (
        unit("fc", 40, fuel_group="gas"),
        unit("ccgt", 50, fuel_group="gas"),
        unit("other", 20, fuel_group="other"),
    )
    events = (SupplyOutage(frame.index[1], frame.index[3], fuel_groups=("gas",), grid=True),)
    cap, limit = supply_availability(frame, gs, outages=events)
    assert cap.loc[frame.index[1:3], ["fc", "ccgt"]].to_numpy().sum() == 0
    assert np.allclose(cap.other, 20)
    assert list(limit) == [30, 0, 0, 30]
    result = optimize_grid(frame, gs, outages=events)
    assert np.allclose(result.timeseries.served_kw.iloc[1:3], 20)


def test_commissioning_and_derating_never_create_capacity():
    frame = profiles()
    g = unit(commissioned_at=frame.index[2])
    avail = pd.DataFrame({"gas": 0.5}, index=frame.index)
    result = optimize_grid(frame, (g,), availability=avail)
    assert np.allclose(result.generators_kw.gas, [0, 0, 50, 50])


def test_capture_auxiliary_energy_cost_and_carbon_are_consistent():
    g = Generator(
        "fc",
        100,
        heat_rate_mmbtu_per_kwh=0.006,
        fuel_price_per_mmbtu=4,
        variable_om_per_kwh=0,
        fuel_carbon_kg_per_mmbtu=50,
        capture_fraction=0.9,
        capture_availability=1,
        capture_auxiliary_fraction=0.1,
    )
    assert g.net_capacity_kw == 90
    run = optimize_grid(profiles(n=1, demand=90), (g,))
    assert run.summary["residual_carbon_kg"] == pytest.approx(3)
    assert run.summary["captured_carbon_kg"] == pytest.approx(27)
    assert run.summary["operating_cost"] == pytest.approx(2.4)


def test_contingency_does_not_credit_battery_or_hide_common_mode():
    gs = (unit("a", 60, fuel_group="gas"), unit("b", 60, fuel_group="gas"))
    table = contingency_screen(gs, 100, grid_limit_kw=20).set_index("contingency")
    assert table.loc["generator:a", "shortfall_kw"] == 20
    assert table.loc["fuel_group:gas", "shortfall_kw"] == 80


@pytest.mark.parametrize(
    "change", ["nan", "negative_load", "critical", "naive", "spacing", "duplicate"]
)
def test_invalid_profiles_fail_before_optimization(change):
    frame = profiles()
    if change == "nan":
        frame.iloc[0, 0] = np.nan
    if change == "negative_load":
        frame.iloc[0, 0] = -1
    if change == "critical":
        frame["critical_demand_kw"] = 200
    if change == "naive":
        frame.index = frame.index.tz_localize(None)
    if change == "spacing":
        frame.index = pd.date_range("2030-01-01", periods=4, freq="2h", tz="UTC")
    if change == "duplicate":
        frame.index = pd.DatetimeIndex([frame.index[0]] * 4)
    with pytest.raises(ValueError):
        optimize_grid(frame)


def test_unknown_outage_and_misaligned_events_rejected():
    frame = profiles()
    with pytest.raises(ValueError, match="unknown"):
        optimize_grid(
            frame,
            (unit(),),
            outages=(SupplyOutage(frame.index[0], frame.index[1], generator_ids=("typo",)),),
        )
    with pytest.raises(ValueError, match="align"):
        optimize_grid(
            frame,
            (unit(),),
            outages=(
                SupplyOutage(frame.index[0] + pd.Timedelta(minutes=15), frame.index[1], grid=True),
            ),
        )
    with pytest.raises(ValueError, match="unique"):
        optimize_grid(frame, (unit(), unit()))
    with pytest.raises(ValueError, match="terminal"):
        optimize_grid(frame, policy=GridPolicy(terminal_soc=0.5))


def test_peak_charge_reduces_peak_with_identical_served_energy():
    frame = profiles(n=4, grid=100)
    frame["demand_kw"] = [10.0, 10.0, 40.0, 40.0]
    frame["critical_demand_kw"] = frame.demand_kw
    battery = Battery(
        80,
        40,
        40,
        minimum_soc=0,
        maximum_soc=1,
        initial_soc=0.5,
        charge_efficiency=1,
        discharge_efficiency=1,
    )
    result = optimize_grid(frame, battery=battery, policy=GridPolicy(demand_charge_per_kw=10))
    assert result.summary["peak_import_kw"] == pytest.approx(25)
    assert result.summary["served_kwh"] == pytest.approx(100)
    assert result.summary["demand_charge"] == pytest.approx(250)


def test_carbon_cost_changes_merit_order_without_inventing_emissions():
    dirty = Generator(
        "dirty",
        100,
        heat_rate_mmbtu_per_kwh=0.01,
        fuel_carbon_kg_per_mmbtu=100,
        variable_om_per_kwh=0,
    )
    clean = unit("clean", 100, cost=0.08)
    frame = profiles(n=1)
    base = optimize_grid(frame, (dirty, clean))
    priced = optimize_grid(frame, (dirty, clean), policy=GridPolicy(carbon_price_per_kg=0.1))
    assert base.generators_kw.dirty.iloc[0] == pytest.approx(100)
    assert priced.generators_kw.clean.iloc[0] == pytest.approx(100)
    assert priced.summary["residual_carbon_kg"] == pytest.approx(0)


def test_half_hour_energy_scaling_and_forced_ramp_spill():
    frame = profiles(n=2, demand=0)
    frame.index = pd.date_range("2030-01-01", periods=2, freq="30min", tz="UTC")
    g = unit(ramp_kw_per_hour=20, initial_output_kw=100)
    result = optimize_grid(frame, (g,), dt_hours=0.5)
    assert np.allclose(result.generators_kw.gas, [90, 80])
    assert np.allclose(result.timeseries.spilled_kw, [90, 80])
    assert result.summary["operating_cost"] == pytest.approx(4.25)
    assert result.summary["maximum_balance_error_kw"] < 1e-7


def test_empty_fleet_and_no_supply_is_explicit_unserved_load():
    result = optimize_grid(profiles(n=1, demand=5))
    assert result.summary["critical_unserved_kwh"] == pytest.approx(5)
    assert result.generators_kw.empty


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_auxiliary_fraction", 1),
        ("delivery_factor", 0),
        ("initial_output_kw", 200),
        ("ramp_kw_per_hour", 0),
    ],
)
def test_invalid_generator_fields(field, value):
    with pytest.raises(ValueError):
        replace(unit(), **{field: value})
