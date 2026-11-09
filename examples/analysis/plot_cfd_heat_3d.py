"""
19. Simulate three-dimensional airflow and rack heat
====================================================

Level: Advanced

Solve incompressible momentum, pressure and temperature on a staggered 3D grid.
This is a transient research CFD model with declared effective mixing and porous
rack approximations. Numerical verification is separate from site validation.

`Open the interactive CFD simulator <../../_static/lab/cfd/cfd-3d.html>`_.
"""

# %%
# Step 1: define the room, supply boundary and volumetric rack heat sources.
# The four racks release 12 kW into air. Heat removed directly by liquid must
# be excluded from these source powers.
from dataclasses import replace

import matplotlib.pyplot as plt
import numpy as np

from datacenter_simulator.methods.cfd import cell_coordinates, simulate_cfd
from datacenter_simulator.use_cases.cfd import reference_cfd_case

case = reference_cfd_case()
print("Cells:", case.grid.shape, "Air heat kW:", sum(s.heat_kw for s in case.sources))

# %%
# Step 2: integrate velocity, pressure correction, buoyancy and conservative
# temperature transport. The solver chooses stable timesteps and stores frames.
normal = simulate_cfd(case)
half = simulate_cfd(replace(case, settings=replace(case.settings, supply_flow_m3_s=1)))
print(normal.summary)

# %%
# Step 3: compare actual temperature slices with a shared scale. Halving flow
# changes the solved velocity and pressure fields as well as heat removal.
x, y, z = cell_coordinates(case.grid)
k = int(np.argmin(np.abs(z - 1.2)))
maximum = max(r.snapshots[-1].temperature_c.max() for r in (normal, half))
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
for ax, result, title in zip(axes, (normal, half), ("Normal airflow", "Half airflow"), strict=True):
    final = result.snapshots[-1]
    im = ax.pcolormesh(
        x,
        y,
        final.temperature_c[:, :, k].T,
        shading="nearest",
        cmap="inferno",
        vmin=20,
        vmax=maximum,
    )
    ax.quiver(
        x[::2],
        y[::2],
        final.velocity_m_s[0][::2, ::2, k].T,
        final.velocity_m_s[1][::2, ::2, k].T,
        color="cyan",
        scale=5,
    )
    for source in case.sources:
        ax.add_patch(
            plt.Rectangle(
                (source.x_m, source.y_m),
                source.width_m,
                source.depth_m,
                fill=False,
                edgecolor="white",
                linewidth=1,
            )
        )
    ax.set(title=f"{title} at {final.time_s:g} s / z={z[k]:.2f} m", xlabel="x (m)", ylabel="y (m)")
    ax.set_aspect("equal")
fig.colorbar(im, ax=axes, label="Air temperature (°C)", shrink=0.85)

# %%
# Step 4: inspect the vertical thermal plume, then audit transient heat storage.
# Input heat = stored heat + integrated net outward boundary heat at every step.
j = int(np.argmin(np.abs(y - 2)))
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), layout="constrained")
im = axes[0].pcolormesh(
    x,
    z,
    normal.snapshots[-1].temperature_c[:, j, :].T,
    cmap="inferno",
    vmin=20,
    vmax=maximum,
    shading="nearest",
)
axes[0].set(xlabel="x (m)", ylabel="Height z (m)", title=f"Vertical section at y={y[j]:.2f} m")
fig.colorbar(im, ax=axes[0], label="°C")
h = normal.history
axes[1].plot(h.time_s, h.heat_source_w * h.time_s / 1e6, label="Input heat")
axes[1].plot(h.time_s, h.stored_heat_j / 1e6, label="Stored in room air")
axes[1].plot(h.time_s, h.cumulative_heat_out_j / 1e6, label="Net removed")
axes[1].set(xlabel="Time (s)", ylabel="MJ", title="Conservative heat budget")
axes[1].legend()
print("Maximum divergence 1/s:", normal.summary["max_divergence_per_s"])
print("Relative energy closure:", normal.summary["relative_energy_balance_error"])

# %%
# Step 5: produce an offline 3D player, field/slice selectors and numerical exports.
# This command also reruns coarse/base/fine grids; sensitivity is not a claim of
# mesh-independent or measured accuracy. NPZ stores all frames; VTK opens in ParaView.
#
# ``python -m datacenter_simulator.analysis.cfd --mesh-study --output outputs/cfd``
#
# To connect an existing design, use ``cfd_from_design(design,
# air_heat_fraction=0.15)`` and explicitly specify supply flow in CFDSettings.
# The fraction is heat released to room air, not a facility liquid-loop fraction.
plt.show()
