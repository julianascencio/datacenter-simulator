"""
Faraday: utility-linked storage for a data center
================================================

**Level:** Advanced | **Subject:** Off-site storage and hourly supply matching

The November 2026 Faraday announcement motivates this reproducible case.
Reported asset ratings are combined with explicit synthetic load/resource inputs,
not reconstructed Meta operations. See :doc:`../../user_guide/faraday` for
equations, primary evidence and the distinction between procurement and backup.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.faraday import faraday_study

# %%
# Step 1: establish separate generation and customer meters
# --------------------------------------------------------
# Assume 160 MW IT and PUE 1.25: 200 MW facility demand. Solar is a synthetic
# 525 MW AC peak profile; its actual AC/DC basis and allocation are not verified.
# The assumed 525 MW shared POI constrains combined solar and battery export.
study = faraday_study()
print(
    study.comparison[
        ["scenario", "matched_energy_mwh", "hourly_matched_fraction", "facility_meter_peak_mw"]
    ].to_string(index=False)
)
fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
names = ["Grid", "Solar", "600 MWh", "733 MWh*", "2,100 MWh*", "Low solar*"]
ax.bar(names, study.comparison.hourly_matched_fraction * 100, color="#008d82")
ax.set(ylabel="Matched facility energy [%]", ylim=(0, 100), title="Synthetic 168-hour study")
ax.text(0.01, 0.95, "*Sensitivity / proposed expansion / stress", transform=ax.transAxes)

# %%
# Step 2: inspect solar-only charging and the energy inventory
# ----------------------------------------------------------
# Treat 600 MWh as the AC deliverable window. The existing Battery model stores
# internal energy, so its window is 600 / eta_discharge MWh. It can deliver
# 150 MW for four hours when full. This is not inferred installed cell capacity.
# Start with no usable energy; final inventory never counts as delivered energy.
frame = study.results["phase1_600mwh"].timeseries.iloc[:72]
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
for column, label in (
    ("facility_utility_import_kw", "Customer utility meter"),
    ("matched_kw", "Matched supply"),
    ("residual_unmatched_kw", "Residual unmatched"),
):
    axes[0].plot(frame.index, frame[column] / 1000, label=label)
axes[0].set(ylabel="MW", title="Utility imports stay at 200 MW")
axes[0].legend(loc="upper right")
axes[1].plot(frame.index, frame.battery_energy_kwh / 1000, color="#855bb1")
axes[1].set(ylabel="Internal inventory [MWh]", xlabel="Timestamp")
fig.autofmt_xdate()

# %%
# Step 3: examine load and shared connection sensitivities
# -------------------------------------------------------
# The 733 MWh report is retained as an alternative energy assumption, not a
# proven nameplate-to-contract conversion. The combined expansion adds the
# proposed 375 MW / 1,500 MWh to the operating phase. Neither is the baseline.
print(
    study.sensitivity[
        ["load_multiplier", "poi_export_mw", "hourly_matched_fraction", "curtailed_mwh"]
    ].to_string(index=False)
)

# %%
# Step 4: reproduce the interactive report or replace the profiles
# --------------------------------------------------------------
#
# .. code-block:: bash
#
#    python -m datacenter_simulator.analysis.faraday --output outputs/faraday
#    python -m datacenter_simulator.analysis.faraday \
#      --inputs outputs/faraday/inputs.json --profiles outputs/faraday/profiles.csv \
#      --output outputs/faraday-replay
#
# Open the :download:`interactive report </_static/lab/faraday/faraday-storage.html>`.
# Schedule 34 is not modeled as a universal fixed tariff. Hourly energy matching
# does not certify REC ownership, supply reliability or on-site backup autonomy.
