"""
14. Manage a generator fleet, grid service and storage
================================================================================

**Level:** Advanced | **Subject:** campus grid management and correlated outages

The reusable package solves a chronological single-bus mixed-integer dispatch
problem. It includes capture auxiliaries, generator ramps, finite battery energy,
grid limits, import prices, carbon costs and priority-weighted load shedding.
This is an illustrative perfect-foresight schedule, not an AC power-flow model.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.wyoming import grid_management_study

# %%
# Step 1: run controlled normal, generator and shared-supply scenarios
# --------------------------------------------------------------------------------
# The package contains all dispatch algorithms and fixtures. The hypothetical
# 1 GWh / 200 MW battery cannot sustain a full-campus gas outage indefinitely.
runs = grid_management_study()
for name, result in runs.items():
    print(name, result.summary)

fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
for name in ("generator_trip", "trip_with_storage", "common_gas_loss"):
    frame = runs[name].timeseries
    axes[0].plot(frame.index, frame.served_kw / 1000, label=name)
    axes[1].plot(frame.index, frame.critical_unserved_kw / 1000, label=name)
axes[0].set(ylabel="Served facility power [MW]")
axes[1].set(ylabel="Unserved critical power [MW]", xlabel="Synthetic 2030 timeline · UTC")
axes[0].legend()
axes[1].legend()

# %%
# Step 2: inspect storage state and the source-level balance
# --------------------------------------------------------------------------------
# Charges and discharges are mutually exclusive. Terminal energy is constrained
# to at least the initial SOC, so this comparison cannot spend free end energy.
frame = runs["trip_with_storage"].timeseries
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
axes[0].plot(frame.index, frame.battery_energy_kwh / 1000, label="Stored energy")
axes[0].set(ylabel="Battery [MWh]")
axes[0].legend()
axes[1].plot(frame.index, frame.charge_kw / 1000, label="Charge")
axes[1].plot(frame.index, frame.discharge_kw / 1000, label="Discharge")
axes[1].set(ylabel="Battery bus power [MW]", xlabel="Synthetic 2030 timeline · UTC")
axes[1].legend()
print("Maximum balance residual [kW]:", frame.balance_error_kw.abs().max())

# %%
# The utility-path scenario removes both Black Hills generation and market
# service. The common-gas scenario removes every fuel-dependent block. N-1
# screening and chronological economic dispatch answer different questions.
# See :doc:`../../user_guide/grid_management` for equations and exclusions.
