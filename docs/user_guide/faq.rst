Frequently asked questions
==================================

Are the example inputs measured?
----------------------------------------

Most equipment parameters and workload profiles are illustrative. Example 07
uses published SPECpower measurements; examples 10–11 use bundled PVGIS TMY
resources. Their source and measurement boundaries are explicit. CSV/Series
adapters also accept measured or simulated generation,
but a data adapter does not validate the source model or measurements.

Does adding PV reduce PUE?
----------------------------------

No. PUE uses gross facility demand before generation and storage. PV can reduce
grid imports without changing the demand-side PUE.

Does the 3D hall simulate airflow?
------------------------------------------

No. It visualizes device positions and dimensions. Cooling is a lumped energy
model; support routing and server faces are illustrative. The advanced model
solves steady CDU branch hydraulics; spatial airflow/CFD remains on the
:doc:`../roadmap`.

Can the examples run without Internet access?
-----------------------------------------------------

Yes, once the Python dependencies are installed. No gallery example downloads
live data. The generated lab embeds Plotly and works offline in a WebGL-capable
browser. Standard documentation math rendering may use an external MathJax CDN.

Why is a shortage still followed by IT demand?
------------------------------------------------------

The original ``simulate`` workflow reports unmet requested demand and flags
infeasibility while preserving requested load. The separate microgrid, workload
and contingency APIs calculate shedding, throttling or served power within their
declared boundaries; see :doc:`engineering`.
See :doc:`../methodology` before interpreting failure scenarios.

What changed in version 0.2?
-----------------------------

Six new examples cover the :doc:`engineering` methods. Bundled measured SPECpower
points and PVGIS weather resources have explicit provenance; they do not validate
a complete facility. The :doc:`../research/engineering` page separates analytical
checks, independent comparisons and remaining measured-validation work.
