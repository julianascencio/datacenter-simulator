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

## 800 VDC power architecture and migration

Compare **conventional AC, 800 V sidecar, row-level DC and central SST** at the
same IT terminal. Export stage losses, annual energy-cost differences, an SST
efficiency sensitivity, DC conductor current/losses, backup power/energy minima,
and a fault-energy sensitivity with explicit capacitor backfeed and isolation.

```bash
python -m datacenter_simulator.analysis.power_architecture --output outputs/power
# Edit inputs.json and replay:
python -m datacenter_simulator.analysis.power_architecture \
  --inputs outputs/power/inputs.json --output outputs/power-replay
```

Open `outputs/power/power-architecture.html` for the offline interactive charts.
The synthetic 5 MW example retains the upstream transformer and UPS in sidecar
and row scenarios, and keeps DC backup explicit for the central SST. Savings
depend on the stated efficiencies; the sensitivity includes cases worse than AC.
Conversion totals exclude cable/cooling losses. The separate fault screen is
**not arc-flash analysis, protection coordination or certification**.

[Guide, equations and sources](docs/user_guide/power_architecture.rst) ·
[Runnable gallery example](examples/analysis/plot_800vdc_architecture.py) ·
[API](docs/reference/power_architecture.rst)

## 3D airflow and heat CFD

Solve **velocity, pressure and air temperature** through time with the native
incompressible Boussinesq solver: staggered-grid pressure projection, upwind
momentum transport, conservative heat fluxes, buoyancy and permeable rack heat /
resistance zones. Connect rack geometry from the design workflow with an explicit
room-air heat fraction.

```bash
python -m datacenter_simulator.analysis.cfd --mesh-study --output outputs/cfd
# Open outputs/cfd/cfd-3d.html
```

The offline viewer includes rotatable 3D isosurfaces, airflow vectors, time
playback, adjustable horizontal/vertical slices, pressure and speed views, rack
air-temperature probes and normal/half-airflow comparisons. Export full transient
NPZ arrays, VTK for ParaView, CSV fields, numerical budgets and editable JSON.

This is a **research CFD model**, with analytical verification and mesh sensitivity;
constant mixing coefficients and porous rack zones are uncalibrated. It is not
a measured/validated facility model or a calibrated RANS/LES solver.

