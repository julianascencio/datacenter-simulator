"""
Couple HVAC, generation and battery dispatch
====================================================

An eight-rack reference facility is evaluated for 48 hours with identical IT and
weather profiles. Cooling coefficients are illustrative, not manufacturer data.
Compare cooling energy and gross demand-based PUE, then inspect generation and
storage. This is a self-consumption dispatch study, not an economic optimizer.
"""

from dataclasses import replace

import matplotlib.pyplot as plt

from datacenter_simulator import simulate
from datacenter_simulator.methods.cooling import cooling_alternatives
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.use_cases import reference_center, reference_profiles

center = reference_center()
profiles, generation = reference_profiles()
battery = Battery(capacity_kwh=500, max_charge_kw=150, max_discharge_kw=150)
results = {
    key: simulate(replace(center, cooling=plant), profiles, generation=generation, battery=battery)
    for key, plant in cooling_alternatives(400).items()
}

fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
labels = [name.replace("_", "\n") for name in results]
axes[0].bar(labels, [r.summary["cooling_kwh"] for r in results.values()], color="#148d83")
axes[0].set(ylabel="Cooling electricity [kWh / 48 h]")
axes[1].bar(labels, [r.summary["pue"] for r in results.values()], color="#376b9c")
axes[1].set(ylabel="Gross facility demand / IT demand [PUE]")
for name, result in results.items():
    print(name, {k: round(result.summary[k], 3) for k in ["pue", "cooling_kwh", "grid_import_kwh"]})

# %%
# Check storage and power balance for the direct-to-chip case.
selected = results["direct_to_chip"]
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
selected.timeseries[["facility_kw", "generation_kw", "grid_import_kw"]].plot(ax=axes[0])
selected.timeseries["battery_energy_kwh"].plot(ax=axes[1], color="#7351a6")
axes[0].set(ylabel="Power [kW]")
axes[1].set(ylabel="Battery energy [kWh]", xlabel="Interval start [UTC]")
assert selected.summary["max_balance_error_kw"] < 1e-8

# %%
# A supply-constrained case reports unmet energy instead of hiding the shortage.
outage = simulate(
    center,
    profiles,
    generation=generation,
    battery=battery,
    grid_import_limit_kw=0,
    backup_capacity_kw=80,
)
print("Islanded unserved electricity [kWh]:", outage.summary["unserved_kwh"])
print("Flags:", outage.warnings)
