"""Physical/optimization invariants; all datasets here are explicitly synthetic."""

import itertools
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.gpu_benchmark import read_performance_model, write_performance_model
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.gpu_lab import (
    forecast_error_replay,
    inference_job,
    run_gpu_policy,
)
from datacenter_simulator.methods.optimization import DemandOption, optimize_dispatch
from datacenter_simulator.models.gpu import GPUOperatingPoint
from datacenter_simulator.use_cases.gpu_lab import (
    compare_policies,
    gpu_scenario,
    synthetic_performance,
)


@pytest.fixture(scope="module")
def comparisons():
    return compare_policies()


def test_interpolation_is_bounded_quality_specific_and_serializable(tmp_path):
    model = synthetic_performance()
    result = model.evaluate(
        185, configuration_id=model.configuration_id, quality_id=model.quality_id
    )
    assert result.tasks_per_s == pytest.approx(90)
    assert result.board_power_w == pytest.approx(165)
    for limit in (0, 149, 301, np.nan):
        with pytest.raises(ValueError):
            model.evaluate(
                limit, configuration_id=model.configuration_id, quality_id=model.quality_id
            )
    with pytest.raises(ValueError, match="quality mismatch"):
        model.evaluate(185, configuration_id=model.configuration_id, quality_id="different")
    with pytest.raises(ValueError, match="increase"):
        replace(model, points=(model.points[1], model.points[0]))
    with pytest.raises(ValueError, match="observed"):
        replace(model, default_limit_w=290)
    path = tmp_path / "model.json"
    write_performance_model(model, path)
    assert read_performance_model(path) == model


def test_policy_work_is_equal_deadlines_releases_capacity_and_soc(comparisons):
    _, profiles, jobs, _, battery = gpu_scenario()
    for result in comparisons.values():
        assert result.feasible
        f, j = result.facility.timeseries, result.jobs
        assert result.summary["completed_tasks"] == 4104000
        assert j.completed.all() and not j.deadline_missed.any()
        assert (j.start_s >= j.release_s).all()
        assert (j.completion_s <= j.deadline_s + 1e-7).all()
        ordered = j.sort_values("start_s")
        assert np.all(ordered.start_s.to_numpy()[1:] >= ordered.completion_s.to_numpy()[:-1] - 1e-7)
        assert f.grid_import_kw.max() <= profiles.grid_limit_kw.max() + 1e-7
        assert f.battery_energy_kwh.iloc[-1] == pytest.approx(
            battery.initial_soc * battery.capacity_kwh
        )
        assert f.battery_energy_kwh.between(
            battery.minimum_soc * battery.capacity_kwh - 1e-7,
            battery.maximum_soc * battery.capacity_kwh + 1e-7,
        ).all()
        assert (f.charge_kw * f.discharge_kw).abs().max() < 1e-7
        previous = np.r_[battery.initial_soc * battery.capacity_kwh, f.battery_energy_kwh.iloc[:-1]]
        assert np.allclose(
            f.battery_energy_kwh - previous,
            0.5
            * (
                f.charge_kw * battery.charge_efficiency
                - f.discharge_kw / battery.discharge_efficiency
            ),
        )
        assert f.balance_error_kw.abs().max() < 1e-7
        assert np.allclose(
            f.facility_kw,
            f.it_kw + f.dc_loss_kw + f.rectifier_loss_kw + f.cooling_kw + f.auxiliary_kw,
        )
        assert len(j) == len(jobs)
    joint = comparisons["coordinated"].summary["objective_with_storage_wear"]
    assert (
        joint <= min(r.summary["objective_with_storage_wear"] for r in comparisons.values()) + 1e-7
    )


def test_reproducibility_and_fixed_work_under_performance_uncertainty(comparisons):
    rerun = compare_policies()
    for policy in comparisons:
        assert rerun[policy].summary["energy_cost"] == pytest.approx(
            comparisons[policy].summary["energy_cost"]
        )
        pd.testing.assert_frame_equal(rerun[policy].jobs, comparisons[policy].jobs)
    slower = compare_policies(throughput_scale=0.5)
    assert all(r.summary["requested_tasks"] == 4104000 for r in slower.values())
    assert any(not r.feasible for r in slower.values())
    for r in slower.values():
        if r.summary["unfinished_jobs"]:
            assert np.isnan(r.summary["facility_energy_per_task_j"])


