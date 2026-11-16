"""Independent balances, financial fixtures and published-table regression checks."""

import io
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.analysis.speed_to_power import export_speed_power_study
from datacenter_simulator.connectors.speed_to_power import (
    bundled_published_results,
    fetch_published_results,
    power_profiles_from_csv,
    profiles_from_components,
    validate_power_profiles,
    validate_published_results,
)
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.speed_to_power import (
    SupplyPaths,
    break_even_gpu_value,
    dispatch_solar_storage,
    facility_load_summary,
    levelized_power_cost,
    paper_supply_paths,
    project_cashflows,
    published_cost_comparison,
    pv_retention,
    solar_drought_energy,
)
from datacenter_simulator.models.power_architecture import PowerStage
from datacenter_simulator.models.speed_to_power import ComputeFleet, PowerProject, SpeedPowerInputs


def profile(solar=(2.0, 0.0), load=1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {"it_kw": load, "cooling_kw": 0.0, "pv_dc_per_kwp": solar},
        index=pd.date_range("2025-01-01", periods=len(solar), freq="h", tz="UTC"),
    )


IDEAL = SupplyPaths("ideal", (), (PowerStage("IT", 1),), (PowerStage("cooling", 1),))


def test_periodic_storage_energy_and_no_free_initial_charge():
    storage = Battery(1, 1, 1, 1, 1, 0, 1, 1)
    result = dispatch_solar_storage(profile(), IDEAL, pv_kwp=1, battery=storage)
    assert result.summary["delivered_kwh"] == pytest.approx(2)
    assert result.summary["periodic_inventory_error_kwh"] == pytest.approx(0)
    assert result.summary["maximum_balance_error_kw"] < 1e-10
    empty = dispatch_solar_storage(profile((0.0, 0.0)), IDEAL, pv_kwp=1, battery=storage)
    assert empty.summary["delivered_kwh"] == 0
    assert empty.summary["unserved_kwh"] == 2


def test_storage_losses_and_full_hour_availability_are_separate():
    storage = Battery(1, 1, 1, 0.8, 0.5, 0, 1, 0)
    result = dispatch_solar_storage(profile(), IDEAL, pv_kwp=1, battery=storage)
    # First hour serves 1 kWh and stores 0.8; next hour delivers 0.4.
    assert result.summary["delivered_kwh"] == pytest.approx(1.4)
    assert result.summary["battery_loss_kwh"] == pytest.approx(0.6)
    assert result.summary["full_load_hour_fraction"] == 0.5
    assert result.summary["energy_served_fraction"] == pytest.approx(0.7)
    assert result.summary["maximum_balance_error_kw"] < 1e-10


def test_load_conversion_and_source_conversion_are_not_double_counted():
    path = SupplyPaths(
        "lossy", (PowerStage("PV", 0.5),), (PowerStage("IT", 0.8),), (PowerStage("cooling", 0.5),)
    )
    p = profile((10.0,), load=4.0)
    result = dispatch_solar_storage(p, path, pv_kwp=1)
    assert result.summary["delivered_kwh"] == pytest.approx(4)
    assert result.summary["conversion_loss_kwh"] == pytest.approx(6)
    assert result.summary["maximum_balance_error_kw"] < 1e-10


def test_path_efficiencies_follow_figure_two():
    paths = paper_supply_paths()
    assert paths["ac_solar"].pv_efficiency == 0.99
    assert paths["dc_solar"].pv_efficiency == pytest.approx(0.99 * 0.98)
    assert paths["ac_solar"].it_efficiency == pytest.approx(0.98**3 * 0.99**3 * 0.94)
    assert paths["dc_solar"].it_efficiency == pytest.approx(0.98**2 * 0.99**3)
    assert paths["gas"].it_efficiency == paths["grid"].it_efficiency


