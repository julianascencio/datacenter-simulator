Unified facility telemetry
==========================

The operational telemetry layer connects BMS cooling and environmental signals,
EPMS electrical observations and DCIM asset context. It extends the existing
:doc:`scada` model and its 50 profiles. Inventory, ownership, topology and control
authority remain in their source systems. This implementation runs offline.

.. code-block:: bash

   python -m datacenter_simulator.analysis.telemetry --output outputs/telemetry

Open ``outputs/telemetry/telemetry.html``. The report contains three synthetic
incidents and a nine-case investment sensitivity. The executable
:doc:`../gallery/analysis/plot_unified_telemetry` explains the modelling steps.

`Open the bundled interactive report <../_static/lab/telemetry/telemetry.html>`_.

Source scope and implementation coverage
---------------------------------------

The supplied InfluxData PDF, *Unified Telemetry Strategy for Data Centers*, has
**four pages only**. Its table of contents lists sections through page 16, but
pages 5–16 were not supplied. They are not treated as reviewed source material.
The package records the original filename, SHA-256, available pages and exact
claim scope in ``data/telemetry_evidence.json``; it does not redistribute the PDF.

.. list-table:: Source-to-implementation map
   :header-rows: 1
   :widths: 30 40 30

   * - Available source content
     - Implementation
     - Evidence boundary
   * - Page 3: shared historical telemetry beside existing systems
     - Append-only canonical history, replay and cross-system timelines
     - Project-designed contracts; no throughput claim
   * - Page 4: BMS cooling and environmental observations
     - Pump/CDU channels and a thermal failure scenario
     - Existing physical models; synthetic parameters
   * - Page 4: EPMS electrical context
     - Utility, UPS, rack power and facility observations
     - Ideal UPS protection assumed in sag case
   * - Page 4: DCIM inventory, rack and ownership context
     - Time-valid context joins and snapshot dependency traversal
     - Exposure is not proven customer service loss
   * - Page 3: operator and equipment/software supplier audiences
     - Configurable labor, downtime, energy and implementation economics
     - All financial inputs are assumptions
   * - Contents-only later sections
     - Independent sampling, retention and deployment guidance below
     - Not reconstructed or attributed to missing pages

Supplementary first-party InfluxData documentation informs line-protocol
serialization and buffer planning. It does not calibrate the physical models or
validate savings. Consult :doc:`../references` for the source links.

Data and device contracts
-------------------------

``TelemetryRecord`` links one canonical SCADA observation to a site, asset,
device profile, point, source system and collector/source ID. Observation units,
quality, raw value/status, source address, protocol and both timestamps survive
JSONL replay. Timestamps require an offset and normalize to UTC with microsecond
resolution. Source time is preferred; receive-only time is explicitly labelled.
Higher-resolution timestamps are rejected rather than silently truncated.

``AssetContext`` defines a half-open validity interval, profile, owner, rack and
source reference. ``ContextHistory`` rejects overlapping versions. Historical
observations are joined to the context valid at their event time; gaps remain
unknown. The incident fixture stores topology with an explicit snapshot time.
It does not infer past topology from current relationships or implement a
bitemporal inventory database.

``CollectorChannel`` models a device's sampling period, transport delay and
source clock offset. Missing samples remain null with quality metadata. This is
a synthetic observation model, not a live BACnet/Modbus/SNMP/Redfish client or a
calibrated sensor transfer function. Existing SCADA connectors normalize actual
collected records before wrapping them in ``TelemetryRecord``.

The example contains a data hall, utility connection, UPS, rack PDU, pump, CDU,
rack and server. The PDU provides topology context without inventing a measured
point. Exported JSON Schemas cover all 50 existing device profiles and exclude
commands/setpoints from the telemetry record contract.

History, quality and time semantics
----------------------------------

* Identity is site + asset + point + source system + source ID + event time.
  Exact duplicates are idempotent; conflicting duplicate payloads raise.
  Different sources remain distinct. No silent winner is selected.
