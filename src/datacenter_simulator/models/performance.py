"""Traceable power curves and bounded, load/temperature-dependent conversion maps."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class Provenance:
    """Evidence accompanies parameters; a citation alone is not calibration."""

    source: str
    configuration: str
    kind: Literal["measured", "calibrated", "illustrative"] = "illustrative"
    boundary: Literal["ac_input", "dc_terminal", "component"] = "dc_terminal"
    relative_uncertainty: float | None = None

    def __post_init__(self) -> None:
        if not self.source or not self.configuration:
            raise ValueError("source and equipment configuration are required")
        if self.kind not in {"measured", "calibrated", "illustrative"}:
            raise ValueError("unknown evidence kind")
        if self.boundary not in {"ac_input", "dc_terminal", "component"}:
            raise ValueError("unknown power boundary")
        if self.relative_uncertainty is not None:
            fraction("relative_uncertainty", self.relative_uncertainty)


@dataclass(frozen=True)
class PowerCurve:
    """Monotone piecewise-linear terminal power; interpolation never extrapolates."""

    utilization: tuple[float, ...]
    power_kw: tuple[float, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        x, y = np.asarray(self.utilization), np.asarray(self.power_kw)
        if len(x) < 2 or len(x) != len(y) or not np.isfinite(x).all():
            raise ValueError("curve requires equal finite arrays with at least two points")
        if x[0] != 0 or x[-1] != 1 or np.any(np.diff(x) <= 0):
            raise ValueError("utilization must strictly increase from 0 to 1")
        if not np.isfinite(y).all() or np.any(y < 0) or np.any(np.diff(y) < 0):
            raise ValueError("power must be finite, nonnegative and nondecreasing")

    def evaluate(self, utilization: float) -> float:
        fraction("utilization", utilization)
        return float(np.interp(utilization, self.utilization, self.power_kw))

    def utilization_at_power(self, power_kw: float) -> float:
        """Largest utilization under a power cap; below idle returns zero."""
        finite("power_kw", power_kw)
        if power_kw < self.power_kw[0]:
            return 0.0
        return float(np.interp(power_kw, self.power_kw, self.utilization))


@dataclass(frozen=True)
class ConverterMap:
    """Bilinear efficiency map, standby demand and explicit thermal derating.

    Efficiencies are indexed [temperature][output fraction]. Output rating is
    multiplied by the linearly interpolated derating factor. No extrapolation.
    Standby is additional input demand while enabled, including at zero output.
    """

    rated_kw: float
    fractions: tuple[float, ...]
    temperatures_c: tuple[float, ...]
    efficiencies: tuple[tuple[float, ...], ...]
    provenance: Provenance
    standby_kw: float = 0.0
    derating: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        finite("rated_kw", self.rated_kw, strict=True)
        finite("standby_kw", self.standby_kw)
        x, t, e = map(np.asarray, (self.fractions, self.temperatures_c, self.efficiencies))
        if len(x) < 2 or len(t) < 2 or e.shape != (len(t), len(x)):
            raise ValueError("efficiency map dimensions do not match axes")
        if not all(np.isfinite(a).all() for a in (x, t, e)):
            raise ValueError("map must be finite")
        if x[0] != 0 or x[-1] != 1 or np.any(np.diff(x) <= 0) or np.any(np.diff(t) <= 0):
            raise ValueError("axes must increase; fractions must span 0 to 1")
        if np.any(e <= 0) or np.any(e > 1):
            raise ValueError("efficiency must be in (0, 1]")
        if self.derating is not None:
            d = np.asarray(self.derating)
            if d.shape != t.shape or not np.isfinite(d).all() or np.any((d < 0) | (d > 1)):
                raise ValueError("derating needs one fraction per temperature")

    def capacity_kw(self, temperature_c: float) -> float:
        finite("temperature_c", temperature_c, self.temperatures_c[0])
        if temperature_c > self.temperatures_c[-1]:
            raise ValueError("temperature outside converter map")
        factor = (
            1
            if self.derating is None
            else np.interp(temperature_c, self.temperatures_c, self.derating)
        )
        return float(self.rated_kw * factor)

    def input_kw(self, output_kw: float, temperature_c: float = 25) -> float:
        finite("output_kw", output_kw)
        if output_kw > self.capacity_kw(temperature_c) + 1e-9:
            raise ValueError("converter output exceeds temperature-derated capacity")
        interpolator = RegularGridInterpolator(
            (self.temperatures_c, self.fractions), self.efficiencies, bounds_error=True
        )
        efficiency = float(interpolator([[temperature_c, output_kw / self.rated_kw]])[0])
        return output_kw / efficiency + self.standby_kw


def calibration_errors(curve: PowerCurve, samples: list[tuple[float, float]]) -> dict[str, float]:
    """Score independently held-out (utilization, kW) samples at the same boundary."""
    if not samples:
        raise ValueError("held-out samples must not be empty")
    for _, power in samples:
        finite("measured power", power)
    errors = np.asarray([curve.evaluate(u) - p for u, p in samples])
    return {
        "mae_kw": float(np.abs(errors).mean()),
        "rmse_kw": float(np.sqrt(np.mean(errors**2))),
        "bias_kw": float(errors.mean()),
        "n": float(len(samples)),
    }
