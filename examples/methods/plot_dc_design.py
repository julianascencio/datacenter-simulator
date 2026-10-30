"""
07. Size a DC feeder with equipment evidence
=============================================

**Level:** Intermediate | **Subject:** DC design and calibration

Question: which voltage and conductor combinations satisfy the same row demand?
The measured CPU benchmark below is kept at its AC measurement boundary. The
separate converter, cable thermal resistance and installation ratings are
illustrative assumptions. No measured GPU or certified ampacity claim is made.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.engineering import dc_design_study
from datacenter_simulator.connectors.performance import specpower_reference
from datacenter_simulator.methods.design import Feeder, solve_feeder
from datacenter_simulator.methods.uncertainty import sample_study
from datacenter_simulator.models.performance import PowerCurve, calibration_errors

# %%
# Step 1: keep measured inputs and held-out observations separate
# -----------------------------------------------------------------
# The published Compal SR224-2A SPECpower result reports AC input power versus
# target benchmark throughput. Train on alternate load points and assess the
# remaining points; this is interpolation validation for one CPU workload.
measured = specpower_reference()
curve = PowerCurve(measured.utilization[::2], measured.power_kw[::2], measured.provenance)
held_out = list(zip(measured.utilization[1::2], measured.power_kw[1::2], strict=True))
print("Evidence:", measured.provenance)
print("Held-out errors:", calibration_errors(curve, held_out))
fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.plot(curve.utilization, curve.power_kw, "o-", label="Interpolation inputs")
ax.scatter(
    [u for u, _ in held_out],
    [p for _, p in held_out],
    marker="x",
    s=80,
    label="Held-out measurements",
)
ax.set(xlabel="Target benchmark throughput fraction", ylabel="Measured AC input [kW]")
ax.legend()

# %%
# Step 2: sweep voltage and conductor section
# ------------------------------------------------
# The study uses routed lengths from engineering_layout(), a 180 kW DC load,
# an explicit converter efficiency surface, and a self-consistent I²R thermal
# balance. Failed candidates remain visible instead of disappearing.
results = dc_design_study()
print(
    results[["voltage_v", "area_mm2", "temperature_c", "feasible", "warnings"]].to_string(
        index=False
    )
)
fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
for voltage, frame in results.groupby("voltage_v"):
    axes[0].plot(frame.area_mm2, frame.cable_loss_kw, "o-", label=f"{voltage} V")
    axes[1].plot(frame.area_mm2, frame.temperature_c, "o-", label=f"{voltage} V")
    rejected = frame.loc[~frame.feasible]
    axes[0].scatter(rejected.area_mm2, rejected.cable_loss_kw, marker="x", s=110, color="crimson")
axes[0].set(xlabel="Copper section [mm² per conductor]", ylabel="Cable loss [kW]")
axes[1].set(xlabel="Copper section [mm² per conductor]", ylabel="Conductor equilibrium [°C]")
for ax in axes:
    ax.legend()

# %%
# Step 3: propagate explicit uncertainty assumptions
# ---------------------------------------------------------
# These uniform ranges are a sensitivity experiment, not confidence intervals.
# Replace thermal resistance and ampacity with installation-specific evidence.
samples = sample_study(
    {"ambient_c": (20, 40), "thermal_resistance": (0.01, 0.03)},
    lambda p: (
        solve_feeder(
            Feeder(20, 120, 300, p["thermal_resistance"]), 400, 50, ambient_c=p["ambient_c"]
        ).temperature_c
    ),
    samples=100,
    seed=42,
)
fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.hist(samples.loc[samples.feasible, "value"], bins=15, color="#148d83")
ax.set(xlabel="Cable equilibrium under sampled assumptions [°C]", ylabel="Cases")

# %%
# Validation and interpretation
# -------------------------------------
# Analytical two-bus solutions, thermal equilibrium and energy conservation are
# tested independently. The 800 V case is a two-wire pole-pair equivalent; it does
# not represent midpoint imbalance, grounding or DC protection.
#
# References: :doc:`../../research/engineering` and :doc:`../../user_guide/engineering`.
