"""
10. Compare cooling, water and heat reuse across climates
===========================================================

**Level:** Intermediate | **Subject:** weather, energy and water

Question: how does the same IT load behave in Frankfurt, Tenerife and Seville?
The bundled hourly PVGIS 5.3 TMY snapshots are attributed composite resource
records, not observations from operating data centers. Cooling parameters and
local heat demand are illustrative. All 8760 hourly records are used.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.engineering import climate_study
from datacenter_simulator.connectors.weather import bundled_weather

# %%
# Step 1: inspect the source climate rather than assigning a climate label
# -----------------------------------------------------------------------------
# The synthetic calendar is 2021 UTC. Original selected-month timestamps and
# dataset metadata remain in the packaged CSV/JSON files.
fig, ax = plt.subplots(figsize=(9, 3.5), layout="constrained")
for climate in ("frankfurt", "tenerife", "seville"):
    weather = bundled_weather(climate)
    monthly = weather.ambient_c.resample("MS").mean()
    ax.plot(monthly.index.month, monthly, "o-", label=climate.title())
ax.set(xlabel="Month", ylabel="TMY monthly mean dry-bulb [°C]")
ax.legend()

# %%
# Step 2: run matched annual heat-rejection alternatives
# ------------------------------------------------------------
# IT is 200 kW in every case. The boundary is IT plus this cooling plant; it
# excludes electrical distribution and unrelated building loads. PUE here is
# therefore a study metric, not a certified whole-facility measurement.
results = climate_study()
print(results[["climate", "mode", "pue", "makeup_m3", "economizer_hours"]].to_string(index=False))
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
results.pivot(index="climate", columns="mode", values="pue").plot.bar(ax=axes[0], rot=0)
results.pivot(index="climate", columns="mode", values="makeup_m3").plot.bar(ax=axes[1], rot=0)
axes[0].set(ylabel="IT + cooling energy / IT energy", xlabel="")
axes[1].set(ylabel="Annual tower makeup [m³]", xlabel="")

# %%
# Step 3: add a useful heat sink with explicit temperature and demand
# ----------------------------------------------------------------------
# Heat demand is max(0, 18°C - ambient) × 8 kW/K, delivered at 40°C. Heat
# exported is reported separately; it is not subtracted from PUE electricity.
hybrid = results.loc[results["mode"] == "hybrid"]
fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), layout="constrained")
axes[0].bar(hybrid.climate, hybrid.recovery_useful_heat_kwh / 1000, color="#dd943d")
axes[0].set(ylabel="Useful delivered heat [MWh/year]")
axes[1].scatter(
    results.cooling_kwh / 1000, results.makeup_m3, c=range(len(results)), cmap="viridis", s=65
)
for row in results.itertuples():
    axes[1].annotate(
        f"{row.climate[:3]} / {row.mode[:3]}", (row.cooling_kwh / 1000, row.makeup_m3), fontsize=7
    )
axes[1].set(xlabel="Cooling electricity [MWh/year]", ylabel="Makeup water [m³/year]")

# %%
# Water accounting includes evaporation, drift and blowdown. Dry cooling has
# zero modeled tower water; that says nothing about other site or grid water.
# Warm supply temperatures can make all-year economization feasible under these
# assumptions. COP surfaces, capacities and heat sinks require local calibration.
