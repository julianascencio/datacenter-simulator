"""Deterministic synthetic year for an editable, offline power-supply screen."""

import numpy as np
import pandas as pd

from datacenter_simulator.models.speed_to_power import ComputeFleet


def synthetic_power_profiles(fleet: ComputeFleet | None = None) -> pd.DataFrame:
    """No geographic or measured-data claim; includes a five-day cloudy spell.

    Thermal overhead is an explicit 1.10-1.20 sinusoid, not the paper's
    climate-driven cooling selection. Existing weather/pvlib/cooling connectors
    can replace all three columns using ``profiles_from_components``.
    """
    fleet = fleet or ComputeFleet()
    time = pd.date_range("2025-01-01", periods=8760, freq="h", tz="UTC", name="timestamp")
    day = np.arange(8760) / 24
    hour = np.arange(8760) % 24
    season = 0.8 + 0.2 * np.sin(2 * np.pi * (day - 80) / 365)
    solar = 0.9 * season * np.maximum(0, np.sin(np.pi * (hour - 6) / 12))
    solar[(day >= 20) & (day < 25)] *= 0.35
    it = np.full(8760, fleet.average_it_kw)
    cooling = it * (0.15 + 0.05 * np.sin(2 * np.pi * (day - 80) / 365))
    return pd.DataFrame({"it_kw": it, "cooling_kw": cooling, "pv_dc_per_kwp": solar}, index=time)
