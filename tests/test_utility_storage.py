"""Conservation and boundary checks for utility-linked storage matching."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.analysis.faraday import export_faraday_study, faraday_study
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.utility_storage import match_utility_storage
from datacenter_simulator.models.utility_storage import FaradayInputs, contracted_storage
from datacenter_simulator.use_cases.faraday import faraday_profiles


def profiles(load: list[float], solar: list[float], freq: str = "h") -> tuple[pd.Series, pd.Series]:
    index = pd.date_range("2026-01-01", periods=len(load), freq=freq, tz="UTC")
    return pd.Series(load, index=index), pd.Series(solar, index=index)


def test_contracted_600_mwh_delivers_four_hours_at_150_mw() -> None:
    # Five surplus hours charge 600 / 0.9 MWh; four night hours deliver 600 MWh.
    load, pv = profiles([0] * 5 + [150000] * 5, [150000] * 5 + [0] * 5)
    result = match_utility_storage(
        load, pv, battery=contracted_storage(150, 600), poi_export_limit_kw=150000
    )
    frame = result.timeseries
    np.testing.assert_allclose(frame.discharge_kw.iloc[5:9], 150000, atol=1e-8)
    assert frame.discharge_kw.iloc[9] == pytest.approx(0, abs=1e-7)
    assert result.summary["battery_discharge_mwh"] == pytest.approx(600)
    assert result.summary["battery_charge_mwh"] == pytest.approx(600 / 0.9)
    assert result.summary["battery_loss_mwh"] == pytest.approx(600 / 0.9 - 600)
    assert result.summary["equivalent_delivered_cycles"] == pytest.approx(1)
    assert result.summary["storage_balance_max_abs_kwh"] < 1e-7


def test_shared_poi_and_customer_meter_are_separate() -> None:
    load, pv = profiles([200000] * 8, [525000] * 4 + [0] * 4)
    result = match_utility_storage(
        load, pv, battery=contracted_storage(150, 600), poi_export_limit_kw=100000
    )
    f = result.timeseries
    assert (f.site_export_kw <= 100000 + 1e-7).all()
    assert (f.matched_kw <= 100000 + 1e-7).all()
    np.testing.assert_allclose(f.facility_utility_import_kw, 200000)
    assert (f.residual_unmatched_kw >= 100000 - 1e-7).all()
    assert (f.charge_kw * f.discharge_kw == 0).all()
    assert result.summary["curtailed_mwh"] > 0
    assert result.summary["site_balance_max_abs_kw"] < 1e-7


def test_unmatched_exports_are_not_double_counted() -> None:
    load, pv = profiles([1000, 1000], [3000, 0])
    result = match_utility_storage(load, pv, poi_export_limit_kw=3000)
    assert result.summary["hourly_matched_fraction"] == pytest.approx(0.5)
    assert result.summary["unmatched_export_mwh"] == pytest.approx(2)
    assert result.summary["residual_unmatched_mwh"] == pytest.approx(1)
    assert result.summary["facility_meter_peak_mw"] == 1


def test_no_solar_no_grid_charging_and_no_free_initial_energy() -> None:
    load, pv = profiles([1000] * 24, [0] * 24)
    result = match_utility_storage(
        load, pv, battery=contracted_storage(150, 600), poi_export_limit_kw=525000
    )
    assert result.summary["matched_energy_mwh"] == 0
    assert result.summary["battery_charge_mwh"] == 0
    with pytest.raises(ValueError, match="initial usable"):
        match_utility_storage(load, pv, battery=Battery(1000, 100, 100), poi_export_limit_kw=1000)


def test_half_hour_energy_and_final_inventory_accounting() -> None:
    load, pv = profiles([0, 1000, 0], [1000, 0, 1000], "30min")
    result = match_utility_storage(
        load, pv, battery=contracted_storage(1, 1, 1), poi_export_limit_kw=1000, dt_hours=0.5
    )
    assert result.summary["matched_energy_mwh"] == pytest.approx(0.5)
    assert result.summary["final_internal_energy_mwh"] == pytest.approx(0.5)
    assert result.summary["fully_matched_hours"] == pytest.approx(0.5)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_solar_is_rejected(value: float) -> None:
    load, pv = profiles([1000, 1000], [value, 0])
    with pytest.raises(ValueError):
        match_utility_storage(load, pv, poi_export_limit_kw=1000)


def test_bad_timestamps_and_step_are_rejected() -> None:
    load, pv = profiles([1000, 1000], [0, 0])
    with pytest.raises(ValueError, match="spacing"):
        match_utility_storage(load, pv, poi_export_limit_kw=1000, dt_hours=0.5)
    pv.index = pv.index + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="exactly match"):
        match_utility_storage(load, pv, poi_export_limit_kw=1000)
    load.index = load.index.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        match_utility_storage(load, pv, poi_export_limit_kw=1000)


def test_zero_poi_zero_load_and_nonunity_efficiency() -> None:
    load, pv = profiles([0, 1000, 1000], [3000, 0, 0])
    result = match_utility_storage(
        load, pv, battery=contracted_storage(1, 1, 0.8), poi_export_limit_kw=0
    )
    assert result.summary["matched_energy_mwh"] == 0
    assert (result.timeseries.site_export_kw == 0).all()
    assert result.summary["final_internal_energy_mwh"] > 0
    assert result.summary["site_balance_max_abs_kw"] < 1e-7


def test_study_conservation_and_scenario_relationships() -> None:
    study = faraday_study()
    for result in study.results.values():
        s = result.summary
        assert s["site_balance_max_abs_kw"] < 1e-7
        assert s["storage_balance_max_abs_kwh"] < 1e-7
        assert 0 <= s["hourly_matched_fraction"] <= 1
        assert s["facility_meter_peak_mw"] == 200
        assert s["solar_available_mwh"] == pytest.approx(
            s["matched_energy_mwh"]
            + s["unmatched_export_mwh"]
            + s["curtailed_mwh"]
            + s["battery_loss_mwh"]
            + s["final_internal_energy_mwh"]
            - s["initial_internal_energy_mwh"]
        )
    matched = study.comparison.set_index("scenario").matched_energy_mwh
    assert matched.phase1_600mwh > matched.solar_only > matched.grid_only
    assert matched.proposed_combined_2100mwh >= matched.phase1_600mwh
    assert matched.low_solar_phase1 < matched.phase1_600mwh


def test_year_roundoff_and_dst_boundaries() -> None:
    frame = faraday_profiles(FaradayInputs(hours=8760))
    result = match_utility_storage(
        frame.demand_kw,
        frame.solar_kw,
        battery=contracted_storage(150, 600),
        poi_export_limit_kw=525000,
    )
    assert (result.timeseries.battery_energy_kwh >= 0).all()
    assert result.summary["storage_balance_max_abs_kwh"] < 1e-7


def test_export_and_replay(tmp_path: Path) -> None:
    study = export_faraday_study(tmp_path, FaradayInputs(hours=48))
    assert (tmp_path / "faraday-storage.html").is_file()
    assert json.loads((tmp_path / "evidence.json").read_text())["sources"]
    metadata = json.loads((tmp_path / "project_metadata.json").read_text())
    assert metadata["project_name"] == "Faraday BESS"
    assert metadata["actual_data_center_facility_mw"] is None
    assert metadata["commercial_operation_date"] == "2026-09-18"
    raw = pd.read_csv(tmp_path / "profiles.csv")
    raw.index = pd.DatetimeIndex(pd.to_datetime(raw.pop("timestamp"), utc=True))
    replay = faraday_study(FaradayInputs(hours=48), raw)
    np.testing.assert_allclose(
        study.comparison.select_dtypes("number"),
        replay.comparison.select_dtypes("number"),
        atol=1e-7,
    )


def test_scenario_overrides_preserve_reported_metadata() -> None:
    study = faraday_study(FaradayInputs(hours=24, it_mw=80, pue=1.1, solar_ac_peak_mw=400))
    metadata = study.project_metadata
    assert metadata.adjacent_solar_reported_mw == 525
    assert metadata.actual_data_center_facility_mw is None
    assert metadata.actual_data_center_it_mw is None
    assert metadata.actual_data_center_pue is None
    assert metadata.actual_poi_export_limit_mw is None
    assert metadata.actual_battery_round_trip_efficiency is None
    assert metadata.solar_capacity_ac_dc_basis is None
    assert study.profiles.demand_kw.max() == pytest.approx(88000)
    assert study.profiles.solar_kw.max() <= 400000
    ratings = study.comparison.set_index("scenario")
    assert ratings.loc["phase1_600mwh", "battery_power_mw"] == metadata.battery_power_mw
    assert ratings.loc["phase1_600mwh", "deliverable_energy_mwh"] == metadata.contracted_storage_mwh
    assert ratings.loc["proposed_combined_2100mwh", "deliverable_energy_mwh"] == (
        metadata.contracted_storage_mwh + metadata.proposed_phase2_max_mwh
    )


@pytest.mark.parametrize("kwargs", [{"hours": 0}, {"pue": 0.9}, {"round_trip_efficiency": 1.1}])
def test_invalid_assumptions(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        FaradayInputs(**kwargs)  # type: ignore[arg-type]
