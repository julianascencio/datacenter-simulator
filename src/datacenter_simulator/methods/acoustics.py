"""Frequency-resolved acoustic energy propagation with explicit model limits."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.special import logsumexp

from datacenter_simulator.methods.cfd import cell_coordinates
from datacenter_simulator.methods.verification import measurement_metrics
from datacenter_simulator.models.acoustics import (
    A_WEIGHT_DB,
    EXACT_OCTAVE_HZ,
    OCTAVE_HZ,
    AcousticCase,
    AcousticSettings,
)

Array = NDArray[np.float64]


def sum_decibels(levels: Array, axis: int = -1) -> Array:
    """Sum incoherent energies; -infinity denotes a physically silent term."""
    a = np.asarray(levels, dtype=float)
    if np.isnan(a).any() or np.isposinf(a).any():
        raise ValueError("decibels cannot contain NaN or positive infinity")
    # Log-space summation avoids overflow and preserves exact silence.
    return np.asarray(logsumexp(a * np.log(10) / 10, axis=axis) * 10 / np.log(10))


def atmospheric_attenuation(settings: AcousticSettings) -> Array:
    """ISO 9613-1 equations, evaluated at octave centre frequencies, dB/m.

    Humidity is percent (50 means 50%), and h is water-vapour molar percent.
    This is a band-centre approximation, not the broadband integration annex.
    """
    if not settings.atmospheric_absorption:
        return np.zeros(8)
    t = settings.temperature_c + 273.15
    ratio = t / 293.15
    pressure = settings.pressure_kpa / 101.325
    saturation = 10 ** (-6.8346 * (273.16 / t) ** 1.261 + 4.6151)
    h = settings.relative_humidity_percent * saturation / pressure
    oxygen = pressure * (24 + 40400 * h * (0.02 + h) / (0.391 + h))
    nitrogen = pressure * ratio**-0.5 * (9 + 280 * h * np.exp(-4.17 * (ratio ** (-1 / 3) - 1)))
    f = np.asarray(EXACT_OCTAVE_HZ, dtype=float)
    return np.asarray(
        8.686
        * f**2
        * (
            1.84e-11 * np.sqrt(ratio) / pressure
            + ratio**-2.5
            * (
                0.01275 * np.exp(-2239.1 / t) / (oxygen + f**2 / oxygen)
                + 0.1068 * np.exp(-3352 / t) / (nitrogen + f**2 / nitrogen)
            )
        )
    )


def room_acoustics(case: AcousticCase) -> pd.DataFrame:
    """Area-weighted room constant and Sabine RT60 with air absorption.

    These are diffuse-field estimates. Bands below the estimated Schroeder
    transition are flagged; standing-wave modes are not resolved.
    """
    g = case.grid
    areas = np.array(
        [g.width_m * g.height_m] * 2 + [g.length_m * g.height_m] * 2 + [g.length_m * g.width_m] * 2
    )
    area = float(areas.sum())
    absorption = areas @ np.asarray(case.settings.surface_absorption)
    mean = absorption / area
    volume = g.length_m * g.width_m * g.height_m
    air_area = 4 * atmospheric_attenuation(case.settings) / (10 / np.log(10)) * volume
    constant = absorption / (1 - mean) + air_area
    c = np.sqrt(1.4 * 287.05 * (case.settings.temperature_c + 273.15))
    rt60 = 24 * np.log(10) * volume / (c * (absorption + air_area))
    eyring = 24 * np.log(10) * volume / (c * (-area * np.log1p(-mean) + air_area))
    schroeder = 2000 * np.sqrt(eyring / volume)
    return pd.DataFrame(
        {
            "frequency_hz": OCTAVE_HZ,
            "mean_absorption": mean,
            "room_constant_m2": constant,
            "sabine_rt60_s": rt60,
            "eyring_rt60_s": eyring,
            "schroeder_hz": schroeder,
            "below_schroeder": np.asarray(OCTAVE_HZ) < schroeder,
        }
    )


def source_energy(case: AcousticCase, points: Array) -> tuple[Array, NDArray[np.bool_]]:
    """Return normalized mean-square pressure, shape (point, source, band).

    Normalization is (20 microPa)^2. Directivity multiplies only the direct
    path; room energy already includes total emitted source power. Near-field
    points are marked invalid, not clipped into misleading high SPL estimates.
    """
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("points must be finite Nx3 coordinates")
    bounds = np.array([case.grid.length_m, case.grid.width_m, case.grid.height_m])
    if np.any(points < 0) or np.any(points > bounds):
        raise ValueError("points outside the acoustic domain")
    attenuation = atmospheric_attenuation(case.settings)
    reverberant = np.zeros(8)
    if case.settings.mode == "room":
        reverberant = 4 / room_acoustics(case).room_constant_m2.to_numpy()
    t = case.settings.temperature_c + 273.15
    impedance = (case.settings.pressure_kpa * 1000 / (287.05 * t)) * np.sqrt(1.4 * 287.05 * t)
    reference_factor = impedance * 1e-12 / (20e-6) ** 2
    energy = np.zeros((len(points), len(case.sources), 8))
    valid = np.ones(len(points), dtype=bool)
    for i, s in enumerate(case.sources):
        distance = np.linalg.norm(points - (s.x_m, s.y_m, s.z_m), axis=1)
        valid &= distance > s.radius_m
        r = np.maximum(distance, s.radius_m)
        direct = (
            s.directivity_q / (4 * np.pi * r[:, None] ** 2) * 10 ** (-r[:, None] * attenuation / 10)
        )
        power = 10 ** ((np.asarray(s.sound_power_db) - s.insertion_loss_db) / 10) * s.duty_fraction
        energy[:, i, :] = reference_factor * power * (direct + reverberant)
    return energy, valid


def background_energy(settings: AcousticSettings) -> Array:
    return (
        np.zeros(8)
        if settings.background_db is None
        else 10 ** (np.asarray(settings.background_db) / 10)
    )


def levels_from_energy(energy: Array) -> Array:
    with np.errstate(divide="ignore"):
        return np.asarray(10 * np.log10(energy))


@dataclass
class AcousticResult:
    case: AcousticCase
    band_spl_db: Array
    laeq_dba: Array
    valid: NDArray[np.bool_]
    receivers: pd.DataFrame
    contributions: pd.DataFrame
    room: pd.DataFrame
    summary: dict[str, Any]


def simulate_noise(case: AcousticCase, *, samples: int = 2000, seed: int = 42) -> AcousticResult:
    """3D energy map and receiver uncertainty from declared Gaussian input errors.

    Sources are mutually incoherent. Duty fractions produce equivalent levels;
    no instantaneous waveforms or acoustic phase are calculated. Source errors
    are independent between sources but perfectly correlated across bands.
    Propagation uncertainty is common to all sources/receivers in each draw.
    Background is held fixed; model-form uncertainty is not quantified here.
    """
    if type(samples) is not int or not 100 <= samples <= 100000:
        raise ValueError("samples must be an integer between 100 and 100000")
    coords = np.meshgrid(*cell_coordinates(case.grid), indexing="ij")
    points = np.column_stack([v.ravel() for v in coords])
    bands = np.empty((len(points), 8))
    valid = np.ones(len(points), dtype=bool)
    background = background_energy(case.settings)
    for start in range(0, len(points), 1024):
        energy, mask = source_energy(case, points[start : start + 1024])
        bands[start : start + 1024] = levels_from_energy(energy.sum(axis=1) + background)
        valid[start : start + 1024] = mask
    bands[~valid] = np.nan
    if not valid.any():
        raise ValueError("no map cells outside excluded source near fields")
    weighted = np.full(len(points), np.nan)
    weighted[valid] = sum_decibels(bands[valid] + np.asarray(A_WEIGHT_DB))
    receiver_points = np.array([(r.x_m, r.y_m, r.z_m) for r in case.receivers])
    contributions, _ = source_energy(case, receiver_points)
    receiver_bands = levels_from_energy(contributions.sum(axis=1) + background)
    receiver_a = sum_decibels(receiver_bands + np.asarray(A_WEIGHT_DB))
    rng = np.random.default_rng(seed)
    source_errors = rng.normal(size=(samples, len(case.sources))) * np.array(
        [s.standard_uncertainty_db for s in case.sources]
    )
    common = rng.normal(size=(samples, 1)) * case.settings.propagation_standard_uncertainty_db
    gains = 10 ** ((source_errors + common) / 10)
    a_weight = 10 ** (np.asarray(A_WEIGHT_DB) / 10)
    source_a = contributions @ a_weight
    draws = levels_from_energy(gains @ source_a.T + float(background @ a_weight))
    quantiles = np.quantile(draws, [0.025, 0.5, 0.975], axis=0)
    rows, source_rows = [], []
    for i, receiver in enumerate(case.receivers):
        row = {
            "receiver": receiver.name,
            "laeq_dba": float(receiver_a[i]),
            "input_p025_dba": float(quantiles[0, i]),
            "input_p50_dba": float(quantiles[1, i]),
            "input_p975_dba": float(quantiles[2, i]),
        }
        row.update({f"lp_{f}_hz_db": float(receiver_bands[i, j]) for j, f in enumerate(OCTAVE_HZ)})
        if case.settings.criterion_dba is not None:
            row["margin_to_target_db"] = case.settings.criterion_dba - receiver_a[i]
            row["input_probability_above_target"] = float(
                np.mean(draws[:, i] > case.settings.criterion_dba)
            )
        rows.append(row)
        total = float(source_a[i].sum() + background @ a_weight)
        for j, source in enumerate(case.sources):
            source_rows.append(
                {
                    "receiver": receiver.name,
                    "source": source.name,
                    "laeq_contribution_dba": float(levels_from_energy(source_a[i, j])),
                    "energy_fraction": float(source_a[i, j] / total) if total else 0,
                }
            )
    warnings = [
        "Energy propagation model: no phase, diffraction, shielding, "
        "wall transmission or structural vibration.",
        "Input uncertainty intervals are conditional; they do not establish prediction accuracy.",
        "Source spectra and surface absorption require measured/manufacturer data.",
        "Source near fields are excluded; "
        "a point-source assumption remains outside the chosen radius.",
    ]
    room = room_acoustics(case)
    if case.settings.mode == "room":
        warnings.append(
            "Diffuse reverberation assumption; low-frequency room modes are not resolved."
        )
    summary = {
        "model": "octave-band incoherent sound-energy propagation",
        "mode": case.settings.mode,
        "valid_cells": int(valid.sum()),
        "excluded_cells": int((~valid).sum()),
        "peak_valid_cell_dba": float(np.max(weighted[valid])),
        "uncertainty_samples": samples,
        "random_seed": seed,
        "measured_validation": False,
        "warnings": warnings,
    }
    return AcousticResult(
        case,
        bands.reshape((*case.grid.shape, 8)),
        weighted.reshape(case.grid.shape),
        valid.reshape(case.grid.shape),
        pd.DataFrame(rows),
        pd.DataFrame(source_rows),
        room,
        summary,
    )


def validate_noise_receivers(
    result: AcousticResult, observations: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compare independent measured LAeq at named receivers and matched operation."""
    if not {"receiver", "observed_dba"}.issubset(observations) or observations.empty:
        raise ValueError("observations require receiver and observed_dba")
    if observations.receiver.duplicated().any():
        raise ValueError("one matched observation per receiver is required")
    table = observations.merge(
        result.receivers[["receiver", "laeq_dba"]], on="receiver", how="left", validate="one_to_one"
    )
    if table.laeq_dba.isna().any():
        raise ValueError("unknown receiver in measurements")
    metrics = measurement_metrics(table.observed_dba.to_numpy(), table.laeq_dba.to_numpy())
    table["error_db"] = table.laeq_dba - table.observed_dba
    return table, metrics