def test_capacity_power_limit_prevents_false_reliability():
    result = dispatch_solar_storage(
        profile((10.0, 0.0)), IDEAL, pv_kwp=1, battery=Battery(100, 100, 0.1, 1, 1, 0, 1, 0)
    )
    assert result.summary["full_load_hour_fraction"] == 0.5
    assert result.summary["delivered_kwh"] == pytest.approx(1.1)


def test_financial_closed_form_no_discount():
    project = PowerProject("A", 2, 100, 10, 100, 20, 1)
    flows = project_cashflows(project, gpu_count=8, horizon_years=5)
    assert flows.capital_usd.tolist() == [40, 60, 0, 0, 0]
    assert flows.replacement_usd.tolist() == [0, 0, 0, 20, 0]
    assert flows.delivered_kwh.sum() == 300
    result = levelized_power_cost(flows, discount_rate=0, gpu_hour_value_usd=1)
    assert result["base_lcoe_usd_per_kwh"] == pytest.approx(150 / 300)
    assert result["pv_idle_gpu_hours"] == 2 * 8760 * 8
    assert result["adjusted_lcoe_usd_per_kwh"] == pytest.approx((150 + 2 * 8760 * 8) / 300)


def test_midyear_discount_independently():
    flows = project_cashflows(PowerProject("A", 1, 100, 10, 100), gpu_count=8, horizon_years=2)
    result = levelized_power_cost(flows, discount_rate=0.1, gpu_hour_value_usd=0)
    assert result["pv_energy_cost_usd"] == pytest.approx(100 / 1.1**0.5 + 10 / 1.1**1.5)
    assert result["pv_energy_kwh"] == pytest.approx(100 / 1.1**1.5)
    assert result["base_lcoe_usd_per_kwh"] == pytest.approx(1.2)


def test_partial_years_common_horizon_and_readiness():
    project = PowerProject("A", 2.5, 100, 10, 100)
    flows = project_cashflows(project, gpu_count=8, horizon_years=5, compute_ready_year=1.75)
    assert flows.capital_usd.tolist() == [40, 40, 20, 0, 0]
    assert flows.delivered_kwh.sum() == 250
    assert flows.idle_gpu_hours.sum() == pytest.approx(0.75 * 8760 * 8)
    ready_late = project_cashflows(project, gpu_count=8, horizon_years=5, compute_ready_year=3)
    assert ready_late.idle_gpu_hours.sum() == 0
    assert ready_late.delivered_kwh.sum() == 200
    assert (
        project_cashflows(
            replace(project, deployment_years=4), gpu_count=8, horizon_years=5
        ).delivered_kwh.sum()
        == 100
    )


def test_no_replacement_at_or_beyond_horizon():
    project = PowerProject("A", 2, 100, 10, 100, 50, 3)
    assert project_cashflows(project, gpu_count=8, horizon_years=5).replacement_usd.sum() == 0


def test_break_even_uses_each_architectures_denominator():
    assert break_even_gpu_value(0.3, 0.1, 0.1, 0.2) == pytest.approx(2)
    assert break_even_gpu_value(0.3, 0.1, 0.1, 0.1) is None
    assert break_even_gpu_value(0.1, 0.1, 0.3, 0.2) is None


def test_fleet_peak_and_cyclic_solar_drought():
    fleet = ComputeFleet()
    p = profile(tuple(np.ones(240)), load=fleet.average_it_kw)
    p["cooling_kw"] = p.it_kw * 0.2
    assert facility_load_summary(p, fleet)["design_terminal_kw"] == pytest.approx(133875)
    p.iloc[:12, p.columns.get_loc("pv_dc_per_kwp")] = 0
    p.iloc[-12:, p.columns.get_loc("pv_dc_per_kwp")] = 0
    assert solar_drought_energy(p, days=1) == pytest.approx(0)
    assert pv_retention(1) == 0.99
    assert pv_retention(25) == pytest.approx(0.858)


