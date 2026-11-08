"""
15. Reproduce the Wyoming conditional recovery study
================================================================================

**Level:** Advanced | **Subject:** commissioning, firm capacity, carbon and capital

The acquisition is a fact; future operating success is a scenario. Public
announcements establish aggregate capacities, while individual blocks, dates,
PUE, capture performance, costs and contingencies are declared assumptions.
All numerical methods are imported from the installed simulator package.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.wyoming import recovery_study
from datacenter_simulator.use_cases.wyoming import wyoming_sources

# %%
# Step 1: compare early construction with staged investment
# --------------------------------------------------------------------------------
# Cases A and B have identical power schedules: phasing reduces idle-capital
# exposure, not the energy needed for useful computing. Case C adds hypothetical
# firm supply; D delays construction milestones. These are not Google forecasts.
study = recovery_study()
print(study["summary"].to_string(index=False))
print("Evidence records:", len(wyoming_sources()))
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
for name, rows in study["monthly"].groupby("case"):
    axes[0].plot(rows.month, rows.commissioned_it_mw, label=name)
    axes[1].plot(rows.month, rows.idle_it_mw, label=name)
axes[0].set(ylabel="Accepted IT power [MW]")
axes[0].legend(fontsize=8)
axes[1].set(ylabel="Idle facility equivalent [MW IT]")
axes[1].set_xticks([0, 12, 24, 35], ["Jan 2028", "Jan 2029", "Jan 2030", "Dec 2030"])

# %%
# Step 2: keep source-specific capture and power-cost assumptions visible
# --------------------------------------------------------------------------------
# Capturing fuel-cell exhaust does not capture turbine exhaust. The turbine CCS
# case is an optimistic sensitivity without turbine capture auxiliaries/capex.
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
carbon = study["emissions"]
axes[0].bar(["No CCS", "Fuel cells", "FC + CCGT*"], carbon.residual_mt_year)
axes[0].set(ylabel="Direct CO2 [million tonnes/year]", title="Illustrative 1.8 GW facility")
for rate, rows in study["cost_sensitivity"].groupby("discount_rate"):
    axes[1].plot(rows.gas_usd_per_mmbtu, rows.screening_usd_per_net_mwh, label=f"{rate:.0%}")
axes[1].set(
    xlabel="Gas [$/MMBtu HHV]",
    ylabel="Fuel-cell cost [$/net MWh]",
    title="Not a disclosed PPA tariff",
)
axes[1].legend(title="Recovery rate")

# %%
# Reproduce the complete package export, including the interactive grid report:
# ``python -m datacenter_simulator.analysis.wyoming --output outputs/wyoming``.
# See :doc:`../../user_guide/grid_management` for the original source registry,
# assumptions, validation and relationship to facility cooling/workload models.
