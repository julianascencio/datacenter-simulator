from dataclasses import replace

import pandas as pd
import pytest

from datacenter_simulator.methods.feasibility import FeasibilitySite, HallTemplate, screen_site


def template() -> HallTemplate:
    return HallTemplate("synthetic", 20, 30, 48, 20, 1000, 300)


def test_geometry_accounting_and_reproducibility() -> None:
    site = FeasibilitySite(100, 100, 100_000)
    result = screen_site(site, template(), storeys=2)
    assert result.summary["halls"] == 16
    assert result.summary["racks"] == 768
    assert result.summary["gross_floor_area_m2"] == 9600
    assert result.summary["structure_tco2e"] == 2880
    assert result.summary["shell_cost_eur"] == 9_600_000
    assert (result.halls.x_m + result.halls.width_m <= 90).all()
    assert (result.halls.y_m + result.halls.depth_m <= 90).all()
    assert (result.halls.y_m >= 30).all()
    assert not result.halls.duplicated(["level", "x_m", "y_m"]).any()
    pd.testing.assert_frame_equal(result.halls, screen_site(site, template(), storeys=2).halls)
    assert (
        result.equipment.total_installed_modules == result.equipment.installed_modules * 16
    ).all()


def test_power_caps_include_overheads_and_whole_halls() -> None:
    one = screen_site(FeasibilitySite(40, 70, 100_000), template())
    power = float(one.summary["facility_kw"])
    assert power > 960
    result = screen_site(FeasibilitySite(100, 100, power * 2.9), template())
    assert result.summary["halls"] == 2
    assert result.summary["limiting_constraint"] == "grid"
    assert float(result.summary["grid_margin_kw"]) >= 0


@pytest.mark.parametrize("site", [FeasibilitySite(10, 10, 1000), FeasibilitySite(100, 100, 0)])
def test_no_fit(site: FeasibilitySite) -> None:
    result = screen_site(site, template())
    assert result.summary["halls"] == result.summary["facility_kw"] == 0
    assert result.halls.empty and result.equipment.empty


def test_rotation_and_validation() -> None:
    site = FeasibilitySite(50, 80, 100_000)
    assert screen_site(site, template()).summary["halls"] == 1
    assert screen_site(site, template(), rotated=True).summary["halls"] == 2
    with pytest.raises(ValueError):
        screen_site(site, template(), storeys=3)
    with pytest.raises(ValueError):
        screen_site(site, replace(template(), width_m=1))
    with pytest.raises(ValueError):
        replace(site, grid_kw=float("nan"))
    with pytest.raises(ValueError):
        replace(template(), racks=1.5)
