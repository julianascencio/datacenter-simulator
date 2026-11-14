"""
BESS for data centers: power, resilience and renewables
======================================================

Inspired by the attached RENMAD/ATA webinar post. This mainland-Spain screening
uses an Energy Data Insights PVGIS snapshot and hypothetical facility/tariff
inputs. It does not represent a webinar participant's facility or prove Spanish
market profitability. Monetary savings exclude subsidies and ancillary revenues.

Level: Intermediate
"""

# %%
# Step 1: compare a cost-minimizing BESS with one preserving an 80% SOC reserve.
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from datacenter_simulator.analysis.bess_value import break_even_installed_cost, spain_bess_study
from datacenter_simulator.connectors.edi_bess import load_edi_solar_snapshot
from datacenter_simulator.methods.bess_value import ramp_buffer_requirement

_, provenance = load_edi_solar_snapshot(dc_rating_kwp=6000)
print("PV source:", provenance["edi_connector"], provenance["evidence_class"])
study = spain_bess_study()
print(study.comparison.to_string())
fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
first = study.schedules["economic"].timeseries
axes[0].plot(first.index, first.baseline_grid_kw / 1000, label="No BESS", color="gray")
for name, result in study.schedules.items():
    axes[0].plot(result.timeseries.index, result.timeseries.grid_kw / 1000, label=name)
    axes[1].plot(result.timeseries.index, result.timeseries.energy_end_kwh / 6000, label=name)
axes[0].set(ylabel="Facility grid import (MW)", title="Synthetic load/tariff; EDI/PVGIS solar week")
axes[1].set(ylabel="End-of-step SOC", xlabel="UTC (provider timestamps retained)")
axes[0].legend()

# %%
# Step 2: test an unannounced two-hour outage at every possible start.
# Critical demand is an assumed 1.5 MW; PV is set to zero in this stress only.
# This tests energy/power adequacy, not UPS transfer or grid-forming stability.
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
study.comparison.operating_saving_eur.plot.bar(ax=axes[0], color=["#207c91", "#d99c35"], rot=0)
axes[0].set(ylabel="EUR / modeled week", xlabel="", title="Savings after assumed variable wear")
for name, rows in study.outage_sweep.groupby("policy"):
    axes[1].plot(rows.start, rows.unserved_kwh, label=name)
axes[1].axhline(3000, color="gray", linestyle="--", label="No BESS: 3,000 kWh unserved")
axes[1].set(ylabel="Critical unserved energy (kWh)", xlabel="Outage start (UTC)")
axes[1].legend()

# %%
# Step 3: examine rapid AI load changes separately at one-second resolution.
# Hourly PVGIS output cannot demonstrate fast power-control performance.
trace = pd.Series(
    np.r_[np.full(10, 2500), np.full(30, 4500), np.full(30, 2500)],
    index=pd.date_range("2023-06-15", periods=70, freq="s", tz="UTC"),
)
print(
    "Ideal fast-buffer requirement:",
    ramp_buffer_requirement(trace, grid_ramp_kw_per_s=100, dt_seconds=1),
)

# %%
# Step 4: no-subsidy capital-cost threshold using EXPLICIT annual sensitivities.
# These independent annual assumptions are not the sample week multiplied by 52.
annual_savings = np.array([50_000, 100_000, 200_000, 400_000])
budgets = [
    break_even_installed_cost(float(s), years=10, discount_rate=0.08, annual_fixed_om_eur=30_000)
    for s in annual_savings
]
fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
ax.plot(annual_savings / 1000, np.array(budgets) / 1e6, marker="o")
ax.set(
    xlabel="Assumed annual operating saving (kEUR/year)",
    ylabel="Break-even installed cost (MEUR)",
    title="10 years, 8% discount, 30 kEUR/year O&M",
)

# %%
# Step 5: export auditable interval dispatch, sensitivities and outage results.
out = Path("outputs/bess-value")
out.mkdir(parents=True, exist_ok=True)
study.comparison.to_csv(out / "comparison.csv")
study.outage_sweep.to_csv(out / "outage-sweep.csv", index=False)
for name, result in study.schedules.items():
    result.timeseries.to_csv(out / f"{name}.csv", index_label="timestamp")
