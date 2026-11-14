import hashlib
import json
from dataclasses import replace
from importlib.resources import files

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.analysis.bess_value import break_even_installed_cost, spain_bess_study
from datacenter_simulator.connectors.edi_bess import load_edi_solar_snapshot
from datacenter_simulator.methods.bess_value import (
    optimize_bess_value,
    ramp_buffer_requirement,
    replay_outage,
)
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.models.bess_value import BESSValuePolicy


def series(values: list[float], freq: str = "h") -> pd.Series:
    return pd.Series(
        values, index=pd.date_range("2023-01-01", periods=len(values), freq=freq, tz="UTC")
    )


def test_negative_prices_conservation_and_no_free_terminal_energy() -> None:
    load, solar, price = series([10, 90, 10]), series([0, 0, 0]), series([-0.1, 0.3, 0.02])
    battery = Battery(100, 100, 100, initial_soc=0.8)
    result = optimize_bess_value(load, solar, price, battery, BESSValuePolicy(200))
    f = result.timeseries
    assert np.max(abs(f.balance_error_kw)) < 1e-6
    assert (f.charge_kw * f.discharge_kw < 1e-6).all()
    assert f.energy_end_kwh.iloc[-1] == pytest.approx(80)
    assert f.energy_end_kwh.min() >= 10 - 1e-6
    assert f.energy_end_kwh.max() <= 95 + 1e-6
    assert (f.grid_kw <= 200 + 1e-6).all()
    assert (f.grid_kw >= -1e-6).all()
    assert result.summary["charge_kwh"] - result.summary["discharge_kwh"] == pytest.approx(
        result.summary["battery_loss_kwh"]
    )
    assert result.summary["operating_saving_eur"] > 0


def test_no_battery_throughput_matches_baseline() -> None:
    load, solar, price = series([100, 20]), series([0, 50]), series([0.1, 0.2])
    result = optimize_bess_value(load, solar, price, Battery(100, 0, 0), BESSValuePolicy(100))
    assert result.summary["operating_saving_eur"] == pytest.approx(0)
    assert result.summary["bess_curtailed_kwh"] == pytest.approx(30)
    assert result.summary["baseline_energy_cost_eur"] == pytest.approx(10)


def test_reserve_reduces_savings_and_is_released_for_outage() -> None:
    load, solar, price = series([0, 100, 0]), series([0, 0, 0]), series([0.01, 0.3, 0.01])
    battery = Battery(100, 100, 100, initial_soc=0.8)
    policy = BESSValuePolicy(100)
    economic = optimize_bess_value(load, solar, price, battery, policy)
    reserve = optimize_bess_value(load, solar, price, battery, replace(policy, reserve_soc=0.8))
    assert reserve.timeseries.energy_end_kwh.min() >= 80 - 1e-6
    assert economic.summary["operating_saving_eur"] > reserve.summary["operating_saving_eur"]
    outage = replay_outage(series([100]), series([0]), battery, initial_energy_kwh=80)
    assert outage.summary["served_kwh"] == pytest.approx(70 * 0.96)
    assert outage.summary["unserved_kwh"] == pytest.approx(100 - 70 * 0.96)


def test_outage_power_limit_separate_from_energy_limit() -> None:
    battery = Battery(1000, 50, 50, initial_soc=0.9)
    outage = replay_outage(series([100]), series([0]), battery, initial_energy_kwh=900)
    assert outage.summary["unserved_kwh"] == pytest.approx(50)


def test_grid_infeasibility_does_not_report_savings() -> None:
    with pytest.raises(ValueError, match="not optimal/feasible"):
        optimize_bess_value(
            series([100]), series([0]), series([0.1]), Battery(10, 1, 1), BESSValuePolicy(1)
        )


def test_input_validation() -> None:
    load, solar, price = series([1, 2]), series([0, 0]), series([0.1, 0.2])
    b, p = Battery(10, 1, 1), BESSValuePolicy(100)
    with pytest.raises(ValueError, match="spacing"):
        optimize_bess_value(load, solar, price, b, p, dt_hours=0.5)
    with pytest.raises(ValueError, match="price timeline"):
        optimize_bess_value(load, solar, price.shift(1, freq="h"), b, p)
    with pytest.raises(ValueError, match="finite"):
        optimize_bess_value(load, solar, price * np.nan, b, p)
    with pytest.raises(ValueError, match="reserve"):
        optimize_bess_value(load, solar, price, b, replace(p, reserve_soc=0.9))
    with pytest.raises(ValueError):
        replay_outage(load, solar, b, initial_energy_kwh=1000)


def test_ramp_sizing_analytical_step() -> None:
    result = ramp_buffer_requirement(
        series([100, 200, 200], freq="s"), grid_ramp_kw_per_s=50, dt_seconds=1
    )
    assert result["required_discharge_kw"] == 50
    assert result["required_charge_kw"] == 0
    assert result["minimum_lossless_energy_swing_kwh"] == pytest.approx(50 / 3600)


def test_snapshot_integrity_and_scaling(tmp_path) -> None:
    solar, metadata = load_edi_solar_snapshot(dc_rating_kwp=1)
    scaled, _ = load_edi_solar_snapshot(dc_rating_kwp=1000)
    np.testing.assert_allclose(scaled, solar * 1000)
    assert len(solar) == 168 and solar.index[0].minute == 10
    assert metadata["edi_version"] == "0.1.0"
    root = files("datacenter_simulator").joinpath("data")
    for name in ("bess_madrid_pvgis.csv", "bess_madrid_pvgis.json"):
        (tmp_path / name).write_bytes(root.joinpath(name).read_bytes())
    (tmp_path / "bess_madrid_pvgis.csv").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        load_edi_solar_snapshot(dc_rating_kwp=1, directory=tmp_path)
    assert (
        hashlib.sha256(root.joinpath("bess_madrid_pvgis.csv").read_bytes()).hexdigest()
        == json.loads(root.joinpath("bess_madrid_pvgis.json").read_text())["csv_sha256"]
    )


def test_case_study_outage_tradeoff_and_finance_boundaries() -> None:
    study = spain_bess_study()
    assert len(study.outage_sweep) == 334
    assert study.comparison.loc["reserve_80pct", "worst_outage_unserved_kwh"] == pytest.approx(0)
    assert study.comparison.loc["economic", "worst_outage_unserved_kwh"] > 0
    assert break_even_installed_cost(100, years=2, discount_rate=0, annual_fixed_om_eur=10) == 180
    assert break_even_installed_cost(100, years=1, discount_rate=0.1) == pytest.approx(100 / 1.1)
    assert break_even_installed_cost(0, years=2, discount_rate=0, annual_fixed_om_eur=10) == -20


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_timestamp_storage_resolution_independent(unit: str) -> None:
    load = series([10, 20, 10])
    load.index = pd.DatetimeIndex(load.index).as_unit(unit)
    result = optimize_bess_value(
        load, load * 0, load * 0 + 0.1, Battery(100, 10, 10), BESSValuePolicy(100)
    )
    assert abs(result.timeseries.balance_error_kw).max() < 1e-6
    fast = series([100, 200, 200], freq="s")
    fast.index = pd.DatetimeIndex(fast.index).as_unit(unit)
    assert (
        ramp_buffer_requirement(fast, grid_ramp_kw_per_s=50, dt_seconds=1)["required_discharge_kw"]
        == 50
    )
