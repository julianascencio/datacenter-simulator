Coupled engineering studies
===========================

Version 0.2 adds eight study methods and six tutorials to the original facility
workflow. Use each model at its declared boundary, then connect its outputs to
the next layer. The existing :func:`~datacenter_simulator.simulation.simulate`
API remains the simple facility energy workflow; it does not implicitly enable
every advanced solver.

.. list-table:: Choose a study
   :header-rows: 1
   :widths: 25 45 30

   * - Question
     - Method
     - Tutorial
   * - Which device curve is supported by evidence?
     - Provenance, bounded power/efficiency maps, held-out errors
     - :doc:`../gallery/methods/plot_dc_design`
   * - Which DC feeder is feasible?
     - Electrothermal sizing and route-derived resistance
     - :doc:`../gallery/methods/plot_dc_design`
   * - Can cooling branches deliver the heat?
     - Parallel hydraulics, pump curves, finite-UA CDU
     - :doc:`../gallery/methods/plot_cdu_design`
   * - How do sources share a DC network?
     - Meshed resistive load flow, power/voltage/droop ports
     - :doc:`../gallery/analysis/plot_dc_microgrid`
   * - What survives an equipment failure?
     - A/B transfer, N+1 capacity, hold-up and powered cooling
     - :doc:`../gallery/analysis/plot_ab_resilience`
   * - What changes with climate?
     - Dry/wet/hybrid rejection, water and useful heat
     - :doc:`../gallery/analysis/plot_climate_cooling`
   * - When should storage and flexible jobs run?
     - MILP dispatch, forecast replay, carbon-aware start times
     - :doc:`../gallery/analysis/plot_dc_microgrid`
   * - What does congestion cost in energy and completion time?
     - Fluid ECMP/max-min sharing, compute phases and thermal throttling
     - :doc:`../gallery/analysis/plot_workload_network`

Run an offline engineering lab
------------------------------

.. code-block:: bash

   python -m pip install -e '.[docs,solar]'
   python -m datacenter_simulator.analysis.engineering --output outputs/engineering

Open ``outputs/engineering/engineering-lab.html``. Select a rack in any view or
use the selector; connected assets highlight in the 3D hall, floor plan, power,
cooling and communication schematics. The time slider replays a feed failure
with actual supplied rack power, active feed and lumped zone temperature.
``dc-grid.html`` separately shows the solved resistive DC single-line with
signed currents, source modes, bus voltages and feeder losses. CSV tables and a
versioned study manifest make the export inspectable without a browser.

.. raw:: html

   <p><a class="btn btn-primary" href="../_static/lab/engineering-lab.html">Open linked engineering lab →</a>
   <a class="btn btn-secondary" href="../_static/lab/dc-grid.html">Open solved DC single-line →</a></p>

Geometry and connectivity share stable equipment IDs. ``Route.length_m`` feeds
both electrical cable resistance and the supply/return pipe length in the
hydraulic example. The rack meshes are dimensioned representations, not vendor
CAD. Routes are explicit input polylines, not an automatic routing algorithm.
The A/B lab displays the capacity/transfer model; it does not imply that the
single-source numerical DC snapshot includes both regulated feeds.

Evidence and equipment curves
-----------------------------

``PowerCurve`` uses monotone, piecewise-linear interpolation over utilization
0–1. ``ConverterMap`` interpolates efficiency over load and temperature, applies
an optional temperature capacity curve, and adds standby demand. Both reject
extrapolation. ``Provenance`` records source, configuration, measurement boundary,
evidence type and optional relative uncertainty. Unknown uncertainty stays
unknown; the sensitivity sampler is not a confidence interval.

The bundled SPECpower result is whole-system **AC input** for one CPU server and
benchmark configuration. Its target workload fraction is not CPU utilization or
a GPU measurement. ``Electrical(curve=...)`` requires a DC-terminal curve and
rejects that AC dataset unless the user supplies an independently justified
boundary conversion. Example 07 holds out alternating measured points to
quantify interpolation error; it does not validate another server model.
Read-only CSV and Redfish ``EnvironmentMetrics`` parsers accept supplied data;
no credentials, live polling or control commands are involved.

Electrothermal DC design and multiple sources
---------------------------------------------

For a two-conductor feeder:

.. math::

   R(T)=2\rho_{20}L/A[1+\alpha(T-20)],\quad
   I=P/V_r,\quad V_r=V_s-IR(T),\quad T=T_a+\theta I^2R(T).

``Feeder`` requires a route length, conductor area, installation-specific ampacity,
derating and an aggregate loop thermal resistance. These are supplied assumptions,
not an installation-code ampacity calculation. ``solve_feeder`` finds the stable
high-voltage solution and reports voltage, conductor temperature, loss and copper
mass. Voltage collapse or no thermal equilibrium raises an error; sweeps retain
those infeasible rows. Converter input demand and temperature derating are
included when a map is supplied.

``DCGrid`` solves the actual resistive nodal equations, not the linear DC
approximation used for AC transmission:

.. math::

   \sum_j (V_i-V_j)/R_{ij}+P_{load,i}/V_i-I_{source,i}(V_i)=0.

