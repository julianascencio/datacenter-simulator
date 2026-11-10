"""Octave-band sound-power sources, receivers and declared acoustic assumptions."""

from dataclasses import dataclass

import numpy as np

from datacenter_simulator.models.cfd import CFDGrid
from datacenter_simulator.models.devices import finite, fraction

OCTAVE_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000)
EXACT_OCTAVE_HZ = tuple(1000 * 10 ** (0.3 * i) for i in range(-4, 4))
A_WEIGHT_DB = (-26.2, -16.1, -8.6, -3.2, 0.0, 1.2, 1.0, -1.1)


def spectrum(name: str, values: tuple[float, ...], low: float, high: float) -> None:
    if len(values) != 8 or not np.isfinite(values).all():
        raise ValueError(f"{name} requires eight finite octave bands, 63 to 8000 Hz")
    if any(not low <= v <= high for v in values):
        raise ValueError(f"{name} outside [{low}, {high}]")


@dataclass(frozen=True)
class AcousticSource:
    """Incoherent source; Lw is unweighted band power, dB re 1 pW, never Lp.

    The radius marks the excluded near field; its interior is not predicted.
    Insertion loss reduces emitted sound power in every direction, not a barrier.
    Standard uncertainty is a common source-level offset, correlated over bands.
    """

    name: str
    x_m: float
    y_m: float
    z_m: float
    sound_power_db: tuple[float, ...]
    radius_m: float = 0.5
    directivity_q: float = 1
    duty_fraction: float = 1
    insertion_loss_db: tuple[float, ...] = (0,) * 8
    standard_uncertainty_db: float = 2
    provenance: str = "illustrative; replace with measured or manufacturer octave-band Lw"

    def __post_init__(self) -> None:
        if not self.name or not self.provenance:
            raise ValueError("source name and provenance are required")
        for name in ("x_m", "y_m", "z_m", "standard_uncertainty_db"):
            finite(name, getattr(self, name))
        for name in ("radius_m", "directivity_q"):
            finite(name, getattr(self, name), strict=True)
        fraction("duty_fraction", self.duty_fraction)
        spectrum("sound_power_db", self.sound_power_db, -100, 200)
        spectrum("insertion_loss_db", self.insertion_loss_db, 0, 100)


@dataclass(frozen=True)
class AcousticReceiver:
    name: str
    x_m: float
    y_m: float
    z_m: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("receiver name is required")
        for name in ("x_m", "y_m", "z_m"):
            finite(name, getattr(self, name))


@dataclass(frozen=True)
class AcousticSettings:
    """Free-field or direct-plus-diffuse room energy model, not a wave solver.

    Absorption rows are x=0, x=L, y=0, y=W, floor, ceiling; each has eight bands.
    The criterion is an optional user planning target, not a legal limit.
    """

    mode: str = "room"
    temperature_c: float = 20
    relative_humidity_percent: float = 50
    pressure_kpa: float = 101.325
    atmospheric_absorption: bool = True
    surface_absorption: tuple[tuple[float, ...], ...] = ((0.2,) * 8,) * 6
    background_db: tuple[float, ...] | None = None
    criterion_dba: float | None = None
    propagation_standard_uncertainty_db: float = 2

    def __post_init__(self) -> None:
        if self.mode not in ("room", "free_field"):
            raise ValueError("acoustic mode must be room or free_field")
        if not np.isfinite(self.temperature_c) or not -20 <= self.temperature_c <= 50:
            raise ValueError("temperature_c must lie in [-20, 50]")
        if (
            not np.isfinite(self.relative_humidity_percent)
            or not 10 <= self.relative_humidity_percent <= 100
        ):
            raise ValueError("relative_humidity_percent must lie in [10, 100]")
        if not np.isfinite(self.pressure_kpa) or not 50 <= self.pressure_kpa <= 110:
            raise ValueError("pressure_kpa must lie in [50, 110]")
        finite("propagation_standard_uncertainty_db", self.propagation_standard_uncertainty_db)
        if len(self.surface_absorption) != 6:
            raise ValueError("provide absorption for six room surfaces")
        for row in self.surface_absorption:
            spectrum("surface_absorption", row, 0.001, 0.999)
        if self.background_db is not None:
            spectrum("background_db", self.background_db, -100, 160)
        if self.criterion_dba is not None:
            finite("criterion_dba", self.criterion_dba)


@dataclass(frozen=True)
class AcousticCase:
    grid: CFDGrid
    settings: AcousticSettings
    sources: tuple[AcousticSource, ...]
    receivers: tuple[AcousticReceiver, ...]

    def __post_init__(self) -> None:
        if not self.sources or len(self.sources) > 100:
            raise ValueError("provide between one and 100 noise sources")
        if (
            not any(s.duty_fraction > 0 for s in self.sources)
            and self.settings.background_db is None
        ):
            raise ValueError("a map requires an active source or a specified background")
        if not self.receivers:
            raise ValueError("at least one receiver is required")
        for items in (self.sources, self.receivers):
            if len({s.name for s in items}) != len(items):
                raise ValueError("source/receiver names must be unique within their group")
            for item in items:
                if any(
                    a > b
                    for a, b in zip(
                        (item.x_m, item.y_m, item.z_m),
                        (self.grid.length_m, self.grid.width_m, self.grid.height_m),
                        strict=True,
                    )
                ):
                    raise ValueError("acoustic source/receiver lies outside the domain")
        for receiver in self.receivers:
            for source in self.sources:
                r = np.linalg.norm(
                    np.array((receiver.x_m, receiver.y_m, receiver.z_m))
                    - np.array((source.x_m, source.y_m, source.z_m))
                )
                if r <= source.radius_m:
                    raise ValueError("receiver lies inside an excluded source near field")
