Speed to power: AI compute and energy economics
===============================================

This integration uses Newkirk et al., *Speed-to-Power Dominates Energy Costs
for AI Data Centers*, `arXiv:2611.17098v1 <https://arxiv.org/abs/2611.17098v1>`_
(12 November 2026). It provides two deliberately separate workflows:

* Replay the authors' published results for **4,317 locations and 100,000 GPUs**,
  with the original medium-voltage topology labels and 2022 USD cost basis.
* Run an editable native engineering screen using hourly load, solar, storage,
  conversion losses, service constraints and deployment-sensitive economics.

Run and replay
--------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.speed_to_power --output outputs/speed-to-power
   python -m datacenter_simulator.analysis.speed_to_power \
     --inputs outputs/speed-to-power/inputs.json \
     --profiles outputs/speed-to-power/profiles.csv \
     --output outputs/speed-to-power-replay

Open ``speed-to-power.html``. Both runs are offline and deterministic.
The report has interactive cost, compute-value and deployment-time charts.
CSV exports include all candidates, selected designs, annual cashflows,
hourly storage/energy balances, sensitivities and published location rankings.

* :download:`Offline interactive report </_static/lab/speed-to-power/speed-to-power.html>`
* :download:`Editable inputs </_static/lab/speed-to-power/inputs.json>`
* :download:`Hourly profiles </_static/lab/speed-to-power/profiles.csv>`
* :download:`Source ledger </_static/lab/speed-to-power/sources.json>`
* :doc:`Runnable gallery example <../gallery/analysis/plot_speed_to_power>`
* :doc:`API <../reference/speed_to_power>`

Knowledge transferred from the paper
-----------------------------------

.. list-table:: Evidence and implementation boundary
   :header-rows: 1
   :widths: 26 39 35

   * - Paper concept
     - Implemented here
     - Qualification
   * - Equivalent IT and cooling service (S1.1)
     - Shared hourly terminal loads; 8 GPUs/node, 7.3 kW average,
       8.5 kW maximum and 1.05 design contingency
     - H100-equivalent source assumptions, not specifications for all GPUs
   * - Climate-dependent cooling
     - Aligned imports of cooling electrical demand, including outputs
       from existing weather/cooling methods
     - Default thermal overhead is synthetic; no port of the authors'
       six-technology cooling selection or its empirical lookup tables
   * - AC/DC bus-centric conversion (Figure 2, p. 7)
     - Separate PV-to-bus, bus-to-IT and bus-to-cooling stage products
     - Constant efficiencies; no network voltage, clipping, or protection solver
   * - Storage, reliability and solar droughts (S1.2)
     - Existing Battery/dispatch model, power/energy limits, periodic SOC,
       full-load-hour availability, unserved energy and worst cyclic five-day yield
     - Hourly service is not restart-aware training availability or an SLA
   * - PV/BESS ageing (S1.2.3)
     - Linear source PV-retention helper; explicit conservative PV/BESS
       capacity derates and battery replacement expenditure
     - No BLAST-Lite model or surrogate; repeated design year is not a
       simulated lifetime degradation trajectory
   * - Natural gas and grid alternatives (S1.2.2)
     - Peak source-capacity sizing, source-meter energy, gas heat-rate fuel
       accounting, fixed/variable O&M and grid price
     - Native scenarios assume ideal firm supply; no turbine enumeration,
       part-load efficiency, ambient derating, diesel backup or stochastic outages
   * - Time value of energized compute (Eqs. 1-2, S17-S18)
     - Common-horizon, midyear discounted delivered-energy and cost accounting;
       fractional deployment years, compute readiness and break-even value
     - Opportunity cost is a decision assumption; rental revenue is not net profit
   * - U.S. geographic comparison and accelerated gas
     - Version-pinned author CSV import, exact baseline replay, fixed-design
       GPU-value sensitivity and separate three-year-gas results
     - Imported model outputs, not newly measured data or a full independent rerun

Published data connector and reproducibility
-------------------------------------------

