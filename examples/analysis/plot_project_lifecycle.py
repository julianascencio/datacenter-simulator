"""
Which data halls actually reach service?
========================================

A developer proposes a 24 MW IT campus in two independently funded, independently
supplied 12 MW halls. The first hall proceeds in every scenario. How much of the
expansion is online by December 2031 if the utility delivers the last 6 MW late,
leaves their delivery unresolved, or the project loses its rezoning application? Continue the
same ledger through refresh and retirement. All dates, costs and loads are synthetic.
Stargate Abilene motivates phased operation, Fermi's Matador motivates the
commercial hold, and Balico's Pittsylvania proposal motivates the planning
denial. The modeled campus is fictional. :doc:`/user_guide/project_lifecycle`
links the observed event for each real project to its primary record.
"""

from dataclasses import replace

import matplotlib.pyplot as plt
import pandas as pd

from datacenter_simulator import simulate
from datacenter_simulator.analysis.lifecycle import lifecycle_summary
from datacenter_simulator.methods.lifecycle import simulate_lifecycle
from datacenter_simulator.use_cases import reference_center, reference_profiles
from datacenter_simulator.use_cases.lifecycle import expansion_cases, reference_hall

# %%
# Compare the expansion decisions on a common reporting date
# ----------------------------------------------------------
# A stalled project retains the cash already spent and pays a monthly holding
# cost. A cancellation books the explicit exit cost once. Energy starts in the
# first service month after IT acceptance, with a four-month utilization ramp.
cutoff, end = "2031-12", "2048-12"
first = simulate_lifecycle(reference_hall(), end).set_index("month")
expansions = {name: simulate_lifecycle(plan, end) for name, plan in expansion_cases().items()}
summaries = {
    name: lifecycle_summary(ledger[ledger.month <= cutoff]) for name, ledger in expansions.items()
}
print(
    pd.DataFrame(summaries)
    .T[["phase", "status", "first_service_month", "months_stalled", "facility_mwh", "spend_usd"]]
    .to_string()
)

# %%
# Track campus load and each expansion's spending through retirement
# ------------------------------------------------------------------
# Add the common first hall to each alternative separately. Its load remains
# in service while an independently permitted expansion waits. Step changes
# reflect the monthly ramp, refresh downtime and eventual decommissioning.
fig, (load, cost) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
for (label, ledger), style in zip(
    expansions.items(), ["-", "--", "-.", (0, (3, 1, 1, 1)), ":"], strict=True
):
    expansion = ledger.set_index("month")
    campus = first.average_it_mw.add(expansion.average_it_mw, fill_value=0)
    load.step(pd.to_datetime(campus.index), campus, where="post", label=label, linestyle=style)
    cost.plot(pd.to_datetime(expansion.index), expansion.spend_usd.cumsum() / 1e6, linestyle=style)
load.set_ylabel("Campus average IT load (MW)")
cost.set_ylabel("Expansion spend (USD million)")
cost.set_xlabel("Calendar year")
load.legend(ncols=2, fontsize=9)
fig.tight_layout()
plt.show()

# %%
# Use the facility simulation to estimate operating energy
# --------------------------------------------------------
# As a sensitivity, transfer the energy-weighted PUE of the simulator's synthetic
# eight-rack facility profile to the on-time expansion. This explicitly assumes
# that the reference module's efficiency scales to the hall. The two-day input
# illustrates the interface. Use a representative full-year site profile for a study.
profiles, _ = reference_profiles(hours=48)
module = simulate(reference_center(), profiles)
plan = expansion_cases()["On time"]
service = replace(plan.service, pue=module.summary["pue"])
replay = simulate_lifecycle(replace(plan, service=service), cutoff)
print(
    f"Reference-module PUE {service.pue:.3f}; expansion facility energy "
    f"through {cutoff}: {replay.facility_mwh.sum() / 1000:.2f} GWh"
)