* Out-of-order arrival is accepted in history. ``latest_at`` only looks backward
  in event time. Its optional ``known_at`` cutoff reconstructs what had arrived
  by a particular collector time; omitting it gives a retrospective view.
* A newer missing sample replaces the older good sample in a latest snapshot.
  ``quality_snapshot`` marks stale values and source clocks ahead of receive
  time. It cannot measure an unknown device clock error.
* Threshold timelines use half-open investigation windows. Missing/bad samples
  and excessive gaps break continuity. The next valid value is an observation,
  not an inferred threshold crossing. Initial conditions are also observations.
* Rollups include only numeric measurement points, preserving min/max and
  good/total counts. Their mean is sample-weighted, not a time-weighted energy
  calculation. Missing bins stay absent. Counters, alarms and states require
  their own semantics; existing SCADA counter methods remain available.
* A high good fraction says samples were usable, not that all expected samples
  arrived. Track expected cadence and source health separately in deployment.

InfluxDB line protocol export keeps dimensions in tags and typed values/quality
in fields. Point identity includes the point key to avoid collisions between
different quantities. Nulls omit the value field. Raw source payloads and
ownership versions remain in canonical JSONL. Export validates its supported
escaping and timestamp range; the default database precision is nanoseconds.
Reconcile duplicate identities across batches before ingestion: the offline
store's conflict policy does not automatically enforce uniqueness in a database.
No live database write or query compatibility test is claimed.

Operational cases and physical boundaries
----------------------------------------

.. list-table:: Executable incidents
   :header-rows: 1
   :widths: 22 42 36

   * - Scenario
     - Signals and question
     - Boundary
   * - Cooling failure
     - Pump demand falls, coolant flow changes, then temperature rises. Which
       assets depend on that cooling path?
     - Lumped thermal zone; no CFD, pump curve or inferred causal certainty
   * - Workload step
     - Rack terminal demand rises from 60 to 100 kW. Is power change consistent
       with IT demand while cooling remains sufficient?
     - Utilization-driven electrical model, not a measured AI job trace
   * - Utility sag
     - Utility RMS L1-N voltage falls from 230 to 195 V; UPS status changes while
       IT demand remains stable. Does upstream exposure imply customer loss?
     - Ideal protection is assumed; no transfer-time or ride-through validation

All disturbances occupy seconds 60–119. Rack temperature represents a mixed
zone, not a local air or liquid hotspot. The thermal balance is
``C * delta_T = (IT_heat - removed_heat) * delta_t`` with zero conductance in
the fixture. A proportional recovery load restores temperature after the fault.
The separate pump diagnostic trace is not added again to cooling auxiliaries.
Facility power is the synthetic IT plus cooling boundary; it excludes UPS/PDU
losses and other loads. It is not a measured whole-site PUE calculation.

Dependency traversal follows supply links and containment and terminates on
cycles. It ignores monitoring/control links. Redundant feeds, protective actions,
contractual ownership and service dependencies require further analysis before
declaring an outage, SLA breach or root cause.

Sampling, retention and buffering
--------------------------------

``sampling_comparison`` demonstrates a ten-second pulse missed by 30/60 second
sampling for a fixed phase. Faster sampling is useful only when the physical
source and collector support it. A rollup cannot recover an unobserved peak.

For stream ``j``, with series count ``N_j``, sample period ``d_j`` seconds and
assumed bytes ``b_j`` per scalar observation:

.. math::

   R = \sum_j N_j/d_j, \qquad
   S_{raw} = \sum_j (N_j/d_j)\,86400\,D_j\,b_j\,r_j

``r_j`` is the assumed replication factor and ``D_j`` the raw retention days.
Aggregate storage uses its own period, byte size and retention. The two tiers
coexist, so their storage adds. Values are decimal GB, not GiB. The supplied
100/160 byte assumptions are placeholders, not measured InfluxDB compression.
Index overhead, object storage, backups and license fees need deployment data.

