"""
Local opposition and development economics
=========================================

Intermediate, offline, synthetic business case inspired by the user-supplied
Heatmap article dated October 6, 2026. Aggregate reported canceled investment
is not cash lost and does not calibrate individual-site risk. Compare explicit
assumptions for mitigation and relocation, including mitigation with no benefit.
See :doc:`/user_guide/development` for timing, exclusions and provenance.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.methods.development import evaluate_development
from datacenter_simulator.use_cases.development import development_scenarios

scenarios = development_scenarios()
values = [evaluate_development(s).expected_npv_usd / 1e6 for s in scenarios]
fig, ax = plt.subplots(figsize=(8, 4))
ax.barh([s.name for s in scenarios], values)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_xlabel("Expected NPV (million USD), synthetic assumptions")
fig.tight_layout()
plt.show()
