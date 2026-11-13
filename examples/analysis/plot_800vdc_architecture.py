"""
800 VDC migration: conversion, copper, backup and fault energy
==============================================================

**Level:** Intermediate | **Subject:** AI data-center power architecture

Compare a synthetic 5 MW hall at the same low-voltage IT DC terminal. The
manufacturer literature motivates the topologies; every efficiency is an
illustrative input. This is not a reconstruction of the Ulanqab installation.

The conversion, conductor and fault studies have separate boundaries. A low
fault-screen value does not establish safe arc-flash exposure or certification.
See :doc:`../../user_guide/power_architecture` for equations and evidence.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.power_architecture import power_architecture_study

study = power_architecture_study()
print(
    study.architectures[["architecture", "input_kw", "input_energy_saving_pct"]].to_string(
        index=False
    )
)

# %%
# Step 1: compare conversion paths and efficiency assumptions
# ------------------------------------------------------------
# The sidecar and row presets retain the transformer and AC UPS. Their identical
# conversion totals do not imply identical cabling or protection. Central SST
# includes internal conversion losses and still supplies a rack DC/DC stage.
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
labels = ["AC", "Sidecar", "Row", "Central SST"]
axes[0].bar(labels, study.architectures.conversion_loss_kw, color="#247b91")
axes[0].set(ylabel="Conversion loss [kW]", title="Fixed 5 MW IT demand")
axes[1].plot(
    study.efficiency_sensitivity.sst_efficiency * 100,
    study.efficiency_sensitivity.input_energy_saving_pct,
    "o-",
    color="#247b91",
)
axes[1].axhline(0, color="black", linewidth=0.8)
axes[1].set(
    xlabel="Assumed SST efficiency [%]",
    ylabel="Input energy saving vs AC [%]",
    title="Savings can change sign",
)

# %%
# Step 2: compare a fixed-geometry 1 MW DC conductor
# --------------------------------------------------
# The ideal P/V figures are 18,519 A at 54 V and 1,250 A at 800 V. Solved
# current is slightly higher because the receiving voltage falls. The same
# hypothetical 2 m, 1000 mm²-per-pole conductor is overloaded at 54 V; it is
# not a compliant cable selection. Do not compare these DC values with AC
# line current without the three-phase voltage and power-factor relationship.
print(study.conductors.to_string(index=False))
fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), layout="constrained")
axes[0].bar(
    study.conductors.voltage_v.astype(str),
    study.conductors.current_a,
    color=["#c05746", "#247b91", "#247b91"],
)
axes[0].axhline(2000, color="#555555", linestyle="--", label="Assumed current rating")
axes[0].set(xlabel="Sending voltage [V DC]", ylabel="Current [A]")
axes[0].legend()
axes[1].bar(study.conductors.voltage_v.astype(str), study.conductors.loss_kw, color="#247b91")
axes[1].set(xlabel="Sending voltage [V DC]", ylabel="Two-wire copper loss [kW]")

# %%
# Step 3: size backup power, energy and capacitor hold-up
# -------------------------------------------------------
# The DC bus includes rack DC/DC losses. Battery sizing gives separate energy
# and power minima for 60 seconds, using 96% discharge efficiency and an 80%
# available SOC window. The capacitor calculation is an independent 20 ms
# hold-up requirement for 800 -> 720 V. Battery and capacitor durations are not
# subtracted from one another or assumed to implement a hybrid controller.
print("DC backup requirements:", study.backup)

# %%
# Step 4: screen isolation speed, remote backfeed and local energy
# ----------------------------------------------------------------
# The fixed 20 ms observation covers local capacitor discharge even if the
# upstream paths disconnect earlier. Remote reverse blocking is idealized.
# The vertical axis adds RC energy release and nominal-voltage source energy
# envelopes; it is neither arc energy nor a transient network solution.
fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
for blocked, frame in study.faults.groupby("reverse_blocking"):
    label = "Remote backfeed blocked" if blocked else "Remote backfeed allowed"
    ax.semilogx(frame.clearing_s * 1000, frame.combined_screen_j / 1000, "o-", label=label)
ax.axhline(3.2, linestyle="--", color="#555555", label="Local capacitor: 3.2 kJ")
ax.set(
    xlabel="Ideal isolation time [ms]",
    ylabel="Combined screening index [kJ]",
    title="Synthetic 800 V fault domain; not arc-flash incident energy",
)
ax.legend()

# %%
# Reproduce and customize
# ------------------------
#
# .. code-block:: bash
#
#    python -m datacenter_simulator.analysis.power_architecture --output outputs/power
#    python -m datacenter_simulator.analysis.power_architecture \
#      --inputs outputs/power/inputs.json --output outputs/power-replay
#
# Open the :download:`offline report </_static/lab/power/power-architecture.html>`.
# The guide links the CSV results, replay inputs and source ledger. No hardware,
# network request, GPU library or stochastic seed is required to run this study.
