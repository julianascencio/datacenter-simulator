"""
06. Complete facility energy and resilience study
========================================================

**Level:** Advanced | **Subject:** Integrated facility analysis

Prerequisite: complete the component and generation-connector tutorials.

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

# %%
# Step 1: define one common demand, weather and supply scenario
# ---------------------------------------------------------------------
# Each alternative starts with the same battery SOC. The battery dispatch is
# greedy self-consumption; it does not optimize tariffs or lifecycle cost.
center = reference_center()
profiles, generation = reference_profiles()
battery = Battery(capacity_kwh=500, max_charge_kw=150, max_discharge_kw=150)
# %%
# Step 2: vary only the cooling plant
# -------------------------------------------
# Identical profiles isolate the effects of the chosen cooling assumptions.
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
# Step 3: inspect power and stored energy
# -----------------------------------------------
# PUE is energy-based and uses gross facility demand before supply dispatch.
# Battery energy at the end can differ from its initial state; the energy
# balance includes that change and charge/discharge losses.
selected = results["direct_to_chip"]
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
selected.timeseries[["facility_kw", "generation_kw", "grid_import_kw"]].plot(ax=axes[0])
selected.timeseries["battery_energy_kwh"].plot(ax=axes[1], color="#7351a6")
axes[0].set(ylabel="Power [kW]")
axes[1].set(ylabel="Battery energy [kWh]", xlabel="Interval start [UTC]")
assert selected.summary["max_balance_error_kw"] < 1e-8

# %%
# Step 4: constrain the electrical supply
# -----------------------------------------------
# Set grid import capacity to zero and add 80 kW of ideal backup. A shortage
# remains explicit rather than being hidden by automatic workload shedding.
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

fig, ax = plt.subplots(figsize=(9, 3.5), layout="constrained")
outage.timeseries[["facility_kw", "generation_kw", "backup_kw", "unserved_kw"]].plot(ax=ax)
ax.set(ylabel="Electrical power [kW]", xlabel="Islanded interval start [UTC]")

# %%
# Step 5: export the same results as an interactive report
# ----------------------------------------------------------------
# The CLI builds this dashboard automatically. The reusable report API accepts
# this study's exact DataCenter and SimulationResult objects:
#
# .. code-block:: python
#
#    from datacenter_simulator.utilities.report import write_report
#    write_report(center, selected, "outputs/facility-study.html",
#                 comparisons=results)
#
# Requested demand is retained in the islanded case: these results do not
# predict served computing capacity or operational PUE during load shedding.
