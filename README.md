# Data Center Simulator

<p align="center">
  <a href="https://asvaconsulting.com">
    <img
      src="docs/_static/asva-consulting.jpg"
      alt="ASVA Consulting"
      width="280"
    />
  </a>
</p>

<p align="center">
  <strong>Created by ASVA Consulting</strong><br>
  <a href="https://asvaconsulting.com">asvaconsulting.com</a><br>
  <a href="mailto:contacto@asvaconsulting.com">contacto@asvaconsulting.com</a>
</p>

Created by **ASVA Consulting**, Data Center Simulator is a Python research platform for **device-based data center simulation**: DC electrical distribution, communication networks, HVAC alternatives, generation and storage, reproducible studies, and interactive 2D/3D visualization.

The structure follows a modular separation of concerns. Equipment models, numerical methods, external data connectors, reference use cases, and plotting utilities are separate parts of the same Python package.

## AI-assisted development and literature basis

A substantial part of the code, documentation, examples, tests, and repository scaffolding is generated or drafted with AI assistance.

Repository developers select the specific literature, technical reports, datasets, and engineering references that guide the assumptions, methods, examples, and research roadmap. AI supports implementation, documentation, synthesis, testing, and iteration around that selected evidence base.

In practice:

- model assumptions and numerical baselines should be traceable to cited sources or explicitly documented engineering assumptions;
- illustrative rack ratings, efficiencies, cooling coefficients, geometry, and profiles are identified as assumptions, not measured or manufacturer-calibrated inputs;
- AI-generated code and explanations may contain errors or imperfect interpretations of the selected literature;
- review, numerical tests, and validation are developing and are not yet comprehensive across all models and examples;
- research and engineering results should be checked against the underlying sources and independent validation evidence when greater confidence is required.

The curated evidence and preset provenance are maintained in [references and provenance](docs/references.rst). Equations, exclusions, and validation boundaries are documented in [model boundaries](docs/methodology.rst).

## Install from GitHub

Use Python 3.11 or later:

```bash
git clone https://github.com/julianascencio/datacenter-simulator.git
cd datacenter-simulator
python -m pip install -e .
```

Use the public API as:

```python
from datacenter_simulator import simulate
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.use_cases import reference_center, reference_profiles
from datacenter_simulator.utilities.report import write_report

center = reference_center(cooling="direct_to_chip", bus_voltage_v=400)
profiles, generation = reference_profiles(hours=48)
result = simulate(center, profiles, generation=generation, battery=Battery(500, 150, 150))
print(result.summary)
write_report(center, result, "outputs/my-center.html")
```

Optional extras, from the checkout:

```bash
python -m pip install -e '.[dev]'
python -m pip install -e '.[docs]'
python -m pip install -e '.[solar,benchmarks]'  # pvlib and independent PyPSA checks
```

