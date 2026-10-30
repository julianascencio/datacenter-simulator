"""Electrothermal feeder sizing and explicit route lengths for early design studies."""

from dataclasses import asdict, dataclass
from itertools import product
from math import dist, sqrt
from typing import Any

import pandas as pd
from scipy.optimize import brentq

from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.performance import ConverterMap


@dataclass(frozen=True)
class Route:
    """One-way centreline in metres; the electrical model adds the return conductor."""

    id: str
    points_m: tuple[tuple[float, float, float], ...]

    def __post_init__(self) -> None:
        if not self.id or len(self.points_m) < 2:
            raise ValueError("route needs an id and at least two points")
        for point in self.points_m:
            if len(point) != 3:
                raise ValueError("route points must have three coordinates")
            for value in point:
                finite("route coordinate", value, -1e9)
        if self.length_m <= 0:
            raise ValueError("route length must be positive")

    @property
    def length_m(self) -> float:
        return sum(dist(a, b) for a, b in zip(self.points_m[:-1], self.points_m[1:], strict=True))


@dataclass(frozen=True)
class Feeder:
    """Two-wire copper feeder with aggregate loop thermal resistance.

    thermal_resistance_k_w relates total loop I²R heat to conductor temperature.
    Ampacity and installation derating are supplied, never inferred from a standard.
    """

    length_m: float
    area_mm2: float
    ampacity_a: float
    thermal_resistance_k_w: float
    maximum_temperature_c: float = 90
    installation_derating: float = 1

    def __post_init__(self) -> None:
        for name in ("length_m", "area_mm2", "ampacity_a", "thermal_resistance_k_w"):
            finite(name, getattr(self, name), strict=True)
        finite("maximum_temperature_c", self.maximum_temperature_c, -50)
        fraction("installation_derating", self.installation_derating, positive=True)

    def resistance_ohm(self, temperature_c: float) -> float:
        finite("temperature_c", temperature_c, -100)
        return 2 * 0.01724 * self.length_m / self.area_mm2 * (1 + 0.00393 * (temperature_c - 20))


@dataclass(frozen=True)
class FeederResult:
    current_a: float
    receiving_voltage_v: float
    temperature_c: float
    cable_loss_kw: float
    converter_loss_kw: float
    source_kw: float
    copper_kg: float
    feasible: bool
    warnings: tuple[str, ...]


def solve_feeder(
    feeder: Feeder,
    source_voltage_v: float,
    terminal_kw: float,
    *,
    ambient_c: float = 30,
    minimum_voltage_pu: float = 0.9,
    converter: ConverterMap | None = None,
    converter_temperature_c: float = 25,
) -> FeederResult:
    """High-voltage constant-power solution with a self-consistent cable temperature.

    Search for the first stable thermal equilibrium up to 250°C. Thermal runaway
    and voltage collapse raise ValueError; overloads at an equilibrium are flags.
    """
    finite("source_voltage_v", source_voltage_v, strict=True)
    finite("terminal_kw", terminal_kw)
    finite("ambient_c", ambient_c, -50)
    if ambient_c >= 200:
        raise ValueError("ambient outside feeder study range")
    fraction("minimum_voltage_pu", minimum_voltage_pu, positive=True)
    received_kw = (
        terminal_kw
        if converter is None
        else converter.input_kw(terminal_kw, converter_temperature_c)
    )

    def operating(t: float) -> tuple[float, float, float]:
        resistance = feeder.resistance_ohm(t)
        discriminant = source_voltage_v**2 - 4 * resistance * received_kw * 1000
        if discriminant <= 0:
            raise ValueError("feeder voltage collapse")
        voltage = (source_voltage_v + sqrt(discriminant)) / 2
        current = received_kw * 1000 / voltage
        return voltage, current, current**2 * resistance

    def balance(t: float) -> float:
        return t - ambient_c - operating(t)[2] * feeder.thermal_resistance_k_w

    temperature = ambient_c
    if received_kw:
        lower = ambient_c
        # First crossing selects the stable branch; do not accept a hot unstable root.
        for upper in range(int(ambient_c) + 1, 251):
            if balance(float(upper)) >= 0:
                temperature = float(brentq(balance, lower, float(upper), xtol=1e-10))
                break
            lower = float(upper)
        else:
            raise ValueError("no stable cable equilibrium below 250°C")
    voltage, current, loss_w = operating(temperature)
    warnings = []
    if current > feeder.ampacity_a * feeder.installation_derating:
        warnings.append("ampacity")
    if temperature > feeder.maximum_temperature_c:
        warnings.append("temperature")
    if voltage < source_voltage_v * minimum_voltage_pu:
        warnings.append("undervoltage")
    return FeederResult(
        current,
        voltage,
        temperature,
        loss_w / 1000,
        received_kw - terminal_kw,
        received_kw + loss_w / 1000,
        2 * feeder.length_m * feeder.area_mm2 * 1e-6 * 8960,
        not warnings,
        tuple(warnings),
    )


def feeder_sweep(
    voltages_v: list[float],
    feeders: list[Feeder],
    terminal_kw: float,
    *,
    ambient_c: float = 30,
    converter: ConverterMap | None = None,
) -> pd.DataFrame:
    """Retain failed candidates as infeasible rows instead of hiding design limits."""
    if not voltages_v or not feeders:
        raise ValueError("sweep needs voltages and feeders")
    rows = []
    for voltage, feeder in product(voltages_v, feeders):
        row: dict[str, Any] = {
            "voltage_v": voltage,
            "area_mm2": feeder.area_mm2,
            "length_m": feeder.length_m,
        }
        try:
            row.update(
                asdict(
                    solve_feeder(
                        feeder, voltage, terminal_kw, ambient_c=ambient_c, converter=converter
                    )
                )
            )
        except ValueError as error:
            row.update(feasible=False, warnings=(str(error),))
        rows.append(row)
    return pd.DataFrame(rows)
