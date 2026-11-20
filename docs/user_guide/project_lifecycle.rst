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
``cancellation`` to an object with ``month``, ``reason`` and ``exit_cost_usd``.

The eleven steps in the article
-------------------------------

The reference hall implements the four stages in `Lâm Thuyên's November 2026
article <https://lamthuyen.substack.com/p/built-stalled-cancelled-what-decides>`_.
Each work package has a duration, a remaining budget and zero or more dated entry
requirements. Multiple prerequisites can progress in parallel. Work within a hall
is sequenced. Two halls can be at different steps in the same month.

.. list-table::
   :header-rows: 1
   :widths: 15 33 52

   * - Stage
     - Step
     - What the example represents
   * - Plan
     - 1. Demand definition
     - Target IT MW and a customer or owner for each hall.
   * - Plan
     - 2. Site diligence
     - Land option and site suitability. Fiber readiness is checked again before commissioning.
   * - Secure
     - 3. Power contracting
     - An executed service agreement can clear the design gate. Physical power arrives on a separate schedule.
   * - Secure
     - 4. Land entitlement
     - Dated planning and water approval. An adverse decision can end the project.
   * - Secure
     - 5. Financing
     - Tenant commitment and construction financing must both clear before design spend starts in this example.
   * - Build
     - 6. Design
     - Engineering work and a design release for procurement.
   * - Build
     - 7. Long-lead procurement
     - Equipment release and remaining procurement spend. A separately dated equipment deposit can precede entitlement.
   * - Build
     - 8. Construction
     - Monthly payments for shell and fit-out, allocated per hall.
   * - Build
     - 9. Commissioning and energization
     - Firm facility power and fiber readiness. Factory, installation, startup, functional and integrated acceptance milestones can each hold IT installation.
   * - Operate
     - 10. IT installation and acceptance
     - Accelerator installation and acceptance budget. The hall serves its first workload in the following month.
   * - Operate
     - 11. Operations and expansion
     - Utilization ramp, electricity, recurring refresh, independent expansion, then decommissioning and retirement.

Accounting and timing
---------------------

* **Pre-service expenditure.** Work budgets are paid evenly over their active
  months. A stalled package incurs its holding rate and shows its blockers.
  The nonrefundable equipment deposit is paid once on its own date, including
  during a hold. Stage budgets exclude that deposit. A terminal decision stops
  all further work at the beginning of its month and charges the exit cost once.
* **Firm facility power.** With ``power_deliveries`` specified, commissioning
  needs cumulative firm facility MW to cover nameplate IT MW times design PUE
  (here the same PUE used for energy). An empty schedule supplies zero MW.
  Omitting it leaves readiness to the explicit gates. A 12 MW IT hall at PUE
  1.25 can wait on the last 6 MW even after 9 MW of firm supply arrives.
  Split independently commissionable blocks into separate plans and allocate
  shared plant, supply and common costs once.
* **Energy and refresh.** Commissioned IT MW is nameplate capacity serving
  workloads. Average IT MW equals capacity times the load factor and the mean
  monthly ramp fraction. During a linear ramp lasting ``R`` months, this
  fraction in zero-based month ``i`` is ``(i + 0.5) / R``. Facility MWh equals
  average IT MW times actual calendar hours times PUE. Refresh reduces the
  month's average load by the configured unavailable fraction and incurs its
  stated cost. The gallery also transfers energy-weighted PUE from the existing
  device and cooling simulator into a sensitivity.
* **End of life.** The example uses a 16-year operating life, including ramp,
  and a four-year equipment refresh interval. At decommissioning, workload
  energy stops and retirement spending is distributed across its specified
  months. Retired halls stay at zero load and expenditure.

Interpret an example result
---------------------------

By December 2031 the on-time second hall has consumed 131.544 GWh of facility
energy. A six-month power delay reduces this to 79.200 GWh and adds USD 750,000
of holding costs. With power unresolved, the same hall has spent USD 91.175
million and delivered zero IT energy. In the rezoning-denial path it stops
after spending USD 3 million, including the early deposit and exit charge.
Failure to secure a tenant and construction funding instead leaves USD 7.175
million spent and no construction underway by the cutoff. Each scenario retains
the first hall's independent operations.

The ledger measures scenario spending. It excludes operating expenses, revenue,
financing costs, tax, salvage and construction or commissioning-test electricity.
Constant PUE and load factor approximate normal service. A missing clearance
keeps the scenario open at the reporting cutoff. Actual permit outcomes, schedule
probabilities and shared utility capacity require project-specific evidence.
For probability-weighted economics see :doc:`development`.

Evidence and assumptions
------------------------

The article compares three projects. These dated observations motivate the
scenarios. The gallery uses one fictional two-hall campus so that differences
in spending and energy can be attributed to the selected gate.

* **Stargate Abilene, phased operation.** Crusoe `confirmed first-phase service
  on September 30, 2025 <https://www.crusoe.ai/resources/newsroom/crusoe-announces-flagship-abilene-data-center-is-live>`_.
  Its `campus announcement <https://www.crusoe.ai/resources/newsroom/crusoe-expands-ai-data-center-campus-in-abilene-to-1-2-gigawatts>`_
  describes 1.2 GW as total planned power across eight buildings. The model counts
  only the individual halls that have reached service.
* **Project Matador, commercial hold.** Fermi's `quarterly filing
  <https://www.sec.gov/Archives/edgar/data/2071778/000207177826000058/frmi-20260930.htm>`_
  records termination of the TensorWave lease on November 10, 2026, following
  the missed closing date discussed in the article. Fermi also disclosed a
  nonbinding letter of intent with a different prospective customer. Equipment
  financing and a preliminary tenant agreement leave the construction funding
  and firm tenant gates open in the comparable scenario. The lease termination
  applies to the contract, not to the entire campus.
* **Balico, local denial.** `Pittsylvania County's April 18, 2025 report
  <https://www.pittsylvaniacountyva.gov/DocumentCenter/View/1488/April-18-2025-PDF>`_
  confirms the Board voted 6–1 on April 15 to deny the rezoning. The comparable
  scenario preserves predevelopment spend and stops before construction. The
  proposal's on-site generator rating is a supply rating and is excluded from
  delivered IT capacity.

Additional context for the model:

* `Berkeley Lab, Data Center Siting: Criteria, Policies, and Recent Trends
  <https://eta-publications.lbl.gov/sites/default/files/2026-10/eif_webinar_siting_v2.pdf>`_,
  slides 5–6, distinguishes development stages and describes power timing,
  land, fiber, water and local approvals as siting factors.
* `Equinix 2025 Form 10-K, development projects
  <https://investor.equinix.com/sec-filings/all-sec-filings/content/0001101239-26-000075/EQIXAnnualRpt2025PRINT.pdf>`_
  lists separate phases, opening targets and capital budgets within campuses.

All numerical inputs in the simulation are synthetic. The reporting dates illustrate
scenario arithmetic and carry no implied probability of completion.
