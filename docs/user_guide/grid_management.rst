Grid management and the Wyoming recovery case
================================================================================

All models, algorithms and numerical analyses live inside the installed
``datacenter_simulator`` package. The gallery only calls these APIs and plots
their outputs. There is no dependency on Energy Data Insights, Energy Agents,
the earlier standalone ZIP, or any online service.

Run the complete exercise
--------------------------------------------------------------------------------

.. code-block:: bash

   python -m pip install -e '.[dev,docs]'
   python -m datacenter_simulator.analysis.wyoming --output outputs/wyoming
   # Equivalent installed entry point:
   datacenter-grid --output outputs/wyoming

Open ``outputs/wyoming/wyoming-grid-management.html``. The self-contained report
includes dispatch, battery state, critical shortfalls and commissioning curves.
The same directory contains hourly and monthly CSVs, generator availability,
source-level dispatch, assumptions, model boundaries and the evidence registry.

The documentation build also publishes the
`interactive Wyoming report <../_static/lab/wyoming/wyoming-grid-management.html>`_.

The optional ``--inputs recovery_inputs.json`` changes the monthly planning
study only. The operational benchmark deliberately keeps its separately exported
default inputs. For different operational parameters, call ``optimize_grid``
with your own profiles, generators, battery and outage events.

.. code-block:: python

   from datacenter_simulator.methods.energy import Battery
   from datacenter_simulator.methods.grid_management import optimize_grid
   from datacenter_simulator.models.grid_management import GridPolicy
   from datacenter_simulator.use_cases.wyoming import wyoming_generators, wyoming_profiles

   result = optimize_grid(
       wyoming_profiles(),
       wyoming_generators(),
       battery=Battery(1_000_000, 200_000, 200_000, initial_soc=0.7),
       policy=GridPolicy(carbon_price_per_kg=0.05),
   )
   print(result.summary)

This API snippet starts generators from their fixture defaults of zero output;
the comparative outage study uses explicitly supplied initial outputs to isolate
the outage from cold-start behavior. For zero unserved critical load, set
``require_critical_service=True``; infeasible cases raise an error.

Models and locations
--------------------------------------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Package module
     - Responsibility
   * - ``models.grid_management``
     - Generator ratings, heat rates, capture auxiliaries, fuel groups, outage intervals and policy.
   * - ``methods.grid_management``
     - Availability, commissioning, contingency screening and chronological mixed-integer dispatch.
   * - ``methods.project_recovery``
     - Monthly commissioning, firm capacity, staged capital, carbon and power-cost sensitivities.
   * - ``methods.energy``
     - Existing Battery model reused without changing its kW/kWh boundary.
   * - ``use_cases.wyoming``
     - Packaged evidence, editable study inputs and synthetic outage/profile fixtures.
   * - ``analysis.wyoming``
     - Reproducible scenario orchestration and CSV/JSON/report export.
   * - ``utilities.grid_management``
     - Offline Plotly presentation of calculated outputs.

Operational model
--------------------------------------------------------------------------------

Power is interval-average **kW at one facility electrical bus**; stored energy
is **kWh**. Profiles must have unique, increasing, timezone-aware timestamps and
exactly match the declared time step. Required columns are ``demand_kw``,
``critical_demand_kw``, ``renewable_kw``, ``grid_limit_kw``,
``import_price_per_kwh`` and ``grid_carbon_kg_per_kwh``. Generation can also have
an exactly aligned availability matrix. No missing values are interpolated.

The balance in every interval is

.. math::

   \sum_g P_{g,t} + I_t + R_t - C_t + D_t
   = L_t - U^{crit}_t - U^{flex}_t + Q_t + S_t.

Here ``I`` is imported power, ``R`` available renewable power, ``C`` renewable
curtailment, ``D`` battery discharge, ``Q`` battery charge and ``S`` spilled
dispatchable output. Spill allows a ramp-limited generator to reject output
after load falls; it cannot exceed generated power. No grid export is modeled.

Battery energy follows

.. math::

   E_t = E_{t-1} + \eta_c Q_t\Delta t - D_t\Delta t/\eta_d.

A binary direction variable prevents simultaneous charging and discharging,
including during negative-price intervals. Energy and power limits hold at
every step. Terminal SOC defaults to at least the initial SOC. No battery
capacity receives permanent firm-capacity credit in the static screening.

Generator net capacity is its supplied rating multiplied by delivery allowance
and ``(1 - capture_auxiliary_fraction)``. Dispatch is bounded by commissioned,
available net capacity and ramp limits. A forced capacity loss may trip a unit
faster than its normal ramp-down; restoration still obeys ramp-up limits.
Outages may remove named generators, shared fuel groups or imported service.
Event boundaries inside the horizon must align to time steps.

