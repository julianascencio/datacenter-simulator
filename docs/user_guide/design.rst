Facility design workbench
=========================

Use a current IT peak and explicit growth allowance to calculate a future design,
then inspect its power, cooling, equipment schedule, backup energy and rack layout.
The workbench connects the existing cooling, infrastructure power balance, modular
sizing and UPS energy methods. It is a concept study with configurable assumptions.

Run and edit
------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.design --output outputs/design
   # Equivalent installed command:
   datacenter-design --it-kw 2000 --output outputs/design-2mw

Open ``outputs/design/design-workbench.html``. The offline report includes power
flow, capacity/contingency bars, demand sensitivity, annual operating-bin energy,
a dimensioned floor plan and a rotatable 3D rack view. A selector compares five
cooling technologies with N, N+1 and 2N capacity arrangements. These are precomputed
Python results; the browser does not implement a second set of equations.

`Open the design workbench <../_static/lab/design/design-workbench.html>`_ or follow
the :doc:`step-by-step tutorial <../gallery/methods/plot_facility_design>`.

Edit the exported ``inputs.json`` and ``bins.json`` to use your design conditions:

.. code-block:: bash

   datacenter-design --inputs outputs/design/inputs.json \
     --bins outputs/design/bins.json --output outputs/my-design

``inputs.json`` can also contain only the fields you want to override. Unknown
fields and invalid values fail validation. ``bins.json`` is an array of objects
with ``hours``, ``load_fraction`` and ``ambient_c``. It must sum to 8760 hours.
Load fractions are electrical demand / future design IT demand, not CPU utilization.
The default bins are synthetic, not Tenerife weather or measured operating data.

Python API
----------

.. code-block:: python

   from datacenter_simulator.models.design import DesignInputs, OperatingBin
   from datacenter_simulator.analysis.design import design_study, export_design_study
   from datacenter_simulator.utilities.design import design_power_flow, design_floor_plan

   inputs = DesignInputs(it_peak_kw=2000, growth_fraction=0.20,
                         rack_limit_kw=40, redundancy="2N", grid_limit_kw=4000)
   bins = [OperatingBin(4380, 0.6, 20), OperatingBin(4380, 0.9, 32)]
   study = design_study(inputs, bins)
   print(study.design.equipment)
   print(study.summary)
   design_power_flow(study.design).write_html("power.html")
   design_floor_plan(study.design).write_html("floor.html")
   export_design_study("outputs/my-design", inputs, bins)

Design sequence and equations
-----------------------------

1. **Future IT demand.** Networking is already included at equipment terminals.
   Growth is a one-time uplift: :math:`P_d=P_0(1+g)`. Rack count is
   :math:`\lceil P_d/P_{rack}\rceil`; the last rack carries the remainder.
2. **Heat and cooling.** Hall heat is :math:`Q=P_d/\eta_{distribution}`.
   Cooling duty adds the selected thermal margin, then rounds up to whole modules.
   The existing :class:`~datacenter_simulator.methods.cooling.CoolingPlant`
   evaluates the resulting duty capacity at design ambient. Spare modules are
   excluded from operating capacity and parasitic power. Liquid and air flow
   follow :math:`\dot m=Q_l/(c_p\Delta T_l)` and
   :math:`\dot V=Q_a/(\rho c_p\Delta T_a)`; coolant properties come from the
   selected cooling preset, including immersion fluid's separate heat capacity.
3. **Facility power.** The existing infrastructure balance combines IT,
   downstream losses, UPS losses, cooling electricity, auxiliaries and main
   losses. Only downstream losses heat the hall in this boundary. Cooling and
   auxiliaries sit outside the UPS branch. Full-facility generators therefore
   carry a different duty from IT UPS modules.
4. **Discrete power equipment.** Effective module output is
   :math:`\min(P_{rated},S_{rated}PF)d`, where :math:`d` is the module derating.
   Transformers use their kVA rating and facility PF. UPS uses a separate load PF.
   Required modules are :math:`n=\lceil P_{duty}/P_{usable}\rceil`.
