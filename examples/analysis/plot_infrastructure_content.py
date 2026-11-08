"""
16. Turn an equipment infographic into a synthetic facility study
================================================================================

**Level:** Advanced | **Subject:** equipment content, capacity, cooling and capital

The user supplied a screenshot titled *Who Makes the Data Center 2026* and
https://lnkd.in/p/epbFKeP5. The linked post could not be retrieved. Its twelve
cost rates are transcribed into an offline fixture, not validated as market
prices. The image does not establish its MW denominator or scope boundaries.
We explicitly assume **IT MW** and compare the alternative interpretation.

The runnable business question is: how much listed equipment content would a
20 MW IT scenario imply, what supporting capacity does it need, and which
assumptions most affect the result? All numerical methods live in the package.
The original image is not redistributed. Vendor labels are annotations only.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.infrastructure import infrastructure_study
from datacenter_simulator.use_cases.infrastructure import (
    InfrastructureCase,
    infrastructure_evidence,
)

# %%
# Step 1: inspect the source before calculating a budget
# --------------------------------------------------------------------------------
# These are twelve absolute rates in million USD/MW. Engineering/construction
# fees are NOT percentages, and the construction fee is not a building price.
# Servers and networking are separate cost lines but both belong inside IT MW.
# Land, utility connection, building scope, taxes, financing and other exclusions
# remain unpriced. The source does not say whether standby units are included.
case = InfrastructureCase(it_mw=20, rack_kw=100, ups_autonomy_minutes=10)
study = infrastructure_study(case)
print(infrastructure_evidence()["source"]["verification"])
print(study.costs[["name", "million_usd_per_mw", "cost_usd"]].to_string(index=False))
print("Listed subtotal, USD:", study.summary["listed_subtotal_usd"])

fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
axes[0].barh(study.costs.name, study.costs.cost_usd / 1e6, color="#087f8c")
axes[0].set(xlabel="USD million", title="All 12 listed lines × 20 IT MW")
axes[0].tick_params(axis="y", labelsize=8)
grouped = study.costs.groupby("group").cost_usd.sum() / 1e6
axes[1].bar(grouped.index, grouped.values, color=["#123354", "#087f8c", "#d68a28"])
axes[1].set(ylabel="USD million", title="Listed subtotal: $854m (incomplete scope)")

# %%
# Step 2: translate IT capacity into facility power and cooling duty
# --------------------------------------------------------------------------------
# The existing CoolingPlant handles mechanical liquid cooling plus residual air
# cooling. Here 85% is a synthetic heat-capture fraction, unrelated to the two
# cooling cost rates. Economizer operation is disabled. The hall includes losses
# from downstream distribution; the UPS and main losses are outside the hall.
# Heat rejection includes removed heat AND compressor/fan/pump electricity.
# This is aggregate planning, not a solved feeder network or detailed tower design.
print("Design power balance:", study.design)
power_columns = [
    "it_kw",
    "distribution_loss_kw",
    "ups_loss_kw",
    "cooling_kw",
    "auxiliary_kw",
    "main_loss_kw",
]
fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
axes[0].bar(
    ["IT", "Hall loss", "UPS loss", "Cooling", "Aux", "Main loss"],
    [study.design[name] / 1000 for name in power_columns],
    color="#087f8c",
)
axes[0].set(ylabel="MW electrical", title="Utility meter demand closes the balance")
axes[0].tick_params(axis="x", labelrotation=25)
cooling = study.cooling_sensitivity
axes[1].plot(cooling.liquid_heat_fraction, cooling.cooling_kw / 1000, "o-")
axes[1].set(
    xlabel="Liquid heat-capture fraction",
    ylabel="Cooling electricity [MW]",
    title="Change physics; hold source cost rates fixed",
)

# %%
# Step 3: size modules and battery autonomy without multiplying costs twice
# --------------------------------------------------------------------------------
# Module counts use ceiling(duty / usable rating), plus one spare per bank.
# Racks have no spare. Generator units have an invented 10% derating; 1 MW/1 MVA
# UPS modules respect the assumed 0.95 load power factor. Chillers, CDUs,
# air handlers and heat-rejection units have thermal, not electrical, ratings.
# Each bank retains enough capacity after losing its specified reserve count.
# These counts do not certify availability or include common-mode failures.
print(study.sizing.to_string(index=False))
print("Nominal battery kWh:", study.summary["ups_nominal_battery_kwh"])
print("IT-branch autonomy, minutes:", study.summary["ups_runtime_minutes"])

# %%
# The UPS model includes inverter efficiency, usable energy and end-of-life
# capacity. It protects the IT branch ONLY. Cooling remains outside the UPS:
# a ten-minute battery result is not ten minutes of safe facility operation.
# Generator startup, cooling ride-through and shared battery failures require
# the separate resilience model. No battery or N+1 cost is added automatically,
# because the infographic's inclusion boundaries are unknown.

# %%
# Step 4: run 48 hourly operating balances
# --------------------------------------------------------------------------------
# The IT load fraction spans 55–90%; it is NOT CPU utilization. Networking is
# included in the total and assigned an illustrative 4% power share, independently
# of its cost share. Weather and loads are deterministic synthetic inputs. PUE
# over this period is sum(facility kWh) / sum(IT kWh), not mean(hourly PUE).
# The energy bill covers these 48 hours at an invented $0.10/kWh, with no demand
# charges, fuel, staff or maintenance. It is not total OPEX or an annual forecast.
hourly = study.hourly
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
for name in ("it_kw", "cooling_kw", "facility_kw"):
    axes[0].plot(hourly.index, hourly[name] / 1000, label=name.removesuffix("_kw"))
axes[0].set(ylabel="MW", title="Synthetic 48-hour operation")
axes[0].legend()
axes[1].plot(hourly.index, hourly.instantaneous_pue, color="#d68a28")
axes[1].set(ylabel="Instantaneous power ratio", xlabel="UTC")
print("48-hour energy PUE:", study.summary["period_energy_pue"])
print("48-hour electricity-only USD:", study.summary["period_electricity_usd"])
print("48-hour unmet hall heat, kWh:", study.summary["period_unmet_heat_kwh"])

# %%
# Step 5: test denominator ambiguity, cost exposure and discrete scaling
# --------------------------------------------------------------------------------
# These are isolated deterministic sensitivities, not confidence intervals or
# a forecast. Applying the image rates to facility MW raises EVERY line together.
# The 10% contingency applies only to the listed scope, leaving exclusions unpriced.
# Physical equipment counts change in steps even when per-MW content scales linearly.
print(study.cost_sensitivity.to_string(index=False))
fig, axes = plt.subplots(1, 2, figsize=(13, 4), layout="constrained")
sensitivity = study.cost_sensitivity
axes[0].barh(sensitivity.scenario, sensitivity.scenario_total_usd / 1e6, color="#087f8c")
axes[0].set(xlabel="USD million", title="One assumption changed per scenario")
axes[0].tick_params(axis="y", labelsize=8)
scale = study.scale_sensitivity
axes[1].plot(scale.it_mw, scale.generator_units, "o-")
axes[1].set(
    xlabel="IT design capacity [MW]",
    ylabel="Installed 3 MW generator units",
    title="Discrete N+1 sizing with 10% derating",
)

# %%
# Step 6: export a complete reproducible study
# --------------------------------------------------------------------------------
# Run ``python -m datacenter_simulator.analysis.infrastructure --it-mw 20``.
# Open ``outputs/infrastructure/infrastructure-study.html`` for the offline report.
# It includes a waterfall, electrical balance, hourly curves, cost sensitivities,
# equipment table and ten CSV/JSON audit downloads. Edit InfrastructureCase in
# Python to study another load, rack density, cooling mix, efficiency or autonomy.
# See :doc:`../../user_guide/infrastructure` for equations and scope, and
# :doc:`../../reference/infrastructure` for the public APIs.