See the [installation guide](https://julianascencio.github.io/datacenter-simulator/user_guide/installation.html) for an isolated environment and development setup.

## Foundation stack

- **NumPy + pandas + SciPy** — numerical arrays, timezone-aware profiles, nonlinear solvers and MILP optimization.
- **Python model and method modules** — device power curves, radial DC load flow, communication routing, cooling balances, and battery/grid dispatch.
- **Plotly** — interactive equipment scenes, electrical and communication diagrams, and self-contained HTML reports.
- **SVG export** — scalable DC single-line drawings generated from the solved network without a browser or additional rendering dependency.
- **Matplotlib** — reproducible gallery figures.
- **Sphinx + PyData Sphinx Theme + Sphinx-Gallery** — conceptual guides, API documentation, and executable examples.
- **pytest + Ruff + mypy** — numerical checks, formatting, linting, and type checking.

## Repository map

| Location | Responsibility |
|---|---|
| [`src/datacenter_simulator/`](src/datacenter_simulator/) | Public API and coupled facility simulation |
| [`models/`](src/datacenter_simulator/models/) | Equipment, electrical and communication metadata, and physical placement |
| [`methods/`](src/datacenter_simulator/methods/) | DC load flow, network routing, HVAC, thermal dynamics, and energy dispatch |
| [`connectors/`](src/datacenter_simulator/connectors/) | External generation inputs, units, and timestamp alignment |
| [`utilities/`](src/datacenter_simulator/utilities/) | Single-line diagrams, 2D/3D views, plotting, and report exports |
| [`use_cases/`](src/datacenter_simulator/use_cases/) | Reference facility and deterministic profiles |
| [`examples/`](examples/) | Methods, connectors, and integrated analyses for the gallery |
| [`docs/`](docs/) | User guides, API reference, literature, and roadmap |
| [`tests/`](tests/) | Model checks and desktop/mobile browser validation |

`datacenter_simulator` exposes `DataCenter`, `SimulationResult`, and `simulate`. The model, method, connector, and utility modules provide the component APIs used to construct custom facilities.

## Documentation

**[julianascencio.github.io/datacenter-simulator](https://julianascencio.github.io/datacenter-simulator/)**

[User Guide](https://julianascencio.github.io/datacenter-simulator/user_guide/index.html) · [Example Gallery](https://julianascencio.github.io/datacenter-simulator/gallery/index.html) · [API Reference](https://julianascencio.github.io/datacenter-simulator/reference/index.html) · [Research](https://julianascencio.github.io/datacenter-simulator/research/index.html) · [Contributing](https://julianascencio.github.io/datacenter-simulator/contributing/index.html)

The documentation uses Sphinx, PyData Sphinx Theme, and Sphinx-Gallery. All twelve gallery examples execute during the documentation build and call the installed `datacenter_simulator` API.

Build locally:

```bash
python -m pip install -e '.[docs]'
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Open `docs/_build/html/index.html`. GitHub Actions builds documentation previews for pull requests and publishes the site from `main` through GitHub Pages.

## DC electrical design and visualization

The initial focus is **direct-current distribution**: configurable 380/400/800 V study cases, regulated 48 V rack supplies, cable losses, voltage drop, and current/power-rating checks.

The model-derived single-line shows busbars, feeders, DC/DC converters, local loads, voltages, current and power ratings, and branch losses. Overload and undervoltage are highlighted; hover distinguishes converter input and output current. The same solved circuit exports to SVG.

```python
from datacenter_simulator.use_cases import reference_center
from datacenter_simulator.utilities.single_line import dc_single_line, write_single_line_svg

center = reference_center(bus_voltage_v=400)
electrical = center.electrical.solve(center.bus_loads(0.7))
dc_single_line(center.electrical, electrical).write_html("dc-design.html")
write_single_line_svg(center.electrical, electrical, "dc-design.svg")
```

See the [single-line guide](https://julianascencio.github.io/datacenter-simulator/user_guide/dc_single_line.html) and [380/400/800 V gallery example](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_dc_voltage.html).

## Engineering methods in 0.2

Eight additions extend the original facility model: evidence-backed device/converter maps; electrothermal feeder sizing; CDU hydraulics; meshed multi-source DC flow; A/B and N+1 contingencies; weather, water and heat recovery; optimized storage and carbon-aware job scheduling; and workload/network/thermal coupling.

[Engineering guide](docs/user_guide/engineering.rst) · [Research and validation](docs/research/engineering.rst) · [Linked engineering lab](https://julianascencio.github.io/datacenter-simulator/_static/lab/engineering-lab.html)

```bash
python -m datacenter_simulator.analysis.engineering --output outputs/engineering
```

Open `outputs/engineering/engineering-lab.html` to select equipment across 2D/3D, electrical, cooling and communication views and replay an A/B feed failure. The export also contains a solved DC single-line, CSV results and a study manifest. Physical cable/pipe routes feed the electrical and hydraulic calculations. All figures and examples run offline; PVGIS source snapshots are bundled with provenance.

## Development

```bash
python -m pip install -e '.[dev,docs]'
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

CI checks Python 3.11–3.13, builds the package, executes the gallery, and validates the documentation and interactive lab on desktop and mobile. See [Contributing](docs/contributing/index.rst).

## Science pipeline

| Stage | Inputs and results |
|---|---|
| Equipment demand | Device utilization and power curves determine terminal demand. |
| DC distribution | Buses, cables, and converters determine voltage, current, losses, and loading. |
| Cooling | IT demand and conditioned distribution losses determine heat; ambient conditions and the selected HVAC model determine cooling electricity. |
| Facility demand | DC source demand, rectifier efficiency, cooling, and auxiliaries determine gross facility demand and PUE. |
| Supply dispatch | Generation, battery, grid, and backup limits determine storage state, imports, export/curtailment, and unserved energy. |
| Communication study | Port metadata, links, and offered traffic separately determine routes, link loading, and failure outcomes. |

Generation connects at the **common facility meter boundary**. Use net electrical output from PV, wind, biogas, or another generation model through the [Series/CSV integration API](docs/integration.rst). In this original workflow, communication throughput does not automatically change IT workload. The advanced workload model produces per-device power profiles for explicit coupling through `simulate(..., device_power_kw=...)`.

## Interactive simulation lab

[Open the 2D/3D lab](https://julianascencio.github.io/datacenter-simulator/_static/lab/reference-lab.html) · [Open the DC single-line](https://julianascencio.github.io/datacenter-simulator/_static/lab/reference-lab.html#dc-single-line)

Generate a local report:

```bash
python -m datacenter_simulator.cli --output outputs --hours 48
```

Open `outputs/reference-lab.html`. It includes the Plotly runtime and works offline. CSV, JSON, and `reference-lab-single-line.svg` are generated alongside it. Views cover the equipment hall, floor plan, DC and communication networks, thermal balance, generation/storage, and HVAC comparisons.

## Example gallery

| Example | Subject | Complexity |
|---|---|---|
| [01. Device models and spatial layouts](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_device_models.html) | Power curves, ports, and dimensioned 2D/3D placement | Beginner |
| [02. Connect generation from Series and CSV](https://julianascencio.github.io/datacenter-simulator/gallery/connectors/plot_generation_adapter.html) | Units, timestamps, conversion losses, and grid imports | Beginner |
| [03. Compare 380, 400 and 800 V distribution](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_dc_voltage.html) | Feeder current, losses, rack voltage, and single-line export | Intermediate |
| [04. Communication routing, failure and saturation](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_network_failure.html) | Redundant links, latency, and overloaded paths | Intermediate |
| [05. HVAC alternatives and cooling failure](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_cooling_failure.html) | Five cooling options and a thermal transient | Intermediate |
| [06. Complete facility energy and resilience study](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_facility_comparison.html) | HVAC, generation, batteries, grid, and islanded operation | Advanced |
| [07. Calibrated device curves and DC feeder design](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_dc_design.html) | Measured curve provenance, electrothermal sizing, uncertainty | Intermediate |
| [08. A/B feeds, N+1 and powered cooling](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_ab_resilience.html) | Transfer delay, hold-up, shared failures and thermal transients | Advanced |
| [09. Balance a CDU and four cooling branches](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_cdu_design.html) | Pump curves, pressure losses, finite-UA exchange and blockage | Intermediate |
| [10. Compare climates, water and heat recovery](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_climate_cooling.html) | Three PVGIS TMY climates, dry/wet/hybrid rejection and water | Advanced |
| [11. Direct-DC solar, storage and optimized dispatch](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_dc_microgrid.html) | DC/AC PV conversion, islanding, MILP and rolling forecasts | Advanced |
| [12. Couple workloads, networks and cooling](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_workload_network.html) | ECMP fairness, job deadlines, thermal caps and carbon timing | Advanced |

Each tutorial includes explained steps, plots, assumptions, and downloadable Python and Jupyter files. Original reference data are deterministic and synthetic; the new engineering examples also include attributed SPECpower measurements and three offline PVGIS weather/resource snapshots.

## Literature and provenance

[References and provenance](docs/references.rst) identifies the primary sources used for engineering context and numerical constants, including DOE/FEMP data center design guidance, OCP Rack & Power material, and NBS copper wire tables. It distinguishes those references from illustrative developer-selected presets.

## Roadmap and validation

The [roadmap](docs/roadmap.rst) records delivered methods and the remaining vendor calibration, DC protection/EMT, live telemetry, CFD and editable workspace extensions.

Electrical models are steady-state and resistive; workload networking uses fluid flows; cooling uses lumped balances and steady hydraulics. Numerical verification and the independent PyPSA comparison do not establish measured facility accuracy. The original facility API preserves requested demand; the new microgrid and contingency methods explicitly calculate served power. See [engineering boundaries](docs/user_guide/engineering.rst) and [evidence and validation](docs/research/engineering.rst).

## Creator and contact

Data Center Simulator is created and maintained by **ASVA Consulting**.

- Website: [asvaconsulting.com](https://asvaconsulting.com)
- Contact: [contacto@asvaconsulting.com](mailto:contacto@asvaconsulting.com)
