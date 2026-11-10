"""Inputs for a Cartesian, incompressible, Boussinesq room-air CFD model."""

from dataclasses import dataclass
from math import prod

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class CFDGrid:
    """Uniform cells; x is supply-to-return, z points vertically upward (metres)."""

    length_m: float = 8
    width_m: float = 6
    height_m: float = 3
    nx: int = 20
    ny: int = 16
    nz: int = 10

    def __post_init__(self) -> None:
        for name in ("length_m", "width_m", "height_m"):
            finite(name, getattr(self, name), strict=True)
        for name in ("nx", "ny", "nz"):
            value = getattr(self, name)
            if type(value) is not int or value < 3:
                raise ValueError(f"{name} must be an integer >= 3")
        if prod(self.shape) > 100_000:
            raise ValueError("native sparse-direct CFD is limited to 100000 cells")

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.nx, self.ny, self.nz

    @property
    def spacing(self) -> tuple[float, float, float]:
        return self.length_m / self.nx, self.width_m / self.ny, self.height_m / self.nz

    @property
    def cell_volume_m3(self) -> float:
        return prod(self.spacing)


@dataclass(frozen=True)
class CFDSource:
    """Permeable rack envelope with heat to air and linear momentum resistance.

    ``heat_kw`` is heat actually released into room air, after any direct liquid
    removal. The source is a fluid volume, not a solid-temperature/conjugate model.
    ``drag_per_s`` multiplies velocity in the momentum equation.
    """

    name: str
    x_m: float
    y_m: float
    z_m: float
    width_m: float
    depth_m: float
    height_m: float
    heat_kw: float
    drag_per_s: float = 0.5
    inertial_drag_per_m: float = 0
    fan_pressure_pa: float = 0
    fan_free_speed_m_s: float = 1
    fan_axis: int = 0
    fan_direction: int = 1

    def __post_init__(self) -> None:
        finite("fan_free_speed_m_s", self.fan_free_speed_m_s, strict=True)
        if type(self.fan_axis) is not int or self.fan_axis not in (0, 1, 2):
            raise ValueError("fan_axis must be 0, 1 or 2")
        if type(self.fan_direction) is not int or self.fan_direction not in (-1, 1):
            raise ValueError("fan_direction must be -1 or 1")
        if not self.name:
            raise ValueError("CFD source requires a name")
        for name in (
            "x_m",
            "y_m",
            "z_m",
            "heat_kw",
            "drag_per_s",
            "inertial_drag_per_m",
            "fan_pressure_pa",
        ):
            finite(name, getattr(self, name))
        for name in ("width_m", "depth_m", "height_m"):
            finite(name, getattr(self, name), strict=True)


@dataclass(frozen=True)
class CFDSettings:
    """Fluid properties, boundary conditions and explicit integration controls.

    Supply enters a full-width low slot on x=0; a rectangular opening on x=L is a
    zero-gauge-pressure return. Other walls have no penetration, no slip and
    zero heat flux. Return backflow temperature is configurable; it defaults to supply temperature.
    Effective viscosity/diffusivity are declared mixing assumptions, not a
    calibrated RANS/LES turbulence closure. Set molecular values for laminar tests.
    """

    supply_flow_m3_s: float = 2.0
    supply_temperature_c: float = 20
    inlet_height_m: float = 0.9
    density_kg_m3: float = 1.2
    cp_j_kg_k: float = 1006
    viscosity_m2_s: float = 0.03
    diffusivity_m2_s: float = 0.04
    expansion_per_k: float = 1 / 293.15
    gravity_m_s2: float = 9.81
    duration_s: float = 120
    max_dt_s: float = 0.25
    cfl: float = 0.45
    snapshot_interval_s: float = 20
    max_steps: int = 20000
    thermal_scheme: str = "muscl"
    return_temperature_c: float | None = None
    return_width_m: float | None = None
    return_height_m: float | None = None
    return_y_m: float = 0
    return_z_m: float = 0

    def __post_init__(self) -> None:
        for name in (
            "supply_flow_m3_s",
            "viscosity_m2_s",
            "diffusivity_m2_s",
            "expansion_per_k",
            "gravity_m_s2",
        ):
            finite(name, getattr(self, name))
        for name in (
            "inlet_height_m",
            "density_kg_m3",
            "cp_j_kg_k",
            "duration_s",
            "max_dt_s",
            "snapshot_interval_s",
        ):
            finite(name, getattr(self, name), strict=True)
        finite("supply_temperature_c", self.supply_temperature_c, -273.15, strict=True)
        for name in ("return_y_m", "return_z_m"):
            finite(name, getattr(self, name))
        for name in ("return_width_m", "return_height_m"):
            if getattr(self, name) is not None:
                finite(name, getattr(self, name), strict=True)
        if self.thermal_scheme not in ("upwind", "muscl"):
            raise ValueError("thermal_scheme must be upwind or muscl")
        if self.return_temperature_c is not None:
            finite("return_temperature_c", self.return_temperature_c, -273.15, strict=True)
        fraction("cfl", self.cfl, positive=True)
        if self.cfl > 0.5:
            raise ValueError("cfl must be <= 0.5 for the explicit coupled update")
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("max_steps must be a positive integer")


@dataclass(frozen=True)
class CFDCase:
    grid: CFDGrid
    settings: CFDSettings
    sources: tuple[CFDSource, ...] = ()

    def __post_init__(self) -> None:
        width = self.settings.return_width_m or self.grid.width_m
        height = self.settings.return_height_m or self.grid.height_m
        if (
            self.settings.return_y_m + width > self.grid.width_m + 1e-10
            or self.settings.return_z_m + height > self.grid.height_m + 1e-10
        ):
            raise ValueError("return opening exceeds room boundaries")
        if self.settings.inlet_height_m > self.grid.height_m:
            raise ValueError("inlet height exceeds room height")
        if len({s.name for s in self.sources}) != len(self.sources):
            raise ValueError("CFD source names must be unique")
        for source in self.sources:
            for start, size, limit in zip(
                (source.x_m, source.y_m, source.z_m),
                (source.width_m, source.depth_m, source.height_m),
                (self.grid.length_m, self.grid.width_m, self.grid.height_m),
                strict=True,
            ):
                if start >= limit or start + size > limit + 1e-10:
                    raise ValueError(f"source {source.name} exceeds room boundaries")
        for i, a in enumerate(self.sources):
            for b in self.sources[i + 1 :]:
                if (
                    min(a.x_m + a.width_m, b.x_m + b.width_m) > max(a.x_m, b.x_m)
                    and min(a.y_m + a.depth_m, b.y_m + b.depth_m) > max(a.y_m, b.y_m)
                    and min(a.z_m + a.height_m, b.z_m + b.height_m) > max(a.z_m, b.z_m)
                ):
                    raise ValueError("CFD rack envelopes must not overlap")
