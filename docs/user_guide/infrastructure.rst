Synthetic equipment-content study
=================================

Turn the user-supplied *Who Makes the Data Center 2026* infographic into a
reproducible cost and engineering exercise. This is a **synthetic screening
case**, not a procurement budget, vendor performance comparison, or measured
facility. The original graphic is not redistributed.

Run and inspect
---------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.infrastructure --it-mw 20 --output outputs/infrastructure

Open ``outputs/infrastructure/infrastructure-study.html``. It is self-contained
and works offline. Six CSVs contain the cost lines, equipment sizing, hourly
operation, cost sensitivities, cooling sensitivities and capacity sweep. Four
JSONs preserve the assumptions, evidence, design balance and summary.

The :doc:`step-by-step gallery tutorial <../gallery/analysis/plot_infrastructure_content>`
explains every stage. The documentation also bundles an
`interactive report <../_static/lab/infrastructure/infrastructure-study.html>`_.

.. code-block:: python

   from datacenter_simulator.analysis.infrastructure import export_infrastructure_study
   from datacenter_simulator.use_cases.infrastructure import InfrastructureCase

   study = export_infrastructure_study(
       "outputs/my-case",
       InfrastructureCase(it_mw=10, rack_kw=80, liquid_heat_fraction=0.75,
                          ups_autonomy_minutes=15),
   )
   print(study.sizing)

Evidence and the twelve rates
-----------------------------

The supplied link is https://lnkd.in/p/epbFKeP5. The short link was inaccessible
on 8 November 2026; rates and labels were manually transcribed from the attached
screenshot. Original authorship, market date, price scope, redundancy inclusions
and MW denominator were not independently established. The title's "2026" is
not a verified cost base year. The dollar symbol is interpreted as USD.

.. list-table:: Image transcription: million USD per unspecified MW
   :header-rows: 1

   * - Category
     - Rate
   * - Cooling towers
     - 0.1
   * - Chillers
     - 0.4
   * - UPS
     - 1.1
   * - Switchgear
     - 0.8
   * - Generators
     - 1.1
   * - Air cooling
     - 0.5
   * - Liquid cooling
     - 0.6
   * - Power distribution
     - 0.5
   * - Servers
     - 31.4
   * - Networking
     - 4.8
   * - Engineering fee
     - 0.5
   * - Construction fee
     - 0.9
   * - **Listed subtotal**
     - **42.7**

The baseline interprets all rates as **per IT MW**. For 20 MW this produces
USD 854 million: 724 million IT, 102 million infrastructure and 28 million
services. The API separately evaluates the facility-MW interpretation.

All twelve lines are summed once, including both cooling categories. Their
possible scope overlap is unresolved: a real quotation must establish whether
air/liquid equipment, chillers and towers are disjoint. Fees are absolute
per-MW amounts, not percentages. The construction fee does **not** establish the
building-shell cost. Land, utility connection/substation, permits, taxes,
security/fire systems, unspecified storage, financing, operations, maintenance
and replacement are unpriced. Zero extra allowance means unpriced, not absent.

Vendor strings are retained as unverified labels in the cost CSV and evidence
JSON. They are not current capability checks, vendor rankings, calibrated
curves or allocations of spend between companies.

Models and equations
--------------------

Capital accounting
~~~~~~~~~~~~~~~~~~

For item :math:`i`, the rate :math:`r_i` is in million USD/MW, the selected
capacity :math:`M` is MW, and :math:`f_i` is a deliberate sensitivity multiplier:

.. math::

   C_i = 10^6 r_i M f_i, \qquad
   C_{scenario} = \left(\sum_i C_i\right)(1+c) + C_{unlisted}.

Contingency :math:`c` applies to the listed subtotal only. Every scenario retains
its denominator. No N+1 equipment multiplier is automatically applied: the image
may already include redundancy. Engineering counts and cost content remain
separate until traceable unit quotations establish their relationship.

Power and heat boundaries
~~~~~~~~~~~~~~~~~~~~~~~~~

IT terminal demand includes servers and networking. The assumed network power
share (4%) is independent of the networking cost share. The default rack
capacity is 100 kW total IT, with 200 racks in the 20 MW case. The 48-hour
profile's IT load fraction is an electrical load fraction, not CPU utilization.

.. math::

   P_{UPS,out} = P_{IT}/\eta_d, \qquad
   P_{UPS,in} = P_{UPS,out}/\eta_u,

   Q_{hall} = P_{UPS,out}, \qquad
   P_{meter} = (P_{UPS,in}+P_{cool}+P_{aux})/\eta_m.

The downstream distribution loss heats the hall. UPS and main distribution
losses and site auxiliary heat are assumed outside the conditioned hall. The
existing :class:`~datacenter_simulator.methods.cooling.CoolingPlant` evaluates
liquid and residual-air heat removal, compressor demand, fans/pumps, flows and
unmet cooling. Heat rejected by the plant equals removed heat plus cooling
electricity. Site auxiliaries are additional; cooling auxiliaries are not counted
twice. Economizer operation is disabled in this case.

