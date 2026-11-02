GPU Energy & Performance Lab
============================

How much useful AI work can a facility deliver within its electrical and thermal
constraints, at what energy use and electricity cost? This lab connects optional
GPU observations to the existing workload, electrical, cooling and storage APIs.
The :doc:`../gallery/gpu_lab/plot_gpu_energy_lab` is executable without a GPU or
network. The :doc:`../reference/gpu_lab` documents the reusable interfaces.

Evidence status and scope
-------------------------

**First-release evidence:** offline numerical tests, fake-device integration
checks, a deterministic CPU quality reference, and synthetic/simulated gallery
runs. **No GPU hardware experiments or wall-meter calibration were performed.**
No public hardware trace is bundled or presented as a measured result.

The built-in performance curve is deliberately synthetic. Do not use its power,
throughput, energy or savings values to select hardware. Real benchmark output is
labelled ``measured``; a normalized Zeus window is labelled ``imported`` because
this connector imports the result from Zeus. Facility outputs remain ``simulated``
even when driven by measured inputs. Mixed provenance is recorded in the manifest.

This release supports one exclusive physical NVIDIA GPU in one server, independent
batch jobs, fixed model/input/precision, and AC-coupled PV/storage at the facility
bus. Distributed training, MIG energy attribution, online serving, live facility
control, CFD and inference-engine tuning are outside scope. No NVIDIA endorsement
or performance certification is implied.

Existing implementation reused
------------------------------

* ``Provenance`` accompanies the bounded GPU performance observations. The existing
  ``PowerCurve`` remains the utilization-to-terminal-power API; GPU throughput
  versus a configured power limit is a different measured relationship.
* ``Job`` and ``JobPhase`` keep compute-seconds semantics. ``inference_job`` converts
  input-record counts to seconds at the default observation. Other settings use
  the ratio of measured throughputs, not a guessed linear power/speed relation.
* ``simulate(..., device_power_kw=...)`` evaluates the existing DC network,
  rectifier, cooling plant and auxiliaries at declared device terminal power.
* ``optimize_dispatch`` now optionally selects mutually exclusive ``DemandOption``
  job alternatives in its existing MILP, alongside battery decisions. Existing
  callers and defaults are preserved. Exact terminal SOC is an opt-in constraint.
* ``workload_power_profile`` and GPU replay share ``resample_intervals``. The
  existing Plotly ``write_report`` exports the per-policy facility reports.

Offline commands
----------------

.. code-block:: bash

   python -m pip install -e '.[dev,docs]'
   python -m datacenter_simulator.gpu_lab replay --output outputs/gpu-replay
   python -m datacenter_simulator.gpu_lab study --output outputs/gpu-lab --sensitivity
   python examples/gpu_lab/plot_gpu_energy_lab.py
   python -m sphinx -W --keep-going -b html docs docs/_build/html

Replay writes a CSV, mandatory metadata sidecar, resampled profile and energy
summary. Study writes comparison/job CSVs, self-contained interactive facility
reports, a provenance manifest and optional sensitivity CSV. No optional GPU
library is imported by the core simulator, replay, gallery or documentation build.

Live read-only collection
-------------------------

.. code-block:: bash

   python -m pip install -e '.[gpu]'
   python -m datacenter_simulator.gpu_lab collect --device 0 \
     --duration 60 --interval 0.2 --output outputs/gpu/idle.csv
   python -m datacenter_simulator.gpu_lab replay --trace outputs/gpu/idle.csv \
     --step 1 --max-gap 2 --output outputs/idle-replay

``--device`` is a **physical NVML index**, unaffected by CUDA-visible ordering;
a full GPU UUID can be supplied instead. Initializing NVML or finding a device
must succeed. Missing optional APIs, unsupported fields and permission errors are
preserved in per-field status columns, with blank measurements. GPU/driver loss
is retained as an error status, never silently converted to zero power. A trace
with missing energy and power endpoints cannot enter facility replay.

