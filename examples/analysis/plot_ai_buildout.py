"""
Powering and renewing a two-phase AI campus
===========================================

**Level:** Intermediate | **Subject:** AI capacity planning and grid flexibility

When does a delayed grid connection shift capital spending, and how much
electricity can the campus use over the same planning window? A second screen
tests whether a flexible batch job and a battery can meet a temporary import
ceiling after commissioning. All site and event profiles are illustrative.
See :doc:`../../reference/ai_buildout` for source scopes and assumptions.
"""

from dataclasses import replace

import matplotlib.pyplot as plt
import pandas as pd

from datacenter_simulator.methods.ai_buildout import ComputePhase, simulate_buildout
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.optimization import DemandOption, optimize_dispatch

# %%
# Step 1. Compare commissioning dates and chip lives
# --------------------------------------------------
# Goldman Sachs' illustrative package power, node-inclusive price and PUE are
# scenario inputs. Host/network demand, phase sizes, reuse and load factor are
# local assumptions. Infra is priced per new IT MW and generation per new kW.
phases = [
    ComputePhase(2026, 1000, 3.0, 0.5, 80_500, 4, brownfield_fraction=0.25),
    ComputePhase(2028, 2000, 3.0, 0.5, 80_500, 4),
]
fig, (capital, energy) = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
for label, ready, life in [
    ("On time, 4-year life", 2026, 4),
    ("On time, 6-year life", 2026, 6),
    ("Grid in 2028, 4-year life", 2028, 4),
]:
    result = simulate_buildout(
        [replace(p, life_years=life) for p in phases],
        start_year=2026,
        end_year=2031,
        power_ready_year=ready,
        pue=1.2,
        it_load_factor=0.70,
        construction_usd_per_it_mw=15e6,
        new_power_fraction=1.0,
        power_usd_per_kw=2500,
    )
    capital.plot(result.index, result.total_capex_usd.cumsum() / 1e6, marker=".", label=label)
    energy.plot(result.index, result.facility_mwh.cumsum() / 1000, marker=".", label=label)
    print(
        f"{label}: ${result.total_capex_usd.sum() / 1e6:.2f}M, "
        f"{result.facility_mwh.sum() / 1000:.2f} GWh"
    )
capital.set(ylabel="Cumulative capital (million USD)", xlabel="Year")
energy.set(ylabel="Cumulative facility electricity (GWh)", xlabel="Year")
capital.legend(fontsize=8)
plt.show()

# %%
# Step 2. Meet a grid limit on the first 4.2 MW facility phase
# ------------------------------------------------------------
# GraviteQA's discrete flexibility problem motivates this smaller classical
# benchmark. The facility can run one required 0.6 MW, one-hour batch job.
# In slot 1 the grid ceiling falls from 4.2 to 2.8 MW. Fixed load is 3 MW.
# Compare a fixed job time with two permitted times under the same constraints,
# electricity price, wear charge and exact end-of-event battery state.
profiles = pd.DataFrame(
    {
        "demand_kw": 3000,
        "generation_kw": 0,
        "import_price": [0.08, 0.25, 0.15, 0.12],
        "grid_limit_kw": [4200, 2800, 4200, 4200],
    },
    index=pd.date_range("2026-06-01 12:00", periods=4, freq="h", tz="UTC"),
)
battery = Battery(capacity_kwh=2000, max_charge_kw=1000, max_discharge_kw=1000)
now = DemandOption("scheduled", "batch", "cluster", 1, (600,))
later = replace(now, id="deferred", start_slot=2)
fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
for label, options in [("Fixed", (now,)), ("Flexible", (now, later))]:
    dispatch = optimize_dispatch(
        profiles,
        battery,
        demand_options=options,
        required_groups=("batch",),
        require_served=True,
        terminal_soc_exact=True,
        throughput_cost_per_kwh=0.015,
    )
    print(
        f"{label}: {dispatch.selected_options[0]}, ${dispatch.objective:.2f}, "
        f"{dispatch.summary['throughput_kwh']:.0f} kWh battery throughput"
    )
    ax.plot(range(4), dispatch.timeseries.grid_import_kw / 1000, marker="o", label=label)
ax.step(range(4), profiles.grid_limit_kw / 1000, where="mid", linestyle="--", label="Import limit")
ax.set(xlabel="One-hour slot", ylabel="Grid import (MW)", xticks=range(4))
ax.legend()
plt.show()
