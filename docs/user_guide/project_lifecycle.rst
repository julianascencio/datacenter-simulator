From proposed capacity to retirement
====================================

A 24 MW IT campus can have one hall serving customers while its expansion waits
for power. Model each independently deliverable hall with its own start month,
supply allocation, work budgets and decisions. The monthly ledger records the
phase, status, blocking requirements, commissioned IT MW, average IT load,
operating electricity (MWh), and expenditure (USD).

Run the example or replay a plan
--------------------------------

.. code-block:: bash

   python examples/analysis/plot_project_lifecycle.py
   python -m datacenter_simulator.analysis.lifecycle --output outputs/lifecycle
   python -m datacenter_simulator.analysis.lifecycle --inputs outputs/lifecycle/inputs.json --through 2031-12 --output outputs/replay

The gallery requires the docs extra. The CLI uses the core installation and
writes the input plan, ``monthly.csv`` and an as-of ``summary.json``. To model a
hold, set one gate's ``cleared_month`` to JSON ``null``. Enter a calendar month
to release it. To record an explicit decision to abandon the project, set
``withdrawal`` to an object with ``month``, ``reason`` and ``exit_cost_usd``.

Stage and accounting conventions
--------------------------------

* **Origination and site diligence.** Screen demand, land control, site fit and
  fiber access. A plan may start with a later work package for an existing site.
* **Permitting and interconnection.** Track planning, community, water and
  utility requirements as individually dated prerequisites. Their calendars can
  overlap. The example makes sponsor approval and power delivery separate decisions.
* **Financial close, design and procurement.** A lease, financing commitment,
  design release or equipment order can hold up the next work package.
* **Construction, fit-out and commissioning.** Work packages in each hall are
  sequential. A package starts in the first month when its predecessor has
  finished and all its gates have cleared. Its budget is spent evenly over its
  work months. While waiting, only the assumed monthly holding cost accrues.
  During a hold the phase column names the work waiting to start. A withdrawal
  stops work at the start of its effective month and incurs its exit cost once.
  With a ``power_deliveries`` schedule, commissioning requires cumulative firm
  facility MW to reach nameplate IT MW times the assumed design PUE (here the
  same PUE used for energy). Entries are additional MW allocated to this hall.
  An empty schedule supplies zero MW. Omitting it leaves power readiness to the
  explicit gates. For a 12 MW IT hall at PUE 1.25, 9 MW of firm supply holds
  the hall until another 6 MW arrives. To open a smaller first block, give it
  its own plan and supply allocation.
* **Ramp-up and operation.** The first service month follows the last
  commissioning month. Commissioned IT MW is nameplate capacity. Average IT MW
  equals that capacity times the load factor and the average ramp fraction for
  the month. For a linear ramp lasting ``R`` months the fraction in month
  ``i`` (starting at zero) is ``(i + 0.5) / R``. After ramp-up it is one.
  Operating facility MWh equals average IT MW times actual calendar hours times
  PUE. The example also runs the existing device/cooling simulator and uses its
  energy-weighted PUE in a sensitivity.
* **Expansion and refresh.** An additional hall follows its own path. Allocate
  shared capital and power once across halls before summing their ledgers.
  Refresh occurs after each full specified interval of service, costs the entered
  amount, and reduces average IT load by the specified fraction for that month.
* **Decommissioning and retirement.** Operating energy stops at the end of the
  entered service life, including the ramp. Decommissioning spend is spread
  evenly over the specified months. The retired state carries zero operating MW
  and zero further expenditure.

Interpret an example result
---------------------------

By December 2031 the on-time second hall has consumed 131.544 GWh of facility
energy. A six-month power delay reduces this to 79.200 GWh and adds USD 750,000
of holding costs. With power unresolved, the same hall has spent USD 91.175
million and delivered zero IT energy. In the planning-withdrawal path it stops
after spending USD 2 million, including its exit charge. Each scenario retains
the first hall's independent operations.

The ledger measures scenario spending. It excludes operating expenses, revenue,
financing costs, tax, salvage and construction or commissioning-test electricity.
Constant PUE and load factor approximate normal service. A missing clearance
keeps the scenario open at the reporting cutoff. Actual permit outcomes, schedule
probabilities and shared utility capacity require project-specific evidence.
For probability-weighted economics see :doc:`development`.

Evidence and assumptions
------------------------

The `article supplied with the request <https://lamthuyen.substack.com/p/built-stalled-cancelled-what-decides>`_
motivated the built, stalled and cancelled scenarios. Its text was unavailable
for verification. The following sources support the independent model design.

* `Berkeley Lab, Data Center Siting: Criteria, Policies, and Recent Trends
  <https://eta-publications.lbl.gov/sites/default/files/2026-10/eif_webinar_siting_v2.pdf>`_,
  slides 5–6, distinguishes development stages and describes power timing,
  land, fiber, water and local approvals as siting factors.
* `Equinix 2025 Form 10-K, development projects
  <https://investor.equinix.com/sec-filings/all-sec-filings/content/0001101239-26-000075/EQIXAnnualRpt2025PRINT.pdf>`_
  lists separate phases, opening targets and capital budgets within campuses.

All numerical inputs in the example are synthetic. The reporting dates illustrate
scenario arithmetic and carry no implied probability of completion.
