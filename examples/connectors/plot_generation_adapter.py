"""
Connect a generation model or CSV
=========================================

Step 1: define timezone-aware hourly demand intervals. Step 2: take electrical
power from a generation model. Step 3: convert units and apply an explicit
conversion loss. Step 4: simulate and compare grid demand.

The source below is deliberately synthetic. Replace it with interval-average
outputs from pvlib, x2power-simulator or a meter dataset. No external credentials
or live services are needed to reproduce this example.
"""

import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from datacenter_simulator import simulate
from datacenter_simulator.connectors import generation_from_csv, generation_from_series
from datacenter_simulator.use_cases import reference_center, reference_profiles

# Step 1: matching intervals.
profiles, synthetic = reference_profiles(hours=24)

# Step 2: source output before inverter, represented in watts.
source_w = synthetic["PV"] * 1000

# Step 3: either an in-memory Series or a CSV, with explicit units and efficiency.
pv = generation_from_series(source_w, profiles.index, unit="W", conversion_efficiency=0.97)
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "generation.csv"
    pd.DataFrame({"timestamp": profiles.index, "power_kw": synthetic["Biogas"]}).to_csv(
        path, index=False
    )
    biogas = generation_from_csv(path, profiles.index)

# Step 4: connect sources at the facility bus.
result = simulate(reference_center(), profiles, generation={"PV": pv, "Biogas": biogas})
print(result.summary)
fig, ax = plt.subplots(figsize=(9, 3.5), layout="constrained")
result.timeseries[["facility_kw", "generation_kw", "grid_import_kw"]].plot(ax=ax)
ax.set(ylabel="Electrical power [kW]", xlabel="Interval start [UTC]")
