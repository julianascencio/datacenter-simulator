"""Weather-driven heat rejection, water accounting and useful heat recovery."""

from dataclasses import asdict, dataclass
from math import exp, log
from typing import Literal

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import brentq

from datacenter_simulator.models.devices import finite, fraction


def saturation_pressure_pa(temperature_c: float) -> float:
    """Magnus liquid-water approximation; engineering study range -30 to 60°C."""
    finite("temperature_c", temperature_c, -30)
    if temperature_c > 60:
        raise ValueError("psychrometric temperature exceeds 60°C")
    return 610.94 * exp(17.625 * temperature_c / (temperature_c + 243.04))


def dewpoint_c(temperature_c: float, relative_humidity: float) -> float:
    fraction("relative_humidity", relative_humidity, positive=True)
    saturation_pressure_pa(temperature_c)
    alpha = log(relative_humidity) + 17.625 * temperature_c / (243.04 + temperature_c)
    return 243.04 * alpha / (17.625 - alpha)


def wetbulb_c(temperature_c: float, relative_humidity: float, pressure_pa: float = 101325) -> float:
    """Adiabatic-saturation energy balance, including liquid-water enthalpy.

    Humidity ratio in kg/kg dry air, enthalpy in kJ/kg dry air. Liquid-water
    approximation below freezing; use a specialist psychrometric model for icing.
    """
    fraction("relative_humidity", relative_humidity, positive=True)
    finite("pressure_pa", pressure_pa, 30000, strict=True)
    vapor = relative_humidity * saturation_pressure_pa(temperature_c)
    if pressure_pa <= saturation_pressure_pa(temperature_c):
        raise ValueError("ambient pressure must exceed saturation pressure")
    humidity = 0.62198 * vapor / (pressure_pa - vapor)
    enthalpy = 1.006 * temperature_c + humidity * (2501 + 1.86 * temperature_c)

    def balance(t: float) -> float:
        # The root can be colder than the validated outdoor dry-bulb range.
        # Extend the same liquid-water approximation only inside this bracket.
        sat = 610.94 * exp(17.625 * t / (t + 243.04))
        saturated_humidity = 0.62198 * sat / (pressure_pa - sat)
        return (
            1.006 * t
            + saturated_humidity * (2501 + 1.86 * t)
            - (saturated_humidity - humidity) * 4.186 * t
            - enthalpy
        )

    return float(
        brentq(balance, max(-80, dewpoint_c(temperature_c, relative_humidity)), temperature_c)
    )


@dataclass(frozen=True)
class ChillerMap:
    """COP at heat-rejection temperatures and part loads; bounded interpolation."""

    sink_temperatures_c: tuple[float, ...] = (-10, 10, 25, 40, 55)
    load_fractions: tuple[float, ...] = (0, 0.25, 0.5, 1)
    cop: tuple[tuple[float, ...], ...] = (
        (4, 5, 7, 6),
        (4, 5, 7, 6),
        (3, 4.5, 6, 5.5),
        (2, 3, 4, 3.5),
        (1.5, 2, 2.5, 2.2),
    )
    source: str = "Illustrative developer-selected COP surface; not manufacturer data"

    def __post_init__(self) -> None:
        t, f, c = map(np.asarray, (self.sink_temperatures_c, self.load_fractions, self.cop))
        if len(t) < 2 or len(f) < 2 or c.shape != (len(t), len(f)):
            raise ValueError("invalid chiller map shape")
        if not all(np.isfinite(a).all() for a in (t, f, c)) or np.any(c <= 0):
            raise ValueError("chiller map must be finite with positive COP")
        if np.any(np.diff(t) <= 0) or np.any(np.diff(f) <= 0) or f[0] != 0 or f[-1] != 1:
            raise ValueError("chiller axes must increase and part load must span 0 to 1")
        if not self.source:
            raise ValueError("chiller map needs provenance")

    def evaluate(self, sink_c: float, load_fraction: float) -> float:
        fraction("load_fraction", load_fraction)
        finite("sink_c", sink_c, self.sink_temperatures_c[0])
        interpolator = RegularGridInterpolator(
            (self.sink_temperatures_c, self.load_fractions), self.cop
        )
        return float(interpolator([[sink_c, load_fraction]])[0])


@dataclass(frozen=True)
class HeatRecovery:
    demand_kw: float = 0
    supply_c: float = 45
    approach_k: float = 5
    heat_pump_cop: float | None = None

    def __post_init__(self) -> None:
        finite("demand_kw", self.demand_kw)
        finite("supply_c", self.supply_c, -20)
        finite("approach_k", self.approach_k)
        if self.heat_pump_cop is not None:
            finite("heat_pump_cop", self.heat_pump_cop, 1, strict=True)


DEFAULT_CHILLER = ChillerMap()
DEFAULT_RECOVERY = HeatRecovery()


@dataclass(frozen=True)
class WeatherCoolingResult:
    electric_kw: float
    compressor_kw: float
    auxiliary_kw: float
    heat_pump_kw: float
    heat_removed_kw: float
    unmet_heat_kw: float
    useful_heat_kw: float
    recovered_source_heat_kw: float
    rejected_heat_kw: float
    evaporation_l_h: float
    drift_l_h: float
    blowdown_l_h: float
    makeup_l_h: float
    wetbulb_c: float
    supply_c: float
    economizer: bool
    wet_mode: bool
    condensation_margin_k: float


