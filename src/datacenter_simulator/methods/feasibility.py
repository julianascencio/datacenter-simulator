"""Deterministic rectangular site screening; not a permitted or structural design."""

from dataclasses import dataclass, replace
from math import floor

import pandas as pd

from datacenter_simulator.methods.facility_design import design_facility
from datacenter_simulator.models.design import DesignInputs
from datacenter_simulator.models.devices import finite


@dataclass(frozen=True)
class FeasibilitySite:
    """Flat rectangular parcel; a full-width strip reserves plant/access space.

    Power is confirmed import capacity, not the requested connection capacity.
    Setbacks apply to all four boundaries. Other exclusions require a smaller
    pre-screened rectangle; arbitrary polygons and terrain are not supported.
    """

    width_m: float
    depth_m: float
    grid_kw: float
    setback_m: float = 10
    plant_strip_m: float = 20
    maximum_storeys: int = 2

    def __post_init__(self) -> None:
        for name in ("width_m", "depth_m"):
            finite(name, getattr(self, name), strict=True)
        for name in ("grid_kw", "setback_m", "plant_strip_m"):
            finite(name, getattr(self, name))
        if type(self.maximum_storeys) is not int or self.maximum_storeys < 1:
            raise ValueError("maximum_storeys must be a positive integer")


@dataclass(frozen=True)
class HallTemplate:
    """Repeatable hall module including internal circulation/support space.

    Each hall has independent equipment trains sized by the existing facility
    method. Rates are caller-supplied shell/structure-only allowances, excluding
    equipment, land, fees and operating emissions; they are not a full CAPEX/LCA.
    """

    name: str
    width_m: float
    depth_m: float
    racks: int
    rack_kw: float
    shell_eur_m2: float
    structure_kgco2e_m2: float
    engineering: DesignInputs = DesignInputs(growth_fraction=0)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("template needs a name")
        for name in ("width_m", "depth_m", "rack_kw"):
            finite(name, getattr(self, name), strict=True)
        for name in ("shell_eur_m2", "structure_kgco2e_m2"):
            finite(name, getattr(self, name))
        if type(self.racks) is not int or self.racks < 1:
            raise ValueError("racks must be a positive integer")


@dataclass
class SiteOption:
    """Metrics, local metre coordinates and equipment BOQ from the same option."""

    summary: dict[str, str | float | int]
    halls: pd.DataFrame
    equipment: pd.DataFrame


def screen_site(
    site: FeasibilitySite, template: HallTemplate, *, storeys: int = 1, rotated: bool = False
) -> SiteOption:
    """Pack whole halls, then cap them by grid power including cooling/losses.

    Halls share walls; explicit exterior roads belong in the reserved strip or
    setbacks. Upper floors are filled before the next footprint is occupied.
    Zero-fit options return empty geometry/BOQ and zero operational demand.
    """
    if type(storeys) is not int or not 1 <= storeys <= site.maximum_storeys:
        raise ValueError("storeys must satisfy the site limit")
    design = design_facility(
        replace(
            template.engineering,
            it_peak_kw=template.racks * template.rack_kw,
            growth_fraction=0,
            rack_limit_kw=template.rack_kw,
            grid_limit_kw=site.grid_kw,
        )
    )
    geometry = design.summary
    if (
        geometry["hall_width_m"] > template.width_m
        or geometry["hall_depth_m"] > template.depth_m
        or geometry["total_planning_area_m2"] > template.width_m * template.depth_m
    ):
        raise ValueError("template cannot contain rack layout plus support allowance")
    width, depth = template.width_m, template.depth_m
    if rotated:
        width, depth = depth, width
    columns = floor(max(0, site.width_m - 2 * site.setback_m) / width)
    rows = floor(max(0, site.depth_m - 2 * site.setback_m - site.plant_strip_m) / depth)
    spatial_halls = columns * rows * storeys
    hall_power = design.summary["design_facility_kw"]
    power_halls = floor(site.grid_kw / hall_power)
    count = min(spatial_halls, power_halls)
    records = []
    for i in range(count):
        footprint, level = divmod(i, storeys)
        row, column = divmod(footprint, columns)
        records.append(
            dict(
                hall=f"H{i + 1:04d}",
                level=level,
                x_m=site.setback_m + column * width,
                y_m=site.setback_m + site.plant_strip_m + row * depth,
                width_m=width,
                depth_m=depth,
            )
        )
    halls = pd.DataFrame(records, columns=["hall", "level", "x_m", "y_m", "width_m", "depth_m"])
    equipment = design.equipment.copy() if count else design.equipment.iloc[:0].copy()
    equipment["hall_count"] = count
    equipment["total_installed_modules"] = equipment.installed_modules * count
    area = count * width * depth
    occupied = (count + storeys - 1) // storeys
    summary: dict[str, str | float | int] = {
        "template": template.name,
        "storeys": storeys,
        "rotated": int(rotated),
        "spatial_hall_limit": spatial_halls,
        "grid_hall_limit": power_halls,
        "halls": count,
        "racks": count * template.racks,
        "it_kw": count * template.racks * template.rack_kw,
        "facility_kw": count * hall_power,
        "grid_margin_kw": site.grid_kw - count * hall_power,
        "gross_floor_area_m2": area,
        "footprint_m2": occupied * width * depth,
        "site_coverage_fraction": occupied * width * depth / (site.width_m * site.depth_m),
        "shell_cost_eur": area * template.shell_eur_m2,
        "structure_tco2e": area * template.structure_kgco2e_m2 / 1000,
        "limiting_constraint": "grid" if power_halls < spatial_halls else "space",
    }
    return SiteOption(summary, halls, equipment)