The objective includes energy/fuel/variable operating cost, residual-carbon
cost, battery throughput, peak-import demand charge and separate critical and
flexible unserved-energy penalties. Demand charges apply **once per supplied
horizon**, not automatically per billing month. Priorities are economic weights,
not a hard SLA unless critical service is explicitly required. Flexible load
shedding is lost work, not postponed work. Use the existing workload/scheduling
models when useful jobs must be shifted rather than dropped.

Source-specific residual and captured carbon are calculated from HHV heat rate,
fuel emission factor, dispatched net output, capture auxiliaries and effective
capture fraction. Unserved demand and unused generation do not earn fictitious
emissions reductions. Spilled generated power still consumes fuel and emits.

The MILP uses SciPy's HiGHS interface:
`scipy.optimize.milp <https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html>`_.
It is a deterministic **perfect-foresight benchmark**, not a calibrated forecast
or operational controller. It does not model startup fuel, minimum up/down time,
AC voltage, reactive power, frequency, protection or transient islanding.
Static N-1 screening does not make an economic schedule security-constrained.

Relationship to the facility simulator
--------------------------------------------------------------------------------

Use facility demand after electrical conversion and cooling as ``demand_kw``.
Do not send IT-terminal power directly without those overheads. The existing
``simulation`` and cooling methods can produce those loads. The campus optimizer
then manages external supply at that boundary. Conversely, a resulting supply
limit can inform workload/thermal studies. This is sequential coupling, not a
claim that the MILP solves all electrical and thermal equations simultaneously.
The original ``methods.optimization`` and ``methods.microgrid`` APIs remain
available for battery/job scheduling and coupled resistive DC studies.

Evidence and assumptions
--------------------------------------------------------------------------------

Evidence cutoff: **8 November 2026**. Google acquired the site; operational
success is not established. The fixture contains 15 linked source records,
including Google, AEP, Tallgrass, Black Hills, county planning, EPA and EIA.
Read ``wyoming_sources()`` or exported ``sources.json`` for the full registry.

* `Crusoe acquisition statement <https://www.crusoe.ai/resources/newsroom/crusoe-wyoming-data-center-campus-update>`_.
* `Google project announcement <https://blog.google/innovation-and-ai/infrastructure-and-cloud/global-network/wyoming-data-center/>`_.
* `Black Hills power agreements <https://ir.blackhillscorp.com/news-releases/news-release-details/black-hills-corp-executes-definitive-agreements-serve-googles>`_.
* `AEP fuel-cell project <https://pr.aep.com/news/releases/read/12314/AEP-Advances-Innovative-Energy-Solution-for-Google-with-702MW-of-Bloom-Fuel-Cells>`_.
* `Tallgrass turbine allocation <https://www.tallgrass.com/newsroom/press-releases/tallgrass-and-mitsubishi-power-americas-announce-turbine-allocation-for-cheyenne-power-hub-051526>`_.

Identified ratings total 702 MW fuel cells, 1,150 MW turbines, 564 MW utility
generation and 26 MW market service. The broader approximately 2.69 GW portfolio
has a 248 MW reconciliation gap, which receives no modeled capacity credit.
This gap does not prove a real project shortfall. The utility-path outage removes
both Black Hills generation and market service; they are not treated as
independent supplies when that path fails.

The 1.8 GW facility load, PUE 1.20, 100 MW IT blocks, generator partitions,
commissioning dates, 5% delivery allowance, 5% fuel-cell capture auxiliaries,
90% capture at 95% availability, prices, financing, shared gas group and
1 GWh / 200 MW battery are assumptions. Catalog ratings are not site guarantees.
The actual upstream gas topology and electrical outage domains need verification.

The planning study uses **MW/MWh** and reproduces four cases: build-ahead,
power-gated, power-gated plus hypothetical 100 MW delivered firm capacity,
and delayed recovery. The extra capacity is already net of its own contingency
requirements and is not an announced asset. Staged investment assumes perfect
knowledge of power milestones and a three-month investment lead; this is not
a three-month building-construction claim. Idle-capital carry is not a project
valuation, a reported loss or a profit forecast.

The original annual emissions screen uses a fixed source dispatch order and
8,760 hours. The new hourly optimizer uses economic merit order, explicit ramps
and outages, so their carbon results need not agree. Both exclude upstream
methane, embodied emissions and offsets. The combined-cycle CCS sensitivity
omits turbine capture energy penalty and capital cost; it is explicitly optimistic.

Validation and examples
--------------------------------------------------------------------------------

Tests compare closed-form merit order, outage energy deficits, battery duration,
efficiency losses, peak shaving, capture carbon balances and forced trips. They
check timestamp alignment, invalid inputs, shared outages, commissioning, ramp
restoration, direction exclusivity and exact original planning baselines.

.. code-block:: bash

   python -m pytest tests/test_grid_management.py tests/test_wyoming_recovery.py

See :doc:`../gallery/methods/plot_grid_management` and
:doc:`../gallery/analysis/plot_wyoming_recovery` for executable, plotted walkthroughs.
