# Data Center Simulator

A composable Python simulator for **devices → electrical and communication networks → cooling → generation and storage**. Created by [ASVA Consulting](https://asvaconsulting.com), contacto@asvaconsulting.com.

The initial focus is **direct-current electrical distribution**: configurable 380/400/800 V study cases, regulated 48 V rack supplies, cable losses, voltage drop and overload checks. It also provides interactive 2D/3D representations and an offline simulation dashboard.

## Run the interactive lab

```bash
git clone https://github.com/julianascencio/datacenter-simulator.git
cd datacenter-simulator
python -m pip install -e '.[dev,docs]'
python -m datacenter_simulator.cli --output outputs --hours 48
```

Open **`outputs/reference-lab.html`**. No web server or external chart CDN is needed. CSV and JSON results are generated alongside it.

## Included

| Layer | Implemented |
|---|---|
| Devices | Configurable idle/peak power curves, DC input voltage, communication ports/protocol metadata, physical dimensions and placement |
| DC electricity | Radial constant-power load flow, copper cable resistance, converters, voltage/ampacity/power-rating flags |
| Communications | Full-duplex graphs, traffic routing, directional saturation, latency lower bounds, failed-link/node scenarios |
| HVAC | DX/CRAC, chilled water/CRAH, rear-door heat exchanger, direct-to-chip/CDU, single-phase immersion; heat rejection and fluid flows |
| Energy supply | Timestamp-validated Series/CSV adapters for generation, BESS state/efficiencies, grid limits, ideal backup, export/curtailment and unserved demand |
| Visualization | Dimensioned floor plan, orbitable 3D equipment hall, DC single-line, communication topology, thermal Sankey, time plots and HVAC comparison |
| Examples | Methods, connectors and integrated analyses in a Sphinx Gallery; a reproducible eight-rack, 48-hour reference experiment |

```python
from datacenter_simulator import simulate
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.use_cases import reference_center, reference_profiles
from datacenter_simulator.utilities.report import write_report

center = reference_center(cooling="direct_to_chip", bus_voltage_v=400)
profiles, generation = reference_profiles()
result = simulate(center, profiles, generation=generation, battery=Battery(500, 150, 150))
print(result.summary)
write_report(center, result, "outputs/my-center.html")
```

Generation is connected at the **common facility bus**, with explicit unit/efficiency conversion. Use net electrical output from a PV, wind, biogas or other generation model. See [integration](docs/integration.rst) for using Series or CSV outputs from other simulators without assuming their APIs.

## Structure

* `src/datacenter_simulator/models/`: device, electrical, communication and spatial metadata.
* `src/datacenter_simulator/methods/`: DC load flow, network routing, HVAC, thermal mass and energy dispatch.
* `src/datacenter_simulator/connectors/`: external generation profile adapters.
* `src/datacenter_simulator/utilities/`: reusable diagrams, 3D views and report exports.
* `src/datacenter_simulator/use_cases/`: reference system and deterministic synthetic profiles.
* `examples/{methods,connectors,analysis}/`: runnable examples and gallery sources.
* `docs/`: equations, assumptions, API, provenance and development roadmap.

## Model maturity

This is an initial research and design-study implementation. Reference equipment and profiles are **illustrative**, not measured or vendor-calibrated. The electrical solver is steady-state and radial; communications are flow-based; cooling is lumped rather than CFD. The 3D scene uses actual device placement and dimensions, with illustrative server faces, cable routes and cooling-plant placement.

Unserved power and cooling shortfalls are reported explicitly, without automatically shedding IT load. PUE uses gross facility demand before generation/storage, so adding PV does not artificially improve PUE. Direct DC-coupled multi-source dispatch, A/B electrical failover, protection studies, live telemetry, CFD and an editable CAD-like workspace remain on the [roadmap](docs/roadmap.rst).

Much of this initial code was AI-generated from the project requirements, physical balances and [specific primary references](docs/references.rst). It may contain errors, and real-world validation is not yet extensive. See [model boundaries and validation](docs/methodology.rst) before interpreting results.

## Documentation and six-example gallery

The documentation mirrors [OrbitalPV](https://julianascencio.github.io/orbital-pv/): the PyData Sphinx theme, blue palette, ASVA branding, and User Guide / Example Gallery / API Reference / Research / Contributing navigation. It includes the developer-selected literature and AI-assistance/validation notes.

| Example | Subject | Complexity |
|---|---|---|
| 01. Device models and spatial layouts | Power curves, ports, dimensioned 2D/3D placement | Beginner |
| 02. Connect generation from Series and CSV | Units, timestamps, conversion losses, grid imports | Beginner |
| 03. Compare 380, 400 and 800 V distribution | Feeder current, losses, rack voltage | Intermediate |
| 04. Communication routing, failure and saturation | Redundant links, latency and overloaded paths | Intermediate |
| 05. HVAC alternatives and cooling failure | Five cooling options and a thermal transient | Intermediate |
| 06. Complete facility energy and resilience study | HVAC, generation, batteries, grid and islanded operation | Advanced |

All six tutorials execute during the documentation build, include plotted results, and offer Python/Jupyter downloads. The gallery is generated at `gallery/index.html`.

The documentation workflow validates PRs and uploads a preview artifact. On `main`, it publishes through GitHub Actions when repository Pages is configured with **GitHub Actions** as its source. See [hosting setup](docs/contributing/index.rst); the workflow reports the setting required if hosting is not enabled.

## Development and documentation

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` for the documentation, example gallery and interactive lab. GitHub Actions checks Python 3.11–3.13 and builds the package. A separate documentation workflow executes the six examples, validates desktop/mobile pages and uploads the documentation/lab artifact. No hosted deployment is required for local use.
