Data center SCADA data model
============================

The package supplies **50 device/space profiles**, a versioned canonical data
contract, per-device JSON Schemas, a point dictionary, commissioning crosswalk,
and offline importers for five interfaces. It extends the equipment scope of
:doc:`infrastructure` with detailed operational data. The infographic is not a
technical authority for this model.

.. raw:: html

   <p><a class="btn btn-primary" href="../_static/lab/scada/scada-model.html">Browse all device models and download schemas →</a></p>

Run the complete export::

   python -m datacenter_simulator.analysis.scada --output outputs/scada

Open ``outputs/scada/scada-model.html`` locally. No server or credentials are
needed. Follow :doc:`../gallery/connectors/plot_scada_model` for the executable
walkthrough and :doc:`../reference/scada` for the APIs.

Which standards to use
----------------------

The practical primary choices are **Redfish, BACnet, SNMP MIBs and Modbus**.
Selection is based on official specifications and first-party implementation
support, not a quantitative popularity ranking. Dell and HPE document Redfish
support; Vertiv documents SNMP, Modbus TCP/IP and BACnet/IP in its DCIM offering.
OPC UA is an additional SCADA integration layer, and Brick informs relationships.

.. list-table::
   :header-rows: 1
   :widths: 18 35 47

   * - Standard / interface
     - Best fit in this model
     - What still needs commissioning
   * - Redfish (DMTF DSP0268 2026.1)
     - Servers, processors/GPUs, memory, storage, network and supported power/cooling resources
     - Resource links, versions, sensor context and OEM extensions. The importer reads a subset of Sensor resources.
   * - BACnet
     - Building automation, chillers, air handlers, pumps, valves and sensors
     - Device/object instances, PICS, point meaning, units and native enums. Objects are not universal equipment templates.
   * - SNMP: RFC 1628 / RFC 3433
     - UPS scalar/line telemetry and physical sensors; candidate interface for PDUs and networks
     - Supported MIBs, table indexes, vendor enterprise MIBs and security. Network-specific MIB importers are not implemented here.
   * - Modbus V1.1b3
     - Electrical meters, generator/PLC and cooling controllers
     - The entire vendor register map, zero-based offsets, signedness, word/byte order, scale and sentinels. Modbus has no universal device model.
   * - OPC UA DataValue
     - Typed SCADA interchange with quality and timestamps
     - Server namespace URI, node identity and engineering-unit metadata. No universal data-center NodeSet is asserted.
   * - Brick
     - Separate containment, location, feeds and points
     - Semantic design reference only; no RDF/SHACL export or Brick conformance is claimed.

This is an **ASVA engineering superset**, not a certified native schema for any
of these standards. A candidate protocol or Redfish resource association does
not mean an installed product implements it. Every crosswalk row is marked
``requires_commissioning``. Only supported points belong in an installed asset.
Exact UPS scalar OIDs are distinguished from table templates, property templates
and completely unknown vendor mappings. No standard Modbus register addresses,
BACnet instances or OPC UA NodeIds are invented.

Complete device scope
---------------------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Domain
     - Profiles
   * - Spaces (3)
     - Site, building, data hall/room
   * - IT (10)
     - Rack, server, CPU, GPU/accelerator, memory module, storage system, drive, network switch, network port, power supply
   * - Electrical (17)
     - Grid connection, transformer, switchgear, busbar, floor PDU, rack PDU, power meter, outlet, circuit breaker, protection relay, ATS, STS, UPS, battery bank, battery module, generator, PV inverter
   * - Cooling (14)
     - Chiller, heat exchanger, CDU, cooling tower, dry cooler, CRAC, CRAH, in-row cooler, rear-door heat exchanger, immersion tank, pump/VFD, fan/VFD, valve, cooling loop
   * - Auxiliary (2)
     - Water tank, fuel tank
   * - Monitoring (2)
     - Environmental sensor, leak detector
   * - Safety (2)
     - Fire/suppression panel, access controller

Fields are device-specific. Electrical profiles include phase/line voltages,
currents, power, energy, harmonics and protection status. UPS adds battery,
autonomy, source/bypass and explicitly indexed output-line readings. Cooling
profiles include supply/return temperatures, pressure, flow, heat duty and
applicable compressor/fan/pump controls. IT profiles include power, utilization,
clocks, temperatures, capacity, errors and throttling where appropriate.

Shared groups are optional supersets: wet-basin points do not apply to a purely
dry cooler, and water-side points do not apply to every CRAC variant. Device
support, sensor placement and measurement boundaries determine what is populated.
Repeated components are separate assets: each fan, PSU, battery module, network
port or sensor can have its own identity and containment link. The single selected
UPS line importer is not a multi-line aggregate; use separately commissioned
line assets/mappings when retaining all lines simultaneously.

Data contracts
--------------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Record
     - Contents
   * - Device profile
     - Field keys, meanings, types, canonical units, valid bounds/enums, role, suggested polling/staleness and control interlocks
   * - Installed asset
     - Version, stable ID, profile, parent, manufacturer/model/serial/firmware, location, nameplates, supported points, observations and namespaced extensions
   * - Observation
     - Value, unit, quality, source timestamp, collector timestamp, protocol, source address, raw status/value and quality reason
   * - Endpoint
     - Protocol, address, security profile and optional external credential reference; no embedded secrets
   * - Read binding
     - Asset/point/endpoint, concrete protocol locator, native unit, scale/offset, source document and evidence class
   * - Relationship
     - Source, target and electrical feed, cooling supply, network link, monitoring or control relation
   * - Alarm event
     - Asset/point, condition, severity, active/cleared state, raised/cleared/acknowledged times and actor
   * - Control intent
     - Target point/value/unit, request/expiry times, required interlocks and design-only state

