"""Reproducible Faraday-inspired profiles; no operational telemetry is implied."""

import numpy as np
import pandas as pd

from datacenter_simulator.models.utility_storage import FaradayInputs


def faraday_profiles(inputs: FaradayInputs | None = None) -> pd.DataFrame:
    """Hourly synthetic AC solar and constant IT x PUE demand, beginning after COD.

    The sine daylight envelope and repeating cloud multipliers are educational
    inputs, not Utah irradiance measurements, pvlib results, or a TMY forecast.
    Use America/Denver for local daylight; timestamps remain unambiguous at DST.
    """
    p = inputs or FaradayInputs()
    index = pd.date_range("2026-09-19", periods=p.hours, freq="h", tz="America/Denver")
    day = index.day_of_year.to_numpy(dtype=float)
    hour = index.hour.to_numpy(dtype=float) + 0.5
    daylight = 12 + 3 * np.sin(2 * np.pi * (day - 80) / 365.25)
    # Noon is fixed at 12 local civil time: intentionally not a solar-position model.
    phase = (hour - (12 - daylight / 2)) / daylight
    envelope = np.where((phase > 0) & (phase < 1), np.sin(np.pi * phase), 0)
    cloud = np.array([0.90, 0.75, 0.95, 0.60, 0.85, 0.70, 1.0])[(day.astype(int) - 1) % 7]
    return pd.DataFrame(
        {
            "demand_kw": p.it_mw * p.pue * 1000,
            "solar_kw": p.solar_ac_peak_mw * 1000 * envelope * cloud,
        },
        index=index,
    ).rename_axis("timestamp")
