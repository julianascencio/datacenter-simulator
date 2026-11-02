"""
Batch inference under GPU power limits, solar generation, battery storage and electricity prices
================================================================================================

Level: Advanced

**Evidence:** synthetic GPU traces, throughput points, jobs, weather, prices and
PV; simulated facility and optimization results. No measured GPU performance is
claimed. This tutorial answers how equal useful work changes facility energy and
cost under explicitly declared electrical and cooling constraints.

Step 1 — Integrate and align a short trace without inventing missing measurements
---------------------------------------------------------------------------------

CSV + JSON sidecar traces replay without NVIDIA libraries. Counter differences
are preferred; otherwise endpoint power uses trapezoidal integration. Interval
resampling preserves energy, including explicit zero padding of the final bin.
A missing internal measurement is rejected instead of filled with zero.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from datacenter_simulator.models.gpu import server_terminal_power
from datacenter_simulator.simulation import simulate
from datacenter_simulator.use_cases.gpu_lab import (
    compare_policies,
    gpu_scenario,
    sensitivity_study,
    synthetic_trace,
)

trace = synthetic_trace()
profile = trace.replay(step_s=2, max_gap_s=5)
print("SYNTHETIC board energy [J]:", profile.sum() * 2 * 1000)
fig, axes = plt.subplots(2, 1, figsize=(9, 5), sharex=True, layout="constrained")
axes[0].plot(trace.samples.elapsed_s, trace.samples.power_w, "o-", label="Synthetic power")
axes[0].set(ylabel="GPU board [W]", title="SYNTHETIC trace • not a hardware measurement")
axes[1].plot(trace.samples.elapsed_s, trace.samples.temperature_c, "o-", color="tab:red")
axes[1].set(xlabel="Elapsed [s]", ylabel="Temperature [°C]")

# %%
# Step 2 — Respect board, server and facility measurement boundaries
# ------------------------------------------------------------------
# Declare 120 W for CPU/memory/fans and 94% internal DC conversion. A server-level
# trace would already contain these demands and must not have them added again.
# The existing facility API adds DC network losses, rectification and cooling once.
# Short replay is demonstrated separately; it is NOT silently repeated for 24 h.

center, conditions, jobs, model, battery = gpu_scenario()
terminal = server_terminal_power(
    profile, boundary="gpu_board", other_server_kw=0.12, internal_efficiency=0.94
)
short_conditions = pd.DataFrame({"utilization": 0.0, "ambient_c": 25.0}, index=profile.index)
short_run = simulate(
    center, short_conditions, device_power_kw=terminal.to_frame("gpu-server"), dt_hours=2 / 3600
)
print("SIMULATED short replay facility energy [J]:", short_run.summary["facility_kwh"] * 3.6e6)

# %%
# Step 3 — Keep throughput, consumed power and configured limit distinct
# ----------------------------------------------------------------------
# Bounded interpolation is allowed only inside one configuration and quality ID.
# These points are invented to exercise the workflow, not a fit to any GPU.
# The efficient setting minimizes GPU-board J/task among observed points; the
# facility optimum can differ because slower work consumes server baseline power.

points = model.points
fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
axes[0].plot([p.board_power_w for p in points], [p.tasks_per_s for p in points], "o-")
for point in points:
    axes[0].annotate(
        f"{point.power_limit_w:g} W limit",
        (point.board_power_w, point.tasks_per_s),
        xytext=(0, -17),
        textcoords="offset points",
        fontsize=8,
    )
axes[0].set(
    xlabel="GPU-board demand [W]", ylabel="Input records / s", title="SYNTHETIC performance"
)
axes[1].bar(
    [str(p.power_limit_w) for p in points], [p.board_power_w / p.tasks_per_s for p in points]
)
axes[1].set(
    xlabel="Configured limit [W]",
    ylabel="Board energy [J / input record]",
    title="Equal model, precision, inputs and quality",
)

# %%
# Step 4 — Compare identical jobs and battery endpoints under four policies
# -------------------------------------------------------------------------
# Job phases retain the existing API's compute-seconds contract; inference_job
# converts fixed task counts using the default observation. Duration at another
# setting is task_count / throughput. Starts are on 30-minute slots; partial final
# slots use idle/active endpoint averages and reserve the GPU until the next slot.
# All policies use the same battery dispatch optimizer after fixing the schedule.
# The coordinated policy first jointly selects schedule, power setting and battery
# dispatch in that same MILP. Thus the other policies are sequential baselines.
# Every plan starts and ends at 50% SOC; storage cannot create a free-energy win.

results = compare_policies()
summary = pd.DataFrame([r.summary for r in results.values()]).set_index("policy")
print(
    summary[
        [
            "completed_tasks",
            "unfinished_jobs",
            "deadline_misses",
            "feasible",
            "facility_kwh",
            "energy_cost",
        ]
    ].to_string()
)
fig, axes = plt.subplots(4, 1, figsize=(11, 9), sharex=True, layout="constrained")
for ax, (policy, result) in zip(axes, results.items(), strict=True):
    for i, (_, row) in enumerate(result.jobs.iterrows()):
        if np.isfinite(row.start_s):
            ax.broken_barh(
                [(row.start_s / 3600, (row.planned_completion_s - row.start_s) / 3600)],
                (i - 0.3, 0.6),
                facecolors="tab:blue" if row.completed else "tab:red",
            )
        ax.plot(row.release_s / 3600, i, ">", color="tab:green")
        ax.plot(row.deadline_s / 3600, i, "|", color="black", markersize=12)
    ax.set(yticks=range(len(jobs)), yticklabels=[j.id for j in jobs], title=f"SIMULATED • {policy}")
axes[-1].set(xlabel="Hour [UTC] • green: release • black: deadline", xlim=(0, 24))

# %%
# Step 5 — Inspect facility supply, losses, cooling and SOC together
# ------------------------------------------------------------------
# PV and battery power are at the common AC facility bus. Battery efficiency
# already includes its declared conversion boundary. No second inverter penalty
# is applied. Room cooling capacity is a hard scheduling limit; no silicon thermal
# throttling law is inferred from rack temperature. Short experiments are extended
# using constant throughput/power at a matching configuration and adequate cooling.

coordinated = results["coordinated"].facility.timeseries
fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, layout="constrained")
hour = np.arange(len(coordinated)) / 2
for col, label in (
    ("facility_kw", "Facility"),
    ("generation_kw", "PV"),
    ("grid_import_kw", "Grid"),
):
    axes[0].step(hour, coordinated[col], where="post", label=label)
axes[0].axhline(0.55, ls="--", color="red", label="Grid limit")
axes[0].set(ylabel="Power [kW]", title="SIMULATED coordinated policy • synthetic inputs")
axes[0].legend(ncol=4)
axes[1].step(hour, coordinated.battery_energy_kwh / battery.capacity_kwh, where="post")
axes[1].axhline(battery.initial_soc, ls="--", color="black")
axes[1].set(ylabel="Battery SOC", ylim=(0, 1))
for col, label in (
    ("dc_loss_kw", "DC loss"),
    ("rectifier_loss_kw", "Rectifier"),
    ("cooling_kw", "Cooling"),
):
    axes[2].step(hour, coordinated[col], where="post", label=label)
axes[2].set(ylabel="Contribution [kW]", xlabel="Hour [UTC]")
axes[2].legend(ncol=3)

# %%
# Step 6 — Report cost only alongside delivered work and deadline evidence
# ------------------------------------------------------------------------
# Unfinished or supply/thermal-invalid jobs are explicit. No per-task facility
# energy is reported when some requested jobs are unfinished. A job overlapping
# a supply shortfall receives zero validated tasks: partial-job checkpointing is
# not modelled. The cost here is electricity only; the optimizer additionally
# includes the same small storage-throughput wear term for every policy.

fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
short_labels = ["Default", "Efficient", "Price", "Joint"]
for ax, col, title in zip(
    axes,
    ["energy_cost", "completed_tasks", "facility_energy_per_task_j"],
    ["Electricity cost [EUR]", "Completed input records", "Facility J / record"],
    strict=True,
):
    ax.bar(short_labels, summary[col])
    ax.set(title=title)
    ax.tick_params(axis="x", rotation=25)
fig.suptitle("SIMULATED comparison • equal requested work and battery endpoints")

# %%
# Step 7 — Sensitivity and forecast-error replay
# ----------------------------------------------
# Tariff/PV/throughput sensitivities reoptimize and are perfect-foresight comparisons.
# In contrast, forecast-error replay freezes BOTH the original job schedule and
# battery commands, halves PV and shifts the realized tariff by two hours. Imports
# adapt within their cap; deficits and invalidated completions remain visible.
# This is a stress test, not a forecast accuracy claim or a feedback controller.

sensitivity = sensitivity_study()
print(
    sensitivity[
        [
            "scenario",
            "policy",
            "energy_cost",
            "completed_tasks",
            "unfinished_jobs",
            "deadline_misses",
            "unserved_kwh",
            "feasible",
        ]
    ].to_string(index=False)
)
fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
for ax, column, ylabel in (
    (axes[0], "energy_cost", "Electricity cost [EUR]"),
    (axes[1], "completed_tasks", "Validated completed records"),
):
    pivot = sensitivity.pivot(index="scenario", columns="policy", values=column)
    pivot.plot.bar(ax=ax, rot=25)
    ax.set(ylabel=ylabel, xlabel="", title="SIMULATED sensitivity")
    ax.legend(fontsize=7)

# %%
# Collect real evidence separately
# --------------------------------
# Run ``python -m datacenter_simulator.gpu_lab benchmark --help`` on a supported
# CUDA host; follow :doc:`/user_guide/gpu_lab` for exact read-only and power-limit
# commands. Hardware evidence, wall-meter calibration, long-run thermal validation
# and workload representativeness remain pending. This documentation build never
# downloads models/datasets and never initializes NVML, Zeus or CUDA.
#
# Created by ASVA Consulting. AI-assisted implementation; review and measurement
# validation remain necessary. No NVIDIA endorsement is implied.

plt.show()
