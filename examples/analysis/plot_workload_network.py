"""
12. Measure the energy cost of network congestion
===================================================

**Level:** Advanced | **Subject:** workloads, communications and thermal response

Question: does completing the same work require more energy on a slower fabric?
Four identical jobs alternate compute and 20 GB transfer phases. Compute power,
waiting utilization and thermal coefficients are illustrative. Transfers use
max-min fair fluid sharing over equal-cost paths, not a packet/TCP simulator.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.analysis.engineering import network_workload_study
from datacenter_simulator.methods.communications import CommunicationNetwork
from datacenter_simulator.methods.workloads import (
    ComputeDevice,
    Job,
    JobPhase,
    schedule_carbon_aware,
    simulate_workloads,
)
from datacenter_simulator.models.devices import Electrical

# %%
# Step 1: execute identical jobs under four operating conditions
# -------------------------------------------------------------------
# Faster networks shorten the waiting phase. Energy is integrated until the last
# job completes, including idle devices during that period; unfinished work would
# be reported separately. External storage and switch electricity are excluded.
results = network_workload_study()
for name, result in results.items():
    print(name, result.summary)
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
labels = list(results)
axes[0].bar(labels, [r.summary["elapsed_s"] for r in results.values()], color="#2f6fdb")
axes[1].bar(
    labels,
    [r.summary["energy_per_completed_job_kwh"] * 1000 for r in results.values()],
    color="#148d83",
)
axes[0].set(ylabel="Time to complete the batch [s]")
axes[1].set(ylabel="Terminal energy per completed job [Wh]")
for ax in axes:
    ax.tick_params(axis="x", rotation=20)

# %%
# Step 2: inspect link loading and coupled rack heat
# --------------------------------------------------------
failed = results["10 Gbps + link failure"]
fig, axes = plt.subplots(2, 1, figsize=(10, 6), layout="constrained")
for link in ("uplink-a", "uplink-b"):
    frame = failed.links.loc[(failed.links.link == link) & (failed.links.direction == 0)]
    axes[0].step(frame.time_s, frame.used_gbps, where="post", label=link)
axes[0].set(xlabel="Time [s]", ylabel="Allocated bandwidth [Gbps]")
axes[0].legend()
for name, result in results.items():
    rack = result.devices.loc[result.devices.equipment_id == "rack-01"]
    axes[1].plot(rack.time_s + rack.duration_s, rack.temperature_c, label=name)
axes[1].set(xlabel="Time [s]", ylabel="Rack-zone temperature [°C]")
axes[1].legend(fontsize=8)

# %%
# Step 3: demonstrate deadline-aware admission
# -------------------------------------------------
# A nonpreemptive earliest-deadline-first scheduler admits the short urgent job
# before a long batch job when both are ready. Once running, jobs are not migrated.
network = CommunicationNetwork(["rack"], [])
device = ComputeDevice("rack", Electrical(400, 5, 25), 30)
jobs = [
    Job("a-batch", "rack", (JobPhase("compute", 30),), deadline_s=100),
    Job("b-urgent", "rack", (JobPhase("compute", 5),), deadline_s=10),
]
for scheduler in ("fifo", "edf"):
    run = simulate_workloads(network, [device], jobs, scheduler=scheduler)
    print(scheduler, run.jobs[["completion_s", "deadline_missed"]].to_dict("index"))

# %%
# Validation includes analytical shared-link completion times, bandwidth limits,
# exact phase boundaries, energy integration and thermal timestep sensitivity.
# Packet loss and latency percentiles require an external packet simulation.

# %%
# Step 4: schedule flexible work against a carbon forecast
# -------------------------------------------------------------
# Planning reserves whole slots with a declared power estimate. Replaying the
# scheduled jobs resolves actual phases and congestion; it can reveal violations
# of optimistic transfer-duration estimates. Carbon factors below are synthetic.
flexible = [
    Job("flex-1", "rack", (JobPhase("compute", 20),), deadline_s=120),
    Job("flex-2", "rack", (JobPhase("compute", 20),), deadline_s=120),
]
carbon = [0.7, 0.5, 0.1, 0.15, 0.4, 0.8]
plan = schedule_carbon_aware(flexible, carbon, {"rack": 25}, slot_s=20)
replayed = simulate_workloads(network, [device], list(plan.jobs))
print("Scheduled starts and estimated emissions:", plan.plan.to_dict("index"))
print("Replay deadline misses:", replayed.summary["deadline_misses"])
fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.bar([0, 20, 40, 60, 80, 100], carbon, width=18, color="#627ea2")
for row in plan.plan.itertuples():
    ax.axvspan(row.start_s, row.reserved_end_s, alpha=0.15, color="green")
ax.set(
    xlabel="Planning time [s] · green spans are scheduled work", ylabel="Grid factor [kg CO₂/kWh]"
)