@pytest.mark.parametrize("mutation", ["nan", "negative", "naive", "gap", "duplicate", "short"])
def test_profile_validation(mutation):
    p = profile()
    if mutation == "nan":
        p.iloc[0, 0] = np.nan
    elif mutation == "negative":
        p.iloc[0, 2] = -1
    elif mutation == "naive":
        p.index = p.index.tz_localize(None)
    elif mutation == "gap":
        p.index = pd.date_range("2025", periods=2, freq="2h", tz="UTC")
    elif mutation == "duplicate":
        p.index = pd.DatetimeIndex([p.index[0], p.index[0]])
    with pytest.raises(ValueError):
        validate_power_profiles(p, annual=mutation == "short")


def test_csv_and_component_connectors(tmp_path):
    p = profile()
    path = tmp_path / "profiles.csv"
    p.to_csv(path, index_label="timestamp")
    pd.testing.assert_frame_equal(
        power_profiles_from_csv(path, annual=False), p.rename_axis("timestamp"), check_freq=False
    )
    result = profiles_from_components(
        p.it_kw, p.cooling_kw, p.pv_dc_per_kwp * 100, pv_rating_kwp=100
    )
    pd.testing.assert_frame_equal(p, result)
    with pytest.raises(ValueError, match="aligned"):
        profiles_from_components(p.it_kw, p.cooling_kw.iloc[:1], p.pv_dc_per_kwp, pv_rating_kwp=1)
    path.write_text(path.read_text().replace("+00:00", ""))
    with pytest.raises(ValueError, match="timezone"):
        power_profiles_from_csv(path, annual=False)


def test_published_snapshot_exact_replay_and_scale():
    frame = bundled_published_results()
    assert len(frame) == 4317
    assert set(frame.gpu_count) == {100000}
    assert set(frame.ac_topology) == {"mv_coupled"}
    result = published_cost_comparison(frame)
    assert (result.winner == "dc_coupled").sum() == 3663
    assert (result.winner == "natural_gas").sum() == 1
    assert np.allclose(result.dc_coupled, frame.dc_coupled_total_lcoe)
    accelerated = published_cost_comparison(frame, accelerated_gas=True)
    assert (accelerated.winner == "dc_coupled").sum() == 2402
    zero = published_cost_comparison(frame, gpu_hour_value_usd=0)
    assert np.allclose(zero.dc_coupled, frame.dc_coupled_base_lcoe)


def test_published_connector_validation_and_bad_hash(monkeypatch):
    frame = bundled_published_results().iloc[:1].copy()
    frame.loc[frame.index[0], "dc_topology"] = "unknown"
    with pytest.raises(ValueError, match="topology"):
        validate_published_results(frame)
    monkeypatch.setattr(
        "datacenter_simulator.connectors.speed_to_power.urlopen",
        lambda *a, **kw: io.BytesIO(b"wrong payload"),
    )
    with pytest.raises(ValueError, match="hash"):
        fetch_published_results()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"gpu_count": 7},
        {"minimum_uptime": 1.1},
        {"grid_deployment_years": 27},
        {"discount_rate": -0.1},
        {"compute_ready_year": 27},
        {"gpu_count": True},
    ],
)
def test_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        SpeedPowerInputs(**kwargs)


def test_infeasible_solar_is_not_selected_and_exports_are_replayable(tmp_path):
    # All-dark year forces all 18 solar designs to fail, regardless of storage size.
    p = profile(tuple(np.zeros(8760)), load=7.3)
    study = export_speed_power_study(tmp_path, SpeedPowerInputs(gpu_count=8), p)
    assert len(study.candidates) == 20
    assert set(study.selected.architecture) == {"gas", "grid"}
    assert not study.candidates[study.candidates.architecture.str.endswith("solar")].feasible.any()
    assert (tmp_path / "speed-to-power.html").exists()
    pd.testing.assert_frame_equal(
        power_profiles_from_csv(tmp_path / "profiles.csv"),
        p.rename_axis("timestamp"),
        check_freq=False,
    )
