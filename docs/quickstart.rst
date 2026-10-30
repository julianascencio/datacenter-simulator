Quick start
===================

Install from a checkout (Python 3.11+):

.. code-block:: bash

   python -m pip install -e '.[dev,docs]'
   python -m datacenter_simulator.cli --output outputs --hours 48

Open ``outputs/reference-lab.html`` in a browser. It contains its Plotly runtime
and works offline. CSV, JSON and a scalable ``reference-lab-single-line.svg`` sit beside it. The 3D view needs WebGL;
the 2D diagrams and charts remain available on devices without it.

Python API
------------------

.. code-block:: python

   from datacenter_simulator import simulate
   from datacenter_simulator.methods.energy import Battery
   from datacenter_simulator.use_cases import reference_center, reference_profiles
   from datacenter_simulator.utilities.report import write_report

   center = reference_center(cooling="direct_to_chip", bus_voltage_v=400)
   profiles, generation = reference_profiles(hours=48)
   result = simulate(center, profiles, generation=generation,
                     battery=Battery(500, 150, 150))
   print(result.summary)
   write_report(center, result, "outputs/my-center.html")

Every component is replaceable: construct ``Device``, ``DCBus``, ``DCBranch`` and
``Link`` objects to build a custom system. Device types are descriptive strings;
all present IT devices use the same configurable utilization-to-power curve.
Communications metadata include port count, rate, protocols and management address.
Protocol names describe equipment; they do not open live management connections.

Reproduce checks and documentation
------------------------------------------

.. code-block:: bash

   python -m ruff check .
   python -m ruff format --check .
   python -m mypy src
   python -m pytest
   python -m sphinx -W --keep-going -b html docs docs/_build/html

Examples are organized into methods, connectors and integrated analyses.
CI uploads the generated documentation and interactive lab as an Actions artifact.
