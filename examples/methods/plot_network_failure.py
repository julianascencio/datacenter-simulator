"""
04. Communication routing, failure and saturation
=========================================================

**Level:** Intermediate | **Subject:** Communication networks

Trace normal and failed-link routes, distinguish disconnection from overload,
and inspect directional link utilization. Prerequisite: understand network
nodes, links and traffic demand. Latency is a lower bound without queueing.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.methods.communications import Traffic
from datacenter_simulator.use_cases import reference_center

# %%
# Step 1: send traffic through a redundant network
# --------------------------------------------------------
# A rack has two uplinks. The deterministic router chooses one shortest-latency
# path, not equal-cost multipath routing or a packet-level protocol simulation.
network = reference_center().communications
traffic = [Traffic("rack-01", "rack-08", 80)]
normal = network.evaluate(traffic)

# %%
# Step 2: fail one uplink, then both
# ------------------------------------------
# One failed uplink permits rerouting. Losing both makes the source unreachable;
# a disconnected flow has no meaningful latency and is not plotted as zero.
failed = network.evaluate(traffic, failed_links=frozenset({"rack-01-a"}))
disconnected = network.evaluate(traffic, failed_links=frozenset({"rack-01-a", "rack-01-b"}))
print("Normal:", normal.flows.iloc[0].path)
print("Failover:", failed.flows.iloc[0].path)
print("Both uplinks lost:", disconnected.warnings)
assert not disconnected.flows.iloc[0].reachable

fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.bar(
    ["Normal route", "Single-link failure"],
    [normal.flows.iloc[0].latency_lower_bound_ms, failed.flows.iloc[0].latency_lower_bound_ms],
    color=["#2f6fdb", "#d99241"],
)
ax.set(ylabel="End-to-end latency lower bound [ms]")

# %%
# Step 3: increase offered traffic past link capacity
# -----------------------------------------------------------
# Overload is different from losing connectivity: a route still exists, but its
# offered traffic exceeds capacity. Full-duplex directions are tracked separately.
saturated = network.evaluate([Traffic("rack-01", "rack-08", 140)])
active = saturated.links[saturated.links.offered_gbps > 0]
fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.bar(
    [f"{row.source} → {row.target}" for row in active.itertuples()],
    active.utilization * 100,
    color="#b2414e",
)
ax.axhline(100, linestyle="--", color="#333333", label="Rated capacity")
ax.set(ylabel="Offered traffic / directional capacity [%]")
ax.legend()
print("Overload flags:", saturated.warnings)
assert saturated.warnings

# %%
# Saturation does not automatically reduce IT power or simulate delivered
# throughput. Those couplings require a workload/packet model beyond this example.
