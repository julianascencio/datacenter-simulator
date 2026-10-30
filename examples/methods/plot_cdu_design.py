"""
09. Balance a CDU and four cooling branches
==============================================

**Level:** Intermediate | **Subject:** liquid cooling and hydraulics

Question: how do pump speed, pipe routing and partial blockage affect cooling?
The example uses single-phase water, a finite-UA counterflow heat exchanger and
four parallel branches. Component pressure-loss coefficients are illustrative.
The facility and technology loops exchange heat but do not mix fluid.
"""

from dataclasses import replace

import matplotlib.pyplot as plt
import numpy as np

from datacenter_simulator.methods.hydraulics import Fluid, Pump, solve_cdu
from datacenter_simulator.use_cases.engineering import engineering_cooling

# %%
# Step 1: solve the pump and parallel branch operating point
# ---------------------------------------------------------------
# Pipe lengths come from the same geometry displayed in the engineering lab.
# Each pipe model uses total supply+return length; electrical routing independently
# accounts for outgoing and return conductors.
branches = engineering_cooling()
pump = Pump(shutoff_pa=150000, curve_pa_per_l_s2=2500)
normal = solve_cdu(branches, pump, primary_flow_kg_s=10, ua_kw_k=50)
print(normal.branches.to_string())
print("Heat balance [kW]:", normal.rejected_heat_kw - normal.heat_removed_kw - normal.pump_kw)
flows = np.linspace(0.1, 9, 70)
fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
ax.plot(flows, [pump.head_pa(float(q), 1) / 1000 for q in flows], label="Pump curve")
heads = np.linspace(100, pump.shutoff_pa, 70)
ax.plot(
    [sum(b.flow_l_s(float(h), Fluid()) for b in branches) for h in heads],
    heads / 1000,
    label="Parallel system curve",
)
ax.scatter([normal.flow_l_s], [normal.head_pa / 1000], s=70, label="Operating point")
ax.set(xlabel="Secondary flow [L/s]", ylabel="Pressure difference [kPa]", ylim=(0, 160))
ax.legend()

# %%
# Step 2: introduce a partially blocked branch
# ---------------------------------------------------
# Increase the cold-plate/valve coefficient of one branch. Pressure balance then
# redistributes flow; the affected rack has a higher temperature rise.
restricted = [
    replace(b, resistance_pa_per_l_s2=b.resistance_pa_per_l_s2 * 8) if b.id == "rack-01" else b
    for b in branches
]
blocked = solve_cdu(restricted, pump)
fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
locations = np.arange(len(branches))
for offset, run, label in ((-0.18, normal, "Normal"), (0.18, blocked, "Restricted rack-01")):
    axes[0].bar(locations + offset, run.branches.flow_l_s, width=0.36, label=label)
    axes[1].bar(locations + offset, run.branches.component_c, width=0.36, label=label)
for ax in axes:
    ax.set_xticks(locations, [b.id for b in branches], rotation=20)
    ax.legend()
axes[0].set(ylabel="Branch flow [L/s]")
axes[1].set(ylabel="Lumped component temperature [°C]")

# %%
# Step 3: compare speed, pump electricity and finite heat-removal capacity
# ----------------------------------------------------------------------------
speeds = np.linspace(0.3, 1, 12)
runs = [solve_cdu(branches, pump, speed=float(speed), ua_kw_k=12) for speed in speeds]
fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), layout="constrained")
axes[0].plot(speeds, [r.pump_kw for r in runs], "o-")
axes[0].set(xlabel="Pump speed fraction", ylabel="Pump electricity [kW]")
axes[1].plot(speeds, [r.unmet_heat_kw for r in runs], "o-", color="#cc5555")
axes[1].set(xlabel="Pump speed fraction", ylabel="Unmet heat [kW]")

# %%
# Validation uses laminar Poiseuille flow, equal-capacity ε-NTU limits, pressure
# balance and separate primary/secondary heat balances. Component temperatures
# require measured thermal resistance for real equipment. No boiling is modeled.
