"""Reproducible Spain screening inputs; only the PV profile is source-derived."""

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.edi_bess import load_edi_solar_snapshot
from datacenter_simulator.methods.energy import Battery


def spain_bess_inputs() -> tuple[pd.DataFrame, Battery]:
    """A synthetic 2.5–4 MW AC facility with 6 MWp PV and 3 MW / 6 MWh BESS.

    Demand includes cooling/auxiliaries; do not multiply by PUE again. June
    Madrid civil hours drive the hypothetical price/load pattern. PVGIS dates
    remain 2023; the price is NOT a 2023 or 2026 market observation.
    """
    solar, _ = load_edi_solar_snapshot(dc_rating_kwp=6000)
    local_hour = pd.DatetimeIndex(solar.index).tz_convert("Europe/Madrid").hour.to_numpy()
    peak = (local_hour >= 18) & (local_hour < 22)
    load = 2500 + 1500 * peak.astype(float)
    price = np.where(peak, 0.22, np.where((local_hour >= 11) & (local_hour < 16), 0.06, 0.12))
    frame = pd.DataFrame(
        {"demand_kw": load, "solar_kw": solar, "import_eur_per_kwh": price, "critical_kw": 1500.0},
        index=solar.index,
    )
    return frame, Battery(6000, 3000, 3000, initial_soc=0.8)
