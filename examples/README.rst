Example Gallery
===============

Twelve executable tutorials cover different subjects and levels of complexity.
They use the installed ``datacenter_simulator`` API, run offline and produce
figures during every documentation build. The original inputs and equipment parameters are illustrative; advanced
examples also include attributed measured SPECpower points and PVGIS TMY
weather snapshots. Each tutorial declares its boundary and assumptions.

Choose an example
-----------------

.. list-table::
   :header-rows: 1
   :widths: 8 35 17 40

   * - No.
     - Tutorial
     - Level
     - Learn to
   * - 01
     - :doc:`methods/plot_device_models`
     - Beginner
     - Define device power/port metadata and view 2D/3D placement.
   * - 02
     - :doc:`connectors/plot_generation_adapter`
     - Beginner
     - Connect Series/CSV generation with explicit units and timestamps.
   * - 03
     - :doc:`methods/plot_dc_voltage`
     - Intermediate
     - Compare distribution voltages, losses and rack input voltages.
   * - 04
     - :doc:`methods/plot_network_failure`
     - Intermediate
     - Trace routes, reroute failures and identify saturated links.
   * - 05
     - :doc:`methods/plot_cooling_failure`
     - Intermediate
     - Compare five cooling options and study a cooling-loss transient.
   * - 06
     - :doc:`analysis/plot_facility_comparison`
     - Advanced
     - Combine HVAC, generation, battery, grid and resilience studies.

   * - 07
     - :doc:`methods/plot_dc_design`
     - Intermediate
     - Measured curve provenance, electrothermal sizing, uncertainty.
   * - 08
     - :doc:`analysis/plot_ab_resilience`
     - Advanced
     - Transfer delay, hold-up, shared failures and thermal transients.
   * - 09
     - :doc:`methods/plot_cdu_design`
     - Intermediate
     - Pump curves, pressure losses, finite-UA exchange and blockage.
   * - 10
     - :doc:`analysis/plot_climate_cooling`
     - Advanced
     - Three PVGIS TMY climates, dry/wet/hybrid rejection and water.
   * - 11
     - :doc:`analysis/plot_dc_microgrid`
     - Advanced
     - DC/AC PV conversion, islanding, MILP and rolling forecasts.
   * - 12
     - :doc:`analysis/plot_workload_network`
     - Advanced
     - ECMP fairness, job deadlines, thermal caps and carbon timing.

Each tutorial includes a runnable Python download and a Jupyter notebook.
For interactive equipment and network diagrams, open the simulation lab
linked from the documentation homepage.
