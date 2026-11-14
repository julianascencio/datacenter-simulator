"""
Local opposition and development economics
==========================================

**Level:** Intermediate | **Subject:** Development risk economics

Offline, synthetic business case inspired by the user-supplied
Heatmap article dated October 6, 2026. Aggregate reported canceled investment
is not cash lost and does not calibrate individual-site risk. Compare explicit
assumptions for mitigation and relocation, including mitigation with no benefit.
See :doc:`/user_guide/development` for timing, exclusions and provenance.
"""

from dataclasses import replace

import matplotlib.pyplot as plt

from datacenter_simulator.methods.development import evaluate_development
from datacenter_simulator.use_cases.development import development_scenarios

# %%
# Step 1: compare explicit development alternatives
# -------------------------------------------------
# Risk reductions are assumptions; mitigation spending alone guarantees no benefit.
scenarios = development_scenarios()
values = [evaluate_development(s).expected_npv_usd / 1e6 for s in scenarios]
fig, ax = plt.subplots(figsize=(8, 4))
ax.barh([s.name for s in scenarios], values)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_xlabel("Expected NPV (million USD), synthetic assumptions")
fig.tight_layout()
plt.show()

# %%
# Step 2: test cancellation-probability sensitivity
# -------------------------------------------------
# Hold each alternative's cash flows and timing fixed. Sweep a hypothetical
# probability instead of deriving site risk from aggregate investment headlines.
probabilities = [i / 20 for i in range(21)]
fig, ax = plt.subplots(figsize=(8, 4))
for scenario in scenarios:
    sensitivity = [
        evaluate_development(replace(scenario, cancellation_probability=p)).expected_npv_usd / 1e6
        for p in probabilities
    ]
    ax.plot(probabilities, sensitivity, label=scenario.name)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xlabel("Assumed cancellation probability")
ax.set_ylabel("Expected NPV (million USD)")
ax.legend(fontsize=8)
fig.tight_layout()
plt.show()
