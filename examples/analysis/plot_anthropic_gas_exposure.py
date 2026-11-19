"""
How much of Anthropic's mapped US power could come from gas?
============================================================

**Level:** Intermediate

The Better Data Center Project linked 19 US sites to Anthropic in November
2026. How much gas-fired electricity would those facilities use if the mapped
capacity entered service? How much of the fuel price could reach the tenant
directly? Replay the public site estimates using two ways of assigning grid
power. The inputs, including uncertain site attributions, are in
:doc:`../../user_guide/anthropic_gas`.
"""

import matplotlib.pyplot as plt
import numpy as np

from datacenter_simulator.methods.gas_exposure import annual_gas_exposure
from datacenter_simulator.use_cases.anthropic import anthropic_us_sites

# %%
# Attribute the same electricity demand two ways
# ----------------------------------------------
# Both calculations give on-site gas facilities their own generation. For grid
# purchases, the first uses each site's regional average mix. The second uses
# the study's dedicated generation and short-run marginal dispatch estimates.
# Hold operating assumptions fixed to isolate the effect of capacity and mix.
sites = anthropic_us_sites()
low = annual_gas_exposure(sites, capacity="low").sum()
high = annual_gas_exposure(sites, capacity="high").sum()
bounds = {"Low": low, "High": high}

fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
for i, (label, case) in enumerate(bounds.items()):
    for j, (method, grid_gas) in enumerate(
        (
            ("Regional average", case.regional_grid_gas_mwh),
            ("Study dispatch", case.study_grid_gas_mwh),
        )
    ):
        y = 2 * i + j
        onsite = case.onsite_gas_mwh / 1e6
        grid_gas_twh = grid_gas / 1e6
        other = (case.grid_mwh - grid_gas) / 1e6
        ax.barh(y, onsite, color="#A24B2A", label="On-site gas" if y == 0 else None)
        ax.barh(y, grid_gas_twh, left=onsite, color="#E7A04A", label="Grid gas" if y == 0 else None)
        ax.barh(
            y,
            other,
            left=onsite + grid_gas_twh,
            color="#80A4B1",
            label="Other grid power" if y == 0 else None,
        )
        gas_share = (case.onsite_gas_mwh + grid_gas) / case.facility_mwh
        print(
            f"{label} capacity | {method}: {case.facility_mwh / 1e6:.2f} TWh/year, "
            f"{gas_share:.1%} gas"
        )
ax.set_yticks(range(4), [f"{label} · {mix}" for label in bounds for mix in ("Regional", "Study")])
ax.invert_yaxis()
ax.set(
    xlabel="Facility electricity (TWh per 8,760 hours)",
    title="Gas behind the meter and on the grid",
)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.21), ncol=3)

print(f"High build-out, study dispatch: {high.study_co2e_tonnes / 1e6:.1f} Mt CO2e/year.")
print(
    f"High build-out gas inputs (million MMBtu/year): on-site {high.onsite_fuel_mmbtu / 1e6:.1f}; "
    f"grid {high.regional_grid_fuel_mmbtu / 1e6:.1f} (regional) or "
    f"{high.study_grid_fuel_mmbtu / 1e6:.1f} (study)."
)

# %%
# Price the fuel behind the meter
# -------------------------------
# Assume the tenant pays the full on-site fuel commodity charge. Grid fuel
# contributes to physical gas attribution. Actual grid electricity charges
# require tariffs and contract terms. All prices below are illustrative.
prices = np.array([2.0, 4.0, 6.0, 8.0])
fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
for (label, case), color in zip(bounds.items(), ["#326C7C", "#A24B2A"], strict=True):
    ax.plot(
        prices, prices * case.onsite_fuel_mmbtu / 1e9, "o-", color=color, label=f"{label} capacity"
    )
    print(
        f"{label}: at $4/MMBtu, annual on-site fuel costs "
        f"${case.onsite_fuel_cost_usd / 1e6:,.0f} million. "
        f"A $1/MMBtu increase adds ${case.onsite_fuel_mmbtu / 1e6:,.0f} million/year."
    )
ax.set(
    xlabel="On-site gas price (USD/MMBtu, HHV)",
    ylabel="Annual on-site fuel cost (USD billion)",
    title="Annual fuel bill under full commodity pass-through",
    xticks=prices,
    ylim=(0, None),
)
ax.legend()

# %%
# Test the limits of the project list and generator order
# -------------------------------------------------------
# Remove the five sites explicitly marked speculative in the workbook. Other
# sites still have allocation and commissioning uncertainty. A separate test
# assigns the unmapped portion of the reported 15 GW total either zero or
# entirely gas-fired power, with equal utilization and PUE across sites.
screened = annual_gas_exposure([s for s in sites if not s.speculative_attribution]).sum()
screened_gas = screened.onsite_gas_mwh + screened.regional_grid_gas_mwh
print(
    f"Without explicitly speculative sites: {screened.it_capacity_mw / 1000:.3f} GW high case, "
    f"{screened_gas / screened.facility_mwh:.1%} regional-average gas."
)
mapped_weight = high.it_capacity_mw / 15_000
mapped_gas_share = (high.onsite_gas_mwh + high.regional_grid_gas_mwh) / high.facility_mwh
lower = mapped_weight * mapped_gas_share
upper = lower + (1 - mapped_weight)
print(
    f"15 GW illustration, unknown supply for {(1 - mapped_weight) * 15:.3f} GW: "
    f"{lower:.1%} to {upper:.1%} gas."
)

# If the reported 1.7 GW order were installed, dedicated to these sites and
# continuously available, its output would have the following upper bound.
# The generators' deployment and overlap with mapped projects are unknown.
order_max_twh = 1.7 * 8760 / 1000
print(
    f"1.7 GW order operating at nameplate all year: at most {order_max_twh:.2f} TWh, "
    f"versus {high.onsite_gas_mwh / 1e6:.2f} TWh of modeled high-case on-site demand."
)
plt.show()