The current official NVIDIA reference describes power usage in mW and energy
counters in mJ since driver reload; this connector converts to W and J. Availability
varies by GPU and virtualization mode. The documented power getter averages over
one second on Ampere except GA100 and on newer architectures; other supported
architectures may expose instantaneous readings. Faster polling therefore does
not imply equally fast electrical measurement. No millisecond transient fidelity
is claimed. See :ref:`gpu-primary-sources`.

Trace schema v1
---------------

One CSV row is a **point sample**, not an interval average. The mandatory sibling
``<stem>.metadata.json`` provides ``schema_version``, ``kind``, ``boundary``,
``source``, ``configuration`` and ``software_versions``. Native collection also
records GPU model/UUID, driver/NVML versions, VBIOS, MIG and persistence state,
plus the status of each identity query. Unsupported values are JSON null or CSV
blanks, never zero. Persist the CSV and sidecar together.

.. list-table::
   :header-rows: 1
   :widths: 33 15 52

   * - Field
     - Unit
     - Meaning
   * - timestamp
     - UTC ISO 8601
     - Wall-clock anchor plus monotonic elapsed time; sample start
   * - elapsed_s
     - s
     - Monotonic time, normalized to zero at the first retained sample
   * - power_w
     - W
     - GPU and associated board circuitry; architecture-specific averaging
   * - energy_j
     - J
     - Cumulative counter; use differences, never absolute total as window energy
   * - temperature_c
     - °C
     - GPU sensor; distinct from simulated room/rack temperature
   * - gpu_utilization_pct
     - %
     - NVML sampled GPU utilization, not useful throughput
   * - memory_utilization_pct
     - %
     - NVML memory activity, not percentage of allocated memory capacity
   * - graphics_clock_mhz, memory_clock_mhz
     - MHz
     - Reported clock domains
   * - power_limit_w
     - W
     - Configured board limit, not observed consumption
   * - <metric>_status
     - text
     - ok, missing_api, or exception class and reason
   * - query_duration_s
     - s
     - Sequential multi-field query overhead; samples are not atomic

Elapsed times must strictly increase, and timestamp differences must agree within
0.1 seconds. Adjacent counter differences take precedence over trapezoidal power
integration. Negative counter differences are rejected as resets. A caller-supplied
maximum gap prevents arbitrary interpolation through telemetry outages. Missing
power without a complete counter interval stays missing and replay fails.

``resample_intervals`` integrates overlap between contiguous input intervals and
regular output bins. W becomes kW before integration; kW × seconds / 3600 gives
kWh. Source time zero may be aligned to any explicitly supplied timezone-aware
facility start. The last bin is padded with zero only **after** the trace ends;
its complete duration must remain in subsequent accounting. Do not treat that
padding as measured idle demand. CSV is the supported first-release export;
Parquet and remote streaming are not required to replay the schema.

Fixed-quality hardware workload
-------------------------------

The initial benchmark is a small, open **digits classifier**: scikit-learn's
bundled 1,797 8×8 images from UCI optical digits, normalized by 16, with a fixed
stratified 75/25 split (seed 1729). A logistic classifier is fitted on CPU and its
weights transferred to a PyTorch FP32 linear inference operation. The 450 held-out
records are repeated in fixed order. This is a useful instrumentation baseline,
but an intentionally small, launch/synchronization-sensitive workload. It does not
represent LLMs or fully loaded data-center GPUs and may show little power-cap
sensitivity. Repeated records count as completed inference tasks, not distinct
new observations or training examples.

CPU fitting, host-to-device copies and quality validation are outside the measured
window. Inputs stay on GPU. Warm-up runs before three independent windows. Every
batch synchronizes before latency recording. Latencies include dispatch and
synchronization and exclude service queueing. The final short batch is retained,
and raw batch sizes/latencies allow separate inspection. Windows must last at least
10 seconds before they can be fitted to a performance curve; increase repetitions
on faster hardware. This threshold is a guardrail, not an accuracy guarantee.

