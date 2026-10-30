from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from datacenter_simulator.connectors import generation_from_csv, generation_from_series
from datacenter_simulator.methods.cooling import CoolingPlant
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.models import Communications
from datacenter_simulator.simulation import simulate
from datacenter_simulator.use_cases import reference_center, reference_profiles


def test_coupled_simulation_and_pue_boundary() -> None:
    center = reference_center()
    profiles, generation = reference_profiles()
    r = simulate(center, profiles, generation=generation, battery=Battery(500, 150, 150))
    baseline = simulate(center, profiles)
    assert r.summary["pue"] == pytest.approx(baseline.summary["pue"])
    assert r.summary["grid_import_kwh"] < baseline.summary["grid_import_kwh"]
    assert r.summary["pue"] == pytest.approx(r.summary["facility_kwh"] / r.summary["it_kwh"])
    assert r.summary["max_balance_error_kw"] < 1e-10
    assert not r.warnings
    assert np.allclose(
        r.timeseries.facility_kw,
        r.timeseries[
            [
                "it_kw",
                "dc_loss_kw",
                "rectifier_loss_kw",
                "cooling_kw",
                "auxiliary_kw",
            ]
        ].sum(axis=1),
    )


def test_supply_and_cooling_shortfall_are_visible() -> None:
    center = replace(reference_center(), cooling=CoolingPlant("small", 10, 3))
    profiles, _ = reference_profiles(2)
    r = simulate(center, profiles, grid_import_limit_kw=0)
    assert r.summary["unserved_kwh"] > 0
    assert r.summary["unmet_heat_kwh"] > 0
    assert len(r.warnings) == 2


def test_connector_units_and_timezones() -> None:
    profiles, generation = reference_profiles(2)
    series = generation["Biogas"] * 1000
    series.index = series.index.tz_convert("Europe/Madrid")
    result = generation_from_series(series, profiles.index, unit="W", conversion_efficiency=0.98)
    assert result.iloc[0] == pytest.approx(34.3)


def test_connector_missing_and_nan_rejected() -> None:
    profiles, generation = reference_profiles(2)
    with pytest.raises(ValueError, match="match"):
        generation_from_series(generation["PV"].iloc[:1], profiles.index)
    generation["PV"].iloc[0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        generation_from_series(generation["PV"], profiles.index)


def test_csv_adapter_and_naive_timestamp_rejection(tmp_path: Path) -> None:
    profiles, _ = reference_profiles(2)
    target = tmp_path / "input.csv"
    target.write_text(
        "timestamp,power_kw\n2026-01-01T00:00:00+00:00,10\n2026-01-01T01:00:00+00:00,20\n"
    )
    assert generation_from_csv(target, profiles.index).tolist() == [10, 20]
    target.write_text(target.read_text().replace("+00:00", ""))
    with pytest.raises(ValueError, match="timezone"):
        generation_from_csv(target, profiles.index)


def test_irregular_profile_rejected() -> None:
    profiles, _ = reference_profiles(3)
    with pytest.raises(ValueError, match="intervals"):
        simulate(reference_center(), profiles.iloc[[0, 2]])


@pytest.mark.parametrize("resolution", ["s", "ms", "us", "ns"])
def test_datetime_storage_resolution_does_not_change_intervals(resolution: str) -> None:
    profiles, generation = reference_profiles(2)
    profiles.index = profiles.index.as_unit(resolution)
    r = simulate(reference_center(), profiles, generation=generation)
    assert r.summary["facility_kwh"] > 0
    assert r.summary["max_balance_error_kw"] < 1e-8


def test_device_ports_validated_against_topology() -> None:
    center = reference_center()
    devices = center.devices.copy()
    devices[0] = replace(devices[0], communications=Communications(1))
    with pytest.raises(ValueError, match="ports"):
        replace(center, devices=devices)
