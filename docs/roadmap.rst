Development roadmap
===========================

Implemented foundation
------------------------------

* Typed equipment metadata, DC terminal power curves, ports and spatial geometry.
* Radial resistive DC networks with converters, loss accounting and constraint flags.
* Full-duplex traffic routing and explicit failed-link/node scenarios.
* Five configurable lumped cooling alternatives and a standalone thermal mass model.
* Facility-bus generation adapters, battery/grid/backup dispatch and energy KPIs.
* Reusable Plotly diagrams, dimensioned 3D equipment scene and offline report exports.

Next: calibrated equipment and electrical design
--------------------------------------------------------

1. Vendor-specific server/GPU/PSU and converter efficiency curves with source versions.
2. Circuit protection metadata, feeder thermal derating, DC fault and grounding studies.
3. A/B supplies, N+1 capacity cases and controlled failover; later a meshed DC solver.
4. Native direct-DC generation/BESS coupling and AC front-end integration.
5. Measured datasets, independent solver comparisons and reproducible calibration cases.

Next: cooling engineering and operational coupling
----------------------------------------------------------

1. CDU/heat-exchanger component networks, pump curves, pipe pressure drops and valves.
2. Weather-driven humidity/dewpoint checks, evaporative alternatives and water metrics.
3. Chiller performance maps, staged equipment, part-load control and heat recovery.
4. Room/rack transient temperatures tied to throttling, dispatch and failures.
5. CFD or EnergyPlus/FMU coupling for spatial or dynamic thermal validation.

Next: visual design workspace
-------------------------------------

1. Editable 2D/3D layouts with model serialization, rack units and collision checks.
2. glTF equipment assets and facility geometry import/export.
3. Cable/pipe routing with lengths fed back into electrical/hydraulic simulation.
4. Time animation, linked selections and operational overlays across all views.
5. Read-only telemetry adapters (Redfish, SNMP, gNMI, Modbus/BACnet) with replay tests.

These are planned extensions, not functionality delivered by version 0.1.
