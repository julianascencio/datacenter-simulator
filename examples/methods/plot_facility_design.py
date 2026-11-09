"""
18. Design a facility from IT demand to equipment and floor space
=================================================================

Start with 1 MW of current peak IT demand (including networking), reserve 25%
growth, then size racks, electrical capacity, cooling and UPS energy. Every
method is in the installed package; this tutorial only orchestrates and plots.
Defaults are synthetic and require site/vendor calibration before design use.

Level: Intermediate
"""

# %%
# Step 1: define the design requirement and the capacity arrangement.
# N+1 adds a spare module. 2N means two independently full-duty trains.
import matplotlib.pyplot as plt

from datacenter_simulator.analysis.design import compare_designs, design_study
from datacenter_simulator.models.design import DesignInputs
from datacenter_simulator.utilities.design import design_floor_plan, design_power_flow

inputs = DesignInputs(
    it_peak_kw=1000,
    growth_fraction=0.25,
    rack_limit_kw=30,
    redundancy="N+1",
    cooling="direct_to_chip",
)
study = design_study(inputs)
print(study.design.equipment.to_string(index=False))
print("Future IT kW:", study.summary["design_it_kw"])
print("Battery kWh:", round(study.summary["battery_total_kwh"], 1))

# %%
# Step 2: inspect duty, installed usable capacity and capacity after a loss.
# The thermal row is deliberately separated from electrical capacities.
equipment = study.design.equipment
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
for ax, domain, unit in zip(axes, ("electrical", "thermal"), ("kWe", "kWth"), strict=True):
    frame = equipment[equipment.domain == domain].set_index("equipment")
    frame[["duty_kw", "installed_usable_kw", "remaining_kw"]].plot.bar(
        ax=ax, color=["#207c91", "#bcced8", "#d99c35"], rot=0
    )
    ax.set(ylabel=unit, xlabel="", title=f"{domain.title()} design — N+1")
    ax.legend(["Duty", "Installed", "After loss"], fontsize=8)

# %%
# Step 3: calculate annual energy from weighted load/weather bins. This is a
# histogram, not an hourly dispatch. PUE is facility energy / IT energy.
print("Annual energy PUE:", round(study.summary["annual_energy_pue"], 3))
print("Annual electricity EUR:", round(study.summary["annual_electricity_eur"]))
print("Design grid margin kW:", round(study.summary["grid_margin_kw"], 1))

# %%
# Step 4: compare five cooling methods at identical IT demand and draw the
# actual calculated rack geometry. Floor area includes alternating aisle widths.
variants = compare_designs(study)
chosen = {
    name.split(" / ")[0]: result for name, result in variants.items() if name.endswith(" / N+1")
}
fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
axes[0].barh(
    list(chosen), [s.summary["annual_energy_pue"] for s in chosen.values()], color="#207c91"
)
axes[0].set(xlabel="Annual energy PUE", title="Same IT demand; uncalibrated cooling presets")
for rack in study.design.racks.itertuples():
    axes[1].add_patch(
        plt.Rectangle(
            (rack.x_m, rack.y_m), rack.width_m, rack.depth_m, facecolor="#207c91", edgecolor="white"
        )
    )
axes[1].set(
    xlim=(0, study.summary["hall_width_m"]),
    ylim=(0, study.summary["hall_depth_m"]),
    xlabel="Width (m)",
    ylabel="Depth (m)",
    title=f"{len(study.design.racks)} racks / concept plan",
)
axes[1].set_aspect("equal")

# %%
# Step 5: reusable interactive tools expose their figures for notebooks and
# custom reports. Generate the full offline selector and audit files with:
#
# ``python -m datacenter_simulator.analysis.design --output outputs/design``
#
# Open ``outputs/design/design-workbench.html``. Edit exported inputs.json and
# bins.json and rerun with ``--inputs`` and ``--bins`` to change the design.
#
# `Open the interactive design workbench <../../_static/lab/design/design-workbench.html>`_.
power_figure = design_power_flow(study.design)
floor_figure = design_floor_plan(study.design)
assert len(power_figure.data[0].link.value) == 6
assert len(floor_figure.data[0].x) == study.summary["rack_count"]
plt.show()
