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

AI-assisted development
-----------------------

A substantial portion of the code, documentation, examples, tests, and
repository scaffolding is generated or drafted with AI assistance.

The scientific basis is curated by the repository developers. They select
the literature, technical reports, datasets, and engineering references used
to define assumptions, parameters, methods, examples, and the research roadmap.
AI supports implementation, documentation, testing, and synthesis around that
selected evidence base; see :doc:`references` for sources and preset provenance.

AI-generated content may contain errors or imperfect interpretations of the
selected sources. Review and validation are developing and are not yet
comprehensive across all models and examples. Reference equipment and profiles
are illustrative. Users should trace important assumptions to the cited
literature and independently verify results when higher confidence is needed.
See :doc:`methodology` for the implemented boundaries and validation evidence.

Start here
------------------

If you are new to Data Center Simulator:

* Read the :doc:`user_guide/package_overview`.
* Follow :doc:`user_guide/installation` to install the package and optional tools.
* Run the :doc:`quickstart` to generate an offline simulation lab.
* Explore twelve worked examples in the :doc:`gallery/index`, from device basics
  to coupled electrical, cooling, energy and workload studies.
* Follow :doc:`user_guide/engineering` for the eight advanced methods and linked lab.
* Inspect the :doc:`user_guide/dc_single_line` with electrical ratings and SVG export.
* Use the :doc:`reference/index` for classes, functions and source code.

.. raw:: html

   <p><a class="btn btn-primary" href="_static/lab/reference-lab.html">Open the interactive 2D / 3D simulation lab →</a>
   <a class="btn btn-secondary" href="_static/lab/engineering-lab.html">Open linked engineering lab →</a></p>

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

Documentation structure
-------------------------------

The documentation is split into a User Guide, an executable Example Gallery,
and a generated API Reference. Research records the references and roadmap;
Contributing explains the development and evidence requirements.

.. toctree::
   :maxdepth: 2
   :hidden:

   user_guide/index
   gallery/index
   reference/index
   research/index
   contributing/index
