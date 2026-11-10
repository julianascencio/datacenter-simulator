"""
21. 3D noise, source contributions and acoustic treatments
==========================================================

Level: Advanced

Step 1: Declare octave-band sound-power sources
-----------------------------------------------
The example represents four racks and an air-handler in a 12 × 8 × 3.5 m room.
Every source spectrum, treatment and uncertainty input is illustrative. Replace
them with independently sourced equipment data before making design decisions.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from datacenter_simulator.analysis.acoustics import export_noise_study
from datacenter_simulator.methods.cfd import cell_coordinates

results = export_noise_study(Path("outputs/noise"))

# %%
# Step 2: Compare spatial levels on one shared color scale
# --------------------------------------------------------
# Near-field source volumes are masked. Receiver predictions use exact
# coordinates and do not depend on the visualization grid resolution.
levels = np.concatenate([r.laeq_dba[np.isfinite(r.laeq_dba)] for r in results.values()])
fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout="constrained")
for ax, (name, result) in zip(axes, results.items(), strict=True):
    x, y, z = cell_coordinates(result.case.grid)
    k = int(np.argmin(abs(z - 1.5)))
    field = ax.pcolormesh(
        x,
        y,
        result.laeq_dba[:, :, k].T,
        shading="nearest",
        vmin=float(levels.min()),
        vmax=float(levels.max()),
        cmap="magma",
    )
    ax.scatter(
        [s.x_m for s in result.case.sources],
        [s.y_m for s in result.case.sources],
        c="#53e2ec",
        marker="s",
        edgecolors="black",
        s=35,
    )
    ax.scatter(
        [r.x_m for r in result.case.receivers],
        [r.y_m for r in result.case.receivers],
        c="white",
        marker="D",
        edgecolors="black",
        s=25,
    )
    ax.set(title=name, xlabel="x (m)", ylabel="y (m)", aspect="equal")
fig.colorbar(field, ax=axes, label="Equivalent sound level (dBA)", shrink=0.8)
plt.show()

# %%
# Step 3: Inspect receiver predictions and conditional uncertainty
# ----------------------------------------------------------------
# The whiskers use declared source/propagation errors only. They do not include
# the full uncertainty from room-mode physics, absorption, geometry or background.
fig, ax = plt.subplots(figsize=(11, 5))
x = np.arange(3)
for i, (name, result) in enumerate(results.items()):
    table = result.receivers
    y = table.laeq_dba.to_numpy()
    error = np.stack([y - table.input_p025_dba.to_numpy(), table.input_p975_dba.to_numpy() - y])
    ax.errorbar(x + (i - 1) * 0.18, y, yerr=error, fmt="o", capsize=5, label=name)
ax.axhline(75, color="#8e3545", linestyle="--", label="Illustrative planning target")
ax.set(
    xticks=x,
    xticklabels=results["Baseline"].receivers.receiver,
    ylabel="LAeq (dBA)",
    title="Receiver assessment · conditional 95% input intervals",
)
ax.legend(loc="upper right")
ax.grid(axis="y", alpha=0.2)
fig.tight_layout()
plt.show()

# %%
# Step 4: Rank sources and review room validity
# ---------------------------------------------
# Equipment contributions add by energy, not by adding dB values. The room
# table includes RT60 and a modal caution below the estimated Schroeder limit.
baseline = results["Baseline"]
print(baseline.contributions.sort_values(["receiver", "energy_fraction"]))
print(baseline.room)

# %%
# Step 5: Open the 3D studio and bring measured data
# --------------------------------------------------
# `Open the interactive acoustic studio <../../_static/lab/noise/noise-3d.html>`_.
# Change scenario, band, receiver and section positions. All inputs and field
# arrays are downloadable. See :doc:`../../user_guide/acoustics` for the CSV
# measurement contract, method equations and the limits of this energy model.