A voltage port fixes its bus voltage; a power port injects or absorbs specified
DC-bus power; a droop port uses a bounded ``(Vref - V)/Rdroop`` characteristic.
Every island needs a voltage reference or droop source. Power, sink and current
limits are explicit; violations or nonconvergence fail the solve. Line loading
is reported separately. ``solve_with_shedding`` uniformly reduces load for a
**deficit** study; surplus needs explicit generation curtailment. Nominal voltages
must match across a resistive line. This model has no explicit bipolar midpoint,
DC/DC transformer edge, arc, fault clearing, control stability or switching EMT.

``simulate_dc_microgrid`` feeds load-flow losses back into PV/battery/grid dispatch
and uniform terminal-load shedding. It compares array-side DC/DC coupling with
PV inverter plus rectifier coupling, including rating and efficiency limits.
The battery is DC-connected in both cases. The root source power/current ratings
and the interval AC grid-import limit all constrain available grid power. Islanded operation requires available
PV or battery voltage support; an unpowered interval has no invented energized
snapshot. This is a greedy physical dispatch study, separate from the optimizer.

Cooling hydraulics, weather and heat reuse
------------------------------------------

``solve_cdu`` balances parallel branch pressure drops against the pump curve:

.. math::

   \Delta p=(fL/D+K)\rho v^2/2,\qquad
   P_{pump}=\Delta p\dot V/\eta,\qquad
   Q=\epsilon C_{min}(T_{hot,in}-T_{cold,in}).

Pipe lengths include supply and return. The model includes laminar/turbulent
friction, branch resistance, pump speed/parallel pumps, a fixed primary flow and
finite-UA counterflow heat exchange. Pump heat enters the secondary loop;
blocked branches and heat-transfer limits report unmet heat. Component temperature
is a supplied thermal-resistance estimate. Fluid properties are constant;
there is no cavitation, fluid transient, valve controller or two-phase physics.

``evaluate_weather_cooling`` evaluates dry, evaporative and hybrid heat rejection
with an explicit indoor dewpoint margin, bounded chiller COP map and optional
useful heat demand. Water is evaporation plus drift plus nonnegative blowdown,
not recirculating flow. Heat recovery requires a compatible delivery temperature
or a supplied heat-pump COP; heat-pump electricity is counted once.

The three bundled PVGIS TMY snapshots run offline. They are composite typical
years from satellite/reanalysis resources, not measured facility records.
Original selected month-years and source timestamps remain in the data/metadata.
Hourly studies use an explicit 2021 UTC calendar for alignment. Example 10 counts
IT plus plant electricity only: its PUE excludes distribution and other facility
loads, and its WUE includes on-site makeup water only. The warm-water supply and
illustrative performance assumptions explain high economizer availability; they
are not universal rankings of cooling technologies. Below freezing, psychrometrics
use a liquid-water approximation and do not model icing.

Failures, workloads and dispatch
--------------------------------

``simulate_contingencies`` resolves failure/recovery boundaries, transfer delay and
hold-up expiration independently of the reporting step. Feed modules provide N+1
capacity; shared dependencies represent common causes. Cooling consumes capacity
on its declared electrical feed before racks. Racks use input order for capacity
priority, retain a surviving feed after recovery, and do not automatically fail
back. Transfer is triggered by complete feed unavailability; partial module
capacity loss uses the declared load priority and can leave unmet rack demand.
Hold-up energy only covers transfer delay. Actual supplied rack power heats
the lumped zone. These are deterministic scenarios, not failure probabilities,
Tier certification, availability estimates or protection coordination.

``optimize_dispatch`` minimizes import/export cost, optional carbon price, a
throughput degradation proxy, a horizon peak-demand charge and penalized unserved
energy. SOC, terminal reserve, charge/discharge and import/export limits are
constraints; binary direction variables prevent simultaneous opposing flows,
even with negative tariffs. Demand charges apply to this horizon, not an implied
billing month. The throughput term is not a battery lifetime model.

``rolling_dispatch`` replans over a fixed forecast trace and executes one step
against actual demand, generation and grid limits. It cancels infeasible charging,
uses available energy for unexpected deficits and reports curtailment/unserved
load. Its ``reserve_soc`` is a horizon-end target; emergency recourse can use energy
down to the battery minimum. It is a forecast-error experiment, not a probabilistic
forecast service. The optimizer uses a declared common bus and does not embed the
nonlinear ``DCGrid`` equations or automatically size equipment.

``simulate_workloads`` runs nonpreemptive FIFO or earliest-deadline jobs with compute
and transfer phases. Transfers split equally over shortest equal-cost paths and
share directional link capacity by max-min fairness. Network failures change
throughput and completion time; waiting power and compute demand heat each zone.
Power caps and a configurable temperature-throttling law reduce compute progress.
This is a fluid scheduler, with no TCP, packets, queue latency or protocol overhead.
Completion/energy/deadline metrics retain unfinished jobs explicitly.

``schedule_carbon_aware`` places contiguous job reservations within release/deadline
windows on a supplied carbon trace. Duration, transfer bandwidth and planning power
are estimates; replay with ``simulate_workloads`` is required to assess contention,
thermal throttling and actual deadlines. ``workload_power_profile`` integrates
irregular event intervals exactly into regular DC-terminal averages (zero-padding
the final interval). Pass those columns as ``device_power_kw`` to ``simulate`` for
facility losses/cooling/generation accounting, with matching device IDs and times.

Validation and reproducibility
------------------------------

See :doc:`../research/engineering` for source-to-method traceability, verification
checks, optional independent benchmarks and remaining measured-validation work.
