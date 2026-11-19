"""Check alternative grid attribution, unit conversions and the public snapshot."""

from dataclasses import replace

import pytest

from datacenter_simulator.methods.gas_exposure import GasSite, annual_gas_exposure
from datacenter_simulator.use_cases.anthropic import anthropic_us_sites


def test_two_site_energy_balance_and_fuel_charges() -> None:
    onsite = GasSite("on site", 1, 2, True, 0.4, 1, 100)
    grid = GasSite("grid", 2, 3, False, 0.25, 0.80, 500)
    result = annual_gas_exposure(
        [onsite, grid],
        capacity="low",
        pue=1.2,
        it_load_fraction=0.5,
        onsite_heat_rate_mmbtu_per_mwh=10,
        grid_heat_rate_mmbtu_per_mwh=8,
        onsite_price_usd_per_mmbtu=3,
    )
    onsite_row, grid_row = result.loc["on site"], result.loc["grid"]
    assert onsite_row.onsite_gas_mwh == 5256
    assert (
        onsite_row.grid_mwh
        == onsite_row.study_grid_gas_mwh
        == onsite_row.regional_grid_gas_mwh
        == 0
    )
    assert onsite_row.onsite_fuel_cost_usd == 5256 * 10 * 3
    assert grid_row.onsite_fuel_cost_usd == 0
    assert grid_row.regional_grid_fuel_mmbtu == 10512 * 0.25 * 8
    assert grid_row.study_grid_fuel_mmbtu == pytest.approx(10512 * 0.8 * 8)
    assert grid_row.study_co2e_tonnes == pytest.approx(10512 * 500 * 0.00045359237)
    assert (result.onsite_gas_mwh + result.grid_mwh).equals(result.facility_mwh)
    assert annual_gas_exposure([onsite], it_load_fraction=0).facility_mwh.sum() == 0


def test_replay_workbook_and_published_mid_case() -> None:
    sites = anthropic_us_sites()
    assert len(sites) == 19
    assert sum(s.speculative_attribution for s in sites) == 5
    assert sum(s.low_it_mw for s in sites) == 5907
    assert sum(s.high_it_mw for s in sites if s.onsite_gas) == 2510
    totals = annual_gas_exposure(sites).sum()
    assert totals.it_capacity_mw == 9579
    assert totals.facility_mwh == pytest.approx(9579 * 0.70 * 1.15 * 8760)
    assert (
        totals.onsite_gas_mwh + totals.study_grid_gas_mwh
    ) / totals.facility_mwh == pytest.approx(0.874, abs=0.0005)
    assert (
        totals.onsite_gas_mwh + totals.regional_grid_gas_mwh
    ) / totals.facility_mwh == pytest.approx(0.60732, abs=0.00001)
    assert round(totals.study_co2e_tonnes / 1e6) == 32
    shock = annual_gas_exposure(sites, onsite_price_usd_per_mmbtu=5).sum()
    assert shock.onsite_fuel_cost_usd - totals.onsite_fuel_cost_usd == pytest.approx(
        totals.onsite_fuel_mmbtu
    )


def test_reject_invalid_energy_inputs() -> None:
    site = GasSite("one", 1, 2, False, 0.4, 0.8, 500)
    for invalid in (float("nan"), -0.1, 1.1):
        with pytest.raises(ValueError):
            replace(site, regional_grid_gas_fraction=invalid)
    with pytest.raises(ValueError):
        replace(site, high_it_mw=0.5)
    with pytest.raises(ValueError):
        annual_gas_exposure([site], pue=0.9)
    with pytest.raises(ValueError):
        annual_gas_exposure([site, site])