5. **Capacity contingencies.** N installs :math:`n`, N+1 installs :math:`n+1`,
   and 2N installs two full-duty trains of :math:`n` modules each. The report
   removes one module for N/N+1 or one entire train for 2N and tests the remaining
   capacity against duty. All four equipment classes use the chosen arrangement.
   This does not model actual electrical switching or hydraulic topology.
6. **UPS battery.** Each bank requires
   :math:`E=P_{UPS,out}(t/60)/(\eta_{inv} f_{usable} f_{EOL})` nominal kWh.
   N and N+1 allocate one shared bank; 2N allocates two independent full-duty banks.
   Each bank's required output kW and kVA are exported separately. A sufficient
   kWh quantity does not prove adequate battery discharge power or UPS runtime.
7. **Utility service.** :math:`S=P_{facility}/PF` and balanced three-phase
   :math:`I=1000P_{facility}/(\sqrt{3}V_{LL}PF)`. Grid headroom compares the user
   limit with gross facility demand; this is not a cable/protection selection.
8. **Geometry.** Rectangular racks occupy rows separated by alternating cold
   and hot aisles, with perimeter clearance. Total planning area is white space
   times :math:`1+f_{support}`. This allowance does not locate all support equipment.
9. **Annual energy.** With a frozen design, evaluate each load/weather bin:
   :math:`E_f=\sum_i P_{f,i}h_i`, :math:`PUE=E_f/\sum_i P_{IT,i}h_i`.
   Multiply energy by the explicit flat electricity and grid-carbon assumptions.
   Capacity exceedance sums :math:`\max(0,P_{f,i}-P_{grid})h_i`; it is a supply
   gap, not unserved-energy or reliability prediction. Hotter operating bins can
   exceed the design electrical duty and must be assessed separately.

Audit files
-----------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - File
     - Contents
   * - ``inputs.json``, ``bins.json``
     - Editable, round-trippable design assumptions and operating histogram.
   * - ``summary.json``, ``balance.json``
     - Baseline capacities, energy, flow, geometry and conserved peak power balance.
   * - ``equipment.csv``, ``racks.csv``
     - Baseline equipment counts, contingency checks and every rack coordinate.
   * - ``operating.csv``, ``load_sweep.csv``
     - Baseline bin calculations and fixed-design demand sensitivity.
   * - ``comparison.csv``, ``scenarios.json``
     - All 15 scenarios, including inputs, summaries, balances and equipment counts.
   * - ``evidence.json``
     - Method references, equations and exclusions.

Report scenario changes do not rewrite the baseline download files. The comparison
and scenarios files contain the alternatives. Floor-plan previews are capped at
1000 racks for browser performance; the geometry CSV contains all racks.

Evidence and limits
-------------------

The `DOE/FEMP 2024 design guide
<https://www.energy.gov/sites/default/files/2024-07/best-practice-guide-data-center-design_0.pdf>`_
supports the connected IT/cooling/electrical design approach, future and partial
load evaluation, and energy-based PUE. The `Vertiv system-sizing manual
<https://www.vertiv.com/globalassets/products/critical-power/uninterruptible-power-supplies-ups/discontinued---liebert-datawave/liebert-datawave-technical-data-manual.pdf>`_
provides the kW/kVA/PF and balanced three-phase relationships. Neither source
calibrates this example's defaults or establishes compliance.

Cooling presets and efficiencies are illustrative. There is no part-load UPS map,
spare equipment standby consumption, battery discharge curve, generator starting,
fault/protection coordination, CFD, egress/structural validation, availability model
or Tier certification. Electrical redundancy does not make a common battery bank
redundant. Fixed cooling capacity does not include manufacturer ambient derating
curves. Use :doc:`grid_management` for dispatch and :doc:`engineering` for detailed
electrical, hydraulic and contingency models. A lower modelled PUE is not proof of
better compute efficiency or a validated procurement recommendation.

Tests independently check a 980 kW IT hand calculation, kVA-limited module counts,
exact capacity boundaries, battery duplication, energy weighting, grid gaps,
geometry non-overlap, invalid inputs, conservation across all 15 alternatives and
JSON round trips. Browser checks cover scenario changes, downloads, offline use
and desktop/mobile layouts.
