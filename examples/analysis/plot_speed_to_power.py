"""
Speed to power: when earlier compute outweighs cheaper energy
============================================================

**Level:** Intermediate | **Subject:** AI infrastructure technoeconomics

Replay the published 100,000-GPU MV results from Newkirk et al.,
arXiv:2611.17098v1, then compare a separate synthetic engineering scenario.
Author model results are not measurements or a new simulation of U.S. sites.
See :doc:`../../user_guide/speed_to_power` for equations and limitations.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.speed_to_power import speed_power_study
from datacenter_simulator.connectors.speed_to_power import bundled_published_results
from datacenter_simulator.methods.speed_to_power import published_cost_comparison

# %%
# Step 1: reproduce the authors' geographic ranking
# ------------------------------------------------
# The bundled snapshot is version-pinned and attributed. The gas acceleration
# uses the authors' separate three-year result columns, including their costs.
published = bundled_published_results()
fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
colors = {
    "ac_coupled": "#8b5ca6",
    "dc_coupled": "#168783",
    "natural_gas": "#d88038",
    "grid": "#386da8",
}
for accelerated, ax in zip((False, True), axes, strict=True):
    results = published_cost_comparison(published, accelerated_gas=accelerated)
    print("Accelerated gas:", accelerated, results.winner.value_counts().to_dict())
    for name, group in results.groupby("winner"):
        ax.scatter(group.longitude, group.latitude, s=4, color=colors[name], label=name)
    ax.set(
        xlabel="Longitude [degrees]",
        ylabel="Latitude [degrees]",
        title="Three-year gas" if accelerated else "Baseline deployment",
    )
    ax.legend(markerscale=3, fontsize=8)

# %%
# Step 2: screen native AC/DC storage, gas and grid scenarios
# ---------------------------------------------------------
# Synthetic solar/cooling profiles serve the same H100-equivalent terminal
# load. Nine designs per solar topology face a 99% full-load-hour requirement.
# Storage state is periodic. Gas/grid are ideal firm baselines. Costs and
# solar droughts are assumptions; this does not reproduce the paper's sizing.
study = speed_power_study()
print(
    study.selected[
        [
            "architecture",
            "full_load_hour_fraction",
            "base_lcoe_usd_per_kwh",
            "adjusted_lcoe_usd_per_kwh",
        ]
    ].to_string(index=False)
)
print("Rejected solar candidates:", int((~study.candidates.feasible).sum()))
fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
selected = study.selected
ax.bar(selected.architecture, selected.base_lcoe_usd_per_kwh, label="Energy cost", color="#168783")
ax.bar(
    selected.architecture,
    selected.speed_premium_usd_per_kwh,
    bottom=selected.base_lcoe_usd_per_kwh,
    label="Lost compute value",
    color="#d88038",
)
ax.set(ylabel="Illustrative USD / delivered kWh", title="Native synthetic scenario")
ax.legend()

# %%
# Step 3: make the deployment decision sensitive to compute value
# -------------------------------------------------------------
# Recover each architecture's own discounted lost-GPU-hours / delivered-kWh
# slope. A zero GPU-hour value recovers unadjusted energy costs exactly.
fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
for name, data in study.sensitivity[study.sensitivity.timeline_factor == 1].groupby("architecture"):
    ax.plot(data.gpu_hour_value_usd, data.adjusted_lcoe_usd_per_kwh, "o-", label=name)
ax.set(
    xlabel="Assumed USD/GPU-hour",
    ylabel="Speed-adjusted USD/kWh",
    title="Fixed native designs; no guaranteed revenue",
)
ax.legend()

# %%
# Replay with your own profiles and costs
# ---------------------------------------
#
# .. code-block:: bash
#
#    python -m datacenter_simulator.analysis.speed_to_power --output outputs/speed-to-power
#
# Open the :download:`offline report </_static/lab/speed-to-power/speed-to-power.html>`.
# Edit exported inputs.json and profiles.csv, then pass --inputs and --profiles.
# No API key, GPU, network request or upstream Python installation is needed.
