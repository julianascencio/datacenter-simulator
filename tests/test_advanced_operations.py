"""Dispatch, event timing and workload coupling invariants."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.methods.communications import CommunicationNetwork, Link
from datacenter_simulator.methods.cooling import ThermalZone
from datacenter_simulator.methods.dc_grid import DCGrid, DCLine, DCPort
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.microgrid import simulate_dc_microgrid
from datacenter_simulator.methods.optimization import optimize_dispatch, rolling_dispatch
from datacenter_simulator.methods.resilience import (
    CoolingUnit,
    CriticalRack,
    FailureEvent,
    PowerFeed,
    simulate_contingencies,
)
from datacenter_simulator.methods.workloads import (
    ComputeDevice,
    Job,
    JobPhase,
    max_min_rates,
    shortest_paths,
    simulate_workloads,
)
from datacenter_simulator.models.devices import Electrical


def profiles(n=4):
    return pd.DataFrame(
        {
            "demand_kw": [50.0] * n,
            "generation_kw": [0.0] * n,
            "import_price": [0.1, 0.1, 0.5, 0.5][:n],
        },
        index=pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
    )


def test_dispatch_saves_cost_with_terminal_soc_and_conservation():
    frame = profiles()
    battery = Battery(100, 50, 50)
    optimized = optimize_dispatch(frame, battery)
    result = optimized.timeseries
    assert optimized.summary["energy_cost"] < 60
    assert result.battery_energy_kwh.iloc[-1] == pytest.approx(50)
    assert result.balance_error_kw.abs().max() < 1e-7
    assert (result.charge_kw * result.discharge_kw).abs().max() < 1e-7
    previous = np.r_[50, result.battery_energy_kwh.to_numpy()[:-1]]
    assert np.allclose(
        result.battery_energy_kwh - previous, result.charge_kw * 0.96 - result.discharge_kw / 0.96
    )
    assert result.unserved_kw.sum() == 0


def test_dispatch_negative_prices_and_outage_cannot_create_energy():
    frame = profiles()
    frame["import_price"] = -1
    frame["export_price"] = 2
    result = optimize_dispatch(frame, Battery(100, 50, 50), export_limit_kw=100).timeseries
    assert (result.charge_kw * result.discharge_kw).abs().max() < 1e-7
    assert (result.grid_import_kw * result.grid_export_kw).abs().max() < 1e-7
    frame["grid_limit_kw"] = 0
    result = optimize_dispatch(frame, Battery(100, 50, 50), terminal_soc=0.1).timeseries
    assert result.grid_import_kw.sum() == 0
    assert result.unserved_kw.sum() == pytest.approx(200 - 40 * 0.96)
    with pytest.raises(ValueError):
        optimize_dispatch(frame, Battery(100, 50, 50), terminal_soc=0.99)


def test_rolling_forecast_error_reconciles_actual_load():
    actual = profiles()
    actual["grid_limit_kw"] = [100, 0, 0, 100]
    forecast = actual.copy()
    forecast["demand_kw"] = 30
    result = rolling_dispatch(actual, forecast, Battery(100, 50, 50), horizon=3)
    assert result.balance_error_kw.abs().max() < 1e-8
    assert result.battery_energy_kwh.between(10 - 1e-7, 95 + 1e-7).all()
    assert result.grid_import_kw.iloc[1:3].sum() == 0
    assert result.unserved_kw.sum() > 0


def test_microgrid_direct_coupling_and_island_loss_feedback():
    grid = DCGrid(
        {"bus": 400, "rack": 400}, [DCLine("feed", "bus", "rack", 0.1)], [DCPort("grid", "bus")]
    )
    index = profiles().index
    loads = pd.DataFrame({"rack": [50.0] * 4}, index=index)
    pv = pd.Series([20.0, 30, 20, 0], index=index)
    direct = simulate_dc_microgrid(grid, loads, pv)
    ac = simulate_dc_microgrid(grid, loads, pv, pv_coupling="ac")
    assert direct.summary["grid_import_ac_kwh"] < ac.summary["grid_import_ac_kwh"]
    for snap in direct.snapshots:
        assert snap is not None and abs(snap.balance_error_kw) < 1e-7
    island = simulate_dc_microgrid(
        grid,
        loads,
        pd.Series(0.0, index=index),
        battery=Battery(100, 50, 50),
        grid_limit_ac_kw=pd.Series(0.0, index=index),
    )
    result = island.timeseries
    assert result.grid_import_ac_kw.sum() == 0
    assert result.served_terminal_kw.sum() + result.dc_loss_kw.sum() == pytest.approx(
        40 * 0.96, abs=1e-5
    )
    assert result.unserved_terminal_kw.sum() > 100
    assert result.battery_energy_kwh.min() >= 10 - 1e-8
    assert island.snapshots[-1] is None


def test_transfer_delay_hold_up_and_common_cause_are_integrated_exactly():
    feeds = [PowerFeed("A", {"a1": 20}, ("upstream",)), PowerFeed("B", {"b1": 20}, ("upstream",))]
    racks = [CriticalRack("rack", 10, ("A", "B"), transfer_delay_s=0.25, hold_up_s=0.1)]
    events = [FailureEvent("A", 1, 3)]
    result = simulate_contingencies(feeds, racks, [], events, duration_s=4, step_s=1)
    assert result.summary["unserved_kwh"] == pytest.approx(10 * 0.15 / 3600)
    assert result.summary["hold_up_kwh"] == pytest.approx(10 * 0.1 / 3600)
    assert result.racks.iloc[-1].feed == "B"
    common = simulate_contingencies(
        feeds, racks, [], [FailureEvent("upstream", 1, 3)], duration_s=4
    )
    assert common.summary["unserved_kwh"] > result.summary["unserved_kwh"]


def test_n_plus_one_and_cooling_power_dependencies():
    feeds = [PowerFeed("A", {"a1": 20, "a2": 20, "a3": 20}), PowerFeed("B", {"b1": 20})]
    rack = CriticalRack("rack", 30, ("A",), zone=ThermalZone(100, 0))
    cooling = [CoolingUnit("cdu", "B", 40, 2)]
    base = simulate_contingencies(feeds, [rack], cooling, [], duration_s=10)
    n1 = simulate_contingencies(feeds, [rack], cooling, [FailureEvent("a1", 0, 10)], duration_s=10)
    assert base.summary["unserved_kwh"] == n1.summary["unserved_kwh"] == 0
    failed_cooling = simulate_contingencies(
        feeds, [rack], cooling, [FailureEvent("B", 0, 10)], duration_s=10
    )
    assert failed_cooling.timeline.cooling_capacity_kw.max() == 0
    assert failed_cooling.racks.temperature_c.iloc[-1] == pytest.approx(27)
    with pytest.raises(ValueError, match="unknown"):
        simulate_contingencies(feeds, [rack], cooling, [FailureEvent("typo", 0, 1)], duration_s=10)


def test_max_min_fairness_and_directional_paths():
    usage = np.asarray([[1.0, 1.0, 0], [0, 1, 1]])
    rates = max_min_rates(usage, np.asarray([10.0, 4.0]))
    assert np.allclose(rates, [8, 2, 2])
    network = CommunicationNetwork(
        list("abcd"),
        [
            Link("ab", "a", "b", 10),
            Link("bd", "b", "d", 10),
            Link("ac", "a", "c", 10),
            Link("cd", "c", "d", 10),
        ],
    )
    assert len(shortest_paths(network, "a", "d")) == 2
    assert len(shortest_paths(network, "a", "d", ecmp=False)) == 1
    assert len(shortest_paths(network, "a", "d", failed_links=frozenset({"ab"}))) == 1
    assert shortest_paths(network, "d", "a")[0][0][1] == 1


def workload_case(capacity=8):
    network = CommunicationNetwork(
        ["storage", "switch", "a", "b"],
        [
            Link("uplink", "storage", "switch", capacity),
            Link("a", "switch", "a", 100),
            Link("b", "switch", "b", 100),
        ],
    )
    devices = [ComputeDevice(name, Electrical(48, 1, 5), 10) for name in ("a", "b")]
    jobs = [
        Job(
            name,
            name,
            (JobPhase("transfer", 1, "storage", name), JobPhase("compute", 1)),
            deadline_s=4,
        )
        for name in ("a", "b")
    ]
    return network, devices, jobs


def test_congestion_changes_completion_time_energy_and_heat():
    network, devices, jobs = workload_case()
    fast = simulate_workloads(network, devices, jobs, step_s=0.5)
    slow = simulate_workloads(*workload_case(4), step_s=0.5)
    assert fast.jobs.completion_s.tolist() == pytest.approx([3, 3])
    assert slow.jobs.completion_s.tolist() == pytest.approx([5, 5])
    assert slow.summary["terminal_energy_kwh"] > fast.summary["terminal_energy_kwh"]
    assert slow.summary["deadline_misses"] == 2
    assert (slow.links.used_gbps <= slow.links.capacity_gbps + 1e-8).all()
    isolated = simulate_workloads(
        network, devices, jobs, events=[FailureEvent("uplink", 0, 2)], step_s=5
    )
    assert isolated.jobs.completion_s.tolist() == pytest.approx([5, 5])
    unavailable = simulate_workloads(
        network, devices, jobs, duration_s=2, events=[FailureEvent("uplink", 0, 3)]
    )
    assert unavailable.summary["completed_jobs"] == 0


def test_thermal_throttling_power_cap_and_timestep_convergence():
    network, devices, jobs = workload_case()
    job = Job("compute", "a", (JobPhase("compute", 10),), deadline_s=30)
    hot = replace(devices[0], cooling_capacity_kw=0, zone=ThermalZone(10, 0), throttle_c=25)
    coarse = simulate_workloads(network, [hot], [job], step_s=0.2)
    fine = simulate_workloads(network, [hot], [job], step_s=0.05)
    assert fine.jobs.loc["compute", "completion_s"] > 10
    assert abs(fine.summary["elapsed_s"] - coarse.summary["elapsed_s"]) < 0.3
    capped = simulate_workloads(network, [replace(devices[0], power_cap_kw=3)], [job])
    assert capped.jobs.loc["compute", "completion_s"] == pytest.approx(20)
    assert capped.devices.power_kw.max() <= 3


def test_carbon_scheduler_respects_windows_and_replay_energy():
    from datacenter_simulator.methods.workloads import schedule_carbon_aware, workload_power_profile

    jobs = [
        Job("a", "rack", (JobPhase("compute", 10),), deadline_s=40),
        Job("b", "rack", (JobPhase("compute", 10),), deadline_s=40),
    ]
    scheduled = schedule_carbon_aware(jobs, [0.8, 0.1, 0.2, 0.9], {"rack": 10}, slot_s=10)
    assert sorted(j.release_s for j in scheduled.jobs) == [10, 20]
    assert scheduled.estimated_carbon_kg == pytest.approx(10 * 10 / 3600 * (0.1 + 0.2))
    result = simulate_workloads(
        CommunicationNetwork(["rack"], []),
        [ComputeDevice("rack", Electrical(400, 1, 10), 20)],
        list(scheduled.jobs),
        step_s=3,
    )
    assert not result.jobs.deadline_missed.any()
    profile = workload_power_profile(result, pd.Timestamp("2026-01-01", tz="UTC"), step_s=7)
    assert profile.sum().sum() * 7 / 3600 == pytest.approx(result.summary["terminal_energy_kwh"])
    with pytest.raises(ValueError):
        schedule_carbon_aware(jobs, [0.8, 0.1], {"rack": 10}, slot_s=5)


def test_explicit_device_profiles_connect_workloads_to_facility():
    from datacenter_simulator import simulate
    from datacenter_simulator.use_cases import reference_center

    center = reference_center()
    index = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    profiles = pd.DataFrame({"utilization": [0, 0], "ambient_c": [25, 25]}, index=index)
    terminal = pd.DataFrame({d.id: [1, 2] for d in center.devices}, index=index)
    result = simulate(center, profiles, device_power_kw=terminal)
    assert result.summary["it_kwh"] == 3 * len(center.devices)
    with pytest.raises(ValueError, match="equipment"):
        simulate(center, profiles, device_power_kw=terminal.drop(columns=terminal.columns[0]))


def test_microgrid_respects_root_converter_rating_below_import_limit():
    from datacenter_simulator.methods.dc_grid import DCGrid, DCPort
    from datacenter_simulator.methods.microgrid import simulate_dc_microgrid

    index = pd.date_range("2025-01-01", periods=1, freq="h", tz="UTC")
    grid = DCGrid({"bus": 400}, [], [DCPort("source", "bus", max_source_kw=20)])
    result = simulate_dc_microgrid(
        grid,
        pd.DataFrame({"bus": [50]}, index=index),
        pd.Series(0, index=index),
        grid_limit_ac_kw=pd.Series(100, index=index),
    )
    assert result.timeseries.served_terminal_kw.iloc[0] == pytest.approx(20, abs=1e-5)
    assert result.timeseries.unserved_terminal_kw.iloc[0] == pytest.approx(30, abs=1e-5)