``connectors.speed_to_power`` validates the authors' wide CSV schema, retains
auxiliary fields and rejects missing values, negative costs, duplicate site/GPU
pairs and unknown topologies. The packaged subset selects ``gpu_count == 100000``
from commit ``729569fc32582ce4baa4426b5b025d073870f31a`` of
`AI-Datacenter-Microgrid-Analysis
<https://github.com/acnewkirk/AI-Datacenter-Microgrid-Analysis>`_. Both the
upstream bytes and serialized subset have SHA-256 provenance in the source ledger.
The MIT notice accompanies the snapshot; no upstream code or pickle is executed.

``fetch_published_results()`` explicitly fetches and checks the pinned full
CSV, including other GPU scales. Filter scale and topology before aggregating:
the smaller-scale upstream rows use low-voltage designs. Never silently combine
those rows with the paper's headline medium-voltage comparison.

At the authors' USD 2.40/GPU-hour valuation, the packaged baseline contains
3,663 DC-solar winners, 653 grid winners and **one gas winner**. Their shares
are 84.8506%, 15.1262% and 0.0232%. The accelerated gas case has 2,402 DC-solar,
1,518 gas and 397 grid winners (55.6405%, 35.1633%, 9.1962%). This preserves the
unrounded data instead of asserting that baseline gas never wins.
The average proportional base-LCOE DC advantage is 18.3357%.

For a fixed author-generated design, the sensitivity uses:

.. math::

   L(p) = L_{base} + p\frac{L_{total}(2.40)-L_{base}}{2.40}.

This revalues the published speed premium only. It does not refit weather,
change readiness or timelines, or optimize a new design. The accelerated gas
case uses its own published base cost and total cost. Ties use stable column
order; ``winner_gap_usd_per_kwh`` and the one-cent near-tie flag expose fragile
rankings.

Connect operational and resource data
------------------------------------

The native CSV contract is exactly aligned, timezone-aware, regular hourly data:

.. list-table:: Profile columns
   :header-rows: 1

   * - Column
     - Meaning
   * - timestamp
     - Start of each one-hour interval, with explicit UTC offset
   * - it_kw
     - Positive IT terminal demand, including node memory/networking
   * - cooling_kw
     - Nonnegative cooling electrical terminal demand, excluding conversion losses
   * - pv_dc_per_kwp
     - Nonnegative pre-conversion array DC power per installed kWp

Use ``profiles_from_components(it_kw, cooling_kw, pv_dc_kw, pv_rating_kwp=...)``
to connect the existing pvlib adapter, weather-cooling output, SCADA or local
measurements. Pass ``pv_from_weather(...).pv_dc_kw``, not its AC output.
For weather, the repository's attributed PVGIS adapters are already available;
the original study instead uses NSRDB. A new NSRDB API client is not implied.
The connector never fills gaps or silently resamples. Native annual economics
require 8,760 rows; leap years must be deliberately normalized outside this API.

Power and storage equations
---------------------------

For the common bus, with path efficiency products :math:`\eta`:

.. math::

   P_{bus} = P_{IT}/\eta_{IT} + P_{cool}/\eta_{cool}, \qquad
   P_{PV,bus} = P_{PV,DC}\eta_{PV}.

For AC solar, the common bus is upstream of the shared inverter, so bulk
storage can charge without unnecessary inversion. For DC solar, the common
bus is the medium-voltage spine. Each charging/discharging efficiency is
``0.98 * sqrt(0.90)``: one battery converter pass and half the cell round-trip
loss. The DC and AC paths use the distinct source and load placements from
Figure 2. Efficiencies are exposed through ``SupplyPaths`` and ``PowerStage``.

Stored energy changes by :math:`\eta_c P_c\Delta t-P_d\Delta t/\eta_d`.
The existing dispatch method enforces charge/discharge power and SOC bounds.
The profile repeats from minimum SOC until the start/end inventory agrees,
so finite storage cannot supply free annual energy. Explicit output balances
include raw PV, terminal service, curtailment, converter loss, battery loss
and inventory change. Unserved IT and cooling are shed proportionally.

