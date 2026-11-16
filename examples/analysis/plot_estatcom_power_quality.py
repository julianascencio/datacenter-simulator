"""
E-STATCOM: AI load swings, weak-grid voltage and finite storage
===============================================================

**Level:** Advanced | **Subject:** AC power quality and short-duration buffering

Compare identical synthetic aggregate-PCC load profiles with no support,
Q-only STATCOM, finite E-STATCOM and an unlimited auxiliary voltage source
behind finite impedance. The supplied post's 59%/44% improvements are reported
external claims, not calibration data. See :doc:`../../user_guide/power_quality`.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.power_quality import power_quality_study
from datacenter_simulator.methods.power_quality import simulate_power_quality
from datacenter_simulator.models.power_quality import EStatcom, WeakGrid
from datacenter_simulator.use_cases.power_quality import synthetic_ai_load

study = power_quality_study()
print(
    study.comparison[["case", "pcc_active_swing_mw", "voltage_excursion_pu"]].to_string(index=False)
)

# %%
# Power and voltage at consistent boundaries
# ------------------------------------------
# The ideal source supplies sustained energy. Its lower original-grid draw is
# not a storage efficiency gain. Voltage excursion is **not flicker Pst**.
fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
for name, result in study.cases.items():
    f = result.timeseries
    selected = f.time_s <= 15
    axes[0].plot(f.time_s[selected], f.pcc_p_mw[selected], label=name)
    axes[1].plot(f.time_s[selected], f.voltage_pu[selected])
axes[0].set(ylabel="Original-grid PCC power [MW]", title="Synthetic load, 200 MVA base, SCR 4")
axes[0].legend(fontsize=8)
axes[1].set(xlabel="Interval start [s]", ylabel="Balanced PCC voltage [pu]")

# %%
# Shared P-Q rating and finite energy
# -----------------------------------
# Active-power priority can leave less converter capacity for reactive support.
# Charging and discharging losses enter every interval's energy balance.
f = study.cases["estatcom"].timeseries
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
axes[0].plot(f.time_s, f.energy_end_mj)
axes[0].axhline(45.2, linestyle="--", color="gray")
axes[0].axhline(406.8, linestyle="--", color="gray")
axes[0].set(xlabel="Interval start [s]", ylabel="Interval-end energy [MJ]", title="452 MJ nominal")
axes[1].plot(f.time_s, f.support_p_mw, label="P injection [MW]")
axes[1].plot(f.time_s, f.support_q_mvar, label="Q injection [Mvar]")
axes[1].set(xlabel="Interval start [s]", title="Negative Q absorbs reactive power")
axes[1].legend()

# %%
# Independent power/energy sizing across two profiles and three SCR values
# ------------------------------------------------------------------------
# Every failed case remains in the result. Targets (60 MW, 0.025 pu) are
# illustrative planning screens; passing is not flicker or grid compliance.
counts = study.sizing.groupby(["nominal_energy_mj", "rating_mva"]).screen_pass.sum().unstack()
fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
im = ax.imshow(counts.to_numpy(), vmin=0, vmax=6, cmap="Blues", origin="lower", aspect="auto")
ax.set_xticks(range(len(counts.columns)), labels=[f"{x:g}" for x in counts.columns])
ax.set_yticks(range(len(counts.index)), labels=[f"{x:g}" for x in counts.index])
for i in range(len(counts.index)):
    for j in range(len(counts.columns)):
        ax.text(j, i, f"{int(counts.iloc[i, j])}/6", ha="center", va="center", color="#c24b00")
ax.set(
    xlabel="Converter rating [MVA]",
    ylabel="Nominal energy [MJ]",
    title="Test cases passing both screens",
)
fig.colorbar(im, ax=ax, label="Passing cases")

# %%
# A sustained increase cannot be buffered indefinitely
# ----------------------------------------------------
# This stress case is separate from the pulse-sizing envelope. Terminal energy
# is tracked rather than treated as free operating savings.
stress = simulate_power_quality(synthetic_ai_load(shape="sustained"), WeakGrid(), EStatcom())
f = stress.timeseries
fig, ax = plt.subplots(figsize=(9, 3.5), layout="constrained")
ax.plot(f.time_s, f.load_mw, label="Facility load")
ax.plot(f.time_s, f.pcc_p_mw, label="PCC draw with E-STATCOM")
ax.set(xlabel="Interval start [s]", ylabel="MW", title="Sustained-load limitation")
ax.legend()

# %%
# Run the CLI for CSV/JSON and an offline interactive report. External validated
# flickermeter results may be imported with ``--flicker``; the contract requires
# AB/BC/CA for each complete 600 s window and reports the worst channel. No Pst
# is invented from the balanced voltage trace.
#
# :download:`Open the offline report </_static/lab/power-quality/power-quality.html>`.
