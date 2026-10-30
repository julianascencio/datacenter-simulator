Frequently asked questions
==================================

Are the example inputs measured?
----------------------------------------

No. The six examples use explicitly labelled synthetic inputs and illustrative
equipment parameters. CSV/Series adapters accept measured or simulated generation,
but a data adapter does not validate the source model or measurements.

Does adding PV reduce PUE?
----------------------------------

No. PUE uses gross facility demand before generation and storage. PV can reduce
grid imports without changing the demand-side PUE.

Does the 3D hall simulate airflow?
------------------------------------------

No. It visualizes device positions and dimensions. Cooling is a lumped energy
model; support routing and server faces are illustrative. CFD and detailed
hydraulics are on the :doc:`../roadmap`.

Can the examples run without Internet access?
-----------------------------------------------------

Yes, once the Python dependencies are installed. No gallery example downloads
live data. The generated lab embeds Plotly and works offline in a WebGL-capable
browser. Standard documentation math rendering may use an external MathJax CDN.

Why is a shortage still followed by IT demand?
------------------------------------------------------

The simulator reports unmet requested demand and flags infeasibility. It does
not automatically shed computing load, throttle devices or infer served traffic.
See :doc:`../methodology` before interpreting failure scenarios.
