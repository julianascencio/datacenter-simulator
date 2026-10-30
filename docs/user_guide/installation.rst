Installation
============

Data Center Simulator requires Python 3.11 or later. Install from the GitHub
repository to use the current simulator, examples, and documentation sources.

Create a checkout and environment
----------------------------------------

.. code-block:: bash

   git clone https://github.com/julianascencio/datacenter-simulator.git
   cd datacenter-simulator
   python -m venv .venv

Activate the environment on Linux or macOS:

.. code-block:: bash

   source .venv/bin/activate

On Windows PowerShell:

.. code-block:: powershell

   .venv\Scripts\Activate.ps1

Install the core package:

.. code-block:: bash

   python -m pip install -e .

The core installation includes NumPy, pandas, and Plotly. It supports numerical
simulation, interactive HTML reports, and SVG single-line exports. No API key
is needed for the synthetic reference facility and generation profiles.

Optional extras
---------------

From the repository checkout:

.. code-block:: bash

   python -m pip install -e '.[dev]'
   python -m pip install -e '.[docs]'

The ``dev`` extra supplies pytest, Ruff, mypy, pandas type stubs, and package
build tooling. The ``docs`` extra supplies Sphinx, PyData Sphinx Theme,
Sphinx-Gallery, and Matplotlib for the executable gallery.

For the complete contribution environment, install both:

.. code-block:: bash

   python -m pip install -e '.[dev,docs]'

Check the installation
----------------------

.. code-block:: bash

   python -c "import datacenter_simulator as dc; print(dc.__version__)"
   python -m datacenter_simulator.cli --output outputs --hours 48

Open ``outputs/reference-lab.html``. The report works offline and includes
CSV, JSON, and SVG companion exports. The 3D view requires browser WebGL;
2D diagrams and result charts remain available without it.

Continue with :doc:`../quickstart`, explore the :doc:`../gallery/index`, or
read :doc:`../contributing/index` for checks before a pull request.