Full-load-hour availability counts only hours with no terminal deficit.
Energy service fraction counts delivered kWh divided by requested kWh.
They are not interchangeable. The default threshold is 99% full-load hours,
as in the paper, not 99.999% availability. Gas and grid deliver 100% only
because the native screen assumes ideal firm supply. Their larger delivered
energy stays in their denominator; no claim of identical outage sequences is made.

The search checks PV ratings of 5, 9 and 12 times average IT kW against
18, 36 and 72 hours of nominal storage relative to average terminal demand.
Usable battery energy is derated to 80%; bus power limits equal nominal
energy divided by four hours. PV is derated to 85.8%, the source's year-25
retention. These simultaneous derates are a conservative screening assumption,
not the paper's chronological degradation path. At fixed topology, every
candidate has the same deployment time. The lowest base-LCOE feasible
candidate is selected; this is a finite search, not a global optimizer.
All failed candidates remain in the output, including zero-delivery designs.

Financial accounting and interpretation
---------------------------------------

Every architecture uses the same exclusive horizon ``[0, 27)`` by default.
It is not given 27 operating years after its own completion date. Energy,
O&M and idle compute are prorated for partial years and discounted at
:math:`(1+r)^{-(t+0.5)}`. The capital schedule follows S1.3.1: builds up to
one year spend in bucket zero, exact two/three-year builds use 40/60 and
30/40/30, and other durations spend in proportion to construction-year
overlap. Every bucket, including bucket-zero capex, uses midyear discounting.

For compute-ready date :math:`q`, deployment :math:`d` and annual bucket
:math:`[t,t+1)`, idle GPU-hours are:

.. math::

   H_{idle,t}=8760N_{GPU}\max(0,\min(t+1,d)-\max(t,q)).

Useful-load operation starts at :math:`\max(d,q)`; no energy is credited to
GPUs before readiness. Pre-operation O&M is excluded. Replacement expenditure
is booked after 13 operational years when it falls inside the common horizon;
there is no terminal replacement or salvage credit. Native design-year
delivered energy and O&M repeat unchanged, even after replacement.

.. math::

   L_{base}=\frac{PV(C_{cap}+C_{replacement}+C_{op})}{PV(E_{delivered})},\qquad
   L_{adj}=L_{base}+p_{GPU}\frac{PV(H_{idle})}{PV(E_{delivered})}.

The break-even GPU value solves the intersection of these two affine curves,
using each architecture's own denominator. Common pre-energization lost value
does not cancel exactly in LCOE ratios with unequal energy denominators.
Set readiness to the firm's actual date rather than assuming procurement at
project inception. Costs exclude GPU capex, GPU refresh, operating downtime
opportunity cost, emissions, taxes and business-model margin.

Native prices are **illustrative constant USD**, not source-calibrated 2022
costs or live quotations. By default PV costs are 1,000/800 USD/kWp for AC/DC,
batteries 150 USD/kWh, replacement 80 USD/kWh, solar O&M 2% of initial capex,
gas capital 1,500 USD/kW, gas heat rate 8 MMBtu/MWh, fuel 5 USD/MMBtu,
gas fixed O&M 20 USD/kW/year and variable O&M 0.005 USD/kWh. Grid capital
is 150 USD/kW and electricity 0.07 USD/kWh. These defaults are editable
assumptions, not a reproduction of the paper's ATB/EIA/PNNL costing model.

Validation and next fidelity steps
----------------------------------

Tests cover closed-form midyear and zero-discount cashflows, partial years,
readiness, horizon boundaries, replacement timing, analytical break-even values,
conversion/storage energy conservation, periodic inventory, storage power limits,
cyclic solar droughts, invalid connector inputs, exact author-table replay and
infeasible-design exclusion. Passing these tests does not validate real plants.

For full scientific replication use the authors' pinned source and its runtime
inputs. Future native extensions should add chronological multi-year weather,
empirically calibrated cooling, BLAST-Lite or validated equivalent degradation,
turbine and fuel-supply reliability, diesel backup, protection costs, workload
restart penalties and silicon procurement/depreciation. The supply-side
interconnection queue proxy and TMY weather limitations discussed in the paper
remain material when interpreting its published geographic ranking.
