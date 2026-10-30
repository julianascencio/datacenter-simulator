"""
11. Couple solar and storage to a DC network
==============================================

**Level:** Advanced | **Subject:** generation, storage and dispatch

Question: how do conversion topology and control affect imports and resilience?
The example models 400 kWp PV with pvlib using an attributed Tenerife TMY, a
600 kWh battery, and a six-hour grid outage. Equipment sizes and efficiencies
are illustrative. Battery storage stays DC-connected in both PV-coupling cases.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.engineering import solar_study
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.optimization import optimize_dispatch, rolling_dispatch

# %%
# Step 1: connect DC array generation at its explicit boundary
# -----------------------------------------------------------------
# Direct coupling uses a DC converter; AC coupling uses an inverter followed by
# the facility rectifier. The electrical solver accounts for cable losses.
loads, generation, results = solar_study()
direct = results["dc"].timeseries
print({name: run.summary for name, run in results.items()})
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
axes[0].plot(generation.index, generation, label="PV array DC availability")
axes[0].plot(loads.index, loads.sum(axis=1), label="Requested terminal demand")
axes[0].plot(direct.index, direct.grid_import_ac_kw, label="Grid AC import")
axes[0].set(ylabel="Power [kW]")
axes[0].legend()
axes[1].plot(direct.index, direct.battery_energy_kwh, color="#7755aa", label="Stored energy")
axes[1].set(ylabel="Battery [kWh]", xlabel="Synthetic TMY calendar · UTC")
axes[1].legend()

# %%
# Step 2: compare losses and inspect delivered load during the outage
# ------------------------------------------------------------------------
# Supply deficits cause explicit uniform shedding with feeder-loss feedback.
# Snapshot ports identify which converter regulates the islanded bus.
fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
axes[0].bar(
    list(results), [r.summary["conversion_loss_kwh"] for r in results.values()], color="#e3a343"
)
axes[0].set(ylabel="PV + rectifier + battery losses [kWh]", xlabel="PV coupling")
axes[1].plot(direct.index, direct.served_fraction, label="Served terminal fraction")
axes[1].plot(
    direct.index, direct.grid_connected.astype(int), linestyle="--", label="Grid available"
)
axes[1].set(ylabel="Fraction", ylim=(-0.05, 1.05))
axes[1].legend()

# %%
# Step 3: optimize storage and replay forecast errors at a common DC bus
# ----------------------------------------------------------------------------
# This dispatch study declares the DC-bus boundary explicitly. It uses the
# simulated distribution losses in demand and an outage reserve/end-SOC rule.
# Forecast errors are deterministic perturbations, not claimed forecast accuracy.
profiles = loads.sum(axis=1).to_frame("demand_kw")
profiles["demand_kw"] += direct.dc_loss_kw
profiles["generation_kw"] = generation * 0.98
profiles["import_price"] = [0.3 if 17 <= t.hour < 22 else 0.1 for t in profiles.index]
profiles["carbon_kg_kwh"] = [0.5 if 17 <= t.hour < 22 else 0.15 for t in profiles.index]
profiles["grid_limit_kw"] = direct.grid_connected.astype(float) * 250 * 0.97
battery = Battery(600, 200, 200, initial_soc=0.7)
optimized = optimize_dispatch(profiles, battery, terminal_soc=0.4, carbon_price_per_kg=0.1)
forecast = profiles.copy()
forecast["generation_kw"] *= 1.15
forecast["demand_kw"] *= 0.95
rolling = rolling_dispatch(profiles, forecast, battery, horizon=12, reserve_soc=0.4)
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
axes[0].plot(profiles.index, optimized.timeseries.grid_import_kw, label="Known-profile optimum")
axes[0].plot(profiles.index, rolling.grid_import_kw, label="Rolling forecast + actual recourse")
axes[0].set(ylabel="Grid contribution at DC bus [kW]")
axes[0].legend()
axes[1].plot(profiles.index, optimized.timeseries.battery_energy_kwh, label="Known profile")
axes[1].plot(profiles.index, rolling.battery_energy_kwh, label="Rolling forecast")
axes[1].set(ylabel="Stored energy [kWh]", xlabel="Synthetic TMY calendar · UTC")
axes[1].legend()
print("Optimization summary:", optimized.summary)
print("Maximum replay balance residual [kW]:", rolling.balance_error_kw.abs().max())

# %%
# Storage optimization and nonlinear DC feasibility are separate numerical steps.
# The microgrid sequence uses ideal voltage regulation, not switching dynamics.
# :doc:`../../user_guide/engineering` explains boundaries and converter controls.
