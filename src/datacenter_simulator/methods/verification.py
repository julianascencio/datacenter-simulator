"""Explicit numerical convergence and held-out measurement comparisons."""

from typing import Any

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

from datacenter_simulator.methods.cfd import CFDResult, cell_coordinates


def richardson_gci(values: list[float], spacings: list[float]) -> dict[str, Any]:
    """Three equal-ratio levels in coarse-to-fine order; absolute error units.

    Reject oscillation, divergence and degenerate differences instead of reporting
    a misleading accuracy percentage. GCI is a discretization estimate only.
    Inputs must describe the same observable, physical case and comparison time.
    """
    v, h = np.asarray(values, dtype=float), np.asarray(spacings, dtype=float)
    if v.shape != (3,) or h.shape != (3,) or not np.isfinite([v, h]).all():
        raise ValueError("provide three finite values and spacings, coarse to fine")
    if np.any(h <= 0) or not np.all(np.diff(h) < 0):
        raise ValueError("spacings must be positive and decrease")
    r = h[0] / h[1]
    if not np.isclose(r, h[1] / h[2], rtol=1e-6) or r < 1.1:
        raise ValueError("GCI requires a common refinement ratio >= 1.1")
    a, b = v[0] - v[1], v[1] - v[2]
    result: dict[str, Any] = {"eligible": False, "refinement_ratio": float(r)}
    if abs(a) < 1e-12 or abs(b) < 1e-12:
        return {**result, "reason": "degenerate differences; order cannot be estimated"}
    if a * b <= 0:
        return {**result, "reason": "oscillatory convergence"}
    order = float(np.log(abs(a / b)) / np.log(r))
    if not 0.25 <= order <= 4:
        return {**result, "reason": "order outside credible screening range", "order": order}
    correction = float((v[2] - v[1]) / (r**order - 1))
    return {
        **result,
        "eligible": True,
        "order": order,
        "extrapolated": float(v[2] + correction),
        "fine_gci_absolute": 1.25 * abs(correction),
        "safety_factor": 1.25,
        "reason": "conditional discretization estimate; not physical validation",
    }


def measurement_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Signed bias is prediction minus observation; arrays must match exactly."""
    a, b = np.asarray(observed, dtype=float), np.asarray(predicted, dtype=float)
    if a.ndim != 1 or a.shape != b.shape or not a.size or not np.isfinite([a, b]).all():
        raise ValueError("measurement arrays must be matching nonempty finite vectors")
    error = b - a
    return {
        "n": int(a.size),
        "bias": float(np.mean(error)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "max_absolute_error": float(np.max(np.abs(error))),
    }


def validate_temperature_probes(
    result: CFDResult, observations: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Interpolate saved fields to independent probe positions and times.

    Requires time_s, x_m, y_m, z_m, observed_c. Extrapolation is rejected,
    including outside the cell-centre envelope. Save sufficiently frequent frames.
    This comparison does not calibrate inputs or claim experimental validation
    without independently acquired observations and documented uncertainty.
    """
    columns = ["time_s", "x_m", "y_m", "z_m", "observed_c"]
    if not set(columns).issubset(observations.columns) or observations.empty:
        raise ValueError("probe observations require " + ", ".join(columns))
    if not np.isfinite(observations[columns].to_numpy(dtype=float)).all():
        raise ValueError("probe observations must be finite")
    times = np.array([f.time_s for f in result.snapshots])
    fields = np.stack([f.temperature_c for f in result.snapshots])
    interpolate = RegularGridInterpolator(
        (times, *cell_coordinates(result.case.grid)), fields, bounds_error=True
    )
    predicted = interpolate(observations[columns[:4]].to_numpy(dtype=float))
    table = observations.copy()
    table["predicted_c"] = predicted
    table["error_c"] = predicted - table.observed_c
    if "standard_uncertainty_c" in table:
        sigma = table.standard_uncertainty_c.to_numpy(dtype=float)
        if not np.isfinite(sigma).all() or np.any(sigma <= 0):
            raise ValueError("standard_uncertainty_c must be finite and positive")
        table["residual_over_measurement_sigma"] = table.error_c / sigma
    return table, measurement_metrics(table.observed_c.to_numpy(), predicted)