All per-device schemas reject unknown fields, incompatible canonical units,
invalid enum values and invalid types. Python validation also rejects non-finite
numbers. Plant validation checks unique assets, declared capabilities, dangling
references and containment cycles. Topology links can form meshes; containment
cannot. Dynamic cross-record and alarm lifecycle checks use the Python validators
in addition to JSON Schema.

Unsupported points and unknown metadata are omitted. A missing observation uses
``null`` plus ``quality="missing"``; zero is a real measured value. Bad samples can
retain an interpretable value, but it is not usable as good telemetry. Health and
alarm severity describe equipment condition, not sample validity.

A synthetic UPS voltage observation is::

   {
     "value": 540.0,
     "unit": "V",
     "quality": "good",
     "source_timestamp": null,
     "received_at": "2026-01-01T12:00:00Z",
     "source_protocol": "snmp",
     "source_address": "1.3.6.1.2.1.33.1.2.5.0",
     "raw_status": "poll_result",
     "raw_value": 5400,
     "quality_reason": "Source reported a usable value."
   }

The RFC 1628 value is in tenths of volts. Collection time is not device source
time. RFC 3433 sysUpTime ticks are retained as metadata, not labelled UTC;
negative precision describes accuracy and does not multiply the value. Overflow
and underflow sentinel readings become bad/null. OPC UA source and server times
are both preserved. BACnet alarm flags alone do not invalidate a reading;
faults and overrides affect quality.

Freshness uses source time when available, otherwise receive time. It cannot
prove the age of a device's internal cache. Counter deltas require good data,
consistent sources/units, increasing timestamps and no reset/wrap. Site thresholds,
scan rates, deadbands, aggregation windows and sensor calibration require explicit
engineering decisions. Generic bounds are data plausibility constraints, not
alarm thresholds or equipment operating limits.

Commissioning workflow
----------------------

1. Create equipment with stable IDs, containment and separate physical connections.
2. Populate verified identity, nameplates and location. Choose each meter's
   boundary, phase, sign convention and pressure reference.
3. Discover actual interfaces and capabilities. Record protocol versions,
   PICS/MIB/register-map references and native unit/enum meanings.
4. Declare supported points. Add concrete read bindings and endpoint metadata;
   validate them against the installed inventory.
5. Decode source records, normalize units, preserve timestamps/status and validate
   before updating snapshots. Reject out-of-order observations.
6. Configure site-specific timing, alarms, historian policy and reset handling.
   Reconcile parent/child meters before deriving facility totals or PUE.

The current importers accept decoded records. They do not connect, authenticate,
poll, subscribe, operate a historian, expose an OPC UA server or control hardware.
Bindings describe deployment metadata; they are not an executable polling engine.
Controls are separate design-only records, with no execution path. A real
controller must implement authorization, limits, priority, permissives and
readback. Safety panel models are monitoring-only.

Reproducible artifacts and validation
-------------------------------------

The export writes the full profile dictionary, ``points.csv``, ``attributes.csv``,
``commissioning_crosswalk.csv``, 50 device schemas, endpoint/binding/event schemas,
a 51-asset synthetic inventory and raw/normalized examples for five interfaces.
It also bridges an existing simulator server with an explicit DC-terminal power
boundary; no AC meter reading is inferred.

Tests verify schema validity, all profile inventories, unit conversions, quality,
SNMP precision/sentinels, four Modbus endian combinations, timestamp handling,
counter resets, topology, event lifecycle and commissioning requirements. These
are synthetic contract tests, not field-device interoperability certification.

Primary evidence
----------------

The complete versioned source ledger is in
``datacenter_simulator/data/scada_standards.json`` and in the downloadable
catalogue. Main sources:

* `DMTF Redfish DSP0268 2026.1 <https://redfish.dmtf.org/schemas/DSP0268_2026.1.html>`_
  and `Sensor 1.11.0 <https://redfish.dmtf.org/schemas/v1/Sensor.v1_11_0.json>`_.
* `BACnet committee FAQ <https://bacnet.org/faq/>`_ and
  `OPC BACnet analog object model <https://reference.opcfoundation.org/specs/OPC-30030/7.4>`_.
* `IETF UPS-MIB, RFC 1628 <https://www.rfc-editor.org/rfc/rfc1628>`_ and
  `ENTITY-SENSOR-MIB, RFC 3433 <https://www.rfc-editor.org/rfc/rfc3433>`_.
* `Modbus specification V1.1b3 <https://www.modbus.org/file/secure/modbusprotocolspecification.pdf>`_.
* `OPC UA DataValue <https://reference.opcfoundation.org/specs/OPC-10000-4/7.11>`_
  and `Brick relationships <https://docs.brickschema.org/brick/relationships.html>`_.
* `Dell Redfish support <https://www.dell.com/support/kbdoc/en-us/000178045/redfish-api-with-dell-integrated-remote-access-controller>`_,
  `HPE server management <https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted>`_
  and `Vertiv supported protocols <https://www.vertiv.com/en-us/support/faqs/environet-alert/>`_.
