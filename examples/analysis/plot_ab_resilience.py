"""
08. Survive a feed failure with A/B supplies
============================================

**Level:** Advanced | **Subject:** electrical and cooling resilience

Question: what survives a feed, module, cooling or shared-upstream failure?
Four illustrative racks share three 100 kW modules per feed. The CDU takes power
from feed B. Transfer delay is 2 s and hold-up is 0.2 s; they are assumptions,
not manufacturer specifications. Common dependencies are represented explicitly.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.engineering import resilience_study

# %%
# Step 1: run event-resolved supply and thermal balances
# ------------------------------------------------------------
# Every event boundary and transfer deadline splits the integration interval.
# Racks retain the surviving feed after restoration; automatic failback is absent.
result = resilience_study("feed")
print(result.summary)
fig, ax = plt.subplots(figsize=(9, 3.5), layout="constrained")
for name, frame in result.feeds.groupby("feed"):
    ax.step(frame.time_s, frame.delivered_kw, where="post", label=name)
ax.step(result.timeline.time_s, result.timeline.hold_up_kw, where="post", label="PSU hold-up")
ax.set(xlabel="Time [s]", ylabel="Delivered power [kW]")
ax.legend()

# %%
# Step 2: distinguish redundant equipment from shared dependencies
# ---------------------------------------------------------------------
# A lost module leaves sufficient N+1 capacity here. A shared upstream event
# disables both feeds and the electrically dependent CDU.
cases = {name: resilience_study(name) for name in ("module", "feed", "common", "cooling")}
fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
axes[0].bar(list(cases), [r.summary["unserved_kwh"] for r in cases.values()], color="#2f6fdb")
axes[0].set(ylabel="Unserved terminal energy [kWh]")
for name, run in cases.items():
    rack = run.racks.loc[run.racks.equipment_id == "rack-01"]
    axes[1].plot(rack.time_s + rack.duration_s, rack.temperature_c, label=name)
axes[1].set(xlabel="Time [s]", ylabel="Rack-zone temperature [°C]")
axes[1].legend()

# %%
# Step 3: inspect timestep sensitivity and connected diagrams
# ----------------------------------------------------------------
# Electrical event energy is exact at event boundaries. Thermal control is a
# lumped approximation, so check whether a smaller integration step changes it.
finer = resilience_study("feed", step_s=0.5)
print("Energy difference [kWh]:", finer.summary["unserved_kwh"] - result.summary["unserved_kwh"])
print(
    "Peak temperature difference [K]:",
    finer.summary["peak_temperature_c"] - result.summary["peak_temperature_c"],
)

# %%
# `Open the linked engineering lab <../../_static/lab/engineering-lab.html>`_
# for the animated A/B schematic, cooling/network schemas and 2D/3D equipment.
# Selecting a rack highlights its connections in every view.
#
# This capacity/transfer model does not infer failure probabilities, breaker
# operation or voltage transients. Hold-up energy is counted separately.
