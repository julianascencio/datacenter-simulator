Contributing
====================

Contributions should improve reproducibility, model clarity and evidence for
the claimed fidelity. Start with the :doc:`../quickstart` development setup.

Checks before opening a pull request
--------------------------------------------

.. code-block:: bash

   python -m ruff check .
   python -m ruff format --check .
   python -m mypy src
   python -m pytest
   python -m sphinx -W --keep-going -b html docs docs/_build/html

The documentation build executes all six gallery examples. Keep them
deterministic and offline, identify their difficulty and assumptions, explain
each modelling step, and include figures that help interpret the results.

Scientific and AI-assisted contributions
------------------------------------------------

AI assistance is part of this project's development workflow. It does not
replace scientific provenance or validation. For each model change:

* cite the specific literature, dataset or technical reference selected by
  the developers;
* distinguish measured values and published specifications from assumptions;
* document units, boundaries, numerical methods and known limitations;
* check physical balances and relevant failure cases;
* add validation evidence appropriate to the claimed model fidelity;
* record deterministic seeds for any stochastic example.

Validation is still developing. AI-generated code or prose may contain errors,
and passing numerical tests does not independently establish real-world accuracy.

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