An outage of ``T`` seconds needs approximately ``ceil(R*T)`` buffered scalar
observations from an empty queue. Drops are the excess above configured
capacity. With backlog ``B``, recovery writer rate ``W`` and continuing input
``R``, drain time is ``B/(W-R)`` only when ``W > R``; otherwise it is unavailable.
This is steady-rate planning, not a durable queue simulation. Telegraf metrics
may bundle several fields, so scalar observations are not interchangeable with
its metric-buffer count without a commissioning conversion.

Business cases
--------------

``TelemetryBusinessCase`` supports operator incident investigation, colocation
triage, supplier support and separately evidenced energy-saving scenarios.
``business_sensitivity`` evaluates 4/12/36 incidents per year against
0/25/50 percent realization of saved triage time as avoided downtime.

Annual saved investigation hours equal incident count times saved minutes/60.
Labor value multiplies these by responders and labor cost/hour. Downtime value
uses a separate realization fraction and downtime value/hour. Energy value is
an independently supplied kWh saving times price/kWh; it defaults to zero.
The implementation does not estimate energy savings from incident correlation.

Gross benefit less annual operating cost yields net cash flow. NPV discounts
constant annual cash flows over the chosen horizon and subtracts implementation
cost. Simple payback is unavailable when net cash flow is nonpositive. The
operating break-even incident count covers recurring OPEX only, not initial
CAPEX or the NPV hurdle. Labor and downtime inputs must exclude overlapping
costs. Taxes, financing, escalation, SLA penalties and contractual liability
are outside this model. Negative outcomes remain visible.

These calculations support a pilot decision: measure current triage time,
incident frequency, affected service value and actual storage requirements,
then compare a limited deployment against the baseline. They are not market
prices or a vendor ROI claim.

Deployment options and supplier integration
------------------------------------------

The following are project design options, not details from the missing PDF pages:

* **Local replay:** CSV/JSONL evidence, no running database; use for design,
  commissioning tests and independent incident review.
* **Facility-local telemetry:** read-only collectors, a site time-series store
  and versioned DCIM exports. Keep equipment protection/control in local systems.
* **Site plus fleet:** retain detailed site traces and send selected aggregates
  or incident evidence centrally. Track queue depth, late arrivals, clock health,
  collection version and schema drift; size retention separately by tier.
* **Embedded supplier offering:** package the canonical contracts and profile
  mappings with the supplier's BMS/EPMS/DCIM product. Benchmark ingestion and
  support effort with real deployments before claiming scalability or savings.

Commission native addresses, units, topology and freshness with site evidence.
Apply tenant/site access controls in the actual service; this local model does
not implement authorization. Store credentials outside datasets and reports.
The existing repository's noncommercial license still applies to this code;
business-case descriptions do not grant commercial-use rights.

Replay an exported incident
---------------------------

.. code-block:: python

   import json
   from pathlib import Path
   from datacenter_simulator.connectors.telemetry import TelemetryHistory
   from datacenter_simulator.models.telemetry import (
       AssetContext, ContextHistory, ThresholdRule,
   )
   from datacenter_simulator.methods.telemetry import incident_timeline

   root = Path("outputs/telemetry/cooling_failure")
   manifest = json.loads((root / "incident.json").read_text())
   history = TelemetryHistory.read_jsonl(root / "telemetry.jsonl")
   contexts = ContextHistory([AssetContext(**c) for c in manifest["contexts"]])
   rules = [ThresholdRule(**r) for r in manifest["rules"]]
   timeline = incident_timeline(
       history, contexts, rules, site_id="demo-site",
       start="2026-01-01T00:00:00Z", end="2026-01-01T00:03:00Z",
   )
   assert timeline == manifest["timeline"]

Validation includes conservation of the composed thermal/energy models,
independent cash-flow arithmetic, replay equality, duplicate conflicts, source
separation, context boundaries, missing/stale values, clock flags, receive-time
cutoffs, gap handling, topology cycles, buffering units and serialization.
The interactive report is built from deterministic traces; a database-backed
deployment still needs its own integration, security and load testing.
