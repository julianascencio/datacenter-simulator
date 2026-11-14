"""
Site-first feasibility: capacity, quantities and structural carbon
==================================================================

Inspired by Nuno Mourão's Autodesk University 2026 class BLD4108.
All site dimensions and cost/carbon rates below are synthetic. Each option
reuses the package electrical/cooling sizing and reserves a plant/access strip.
This screening cannot establish constructability or regulatory compliance.

Level: Intermediate
"""

# %%
# Generate options from land and confirmed grid capacity, not target IT MW.
from itertools import product
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from datacenter_simulator.methods.feasibility import FeasibilitySite, HallTemplate, screen_site

site = FeasibilitySite(180, 140, grid_kw=30_000, plant_strip_m=30)
options = [
    screen_site(
        site,
        HallTemplate(f"{density} kW/rack", 20, 30, 48, density, 1400, 300),
        storeys=levels,
        rotated=rotation,
    )
    for density, levels, rotation in product((20, 40), (1, 2), (False, True))
]
comparison = pd.DataFrame([option.summary for option in options])
print(comparison.to_string(index=False))

# %%
# A reproducible business shortlist: maximum IT, then lowest shell allowance.
best_index = comparison.sort_values(
    ["it_kw", "shell_cost_eur"], ascending=[False, True], kind="stable"
).index[0]
best = options[best_index]
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
axes[0].scatter(comparison.it_kw / 1000, comparison.structure_tco2e)
for index, row in comparison.iterrows():
    axes[0].annotate(str(index), (row.it_kw / 1000, row.structure_tco2e))
axes[0].set(xlabel="Derived IT capacity (MW)", ylabel="Structure allowance (tCO2e)")
for hall in best.halls[best.halls.level == 0].itertuples():
    axes[1].add_patch(
        plt.Rectangle(
            (hall.x_m, hall.y_m), hall.width_m, hall.depth_m, facecolor="#207c91", edgecolor="white"
        )
    )
axes[1].set(
    xlim=(0, site.width_m),
    ylim=(0, site.depth_m),
    xlabel="Site x (m)",
    ylabel="Site y (m)",
    title="Selected ground-floor modules",
)
axes[1].set_aspect("equal")

# %%
# Neutral tables preserve quantities and geometry for downstream work.
# These are not native Revit, Forma or AutoCAD integrations.
out = Path("outputs/site-feasibility")
out.mkdir(parents=True, exist_ok=True)
comparison.to_csv(out / "options.csv", index=False)
best.halls.to_csv(out / "selected-halls.csv", index=False)
best.equipment.to_csv(out / "selected-equipment.csv", index=False)

# %%
# Audit the source's 120 MW case separately; this is arithmetic, not validation
# of PODIUM's proprietary structural model or a generalized density benefit.
for rack_kw, carbon_t, intensity in ((40, 8338, 302), (20, 16115, 315)):
    print(
        f"Source case: {120000 / rack_kw:.0f} racks; "
        f"implied area {carbon_t * 1000 / intensity:.0f} m²"
    )