def evaluate_weather_cooling(
    heat_kw: float,
    ambient_c: float,
    relative_humidity: float,
    *,
    mode: Literal["dry", "evaporative", "hybrid"] = "dry",
    capacity_kw: float = 500,
    supply_c: float = 30,
    return_c: float = 45,
    approach_k: float = 5,
    indoor_c: float = 24,
    indoor_rh: float = 0.5,
    dewpoint_margin_k: float = 2,
    cycles_of_concentration: float = 4,
    drift_fraction: float = 0.00002,
    circulation_l_s: float = 20,
    pressure_pa: float = 101325,
    chiller: ChillerMap = DEFAULT_CHILLER,
    recovery: HeatRecovery = DEFAULT_RECOVERY,
) -> WeatherCoolingResult:
    """Steady-state plant comparison with explicit direct/heat-pump recovery.

    Heat is recovered before heat rejection; heat-pump electricity is charged to
    facility demand. Indoor dewpoint controls condensation margin. Tower water
    includes evaporation + drift + nonnegative blowdown, never circulation flow.
    """
    finite("heat_kw", heat_kw)
    finite("capacity_kw", capacity_kw, strict=True)
    finite("approach_k", approach_k)
    finite("supply_c", supply_c, -20)
    finite("return_c", return_c, supply_c, strict=True)
    finite("cycles_of_concentration", cycles_of_concentration, 1, strict=True)
    fraction("drift_fraction", drift_fraction)
    finite("circulation_l_s", circulation_l_s)
    finite("dewpoint_margin_k", dewpoint_margin_k)
    if mode not in {"dry", "evaporative", "hybrid"}:
        raise ValueError("unknown heat rejection mode")
    wet = wetbulb_c(ambient_c, relative_humidity, pressure_pa)
    dew = dewpoint_c(indoor_c, indoor_rh)
    supply = max(supply_c, dew + dewpoint_margin_k)
    if supply >= return_c:
        raise ValueError("condensation-safe supply must remain below return temperature")
    useful = heat_pump = recovered = 0.0
    if return_c >= recovery.supply_c + recovery.approach_k:
        useful = recovered = min(heat_kw, recovery.demand_kw)
    elif recovery.heat_pump_cop is not None:
        cop = recovery.heat_pump_cop
        useful = min(recovery.demand_kw, heat_kw / (1 - 1 / cop))
        heat_pump = useful / cop
        recovered = useful - heat_pump
    remaining = heat_kw - recovered
    removed = min(remaining, capacity_kw)
    wet_mode = mode == "evaporative" or (mode == "hybrid" and ambient_c + approach_k > supply)
    sink = wet if wet_mode else ambient_c
    free = sink + approach_k <= supply
    compressor = (
        0.0 if free or removed == 0 else removed / chiller.evaluate(sink, removed / capacity_kw)
    )
    auxiliary = (
        0.0 if removed == 0 else capacity_kw * 0.025 * (0.15 + 0.85 * (removed / capacity_kw) ** 3)
    )
    rejected = removed + compressor + auxiliary
    # Evaporation-only latent rejection is an explicit wet-tower approximation.
    evaporation = rejected / 2450 * 3600 if wet_mode and removed else 0.0
    drift = circulation_l_s * 3600 * drift_fraction if wet_mode and removed else 0.0
    blowdown = max(0, evaporation / (cycles_of_concentration - 1) - drift)
    return WeatherCoolingResult(
        compressor + auxiliary + heat_pump,
        compressor,
        auxiliary,
        heat_pump,
        removed + recovered,
        remaining - removed,
        useful,
        recovered,
        rejected,
        evaporation,
        drift,
        blowdown,
        evaporation + drift + blowdown,
        wet,
        supply,
        free and removed > 0,
        wet_mode and removed > 0,
        supply - dew,
    )


def cooling_year(
    weather: pd.DataFrame,
    it_kw: float,
    *,
    mode: Literal["dry", "evaporative", "hybrid"] = "dry",
    recovery_demand_kw: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Hourly comparison at a declared boundary: IT plus plant electricity only."""
    from datacenter_simulator.connectors.weather import validate_weather

    validate_weather(weather)
    finite("it_kw", it_kw, strict=True)
    if mode not in {"dry", "evaporative", "hybrid"}:
        raise ValueError("unknown mode")
    if recovery_demand_kw is not None and not recovery_demand_kw.index.equals(weather.index):
        raise ValueError("heat demand index must match weather exactly")
    rows = []
    samples = weather[["ambient_c", "relative_humidity", "pressure_pa"]].to_numpy(dtype=float)
    for position, sample in enumerate(samples):
        demand = 0.0 if recovery_demand_kw is None else float(recovery_demand_kw.iloc[position])
        result = evaluate_weather_cooling(
            it_kw,
            float(sample[0]),
            float(sample[1]),
            mode=mode,
            pressure_pa=float(sample[2]),
            recovery=HeatRecovery(demand, supply_c=40),
        )
        rows.append(asdict(result))
    frame = pd.DataFrame(rows, index=weather.index)
    facility = it_kw * len(frame) + float(frame.electric_kw.sum())
    return frame, {
        "pue": facility / (it_kw * len(frame)),
        "facility_kwh": facility,
        "cooling_kwh": float(frame.electric_kw.sum()),
        "makeup_m3": float(frame.makeup_l_h.sum() / 1000),
        "wue_l_kwh": float(frame.makeup_l_h.sum() / (it_kw * len(frame))),
        "useful_heat_kwh": float(frame.useful_heat_kw.sum()),
        "economizer_hours": float(frame.economizer.sum()),
        "unmet_heat_kwh": float(frame.unmet_heat_kw.sum()),
        "peak_cooling_kw": float(frame.electric_kw.max()),
    }
