Engineering evidence and validation
===================================

The version 0.2 research additions implement eight methods and six reproducible
examples. A source can motivate a model without validating its predictions.
This page separates measured inputs, numerical verification, external comparisons
and work still required for engineering use.

Source-to-method map
--------------------

.. list-table::
   :header-rows: 1
   :widths: 26 39 35

   * - Primary evidence
     - Implemented method
     - Verification and boundary
   * - `SPECpower Compal SR224-2A result <https://spec.org/power_ssj2008/results/res2026q2/power_ssj2008-20260329-01559.html>`_
     - Attributed measured AC-input curve, configuration metadata, held-out interpolation study
     - Five held-out points; no claim about another CPU/GPU or DC-terminal power
   * - `NBS Copper Wire Tables <https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e3.pdf>`_
     - Copper resistance, temperature feedback, explicit installation ampacity and route length
     - Analytical quadratic voltage and energy/thermal balances; ampacity remains a supplied rating
   * - `OCP LVDC architecture overview <https://www.opencompute.org/news/powering-the-next-era-of-ai-how-google-microsoft-and-nvidia-are-standardizing-and-accelerating-the-industry-transition-to-lvdc/>`_
     - 400/800 V comparison, distributed source ports, direct DC PV/storage study
     - Topology context only; no OCP certification or explicit bipolar midpoint
   * - `PyPSA nonlinear power flow <https://docs.pypsa.org/latest/user-guide/power-flow/>`_
     - Meshed resistive nodal equations, power/voltage/droop controls
     - Optional executed PyPSA voltage/loss comparison, analytic source sharing, KCL and energy residuals
   * - `OCP Cold Plate Cooling Loop Requirements, Rev. 2 <https://www.opencompute.org/documents/cold-plate-cooling-loop-requirements-rev-2-pdf>`_
     - Separate primary/secondary loops, branch hydraulics, CDU heat exchange
     - Poiseuille limit, equal-capacity epsilon-NTU limit, pressure/heat conservation; no vendor curve fit
   * - `DOE/FEMP data center design guide <https://www.energy.gov/cmei/femp/articles/best-practices-guide-energy-efficient-data-center-design>`_
     - Powered cooling dependencies, warm-water economizers, useful heat recovery
     - Deterministic failure timing, transfer hold-up and thermal-step convergence; no reliability probability
   * - `EnergyPlus cooling tower engineering reference <https://energyplus.readthedocs.io/en/v26.2.0/guides/engineering-reference/16.1-cooling-towers-and-evaporative-fluid-coolers.html>`_
     - Evaporation, drift and blowdown accounting; dry/wet/hybrid alternatives
     - Water and energy invariants, saturation/dewpoint bounds; not a reproduction of the EnergyPlus plant solver
   * - `JRC PVGIS TMY generator <https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/pvgis-5-tools/pvgis-typical-meteorological-year-tmy-generator_en>`_
     - Three offline hourly weather/resource snapshots; annual cooling and solar studies
     - 8760 unique regular UTC intervals each, units, humidity range, original month-year provenance and SHA-256
   * - `pvlib ModelChain <https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.modelchain.ModelChain.run_model.html>`_
     - PVWatts array DC and inverter AC output from supplied irradiance/weather
     - Optional pvlib scaling/conversion-boundary test; weather is not a measured site PV output trace
   * - `REopt method context <https://www.nlr.gov/reopt/curriculum/what-is-reopt>`_ and `SciPy MILP <https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html>`_
     - Cost/carbon/reserve storage dispatch, peak and throughput penalties, rolling replay
     - Small known optimum, SOC/conservation, negative tariffs, forecast error and outage tests; not REopt integration
   * - `Carbon-Aware Computing for Datacenters <https://arxiv.org/abs/2106.11750>`_
     - Deadline-constrained flexible job starts over a carbon trace
     - Toy optimum, release/deadline windows and replay; a simplified scheduler, not a reproduction of Google's system
   * - `DMTF Redfish schemas <https://redfish.dmtf.org/redfish/schema_index>`_
     - Read-only EnvironmentMetrics payload normalization
     - Missing/null telemetry preserved; live authentication, polling and control remain outside this adapter

