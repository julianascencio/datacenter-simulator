Anthropic's US gas exposure
===========================

Run the offline case from the repository root:

.. code-block:: bash

   python -m pip install -e ".[docs]"
   python examples/analysis/plot_anthropic_gas_exposure.py

The example uses the Better Data Center Project's November 2026 estimates
for 19 US facilities. A full year with the mapped capacity online is a
build-out scenario. The site list includes proposals and uncertain tenant
allocations. It cannot establish the electricity supply for a particular
Claude request or the routing of European workloads.

Electricity and fuel boundaries
-------------------------------

The low and high cases use each site's lower and upper attributed IT capacity.
Both hold IT power at 70% of rated capacity and use a common PUE of 1.15,
following the source article's central operating assumptions. These differ
from the defaults visible in the downloadable worksheet. Each MW of IT
capacity therefore requires 7,051.8 MWh of facility electricity over a
normalized 8,760-hour year. The model assumes firm service, constant heat
rates and zero grid delivery losses.

* **Regional average.** The four sites classified as on-site gas supply their
  full facility loads. Every other site takes its workbook eGRID regional gas
  fraction on imported MWh. This includes sites linked to new gas plants or
  nuclear supply contracts.
* **Study dispatch.** The workbook's site-specific gas fractions reflect named
  generators where identified and EPA AVERT short-run marginal generation
  elsewhere. The replay weights those published factors by modeled MWh.
  The CO2e result uses the workbook's whole-site lb/MWh factors under this
  same method. It covers operating electricity across all fuels.
* **Direct fuel bill.** On-site electrical MWh times an assumed HHV heat rate
  of 9.0 MMBtu/MWh gives fuel consumed. Apply the scenario commodity price
  to those MMBtu. The example assumes full pass-through for all on-site
  fuel, with no hedge. Separate grid fuel estimates use 7.754 MMBtu/MWh,
  the EIA 2024 US gas fleet benchmark. Grid tariffs, pipeline transport,
  equipment costs and taxes are outside the fuel bill.

Reproduced results
------------------

.. list-table::
   :header-rows: 1

   * - Assumed build-out
     - Facility TWh/year
     - On-site gas TWh/year
     - Regional gas share
     - Study gas share
     - On-site fuel at $4/MMBtu
   * - 5.907 GW
     - 41.65
     - 8.89
     - 56.2%
     - 83.8%
     - $320M/year
   * - 9.579 GW
     - 67.55
     - 17.70
     - 60.7%
     - 87.4%
     - $637M/year

The high case reproduces the workbook's 87.4% gas share and rounds to the
study's published 32 million metric tonnes CO2e per year. The alternative
regional-average calculation explains how the screenshot's roughly 60% can
arise from the same portfolio. Capacity includes on-site and grid-powered
sites with the same operating assumptions. Changing their relative
utilizations or commissioning dates would change their weights.

Data and uncertainty
--------------------

The packaged CSV is a numeric extract of rows 4–22 of the public workbook,
retrieved on 19 November 2026. It retains the source row numbers, US states
and power classifications. Gas columns reproduce the workbook's percentages.
The speculative flag identifies the five rows whose attribution the workbook
explicitly calls speculative. Other rows range from reported downstream
tenants to confirmed users with undisclosed allocations. Maysville's source
note describes its 120–180 MW as grid capacity. The replay preserves the
workbook's treatment in its IT columns for comparability. The CSV export of
the original sheet had SHA-256
``04419479c8884501a050d6c79984d235af1967b950f35351126ccd0f228414c4``.

The example also tests how results change when the five speculative rows
are removed, and how wide the gas share could be if all of the reported
15 GW were built with identical utilization and PUE. The latter sensitivity
varies the unknown capacity's gas share from zero to 100%. It assigns no
locations or supply contracts to that capacity.

The reported 1.7 GW generator order is compared separately with modeled
on-site demand. Its 14.89 TWh/year ceiling assumes the full order is
available at rated output for 8,760 hours. Deployment dates, allocation to
these projects and overlap with planned generation are unknown. The
reported $3.4 billion equipment deal and the SEC filing's $900.9 billion
in aggregate commitments provide financial context only.

.. seealso::

   :ref:`anthropic-gas-sources` and
   :ref:`sphx_glr_gallery_analysis_plot_anthropic_gas_exposure.py`.
