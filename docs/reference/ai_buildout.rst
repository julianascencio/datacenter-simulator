AI campus commissioning and renewal
===================================

Compare an identical fleet under different power-ready dates, silicon lifetimes,
chip specifications and construction prices. Each phase enters service at the
start of the later of its equipment-ready year and power-ready year. Cash is
booked at commissioning or replacement. Construction drawdowns, financing,
depreciation, early procurement and partial-year ramp-up are outside this convention.

.. autofunction:: datacenter_simulator.methods.ai_buildout.simulate_buildout

.. autoclass:: datacenter_simulator.methods.ai_buildout.ComputePhase
   :members: it_mw

Capacity and cost boundaries
----------------------------

* IT MW = accelerator count × (package kW + other IT kW per accelerator) / 1000.
  For alternative silicon, supply the counts and host power required for the
  chosen workload. The model assumes like-for-like renewal with no change in
  throughput or power. It does not infer compute equivalence across chips.
* Facility MW = IT MW × PUE. Annual MWh = facility MW × electrical load factor
  × 8760. PUE is held constant at design and operating load. The load factor
  refers to average electrical draw relative to the design load.
* Initial compute and each renewal use the node-inclusive unit price. Each
  cohort renews after its own economic useful life. A cohort commissioned before
  the reporting window retains its age. Long-lived systems are priced once.
* Construction applies only to new, non-reused IT MW. The power allowance
  applies to an independently chosen fraction of new facility kW. The example
  assumes all new facility demand requires new power capacity, including demand
  in reused space. Grid reinforcement, reserves and retrofit costs need their
  own engineering estimates.

Source interpretation
---------------------

The `Goldman Sachs Global Institute scenario
<https://www.goldmansachs.com/insights/articles/tracking-trillions-the-assumptions-shaping-scale-of-the-ai-build-out>`_
(p. 4 of the accompanying report) supplies the example's USD 80,500 per
accelerator including node costs, 3 kW per package, 1.2 PUE, USD 15 million per
MW of construction and USD 2,500 per kW of new power. Pricing construction on
IT MW is an explicit site modelling choice.

`JLL's January 2026 outlook
<https://www.jll.com/en-us/insights/market-outlook/global-data-centers>`_
gives a 2026 global shell-and-core estimate of USD 11.3 million per MW,
excluding tenant fit-out. `Reuters' October 2026 account of BofA's estimates
<https://www.marketscreener.com/news/data-center-spending-to-more-than-double-to-2-1-trillion-by-2028-ce785cdfda8ffe22>`_
puts a broader IT-inclusive benchmark at USD 49 million per MW. Adding either
headline to the example budget would overlap scopes. Confirm the MW denominator
and the items covered before substituting a local quotation.

The grid event adapts the discrete demand-flexibility question in Fsas
International Quantum Center, *Quantum Computing in the Energy Sector* (2026),
GraviteQA demand-side case. The example reuses the simulator's classical MILP,
prices battery throughput and holds end-of-event charge fixed. It assesses an
active power ceiling at a single bus. Network voltage, thermal constraints and
quantum hardware performance would require separate studies.

Run the gallery from a checkout with the docs dependencies installed::

   python examples/analysis/plot_ai_buildout.py
