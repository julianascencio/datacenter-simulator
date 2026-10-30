Contributing
============

Data Center Simulator welcomes reproducible improvements to models,
connectors, analyses, examples, tests, and documentation.

Development setup
-----------------

.. code-block:: bash

   git clone https://github.com/julianascencio/datacenter-simulator.git
   cd datacenter-simulator
   python -m pip install -e '.[dev,docs]'

See :doc:`../user_guide/installation` for an isolated Python environment.

Before opening a pull request
-----------------------------

.. code-block:: bash

   python -m ruff check .
   python -m ruff format --check .
   python -m mypy src
   python -m pytest
   python -m sphinx -W --keep-going -b html docs docs/_build/html

AI-assisted contribution policy
-------------------------------

A substantial share of repository content is generated or drafted with AI
assistance, including code, documentation, tests, examples, and research
synthesis. AI assistance does not replace scientific provenance.

Contributors should:

* select and cite the specific literature, datasets, standards, or technical
  references that motivate a method or parameter choice;
* distinguish published or measured values from engineering assumptions and
  illustrative defaults;
* review generated implementations for physical validity, numerical
  correctness, units, edge cases, and reproducibility;
* add tests and validation evidence appropriate to the claimed fidelity;
* update :doc:`../references` when new evidence influences the implementation.

The workflow starts with developer-selected evidence, followed by AI-assisted
implementation, human review, testing, and progressive validation. Generated
content may contain errors or imperfect source interpretations. Validation is
still developing; passing numerical tests does not establish measured accuracy.

Scientific contributions
------------------------

Model and analysis changes should state their physical or statistical
assumptions, units, time conventions, input provenance, numerical methods,
validation evidence, and known limitations. Use deterministic seeds for
stochastic experiments and check relevant physical balances and failure cases.

Documentation
-------------

User-facing functionality should have conceptual documentation and API
docstrings. Keep examples deterministic and offline, identify their difficulty
and assumptions, explain each modelling step, and include figures that help
interpret the results. The documentation build executes the six gallery
examples and builds the interactive lab.

Documentation hosting
-----------------------------

The documentation workflow builds every pull request and uploads a browsable
documentation artifact. On ``main`` it deploys to GitHub Pages if Pages is
enabled with **GitHub Actions** as the source. A missing or legacy Pages setup
does not prevent the build; the workflow summary explains the required setting.

To enable publication, a repository administrator selects **Settings → Pages →
Build and deployment → Source → GitHub Actions**, then runs the documentation
workflow on ``main`` (or merges the next documentation update).

The published gallery path is ``/datacenter-simulator/gallery/index.html``.
Keep repository documentation focused on public technical material; do not
include credentials or private employer/client data.
