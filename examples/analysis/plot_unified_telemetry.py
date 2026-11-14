"""
23. Reconstruct incidents across BMS, EPMS and DCIM
===================================================

**Level:** Advanced | **Subject:** operational telemetry, device context and business cases

This offline tutorial extends the supplied four-page InfluxData excerpt with
explicitly synthetic models. The paper motivates the architecture; it supplies
none of the numerical parameters below. No database, equipment or credentials
are needed. See :doc:`../../user_guide/telemetry` for contracts and limitations.
"""

import matplotlib.pyplot as plt
import pandas as pd

from datacenter_simulator.analysis.telemetry import (
    business_sensitivity,
    incident_study,
    sampling_comparison,
)
from datacenter_simulator.methods.telemetry import capacity_plan
from datacenter_simulator.models.telemetry import StreamBudget

# %%
# Step 1: compose the existing power, cooling and thermal models
# --------------------------------------------------------------
# A 60 kW rack is supported by a synthetic 120 kW cooling plant. From second
# 60 to 120, available cooling drops to 20 kW. A mixed thermal capacitance of
# 500 kJ/K provides a transparent energy balance, not a rack-hotspot prediction.
study = incident_study("cooling_failure")
trace = study["traces"]
fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
axes[0].plot(trace.second, trace.rack_power_kw, label="Rack terminal input")
axes[0].plot(trace.second, trace.removed_heat_kw, label="Heat removed")
axes[0].set(ylabel="kW", title="Synthetic cooling failure and recovery")
axes[0].legend()
axes[1].plot(trace.second, trace.inlet_temperature_c, color="#b54708")
axes[1].axhline(28, linestyle="--", color="gray", label="Illustrative threshold")
axes[1].set(xlabel="Elapsed seconds", ylabel="Mixed-zone temperature (°C)")
axes[1].legend()

# %%
# Step 2: join observations to time-valid asset ownership
# -------------------------------------------------------
# Source and receive timestamps are distinct. EPMS samples power every second;
# BMS samples temperature/flow every five seconds; the synthetic DCIM warning
# feed reports server inlet temperature every fifteen seconds. Ownership joins
# use the event time. Missing context stays unknown rather than becoming today's
# owner. The synthetic customer name is deliberately not a real client.
observations = pd.DataFrame(study["history"].frame(study["contexts"]))
print(observations.groupby("source_system").size())
print(observations[["asset_id", "point_key", "source_system", "owner"]].drop_duplicates())

# %%
# Step 3: inspect temporal evidence and dependency exposure
# ---------------------------------------------------------
# The pump signal crosses its threshold before the thermal symptom. This is
# useful evidence for investigation, not proof of causation. Topology traversal
# lists dependent assets, but does not claim that their customers lost service.
print(pd.DataFrame(study["timeline"]).to_string(index=False))
print("Potentially exposed assets:", study["potentially_affected"])

# %%
# Step 4: test whether sampling can see a short workload pulse
# ------------------------------------------------------------
# A ten-second pulse at seconds 11–20 is observed at 1, 5 and 15 second sampling
# but missed at 30 and 60 seconds for this phase. Faster sampling alone does not
# synchronize clocks. Rollups preserve extrema only if a source captured them.
sampling = pd.DataFrame(sampling_comparison())
fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
ax.bar(sampling.interval_s.astype(str), sampling.observed_max_kw, color="#087f8c")
ax.axhline(100, color="#b54708", linestyle="--", label="True synthetic peak")
ax.set(
    xlabel="Sampling period (s)",
    ylabel="Observed maximum (kW)",
    title="Averaging and sparse sampling can hide evidence",
)
ax.legend()

# %%
# Step 5: estimate retention and outage buffering
# -----------------------------------------------
# The budget is scalar observations, not Telegraf multi-field metrics. Assumed
# byte sizes require measurement in deployment. Raw and aggregate tiers coexist.
budget = StreamBudget(10000, 5, 100, 7, 60, 365, 160, 2)
print(capacity_plan([budget], outage_s=600, buffer_observations=100000))

# %%
# Step 6: compare business assumptions, including negative outcomes
# -----------------------------------------------------------------
# Reduced investigation time is a labor scenario. Only an explicit realization
# fraction converts it into hypothetical avoided downtime. Zero is the default.
# The nine combinations expose sensitivity; no product prices or measured ROI
# are extracted from the source. Cash flow is constant with 8% discounting.
economics = pd.DataFrame(business_sensitivity())
fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
for realization, group in economics.groupby("downtime_realization_fraction"):
    ax.plot(
        group.incidents_per_year,
        group.npv / 1000,
        marker="o",
        label=f"Assumed downtime realization {realization:.0%}",
    )
ax.axhline(0, color="gray", linewidth=1)
ax.set(
    xlabel="Incidents per year",
    ylabel="Five-year NPV (thousand EUR)",
    title="Synthetic telemetry investment sensitivity",
)
ax.legend()
print(
    economics[
        ["incidents_per_year", "downtime_realization_fraction", "npv", "simple_payback_years"]
    ].to_string(index=False)
)

# %%
# Step 7: export and replay the evidence package
# ----------------------------------------------
# Run ``python -m datacenter_simulator.analysis.telemetry --output outputs/telemetry``.
# Open ``outputs/telemetry/telemetry.html`` for the interactive report. The export
# includes all three incidents, eight device instances, schemas for the existing
# 50 profiles, CSV/JSONL histories, line protocol, model inputs, context, rules,
# source ledger, storage/sampling sensitivities and nine economic combinations.
# See the guide for a complete JSONL replay example.
plt.show()
