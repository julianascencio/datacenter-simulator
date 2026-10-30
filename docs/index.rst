Data Center Simulator
=============================

.. raw:: html

   <div class="asva-brand">
     <a href="https://asvaconsulting.com">
       <img src="_static/asva-consulting.jpg" alt="ASVA Consulting">
     </a>
     <p><strong>Created by ASVA Consulting</strong><br>
       <a href="https://asvaconsulting.com">asvaconsulting.com</a><br>
       <a href="mailto:contacto@asvaconsulting.com">contacto@asvaconsulting.com</a>
     </p>
   </div>

**Data Center Simulator** is a Python research platform for device-based
electrical, communication, cooling and energy-supply studies, created by
**ASVA Consulting**.

Build a facility from equipment models, connect its DC power and communication
networks, compare cooling alternatives, and balance demand against generation,
batteries and the grid. Interactive 2D and 3D views use the same equipment models.

Start here
------------------

* Read the :doc:`user_guide/package_overview`.
* Follow the :doc:`quickstart` to install and run the offline simulation lab.
* Explore six worked examples in the :doc:`gallery/index`, from device basics
  to a complete facility study.
* Inspect the :doc:`user_guide/dc_single_line` with electrical ratings and SVG export.
* Use the :doc:`reference/index` for classes, functions and source code.

.. raw:: html

   <p><a class="btn btn-primary" href="_static/lab/reference-lab.html">Open the interactive 2D / 3D simulation lab →</a></p>

Core modelling idea
---------------------------

Device utilization determines IT terminal demand. The DC network adds
distribution losses. The heat balance determines cooling electricity, and
the facility demand then feeds generation, battery and grid dispatch.

.. list-table::
   :header-rows: 1
   :widths: 25 45 30

   * - Layer
     - Model inputs
     - Main outputs
   * - Devices
     - Power curves, ports, dimensions, placement
     - IT demand and geometry
   * - Networks
     - Buses, cables, converters, links, traffic
     - Voltages, losses, loading, routes
   * - Cooling
     - Heat, capacity, ambient temperature, cooling technology
     - Cooling demand and rejected heat
   * - Supply
     - Generation, battery, grid and backup limits
     - Imports, storage state, curtailment, unserved energy

AI-assisted development
-------------------------------

A substantial portion of the code, documentation, examples and tests was
generated or drafted with AI assistance. The repository developers select
the specific literature, technical references and assumptions used to guide
implementation; see :doc:`references` for provenance.

AI-generated content may contain errors or imperfect interpretations.
Testing and validation are developing and are not yet comprehensive across
all models. Reference equipment and profiles are illustrative, and numerical
checks do not establish measured accuracy. Important assumptions should be
traced to sources and results independently checked when greater confidence
is required. See :doc:`methodology` for the implemented model boundaries.

Documentation structure
-------------------------------

The documentation follows the same PyData Sphinx layout as
`OrbitalPV <https://julianascencio.github.io/orbital-pv/>`_: a User Guide,
executable Example Gallery, generated API Reference, Research and Contributing.

.. toctree::
   :maxdepth: 2
   :hidden:

   user_guide/index
   gallery/index
   reference/index
   research/index
   contributing/index