Data provenance
---------------

``data/specpower_compal.csv`` contains eleven published numerical operating points
from the Compal SR224-2A result (tested 2026-03-18). Its JSON companion identifies
two AMD EPYC 9965 CPUs, 384 GB memory, the original result URL and the AC-input
measurement boundary. Consult that result for complete software, BIOS, workload
and measurement settings. These factual values are transcribed for a calibration
example; SPEC marks and benchmark definitions belong to their respective owners.
No original report text, charts or vendor endorsement is reproduced.

``data/weather_{tenerife,frankfurt,seville}.csv`` contains PVGIS 5.3 TMY resources
requested at the coordinates recorded in each JSON companion. Metadata preserves
the exact API URL, selected month-years, provider inputs, retrieval timestamp,
source URL and CSV checksum. Credit the European Commission Joint Research Centre
PVGIS and the underlying databases named in the response. The dataset remains
subject to the source provider's reuse terms; the package's software license does
not replace those terms. Each year is mapped to a non-leap 2021 UTC calendar while
preserving original source timestamps. No measured facility weather, load or
renewable output is implied.

The converter/chiller maps, hydraulic resistances, equipment capacities, routes,
thermal masses, tariffs, carbon traces and jobs are deliberately **illustrative**.
The carbon and tariff traces are not live grid data. The engineering lab's geometry
and equipment are not manufacturer assets. Sensitivity samples use a recorded seed
and independent bounded distributions, with failed samples retained. They describe
assumption sensitivity, not statistical uncertainty in a calibrated facility.

Verification you can reproduce
------------------------------

.. code-block:: bash

   python -m pip install -e '.[dev,docs,solar,benchmarks]'
   python -m pytest
   python -m pytest tests/test_external_benchmarks.py -v
   python -m sphinx -W --keep-going -b html docs docs/_build/html

Core tests cover electrical KCL/energy and voltage collapse, converter boundaries,
feeder temperature, droop sharing, battery bounds, dispatch direction, heat/water
balances, hydraulic operating points, failure timing, fluid network fairness,
completion energy and thermal timestep convergence. Gallery examples execute from
installed public APIs. CI runs Python 3.11–3.13 and a separate optional benchmark
job so independent comparisons are not silently skipped everywhere.

The PyPSA benchmark uses AC-labelled buses with purely resistive lines, zero
reactance, zero reactive power and verified zero phase angles. That reduces the
nonlinear equations to the resistive DC problem while using PyPSA's admittance
assembly. It compares the same three-bus meshed load case in explicit SI units,
with tight convergence tolerance. It verifies this operating point, not every
controller or contingency in the package. The pvlib test verifies adapter scaling
and DC/AC boundaries against the installed upstream library; it is not an
independent solar yield validation.

Remaining validation and higher-fidelity methods
------------------------------------------------

* Acquire permissioned DC-terminal server/GPU power traces, converter maps and
  measured CDU/pump/heat-exchanger data with configuration and uncertainty.
* Compare hydraulic/thermal transients with the
  `Modelica Buildings liquid-cooled data center models <https://simulationresearch.lbl.gov/modelica/releases/v14.0.0/help/Buildings_Applications_DataCenters_LiquidCooled.html>`_.
  This is a proposed benchmark, not an executed comparison in this release.
* Compare fluid workload completion against packet-level traces using
  `ns-3 FlowMonitor <https://www.nsnam.org/docs/models/html/flow-monitor.html>`_.
  TCP, packet loss, queuing and retransmission remain unmodeled.
* Add optional detailed DC fault/grounding, protection coordination and EMT studies;
  the `PNNL data center EMT work <https://www.osti.gov/biblio/3422378>`_ is context
  for a separate fidelity tier, not a solver currently embedded here.
* Validate spatial cooling through CFD or calibrated room models before making
  claims about rack hotspots or actual component safety margins.

None of the analytic tests or third-party comparisons establishes measured
real-world accuracy for a facility, vendor, cooling product or protection design.
