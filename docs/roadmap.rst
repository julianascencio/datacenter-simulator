Development roadmap
===================

Implemented foundation
----------------------

* Typed devices, DC-terminal demand, communication ports and physical placement.
* Radial DC networks with regulated converters and model-derived single-line/SVG.
* Offered-flow routing, five lumped cooling alternatives and a thermal zone model.
* Facility-meter generation adapters, greedy storage/grid/backup energy balances.
* Offline Plotly reports, OrbitalPV-style Sphinx guides and executable gallery.

Implemented engineering studies in 0.2
--------------------------------------

* Attributed power curves, bounded converter maps, held-out calibration errors,
  read-only Redfish payload parsing and seeded assumption sensitivity.
* Route-derived electrothermal feeder sizing with explicit installation ratings.
* Meshed resistive DC load flow with power/voltage/droop ports and constrained
  direct-DC PV/battery/grid coupling, islanding and terminal-load shedding.
* A/B transfer timing, hold-up, N+1 capacity, common causes and powered cooling.
* CDU parallel branches, pump curves, finite-UA exchange and partial blockage.
* Three real PVGIS TMY resource snapshots; humidity, dry/wet/hybrid rejection,
  water accounting, bounded chiller maps and useful heat recovery.
* Cost/carbon/reserve MILP storage dispatch, forecast-error replay and
  deadline-constrained carbon-aware flexible job scheduling.
* Fluid ECMP/max-min bandwidth allocation, compute/transfer phases, FIFO/EDF,
  power/thermal throttling and exact interval integration into facility demand.
* Six additional tutorials (twelve total), linked selections/time overlays across
  2D/3D and schema views, shared routing geometry and independent PyPSA comparison.

See :doc:`user_guide/engineering` for the supported boundaries and
:doc:`research/engineering` for the evidence and validation map.

Next: calibration and optional fidelity
---------------------------------------

1. Permissioned device/GPU/PSU and CDU datasets, held-out whole-facility telemetry,
   sensitivity with correlated inputs and measured uncertainty estimates.
2. DC faults, grounding, protection/arc models and converter EMT as a separate
   optional fidelity tier, including explicit bipolar midpoint behavior.
3. Modelica/EnergyPlus/FMU and CFD comparisons for transient/spatial cooling;
   packet-level ns-3 comparisons for communications. These are not yet executed.
4. Joint nonlinear electrical/thermal economic optimization, equipment sizing,
   degradation models, stochastic forecasts and calendar billing periods.

Next: editable workspace and operational data
---------------------------------------------

1. Persistent interactive layout editing, rack units, collision checks and automatic
   routing. Current routes are authored in Python and reused by the solvers.
2. Optional glTF/BIM/CAD assets and geometry import/export.
3. Authenticated read-only telemetry collection and replay for Redfish, SNMP,
   gNMI, Modbus/BACnet, with explicit schemas and measured time alignment.
4. Calibrated fault likelihoods and common-cause models before probabilistic
   availability metrics. Current resilience scenarios are deterministic.
