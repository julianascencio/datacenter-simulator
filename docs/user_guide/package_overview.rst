Package overview
========================

Data Center Simulator separates equipment descriptions, numerical methods,
external data adapters and visualizations. A single device model carries its
electrical demand, communication-port information and physical placement.

.. list-table::
   :header-rows: 1
   :widths: 30 45 25

   * - Package
     - Responsibility
     - Start with
   * - ``models``
     - Equipment and validated metadata
     - :class:`~datacenter_simulator.models.devices.Device`
   * - ``methods.electrical``
     - Radial resistive DC load flow
     - :class:`~datacenter_simulator.methods.electrical.DCNetwork`
   * - ``methods.communications``
     - Traffic routing and directional link loading
     - :class:`~datacenter_simulator.methods.communications.CommunicationNetwork`
   * - ``methods.cooling``
     - Lumped HVAC and thermal mass
     - :class:`~datacenter_simulator.methods.cooling.CoolingPlant`
   * - ``methods.energy``
     - Battery/grid/backup dispatch
     - :func:`~datacenter_simulator.methods.energy.dispatch`
   * - ``connectors``
     - Generation units and timestamp alignment
     - :doc:`../integration`
   * - ``simulation``
     - Facility demand, heat and supply coupling
     - :func:`~datacenter_simulator.simulation.simulate`
   * - ``utilities``
     - Plotly diagrams, 3D equipment and offline reports
     - :doc:`../reference/visualization`

Choose a learning path
------------------------------

**Beginner:** start with :doc:`../gallery/methods/plot_device_models`, then
:doc:`../gallery/connectors/plot_generation_adapter`.

**Intermediate:** work through the DC voltage, communication failure and HVAC
examples in :doc:`../gallery/methods/index`.

**Advanced:** combine the layers in
:doc:`../gallery/analysis/plot_facility_comparison` and compare demand, storage,
cooling and supply-shortfall results.

All six gallery examples run offline and use synthetic, deterministic inputs.
They call the installed package's public functions rather than duplicating the
simulation algorithms in the example scripts.