The quality gate requires at least 90% CPU held-out accuracy, matching class
predictions and FP32 logits within declared tolerances. Dataset, split, weights,
reference predictions, hardware UUID, driver, dependency versions and experiment
configuration are hashed/recorded. Model construction rejects mismatched identities,
missing or zero energy and failed quality gates. Different batch sizes, models,
precision or input shapes cannot be pooled as equivalent observations.

Zeus ``ZeusMonitor`` measures each synchronized window with ``begin_window`` and
``end_window``; its ``Measurement.time`` is seconds and ``gpu_energy`` values are
joules. GPU indices follow CUDA-visible ordering. The benchmark verifies the CUDA
UUID matches the physical NVML UUID and rejects active MIG. Native NVML polling
runs alongside Zeus to capture power/temperature/configuration. Its polling span
brackets the Zeus window; the two energy estimates are never added together.
CPU/RAPL fields are not summed into total server power.

.. code-block:: bash

   python -m pip install -e '.[gpu-benchmark]'
   # Set deterministic cuBLAS configuration before Python starts.
   CUBLAS_WORKSPACE_CONFIG=:4096:8 python -m datacenter_simulator.gpu_lab benchmark \
     --device 0 --cuda-device 0 --batch-size 128 --warmup 100 \
     --repetitions 100000 --windows 3 --output outputs/gpu-default

``benchmark.json`` records window completion, throughput, energy/task, quality,
batch p50/p95/p99 and environment. ``batch-latencies.csv`` records every batch.
Each ``window-N-telemetry.csv`` has its own metadata sidecar. Check for other GPU
processes, record ambient/cooling conditions, and repeat after reaching thermal
stability. Board telemetry covers all concurrent GPU activity, not just this
process. The collector does not enforce exclusivity or guarantee a stable clock.

Optional power-limit experiment
-------------------------------

Normal collection and the command above never write GPU settings. Supplying a
limit requires ``--allow-power-control``; unsupported or unauthorized writes fail.
The connector checks the device's reported range, captures the original setting,
verifies the write and restores the original setting in ``finally``, including
workload exceptions and normal Python interrupts. A restoration failure raises an
error. Unhandled process termination, driver loss or power loss cannot guarantee
restoration. No clocks, fan settings or persistence flags are changed.

.. code-block:: bash

   # Example target only: 150 W must be within this device's reported range.
   CUBLAS_WORKSPACE_CONFIG=:4096:8 python -m datacenter_simulator.gpu_lab benchmark \
     --device 0 --cuda-device 0 --batch-size 128 --warmup 100 \
     --repetitions 100000 --windows 3 --power-limit 150 --allow-power-control \
     --output outputs/gpu-150w

Build a bounded curve only after collecting the default and additional settings
on the same configuration. Idle power needs separate evidence or an explicit
assumption. Here 35 W is merely a placeholder assumption, not a GPU measurement:

.. code-block:: bash

   python -m datacenter_simulator.gpu_lab build-model \
     outputs/gpu-default/benchmark.json outputs/gpu-150w/benchmark.json \
     --idle-board-w 35 --idle-source 'DECLARED ASSUMPTION: replace with idle trace evidence' \
     --output outputs/measured-performance.json
   python -m datacenter_simulator.gpu_lab study \
     --performance-model outputs/measured-performance.json --output outputs/measured-input-study

This substitutes the performance curve into the illustrative facility; it does
not calibrate that facility. A single point supports only that exact limit.
Interpolation stays within observed limits and one configuration/quality ID;
extrapolation raises an error. The CPU-generated fit can vary with dependencies;
hashes ensure such runs are not silently combined. Archive ``pip freeze``, source
commit and all output files with each experiment.