def test_deadline_misses_unfinished_grid_and_thermal_infeasibility():
    center, profiles, _, model, battery = gpu_scenario()
    jobs = [
        inference_job(
            "late", "gpu-server", 864000, model, release_s=23 * 3600, deadline_s=24 * 3600
        )
    ]
    result = run_gpu_policy(
        center, profiles, jobs, model, battery, policy="immediate_default", other_server_kw=0.12
    )
    assert not result.feasible and result.summary["unfinished_jobs"] == 1
    assert result.summary["deadline_misses"] == 1 and result.summary["completed_tasks"] == 0
    jobs = [inference_job("too-tight", "gpu-server", 864000, model, release_s=0, deadline_s=3600)]
    late = run_gpu_policy(
        center, profiles, jobs, model, battery, policy="immediate_default", other_server_kw=0.12
    )
    assert late.jobs.completed.all() and late.jobs.deadline_missed.all() and not late.feasible
    planned = run_gpu_policy(
        center, profiles, jobs, model, battery, policy="coordinated", other_server_kw=0.12
    )
    assert planned.summary["planning_failure"] and not planned.jobs.completed.any()
    center, profiles, jobs, model, battery = gpu_scenario()
    outage = profiles.assign(grid_limit_kw=0, generation_kw=0)
    r = run_gpu_policy(
        center, outage, jobs, model, battery, policy="immediate_default", other_server_kw=0.12
    )
    assert not r.feasible and r.summary["unserved_kwh"] > 0
    assert not r.jobs.completed.any()
    hot = replace(center, cooling=replace(center.cooling, capacity_kw=0.1))
    r = run_gpu_policy(
        hot, profiles, jobs, model, battery, policy="immediate_default", other_server_kw=0.12
    )
    assert not r.feasible and r.summary["unmet_heat_kwh"] > 0
    assert not r.jobs.completed.any()


def test_partial_slot_losses_use_endpoint_time_averages():
    center, profiles, _, model, battery = gpu_scenario()
    tasks = model.default_point.tasks_per_s * 900
    jobs = [inference_job("partial", "gpu-server", tasks, model, release_s=0, deadline_s=3600)]
    r = run_gpu_policy(
        center,
        profiles.iloc[:2],
        jobs,
        model,
        battery,
        policy="immediate_default",
        other_server_kw=0.12,
    )
    idle = model.idle_board_w / 1000 + 0.12
    busy = model.default_point.board_power_w / 1000 + 0.12
    assert r.facility.timeseries.it_kw.iloc[0] == pytest.approx((idle + busy) / 2)
    assert r.facility.timeseries.it_kw.iloc[1] == pytest.approx(idle)
    assert r.jobs.completion_s.iloc[0] == 900


def test_joint_dispatch_matches_exhaustive_schedule_enumeration():
    index = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "demand_kw": 1.0,
            "generation_kw": [0.0, 3.0, 0.0],
            "import_price": [0.1, 0.3, 0.5],
            "grid_limit_kw": 5.0,
        },
        index=index,
    )
    battery = Battery(2, 1, 1)
    options = tuple(
        DemandOption(f"{j}-{t}", j, "gpu", t, (1.0,)) for j in ("a", "b") for t in range(3)
    )
    joint = optimize_dispatch(
        frame,
        battery,
        demand_options=options,
        required_groups=("a", "b"),
        require_served=True,
        terminal_soc_exact=True,
    )
    objectives = []
    for starts in itertools.permutations(range(3), 2):
        explicit = frame.copy()
        explicit.loc[index[list(starts)], "demand_kw"] += 1
        objectives.append(
            optimize_dispatch(
                explicit, battery, require_served=True, terminal_soc_exact=True
            ).objective
        )
    assert joint.objective == pytest.approx(min(objectives), abs=1e-7)
    assert len(joint.selected_options) == 2
    assert joint.timeseries.demand_kw.max() == 2
    with pytest.raises(ValueError, match="every required"):
        optimize_dispatch(frame, battery, required_groups=("missing",))


def test_exact_terminal_soc_at_negative_prices():
    frame = pd.DataFrame(
        {"demand_kw": [0.0, 0.0], "generation_kw": [0.0, 0.0], "import_price": [-1.0, -1.0]},
        index=pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC"),
    )
    result = optimize_dispatch(frame, Battery(1, 0.5, 0.5), terminal_soc_exact=True)
    assert result.timeseries.battery_energy_kwh.iloc[-1] == pytest.approx(0.5)
    assert result.timeseries.balance_error_kw.abs().max() < 1e-7


def test_frozen_forecast_replay_exposes_shortfall_without_free_energy(comparisons):
    _, actual, _, _, battery = gpu_scenario()
    actual = actual.assign(generation_kw=0, grid_limit_kw=0.25)
    plan = comparisons["coordinated"]
    replay = forecast_error_replay(plan, actual, battery)
    assert replay.unserved_kw.sum() > 0
    assert replay.grid_import_kw.max() <= 0.25
    assert replay.balance_error_kw.abs().max() < 1e-7
    pd.testing.assert_series_equal(
        replay.battery_energy_kwh, plan.facility.timeseries.battery_energy_kwh
    )
    pd.testing.assert_series_equal(replay.charge_kw, plan.facility.timeseries.charge_kw)
    assert replay.battery_energy_kwh.iloc[-1] == pytest.approx(0.6)


def test_no_claim_of_measured_data(comparisons):
    assert all(
        r.summary["dataset_kind"] == "synthetic" and r.summary["result_kind"] == "simulated"
        for r in comparisons.values()
    )
    with pytest.raises(ValueError):
        GPUOperatingPoint(200, 200, float("nan"))