These are aggregate planning boundaries, not radial DC load flow, harmonic,
transient, protection or full hydraulic design. Thermal module envelopes do not
replace a detailed chiller/condenser/tower loop model. Water is not calculated.
The existing weather-cooling module supports separate water studies.

The design ambient is an invented 35 degrees C. Synthetic hourly weather spans
25–35 degrees C; no site, climate or annual production claim is made. For the
48-hour series, PUE is an energy ratio:

.. math::

   PUE_{period} = \frac{\sum_t P_{meter,t}\Delta t}{\sum_t P_{IT,t}\Delta t}.

It is neither an arithmetic mean of instantaneous ratios nor measured annual
PUE. The 48-hour electricity bill uses an invented USD 0.10/kWh and excludes
other operating costs. The default results are approximately 26.203 MW design
meter demand and 1.291 period energy PUE, with zero modelled unmet hall heat.

Modular capacity and UPS autonomy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For duty :math:`P`, nameplate rating :math:`R`, derating :math:`d` and reserve
count :math:`s`, the method installs :math:`\lceil P/(Rd)\rceil+s` modules.
Zero duty installs none. The report checks capacity after losing the reserve
count. The default uses one reserve module per bank, except racks. These are
capacity checks, not Tier ratings, reliability probabilities, switchgear
protection studies or independent A/B paths. Common fuel, pipes and feeds remain
possible shared failures.

Unit ratings are invented: 3 MW generators (10% derating), 1 MW/1 MVA UPSs,
5 MW switchgear envelopes, 2 MW IT distribution envelopes, 3 MW thermal chillers,
2 MW thermal CDUs, 250 kW thermal air handlers and 3 MW thermal rejection units.
These ratings, reserve counts and duties are exported in ``sizing.csv``.
Bank counts cover full design duty. The aggregate cooling model separately uses
15% thermal capacity headroom; standby modules are not assumed to consume power.
The bank arithmetic does not reproduce part-load equipment staging.

Both UPS kW and kVA constrain load. Battery autonomy uses a constant-power
energy approximation:

.. math::

   E_{nominal} = \frac{P_{UPS,out}\,t_{minutes}}
   {60\eta_{inverter} f_{usable} f_{EOL}}.

The default inverter, usable-energy and end-of-life factors are 0.95, 0.8 and
0.8. Ten minutes at design UPS output requires about 5.594 MWh nominal battery
energy. Normal AC UPS efficiency and battery-mode inverter efficiency are
separate assumptions.

**UPS support covers IT only. Cooling is outside the UPS branch.** Battery
runtime does not establish safe facility ride-through. Generator startup,
transfer delay, battery discharge curves, recharge, shared battery faults and
thermal survival require further modelling; the existing resilience APIs can
be used for a separate event study. No battery cost is added on top of the image
UPS rate because its inclusions are unknown.

Validation and interpretation
-----------------------------

Tests reconcile all twelve lines, exact group totals, denominator changes,
allowances and price sensitivities. Hand-calculated power/heat and UPS examples
check boundary conservation. Tests cover module ceiling boundaries, kVA overload,
zero duty, invalid inputs, hourly energy weighting and offline report export.
The gallery executes in Sphinx, and browser checks inspect report plots, audit
downloads and desktop/mobile layout. Numerical verification is not empirical
calibration.

Isolated sensitivities include servers +/-20%, networking +20%, infrastructure
+20%, a 10% listed-scope contingency, alternative MW interpretation, heat-capture
mix and a 1–100 MW scale sweep. These percentages are invented stress tests, not
statistical confidence intervals. Cooling scenarios hold source cost rates
fixed; no cooling price saving, vendor revenue or compute throughput is inferred.

Primary engineering context
---------------------------

* `DOE/FEMP, Best Practices Guide for Energy-Efficient Data Center Design (2024)
  <https://www.energy.gov/cmei/femp/articles/best-practices-guide-energy-efficient-data-center-design>`_:
  terminology and IT/electrical/cooling boundaries, not cost or coefficient calibration.
* `DOE/FEMP, Cooling Water Efficiency Opportunities for Federal Data Centers
  <https://www.energy.gov/cmei/femp/cooling-water-efficiency-opportunities-federal-data-centers>`_:
  PUE uses facility energy divided by IT energy.
* `Eaton, UPS sizing guide
  <https://www.eaton.com/us/en-us/products/backup-power-ups-surge-it-power-distribution/backup-power-ups/ups-sizing-guide.html>`_:
  distinguish power capacity, power factor and autonomy. The implemented energy
  approximation is not a manufacturer's battery discharge curve.