Accounting and thermal boundary
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 27 73

   * - Measurement
     - Conversion into simulated server DC-terminal demand
   * - GPU board
     - Add separately measured/assumed CPU, memory, fan and other component demand;
       divide by declared internal DC efficiency once.
   * - Whole-server DC
     - Use directly. Adding GPU or other server loads again raises an error.
   * - Whole-server AC
     - Require explicit original AC PSU efficiency to reconstruct internal DC.
       The simulated DC architecture then replaces that conversion. This is a
       counterfactual assumption, not direct reproduction of the original AC server.

The DC network includes its converters/cables; the central rectifier is upstream.
Cooling electricity appears once at the AC facility bus. All terminal IT demand
becomes heat, and the declared conditioned fraction of DC losses enters the room.
Rectifier and facility auxiliaries remain outside the conditioned room, consistent
with the existing simulator. Battery efficiencies include the declared AC-coupled
storage conversion; PV is already at the same AC bus.

The GPU lab rejects candidate operation exceeding room cooling capacity or
producing electrical warnings. Existing ``simulate_workloads`` still provides
lumped rack-zone thermal throttling for its utilization-based jobs; its law is
**not** substituted for a calibrated GPU silicon throttling curve. Live temperature
is captured for evidence. GPU temperature-dependent extrapolation, transient
hotspots, warm-up transitions and long-run frequency drift remain unmodelled.

Long horizons use stationary mean board power and useful throughput while each
job runs, followed by measured/assumed idle. They do not stretch a 10-second trace
into an alleged day of measurements. Measure longer steady-state windows and
validate thermal representativeness before using this assumption operationally.
The tutorial includes ±20% throughput sensitivity with requested work held fixed.

Policy definition, fairness and optimization
--------------------------------------------

1. **Immediate/default:** FIFO execution at the observed default setting.
2. **Immediate/efficient:** FIFO at the lowest observed board J/task setting.
3. **Price-aware/fixed power:** choose feasible job starts using prices with the
   same efficient setting; PV and battery arbitrage are absent from this scheduling
   decision. Then dispatch storage against the fixed schedule and actual PV.
4. **Coordinated:** one MILP jointly chooses execution alternatives (including
   observed power settings), job starts and storage dispatch against PV and prices.

All four use the same battery optimizer, battery limits, grid cap, idle baseline,
fixed work/quality, initial SOC and **equal terminal SOC**. Policies 1–3 are
sequential scheduling followed by storage optimization, not joint optimization.
This deliberately gives the baselines the same storage capabilities. The fourth
re-solves storage after selecting its joint schedule to produce the common report;
its original scheduling decision already included battery coupling.

The same storage-throughput penalty (0.01 currency units/kWh) enters all objectives;
reported ``energy_cost`` is only grid electricity cost. The synthetic example
interprets its prices as EUR/kWh. There is no export revenue or demand charge in
this example. All optimization uses perfect foresight of its supplied profiles.

The MILP chooses one option per job with release/deadline and resource-occupancy
constraints. Starts use a 30-minute grid; fractional final slots are reserved until
the next slot. Active and idle electrical/cooling endpoints are solved separately,
then time-weighted: nonlinear electrical losses are not evaluated solely at the
slot-average IT load. There is no explicit switching overhead. A cooling or grid
failure invalidates the full affected job; checkpointing is not assumed. Unfinished
jobs, late jobs, planning failure and unserved energy are reported. Facility
J/task becomes missing if not all requested work completes; lower cost from failed
work must never be interpreted as an efficiency improvement.

Sensitivity reoptimizes after tariff/PV/throughput changes. The separate forecast
stress replay freezes job starts **and battery commands**, halves realized PV and
shifts realized prices by two hours. Grid imports adjust within the same cap;
shortfalls invalidate affected jobs, and the identical terminal battery state is
preserved. It is an open-loop stress test, not rolling control or a claim about
real forecasting performance.

.. _gpu-primary-sources:

Primary sources and version record
----------------------------------

Reviewed on **2 November 2026**:

