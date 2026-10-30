DC design single-line diagram
=============================

Inspect the circuit from the regulated source through the main feeder and
common busbar to each rack's feeder, DC/DC converter, 48 V bus and load.
The two network switches have their own converter branches. Every branch and
bus is taken from the solved network; the schematic is independent of floor
coordinates and does not invent circuit breakers or physical cable routes.

.. raw:: html

   <p><a class="btn btn-primary" href="../_static/lab/reference-lab.html#dc-single-line">Open the interactive DC single-line →</a></p>

.. image:: ../_static/lab/reference-lab-single-line.svg
   :alt: Model-derived DC source, main busbar, rack converters and loads
   :target: ../_static/lab/reference-lab-single-line.svg

The published snapshot uses 400 V distribution, 48 V rack converters and
70% IT utilization. Click the image for the full-resolution SVG, or
:download:`download the vector schematic <../_static/lab/reference-lab-single-line.svg>`.
The interactive lab keeps a readable drawing width; scroll its diagram panel
horizontally, pan or zoom to inspect individual circuits.

Reading the drawing
-------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Element
     - Interpretation
   * - Thick vertical line
     - Busbar or bus terminal; labels show solved voltage, nominal voltage and per-unit voltage.
   * - Blue line and arrow
     - Cable branch and source-to-load direction. R loop includes outgoing and return conductors.
   * - Amber split rectangle
     - Regulated DC/DC converter, labelled with efficiency and its power rating when supplied.
   * - Teal load box
     - Local constant-power demand at a bus, including loads on intermediate buses.
   * - I out / rated A
     - Receiving/output-terminal current and the user-supplied current rating. Hover also shows input current.
   * - kW out / ΔP
     - Receiving-terminal power and that branch's electrical loss.
   * - Red label or component
     - Current overload, power overload, or bus undervoltage. Ratings flag a violation; they do not trip.

Reproduce or customize
----------------------

.. code-block:: python

   from datacenter_simulator.use_cases import reference_center
   from datacenter_simulator.utilities.single_line import dc_single_line, write_single_line_svg

   center = reference_center(bus_voltage_v=400)  # also accepts 380 or 800 V
   result = center.electrical.solve(center.bus_loads(0.7))
   figure = dc_single_line(center.electrical, result)
   figure.write_html("dc-design.html")  # self-contained Plotly runtime
   write_single_line_svg(center.electrical, result, "dc-design.svg")

Both outputs share the same geometry and solved values. The SVG needs no
browser, Kaleido, network access or additional rendering dependency to create.
The existing ``electrical_diagram(center, result)`` plotting API now returns
this schematic. ``write_report`` and the CLI produce the SVG beside HTML,
CSV and JSON, and the report provides a download link.

Replace the reference network with your own ``DCNetwork`` for a different
layout. Result bus/branch IDs, branch endpoints and source voltage must match
that network. See :doc:`../gallery/methods/plot_dc_voltage` for the distribution
voltage comparison and :doc:`../reference/electrical` for model fields.

Scope
-----

This is an explanatory single-line for the implemented steady-state radial DC
load-flow model. It is not an IEC/ANSI drawing-compliance claim or an installation
design. Cable ampacity is supplied by the caller; the diagram does not select
cables or protective devices. Grounding, pole imbalance, fault currents,
protection coordination and automatic isolation are not modeled.

Generation, grid, backup and batteries are dispatched at the common facility
meter boundary in the current simulator. They are not additional sources on
this DC network. Rectifier efficiency is accounted for by the facility model,
outside the DC schematic. See :doc:`../methodology` for the exact boundaries.
