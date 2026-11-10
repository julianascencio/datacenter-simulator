"""
20. CFD accuracy, convergence and input sensitivity
===================================================

Level: Advanced

Step 1: Separate numerical error from uncertain physical inputs
---------------------------------------------------------------
This runnable study keeps the case and comparison time fixed across meshes,
then varies timestep caps and heat/airflow/mixing inputs separately. GCI is
conditional numerical evidence; it is not measured facility validation.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from datacenter_simulator.analysis.cfd_accuracy import export_accuracy_study

study = export_accuracy_study(Path("outputs/cfd-accuracy"))
mesh = pd.DataFrame(study["mesh"])
steps = pd.DataFrame(study["time_steps"])

# %%
# Step 2: Inspect mesh and timestep sensitivity independently
# -----------------------------------------------------------
# Requested timestep caps can be overridden by the adaptive stability limit.
# The CSV retains actual timesteps so an ineffective cap change is visible.
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
for key, label in (("peak_rise_k", "Peak rise"), ("mean_rise_k", "Mean rise")):
    axes[0].plot(mesh.cells, mesh[key], "o-", label=label)
    axes[1].plot(steps.actual_max_dt_s, steps[key], "o-", label=label)
axes[0].set(
    xlabel="Cells", ylabel="Temperature rise (K)", title="Same case, three meshes", xscale="log"
)
axes[1].set(
    xlabel="Actual maximum timestep (s)",
    ylabel="Temperature rise (K)",
    title="Same middle mesh, three timestep caps",
)
for ax in axes:
    ax.grid(alpha=0.2)
    ax.legend()
fig.tight_layout()
plt.show()

# %%
# Step 3: Check GCI eligibility before quoting an error estimate
# --------------------------------------------------------------
# Oscillating or degenerate sequences are rejected. Absolute kelvin error is
# used rather than a misleading percentage of Celsius temperature.
for observable, result in study["gci"].items():
    print(observable, result)
print("Requested timestep caps active:", study["time_caps_effective"])

# %%
# Step 4: Compare uncertainty in loads, airflow and assumed mixing
# ----------------------------------------------------------------
# These perturbations are sensitivity scenarios, not probability distributions.
# Calibrate physical inputs using independent measurements before interpreting
# a visually detailed result as an accurate facility prediction.
sensitivity = pd.DataFrame(study["input_sensitivity"])
fig, ax = plt.subplots(figsize=(11, 5))
ax.barh(sensitivity["case"], sensitivity.peak_rise_k, color="#237e9d", label="Peak rise")
ax.scatter(
    sensitivity.mean_rise_k, sensitivity["case"], color="#d57036", label="Mean rise", zorder=3
)
ax.set(
    xlabel="Temperature rise after 20 s (K)",
    title="Physical-input sensitivity on the same middle mesh",
)
ax.grid(axis="x", alpha=0.2)
ax.legend()
fig.tight_layout()
plt.show()

# %%
# Step 5: Bring independent temperature probes to the model
# ---------------------------------------------------------
# Use ``datacenter-cfd --inputs case-0-inputs.json --measurements probes.csv``
# with time_s,x_m,y_m,z_m,observed_c and optional standard_uncertainty_c.
# See :doc:`../../user_guide/cfd` for fan actuators, return openings and
# assumptions that remain outside the numerical error estimate.
