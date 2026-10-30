"""Align measured or simulated generation at the common facility electrical bus."""

from pathlib import Path

import numpy as np
import pandas as pd

from datacenter_simulator.models.devices import fraction


def validate_timeline(index: pd.DatetimeIndex) -> None:
    if len(index) == 0 or index.tz is None or index.hasnans:
        raise ValueError("timestamps must be non-empty, valid and timezone-aware")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and increasing")


def generation_from_series(
    power: pd.Series,
    timeline: pd.DatetimeIndex,
    *,
    unit: str = "kW",
    conversion_efficiency: float = 1,
) -> pd.Series:
    """Convert W/kW/MW and require exact timestamp alignment; never fill missing power.

    Inputs are interval-average available electrical power before an optional converter.
    Use this boundary for pvlib, orbitalpv, x2power or measured-meter outputs, after
    explicitly resampling to matching intervals. No package-specific API is assumed.
    """
    validate_timeline(timeline)
    if not isinstance(power.index, pd.DatetimeIndex):
        raise ValueError("power requires a DatetimeIndex")
    validate_timeline(power.index)
    fraction("conversion_efficiency", conversion_efficiency, positive=True)
    scale = {"W": 0.001, "kW": 1, "MW": 1000}
    if unit not in scale:
        raise ValueError("unit must be W, kW or MW")
    converted = power.copy()
    converted.index = power.index.tz_convert(timeline.tz)
    if not converted.index.equals(timeline):
        raise ValueError("generation timestamps must exactly match the simulation timeline")
    values = converted.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("generation must contain finite non-negative values")
    return pd.Series(values * scale[unit] * conversion_efficiency, index=timeline, name=power.name)


def generation_from_csv(
    path: str | Path,
    timeline: pd.DatetimeIndex,
    *,
    time_column: str = "timestamp",
    power_column: str = "power_kw",
    unit: str = "kW",
    conversion_efficiency: float = 1,
) -> pd.Series:
    """Read timestamps with explicit timezone offsets and interval-average power."""
    frame = pd.read_csv(path)
    timestamps = [pd.Timestamp(value) for value in frame[time_column]]
    if any(stamp.tzinfo is None for stamp in timestamps):
        raise ValueError("CSV timestamps must include a timezone offset")
    series = pd.Series(
        frame[power_column].to_numpy(),
        index=pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True)),
        name=power_column,
    )
    return generation_from_series(
        series, timeline, unit=unit, conversion_efficiency=conversion_efficiency
    )
