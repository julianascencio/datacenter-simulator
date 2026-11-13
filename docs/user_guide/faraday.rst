Faraday utility-linked storage
==================================

This case asks how a remote solar/storage portfolio can improve hourly energy
matching for a continuously supplied data center. It uses reported Faraday asset
ratings and clearly separate synthetic operating assumptions.

Run and replay
------------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.faraday --output outputs/faraday
   python -m datacenter_simulator.analysis.faraday --hours 8760 --output outputs/faraday-year
   python -m datacenter_simulator.analysis.faraday \
     --inputs outputs/faraday/inputs.json --profiles outputs/faraday/profiles.csv \
     --output outputs/faraday-replay

The default is a synthetic week starting September 19, 2026. The 8,760-hour
option starts on the same date and is a synthetic rolling year, not a calendar
year reconstruction. JSON changes IT MW, PUE, solar AC peak, POI limit and
round-trip efficiency. CSV inputs override the synthetic load and solar profiles;
they require ``timestamp,demand_kw,solar_kw``, explicit timezone offsets, finite
nonnegative kW and contiguous one-hour intervals. Missing samples are rejected.
The Python matching API also accepts a declared subhourly step.

.. raw:: html

   <p><a class="reference external" href="../_static/lab/faraday/faraday-storage.html">Open the interactive Faraday report</a></p>

Download :download:`comparison CSV </_static/lab/faraday/comparison.csv>`,
:download:`hourly profiles </_static/lab/faraday/profiles.csv>`,
:download:`replay inputs </_static/lab/faraday/inputs.json>`,
:download:`source ledger </_static/lab/faraday/evidence.json>` and
:download:`model scope </_static/lab/faraday/scope.json>`.
See the :doc:`runnable tutorial <../gallery/analysis/plot_faraday_storage>`.

Reported facts and unknowns
-------------------------------

The `November 10 issuer announcement <https://www.businesswire.com/news/home/20261110822031/en/>`_
reports an operating 150 MW / 600 MWh LFP resource and a proposed addition of up
to 375 MW / 1,500 MWh targeting Q4 2028. Its solar neighbor is reported as
525 MW and shares the grid connection. The evidence ledger records the
syndicated issuer-text mirror used when Business Wire was inaccessible.

`Earlier financing disclosure <https://lydianenergy.com/news/lydian-energy-announces-689-million-financing-for-solar-and-battery-storage-projects/>`_
used 733 MWh. That discrepancy is unresolved: the example changes only the
deliverable-energy assumption in a sensitivity. It does not infer degradation,
reserve margins or installed capacity from the difference. The disclosed
$689 million financed three assets and is not a battery CAPEX input.

`Meta's announcement <https://datacenters.atmeta.com/2026/09/deepening-our-investment-in-eagle-mountain-utah/>`_
confirms support for Faraday, without supplying a data-center load trace.
Actual load, PV allocation, AC/DC solar basis, POI rating, battery efficiency,
dispatch obligations and energy-attribute rights are not established here.

The current utility `Schedule 34 <https://www.rockymountainpower.net/content/dam/pcorp/documents/en/rockymountainpower/rates-regulation/utah/rates/034_Clean_Energy_Purchases_for_Qualified_Customers_5000kW_and_Over.pdf>`_
is titled *Clean Energy Purchases for Qualified Customers*. The article uses
the older *Renewable Energy* title. The utility receives resource output and
serves the customer under approved contract terms. This study does not infer
a private wire or calculate a customer-specific tariff bill.

Two electrical boundaries
-----------------------------

At the generation site, solar can charge the battery or export through a shared
POI. At the remote data center, the utility supplies the entire facility load.
The simulation matches eligible generation exports to load in the same hour as
an analytical procurement metric. It does not trace physical electrons.

Let ``D`` be facility demand, ``G`` available solar, ``X`` the POI limit,
``C`` battery charging and ``B`` battery discharging (all interval-average kW):

.. math::

   T_t &= \min(D_t, X) \\
   M_t &= \min(G_t, T_t) + B_t \\
   R_t &= D_t - M_t \\
   I_{\mathrm{customer},t} &= D_t

The existing :func:`~datacenter_simulator.methods.energy.dispatch` serves the
virtual target ``T`` first, charges surplus solar, discharges into deficits,
and exports excess up to remaining POI headroom. Its virtual grid-import term
is not reported as a customer meter. No grid charging is allowed.

.. math::

   E_{t+1} &= E_t + \Delta t(\eta_c C_t - B_t/\eta_d) \\
   G_t + B_t &= C_t + X_{\mathrm{site},t} + G_{\mathrm{curtailed},t} \\
   X_{\mathrm{site},t} &= M_t + X_{\mathrm{unmatched},t} \le X

The two one-way efficiencies equal the square root of the assumed round-trip
efficiency. Interpreting the contract rating as AC deliverable energy means
``internal usable energy = deliverable AC energy / discharge efficiency``.
This convention avoids applying discharge losses twice to the 600 MWh rating;
it does not establish the installed nameplate or actual contract measurement
boundary. SOC spans this usable window, not electrochemical cell SOC.

The initial usable window is empty. Stored energy remaining at the end is
exported as inventory and never credited as delivered matching. Reserve energy,
if represented by a nonzero minimum SOC in the Python API, cannot be discharged.

What the outputs mean
-------------------------

* ``hourly_matched_fraction`` is sum(matched kWh) / sum(load kWh). It caps
  matching by load every hour; annual surplus cannot offset an unmatched night.
* ``fully_matched_hours`` counts positive-load hours with no matching deficit.
* ``residual_unmatched_mwh`` is a procurement gap, not unserved energy.
* ``facility_meter_peak_mw`` remains full utility-meter demand in all cases.
  A remote battery does not imply a reduction in the customer's demand charge.
* ``unmatched_export_mwh`` is physically exported but excluded from matching.
* ``battery_loss_mwh`` and both balance-error columns make conservation auditable.
  Equivalent cycles use discharged AC energy / deliverable AC window.

The six scenarios are grid-only, solar-only, operating ratings, the 733 MWh
sensitivity, an additive proposed expansion, and a 25%-solar stress. Only the
last case changes resource conditions. The nine additional sensitivities change
demand and the POI while retaining the 150 MW / 600 MWh battery.

Limits and validation
-------------------------

The default 200 MW demand, full allocation of a 525 MW AC solar profile,
525 MW POI and 90% round-trip efficiency are assumptions. Solar is a
deterministic daylight sine curve with repeating cloud factors, not measured
weather, pvlib output or a production forecast. Standby/auxiliary losses,
degradation, transmission losses, congestion, grid charging and ancillary
service obligations are excluded. Greedy matching is not an economic optimum
or a reconstruction of utility dispatch. Load-growth and low-solar cases are
stress tests, not forecasts.

Tests verify four-hour delivery from a full 600 MWh usable window, conversion
losses, POI constraints, separate meters, no simultaneous charging/discharging,
no free initial energy, no double counting, half-hour integration, exact input
alignment, conservation and exported-profile replay. None establishes measured
Faraday performance, reliable islanding, capacity accreditation or REC ownership.
