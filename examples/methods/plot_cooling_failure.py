"""
05. HVAC alternatives and cooling failure
=================================================

**Level:** Intermediate | **Subject:** Cooling and thermal dynamics

Compare five HVAC alternatives for the same 200 kW heat load, examine heat
rejection at a fixed outdoor temperature, then simulate a loss of cooling.
Prerequisite: understand power versus energy and basic heat balances.

COPs, capacity, liquid-capture fractions and thermal mass are illustrative.
The thermal zone predicts mean temperature, not individual rack inlets or CFD.
"""

import matplotlib.pyplot as plt
import numpy as np

from datacenter_simulator.methods.cooling import ThermalZone, cooling_alternatives

# %%
# Step 1: compare cooling electricity across ambient temperatures
# -----------------------------------------------------------------------
# Each plant has 400 kW of thermal capacity and sees exactly the same heat load.
# Economizer transitions are idealized thresholds; site humidity and hydraulic
# constraints are outside this model.
heat_kw = 200.0
plants = cooling_alternatives(capacity_kw=400)
ambient = np.linspace(5, 45, 81)
fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
for plant in plants.values():
    ax.plot(
        ambient, [plant.evaluate(heat_kw, float(t)).electric_kw for t in ambient], label=plant.name
    )
ax.set(xlabel="Outdoor temperature [°C]", ylabel="Cooling electricity [kW]")
ax.legend(fontsize=8)
ax.grid(alpha=0.2)

# %%
# Step 2: inspect heat and electricity at 30°C
# ----------------------------------------------------
# Rejected heat includes both removed IT heat and cooling electricity. A lower
# cooling-demand curve is not evidence that one technology is always superior:
# the curves depend on these assumed coefficients and system boundaries.
for plant in plants.values():
    result = plant.evaluate(heat_kw, 30)
    print(
        f"{plant.name}: electrical={result.electric_kw:.1f} kW, "
        f"rejected={result.rejected_heat_kw:.1f} kW, "
        f"liquid flow={result.liquid_flow_kg_s:.2f} kg/s"
    )
    assert np.isclose(result.rejected_heat_kw, result.heat_removed_kw + result.electric_kw)

# %%
# Step 3: lose active cooling after five minutes
# ------------------------------------------------------
# The separate ThermalZone model integrates a well-mixed thermal mass. Here
# ambient temperature equals the initial room temperature, so the room remains
# at 24°C while all internal heat is removed, then heats up after cooling fails.
zone = ThermalZone(capacitance_kj_k=100_000, conductance_kw_k=0.5)
temperature = 24.0
temperatures = [temperature]
for minute in range(30):
    removed = heat_kw if minute < 5 else 0
    temperature = zone.advance(temperature, 24, heat_kw, removed, 1 / 60)
    temperatures.append(temperature)

fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.plot(range(31), temperatures, color="#b2414e", linewidth=2)
ax.axvline(5, color="#555555", linestyle="--", label="Cooling failure")
ax.set(xlabel="Elapsed time [min]", ylabel="Mean zone temperature [°C]")
ax.legend()
print(f"Mean zone temperature at 30 min: {temperatures[-1]:.1f} °C")

# %%
# This transient is separate from the steady-state facility simulation. It
# does not automatically throttle IT, shed load or predict local hot spots.