[CFD guide and equations](docs/user_guide/cfd.rst) ·
[Runnable CFD example](examples/analysis/plot_cfd_heat_3d.py) ·
[CFD API](docs/reference/cfd.rst) ·
[Interactive CFD viewer](https://julianascencio.github.io/datacenter-simulator/_static/lab/cfd/cfd-3d.html)

## Facility design methods and visualization

Calculate future IT demand, rack counts and floor space, UPS/transformer/generator
and cooling capacity, N/N+1/2N contingencies, battery autonomy, service kVA/current,
air/liquid flow, annual energy PUE and grid capacity gaps. All calculations reuse
the package methods and expose validated Python inputs and editable JSON.

```bash
python -m datacenter_simulator.analysis.design --output outputs/design
# Customize the generated assumptions and calculate again:
datacenter-design --inputs outputs/design/inputs.json \
  --bins outputs/design/bins.json --output outputs/my-design
```

Open `outputs/design/design-workbench.html`: compare **15 cooling/redundancy
scenarios**, inspect power flow and capacity charts, rotate the 3D rack layout,
and download the calculation tables. Defaults are illustrative; capacity arithmetic
does not establish a reliability level or Tier certification.

[Design guide and equations](docs/user_guide/design.rst) ·
[Runnable example](examples/methods/plot_facility_design.py) ·
[API reference](docs/reference/design.rst) ·
[Interactive workbench](https://julianascencio.github.io/datacenter-simulator/_static/lab/design/design-workbench.html)

## Campus grid management and Wyoming recovery

The Wyoming case and all its methods live in this repository: generator and fuel-supply models,
mixed-integer fleet/storage dispatch, commissioning and correlated outages, ramp constraints,
critical/flexible load shedding, carbon accounting, N-1 screening, staged investment and power-cost
sensitivities. The existing battery model is reused. Gallery scripts only orchestrate and plot
installed package APIs.

```bash
python -m datacenter_simulator.analysis.wyoming --output outputs/wyoming
# Or, after installing the updated package:
datacenter-grid --output outputs/wyoming
```

Open `outputs/wyoming/wyoming-grid-management.html` for an offline interactive report. The directory
also includes editable inputs, 15 source records and hourly/monthly CSVs. All company-outcome
scenarios are illustrative: the acquisition is confirmed; operational success is not established.
The grid manager is a common-bus scheduling model, not an AC transmission or transient solver.

[Guide and equations](docs/user_guide/grid_management.rst) ·
[API reference](docs/reference/grid_management.rst) ·
[Grid example](examples/methods/plot_grid_management.py) ·
[Recovery example](examples/analysis/plot_wyoming_recovery.py)

## Synthetic data center equipment and capital study

The infographic-inspired example reproduces twelve unverified per-MW content rates,
then builds an explicitly synthetic 20 MW IT facility. It adds modular N+1 equipment
sizing, UPS power/energy checks and reusable capital accounting, reusing the existing
cooling model for power and heat balances. Cost rates and engineering unit counts are
kept separate because the image's MW basis and redundancy inclusions are unspecified.

```bash
python -m datacenter_simulator.analysis.infrastructure --it-mw 20 --output outputs/infrastructure
```

Open `outputs/infrastructure/infrastructure-study.html` for the offline report,
waterfall, power balance, 48-hour operation, sensitivities and ten CSV/JSON audit files.
The image's listed subtotal is $42.7m per assumed IT MW; this is incomplete project
scope, not a validated construction budget. All engineering ratings are assumptions.

[Runnable gallery example](examples/analysis/plot_infrastructure_content.py) ·
[Equations and scope](docs/user_guide/infrastructure.rst) ·
[API reference](docs/reference/infrastructure.rst)

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

The documentation uses Sphinx, PyData Sphinx Theme, and Sphinx-Gallery. All twenty-one gallery examples execute during the documentation build and call the installed `datacenter_simulator` API.

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
| [13. GPU Energy & Performance Lab](https://julianascencio.github.io/datacenter-simulator/gallery/gpu_lab/plot_gpu_energy_lab.html) | Trace replay, quality-specific throughput, joint scheduling/storage and forecast errors | Advanced |
| [16. Synthetic equipment-content study](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_infrastructure_content.html) | Cost boundaries, modular sizing, UPS autonomy and cooling | Advanced |
| [18. Facility design workbench](https://julianascencio.github.io/datacenter-simulator/gallery/methods/plot_facility_design.html) | IT-to-facility sizing, N/N+1/2N, annual energy and 2D/3D rack layouts | Intermediate |
| [19. 3D airflow and rack heat CFD](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_cfd_heat_3d.html) | Transient velocity/pressure/temperature, heat budgets and mesh sensitivity | Advanced |
| [20. CFD accuracy](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_cfd_accuracy.html) | Separate mesh, timestep and input sensitivity; conditional GCI | Advanced |
| [21. 3D acoustic studio](https://julianascencio.github.io/datacenter-simulator/gallery/analysis/plot_noise_3d.html) | Octave-band propagation, receiver contributions and treatments | Advanced |

Each tutorial includes explained steps, plots, assumptions, and downloadable Python and Jupyter files. Original reference data are deterministic and synthetic; the new engineering examples also include attributed SPECpower measurements and three offline PVGIS weather/resource snapshots.

## GPU Energy & Performance Lab

Read the [GPU lab guide](docs/user_guide/gpu_lab.rst) and the
[flagship runnable tutorial](examples/gpu_lab/plot_gpu_energy_lab.py).
The offline comparison uses explicitly **synthetic** performance inputs and
**simulated** facility results. No GPU hardware validation is claimed.

```bash
python -m datacenter_simulator.gpu_lab replay --output outputs/gpu-replay
python -m datacenter_simulator.gpu_lab study --output outputs/gpu-lab --sensitivity
# On a supported GPU host (read-only by default):
python -m pip install -e '.[gpu-benchmark]'
CUBLAS_WORKSPACE_CONFIG=:4096:8 python -m datacenter_simulator.gpu_lab benchmark \
  --device 0 --cuda-device 0 --repetitions 100000 --output outputs/gpu-default
```

The optional NVML connector exports timestamped CSV traces with provenance;
Zeus measures fixed-quality inference windows. Board/server boundary conversion
feeds the existing facility simulator. Four policies share identical work and
battery endpoints, with joint scheduling/storage optimization and forecast-error
stress tests. Power-limit writes require explicit opt-in and restore the captured
setting. See the guide for hardware identity checks, calibration limits and commands.

## Literature and provenance

[References and provenance](docs/references.rst) identifies the primary sources used for engineering context and numerical constants, including DOE/FEMP data center design guidance, OCP Rack & Power material, and NBS copper wire tables. It distinguishes those references from illustrative developer-selected presets.

## Roadmap and validation

The [roadmap](docs/roadmap.rst) records delivered methods and the remaining vendor calibration, DC protection/EMT, live telemetry, measured CFD validation and editable workspace extensions.

Electrical models are steady-state and resistive; workload networking uses fluid flows; cooling uses lumped balances and steady hydraulics. Numerical verification and the independent PyPSA comparison do not establish measured facility accuracy. The original facility API preserves requested demand; the new microgrid and contingency methods explicitly calculate served power. See [engineering boundaries](docs/user_guide/engineering.rst) and [evidence and validation](docs/research/engineering.rst).

## Creator and contact

Data Center Simulator is created and maintained by **ASVA Consulting**.

- Website: [asvaconsulting.com](https://asvaconsulting.com)
- Contact: [contacto@asvaconsulting.com](mailto:contacto@asvaconsulting.com)

## License

Copyright (c) 2026 **ASVA Consulting TFE SL**. The original software is
source-available under the [ASVA Noncommercial Software License 1.0](LICENSE).
**Commercial use is prohibited**, including internal business use, paid client
work, commercial products, and paid hosted services. Noncommercial use,
modification, and sharing are allowed subject to the license.

Third-party materials retain their own terms. See [licensing scope](LICENSING.md).

### Data center SCADA models

[Standards and commissioning guide](https://julianascencio.github.io/datacenter-simulator/user_guide/scada.html)
· [Searchable device dictionary](https://julianascencio.github.io/datacenter-simulator/_static/lab/scada/scada-model.html)
· [Runnable example](examples/connectors/plot_scada_model.py)

Export 50 device/space profiles with per-device JSON Schemas, points, attributes,
quality/timestamps, alarms, topology, read bindings and control-intent definitions:

```bash
python -m datacenter_simulator.analysis.scada --output outputs/scada
```

Open `outputs/scada/scada-model.html`. Redfish, BACnet, SNMP MIBs and Modbus are the
primary integration choices; OPC UA is an additional interchange and Brick a
relationship design reference. These are project-defined engineering profiles,
not native-protocol conformance claims. Importers work on offline decoded records.
Installed-device support and vendor-specific mappings require commissioning; no
universal Modbus addresses or live control are assumed.

### Acoustic studio and CFD accuracy

Run `datacenter-noise --output outputs/noise` for octave-band 3D sound levels,
receiver source rankings, source-treatment/absorption comparisons and declared
input-uncertainty intervals. Open `outputs/noise/noise-3d.html`. The Python model
uses sound-power spectra, direct propagation, atmospheric absorption and an
optional diffuse room term. Source data are illustrative; this is not a wave
solver or a complete outdoor compliance model.

The CFD now supports MUSCL heat transport, configurable return openings,
independent return-backflow temperature, distributed rack fan curves and
quadratic resistance. Run `datacenter-cfd-accuracy` for separate mesh, timestep
and input-sensitivity studies; both CFD and acoustics accept measured comparisons.
See [acoustic methods](docs/user_guide/acoustics.rst) and
[CFD verification](docs/user_guide/cfd.rst) for equations, assumptions and limits.


## Local opposition and development risk

Compare synthetic cancellation, permitting delay, mitigation and relocation economics.
Run `python -m datacenter_simulator.analysis.development --output outputs/development`
for an offline sensitivity heatmap and replayable inputs. Reported canceled planned
investment is kept separate from cash losses and site-level probability assumptions.
[Guide](docs/user_guide/development.rst) · [Gallery](examples/analysis/plot_development_risk.py)