* NVIDIA, `NVML Device Queries <https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html>`_
  and `change log <https://docs.nvidia.com/deploy/nvml-api/latest/change-log.html>`_.
  The connector uses the established ``nvmlDeviceGetPowerUsage``,
  ``nvmlDeviceGetTotalEnergyConsumption``, temperature/utilization/clock getters,
  power-limit constraints and ``nvmlDeviceSetPowerManagementLimit`` interfaces.
  Newer versioned APIs exist; this release does not assume their availability.
  The online ``latest`` reference is mutable: runtime driver/NVML versions are
  recorded for every collection rather than claiming a universal driver revision.
* NVIDIA-maintained `nvidia-ml-py bindings <https://pypi.org/project/nvidia-ml-py/>`_
  (import name ``pynvml``). Extra requires >=12.560; exact installed version is
  recorded. Compatibility still depends on the actual driver/device capabilities.
  Offline binding inspection used nvidia-ml-py 13.615.71 (NVML itself was unavailable).
* Zeus, `measurement API <https://ml.energy/zeus/reference/monitor/energy/>`_,
  `measurement guide <https://ml.energy/zeus/measure/>`_ and
  `v0.16.0 release <https://github.com/ml-energy/zeus/releases/tag/zeus-v0.16.0>`_.
  Integration targets >=0.16,<0.17. Library energy measurement is reused rather
  than implementing another workload-window measurement engine.
* scikit-learn, `load_digits <https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html>`_.
  The package supplies a 1,797-sample subset of the UCI dataset; no download occurs
  during a run. This lab's held-out split is not the original UCI train/test benchmark.
* PyTorch, `CUDA device tests <https://github.com/pytorch/pytorch/blob/main/test/test_cuda.py>`_.
  CUDA device properties expose a bare UUID object; physical NVML IDs include a
  ``GPU-`` prefix. The identity check normalizes both formats and rejects MIG IDs.
* Alpaydin and Kaynak, `Optical Recognition of Handwritten Digits <https://doi.org/10.24432/C50P49>`_,
  UCI Machine Learning Repository (1998), CC BY 4.0 as stated on the dataset page.
  Inputs are consumed from the installed scikit-learn package, not redistributed here.

This work retains ASVA Consulting attribution and the repository's
:doc:`../contributing/index` AI-assisted-development disclosure. Numerical tests
and synthetic fixtures do not establish hardware measurement accuracy.

Implementation validation record
--------------------------------

Local validation on 2 November 2026 used Python 3.12.14, NumPy 2.5.4,
SciPy 1.18.1, pandas 3.1.0, scikit-learn 1.9.1, Sphinx 9.1.1 and
sphinx-gallery 0.22.1. NVML Python bindings 13.615.71 and Zeus 0.16.0 were inspected;
PyTorch and the NVIDIA driver library were unavailable. The real collector
reported ``NVML Shared Library Not Found``. No GPU measurement was attempted
successfully, and the full-run benchmark integration test uses explicit mocks.

* Ruff lint/format and mypy pass.
* 128 pytest tests pass, including independent pvlib/PyPSA comparisons. Three
  upstream dependency deprecation warnings remain; there are no test failures.
* The strict Sphinx build passes. All 13 gallery examples executed with Python
  socket connections disabled; six figures and both Python/notebook downloads
  were checked for the new tutorial.
* CPU reference accuracy is 0.971111 on 450 held-out records; repeated preparation
  produced identical input, weight and prediction hashes. This verifies the
  CPU workload, not GPU throughput or electrical accuracy.
* Wheel and source distributions build successfully. Replay and study commands
  produce reports without GPU hardware or model/data downloads.
* Local Playwright checks were attempted but Chromium could not open sockets in
  this execution environment. Desktop/mobile browser checks remain in repository
  CI and must be reviewed there. Static HTML/image checks are not browser tests.

Pending hardware evidence: synchronized Zeus/NVML runs at supported default and
reduced limits; independent wall-meter/server telemetry; thermal-stability and
sampling-bias studies; validation on larger GPU-representative models. The small
digits workload may be CPU/launch limited. These limitations should accompany
any reuse of the first-release results.
