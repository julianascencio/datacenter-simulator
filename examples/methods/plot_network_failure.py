"""
Communication failover and saturation
=============================================

The reference rack has two uplinks. Remove its preferred uplink and inspect the
alternate route. Latency is only a lower bound: queueing is not simulated.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.methods.communications import Traffic
from datacenter_simulator.use_cases import reference_center

network = reference_center().communications
traffic = [Traffic("rack-01", "rack-08", 80)]
normal = network.evaluate(traffic)
failed = network.evaluate(traffic, failed_links=frozenset({"rack-01-a"}))
disconnected = network.evaluate(traffic, failed_links=frozenset({"rack-01-a", "rack-01-b"}))
print("Normal:", normal.flows.iloc[0].path)
print("Failover:", failed.flows.iloc[0].path)
print("Both uplinks lost:", disconnected.warnings)

fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.bar(
    ["Normal route", "Single-link failure"],
    [normal.flows.iloc[0].latency_lower_bound_ms, failed.flows.iloc[0].latency_lower_bound_ms],
    color=["#148d83", "#d99241"],
)
ax.set(ylabel="End-to-end latency lower bound [ms]")
