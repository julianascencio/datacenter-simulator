"""
02. Connect generation from Series and CSV
==================================================

**Level:** Beginner | **Subject:** Generation data connectors

Connect interval-average PV and biogas electrical output, apply an explicit
unit/conversion boundary, then inspect grid imports. Prerequisite: basic pandas
Series and CSV familiarity. No external credentials or live sources are needed.

The source below is deliberately synthetic. Replace it with interval-average
outputs from pvlib, x2power-simulator or a meter dataset. This is a generic
Series/CSV boundary, not a package-specific API integration.
"""

import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from datacenter_simulator import simulate
from datacenter_simulator.connectors import generation_from_csv, generation_from_series
from datacenter_simulator.use_cases import reference_center, reference_profiles

# %%
# Step 1: define demand intervals and source units
# --------------------------------------------------------
# Every timestamp identifies an interval start. Power is the average over that
# interval. Both sources must cover exactly the same timezone-aware intervals.
profiles, synthetic = reference_profiles(hours=24)
source_w = synthetic["PV"] * 1000

# %%
# Step 2: adapt an in-memory Series
# -----------------------------------------
# The synthetic source is upstream of a 97% inverter. Convert watts to facility-
# bus kW and apply efficiency once. Use efficiency=1 for already converted power.
pv = generation_from_series(source_w, profiles.index, unit="W", conversion_efficiency=0.97)
fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
(source_w / 1000).plot(ax=ax, label="Source power before conversion")
pv.plot(ax=ax, label="Facility-bus power after conversion")
ax.set(xlabel="Interval start [UTC]", ylabel="PV power [kW]")
ax.legend()

# %%
# Step 3: adapt CSV data with explicit timezone offsets
# -------------------------------------------------------------
# The temporary file demonstrates the same interface used for a measured CSV.
# Biogas values here represent net electrical output at the facility boundary.
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "generation.csv"
    pd.DataFrame({"timestamp": profiles.index, "power_kw": synthetic["Biogas"]}).to_csv(
        path, index=False
    )
    biogas = generation_from_csv(path, profiles.index)

# %%
# Step 4: compare grid imports with and without generation
# ----------------------------------------------------------------
# Available generation above demand is curtailed here: there is no battery and
# export is disabled. Adding generation changes imports but not gross-demand PUE.
center = reference_center()
result = simulate(center, profiles, generation={"PV": pv, "Biogas": biogas})
baseline = simulate(center, profiles)
fig, ax = plt.subplots(figsize=(9, 3.5), layout="constrained")
result.timeseries[["facility_kw", "generation_kw", "grid_import_kw"]].plot(ax=ax)
ax.set(ylabel="Electrical power [kW]", xlabel="Interval start [UTC]")
print(
    f"Grid imports: {baseline.summary['grid_import_kwh']:.1f} → "
    f"{result.summary['grid_import_kwh']:.1f} kWh"
)
print("PUE with and without generation:", result.summary["pue"], baseline.summary["pue"])
assert np.isclose(result.summary["pue"], baseline.summary["pue"])

# %%
# Step 5: make missing intervals visible
# ----------------------------------------------
# An incomplete source is rejected instead of silently interpolated or filled.
try:
    generation_from_series(pv.iloc[:-1], profiles.index)
except ValueError as error:
    print("Expected validation error:", error)
