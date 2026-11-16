"""Deterministic synthetic load shapes; none reconstructs the supplied post."""

from math import acos, tan

import numpy as np
import pandas as pd

from datacenter_simulator.models.devices import finite, fraction


def synthetic_ai_load(
    *, duration_s: float = 120, dt_s: float = 0.1, shape: str = "pulsed", power_factor: float = 0.98
) -> pd.DataFrame:
    """Aggregate receiving-PCC load including facility/UPS consumption.

    Balanced fixed lagging PF; no battery dispatch or separate UPS/transformer
    dynamics. ``sustained`` exposes the finite-duration smoothing limitation.
    Rows describe interval starts, including one full final interval.
    """
    finite("duration_s", duration_s, strict=True)
    finite("dt_s", dt_s, strict=True)
    fraction("power_factor", power_factor, positive=True)
    count = round(duration_s / dt_s)
    if count < 2 or not np.isclose(count * dt_s, duration_s, rtol=0, atol=1e-9):
        raise ValueError("duration must be an integer multiple of dt with >=2 intervals")
    t = np.arange(count) * dt_s
    if shape == "pulsed":
        p = 130 + 45 * np.sin(2 * np.pi * 0.4 * t) + 5 * np.sin(2 * np.pi * 0.07 * t)
    elif shape == "bursty":
        p = 130 + 40 * np.sin(2 * np.pi * 0.8 * t) * (0.6 + 0.4 * np.cos(2 * np.pi * 0.03 * t))
    elif shape == "sustained":
        p = np.where(t < duration_s / 4, 80.0, 180.0)
    else:
        raise ValueError("shape must be pulsed, bursty or sustained")
    return pd.DataFrame({"time_s": t, "load_mw": p, "load_mvar": p * tan(acos(power_factor))})
