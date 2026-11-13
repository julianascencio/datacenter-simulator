References and provenance
=================================

The architecture follows basic energy and network balances. The following
primary references inform the terminology, topology options and engineering
context; the package does not claim to reproduce a validated model from them.

* US Department of Energy / FEMP, **Best Practices Guide for Energy-Efficient
  Data Center Design**, 2024. IT demand, airflow, cooling, electrical systems,
  liquid cooling and heat recovery.
  `Guide and publication page <https://www.energy.gov/cmei/femp/articles/best-practices-guide-energy-efficient-data-center-design>`_.
* Open Compute Project, **Rack & Power** specifications and Open Rack V3
  contribution catalog. Context for 48 V rack distribution and evolving
  higher-voltage power architectures. No OCP compliance is asserted.
  `OCP Rack & Power <https://www.opencompute.org/projects/rack-and-power/>`_.
* US National Bureau of Standards, **Copper Wire Tables**, Circular 31, third
  edition. Copper resistivity and temperature coefficient; rounded constants
  are used by the cable convenience constructor.
  `NIST archival publication <https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e3.pdf>`_.
* Plotly, **Interactive HTML export**. Self-contained interactive figures and
  browser visualization.
  `Official documentation <https://plotly.com/python/interactive-html-export/>`_.

The additional methods, actual data snapshots and optional solver comparisons
are documented in :doc:`research/engineering`.

Preset provenance
-------------------------

All rack ratings, efficiencies, cooling COPs, capture fractions, auxiliary
coefficients, capacities, geometry and hourly profiles in the reference use case
are **illustrative developer-selected assumptions**. They are neither measured
records nor specifications extracted from these references. Replace them with
traceable manufacturer or measurement data before evaluating a real facility.

Created by `ASVA Consulting <https://asvaconsulting.com>`_.
Contact: contacto@asvaconsulting.com.

GPU measurement and inference
-----------------------------

The :ref:`gpu-primary-sources` section records the reviewed official NVML API,
NVIDIA Python bindings, Zeus v0.16.0 and UCI/scikit-learn dataset provenance.
GPU gallery traces and performance curves are synthetic fixtures; hardware
measurements and facility calibration remain pending.

Synthetic infrastructure content
--------------------------------

The :doc:`equipment-content study <user_guide/infrastructure>` transcribes twelve
unverified image rates supplied by the user. The linked post was inaccessible;
no market-price verification or vendor-performance calibration is asserted.
The packaged evidence JSON records the source limitations, assumed denominator,
unpriced scope and primary DOE/FEMP/Eaton engineering context.


Development risk context
------------------------

Robinson Meyer, Heatmap, October 6, 2026: "Exclusive: Data Center Cancellations
Top $260 Billion in 2026". User-supplied excerpt; underlying proprietary records
not independently verified. Aggregate claims are context only, not probability
calibration. See :doc:`user_guide/development` for provenance and boundaries.
