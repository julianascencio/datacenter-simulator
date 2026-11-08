"""
17. Build a standards-informed data center SCADA inventory
===============================================================================

**Level:** Advanced | **Subject:** device schemas, protocol mappings and quality

Use Redfish for IT resources, BACnet for building equipment, SNMP MIBs for
monitoring and commissioned Modbus maps for electrical/mechanical equipment.
OPC UA provides an additional typed interchange. These are practical integration
choices supported by first-party sources, not a measured market-share ranking.

The canonical model contains 50 device/space profiles. It is an engineering
superset, not a claim that any installed device exposes every point. This example
works offline, with explicitly synthetic inputs and no network access or writes.
See :doc:`../../user_guide/scada` for sources, boundaries and commissioning steps.
"""

import matplotlib.pyplot as plt
import pandas as pd

from datacenter_simulator.analysis.scada import dictionary_tables, scada_example
from datacenter_simulator.methods.scada import commissioning_crosswalk, standards_evidence
from datacenter_simulator.models.scada import validate_bindings, validate_plant
from datacenter_simulator.models.scada_catalog import device_profiles

# %%
# Step 1: inspect the model before populating equipment
# -----------------------------------------------------------------------------
# Each profile defines identity/nameplate attributes, timestamped measurements,
# counters, states, alarms and design-only controls. Canonical units accompany
# every point. Poll/stale intervals are suggestions for commissioning, not
# requirements from the cited standards. Missing metadata remains absent.
profiles = device_profiles()
tables = dictionary_tables(profiles)
points = tables["points"]
print("Profiles:", len(profiles), "Point definitions:", len(points))
print(standards_evidence()["selection_basis"])
print(points.query("profile == 'ups'")[["key", "unit", "role"]].to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
counts = points.groupby(["domain", "role"]).size().unstack(fill_value=0)
counts.plot.barh(stacked=True, ax=axes[0], colormap="tab20")
axes[0].set(xlabel="Point definitions across profiles", ylabel="", title="Catalogue coverage")
axes[0].legend(fontsize=7, loc="lower right")
attributes = tables["attributes"].groupby("domain").size()
axes[1].barh(attributes.index, attributes.values, color="#087f8c")
axes[1].set(xlabel="Attribute definitions across profiles", title="Identity / engineering context")

# %%
# Step 2: create a connected inventory and declare supported points
# -----------------------------------------------------------------------------
# The fixture instantiates one asset per family plus one existing simulator
# server. Only demonstrated telemetry is declared supported. Containment is
# acyclic; separate power/cooling/network links can form meshes. A rack meter
# overlaps its server meters, so their values must not be summed blindly.
example = scada_example()
validate_plant(example["assets"], example["relationships"], profiles)
validate_bindings(example["bindings"], example["endpoints"], example["assets"], profiles)
print("Assets:", len(example["assets"]), "Links:", len(example["relationships"]))
print(pd.DataFrame(example["relationships"]).to_string(index=False))

# %%
# Step 3: distinguish a standard property from a commissioned address
# -----------------------------------------------------------------------------
# A UPS-MIB scalar OID has standardized meaning. A BACnet Present_Value template
# still needs object discovery. Every Modbus register offset in a real deployment
# requires its manufacturer/site map, word order, scale, units and source document.
# The fixture's offset 100 is invented; it is never advertised as a vendor map.
crosswalk = pd.DataFrame(commissioning_crosswalk(profiles))
print(crosswalk.query("mapping_status == 'standard_scalar'").to_string(index=False))
print(pd.DataFrame(example["bindings"])[["protocol", "asset_id", "point_key", "evidence_kind"]])

fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
mapping_counts = crosswalk.groupby("mapping_status").size().sort_values()
ax.barh(mapping_counts.index.str.replace("_", " "), mapping_counts.values, color="#123354")
ax.set(xlabel="Candidate point/interface rows", title="Templates still require commissioning")
ax.tick_params(axis="y", labelsize=8)

# %%
# Step 4: normalize five protocol records without losing provenance
# -----------------------------------------------------------------------------
# Redfish: 1,200 W -> 1.2 kW. UPS-MIB: 5,400 tenths of volts -> 540 V;
# 12 minutes -> 720 seconds. Modbus: [0, 24500] unsigned 32-bit W -> 24.5 kW.
# BACnet carries a Celsius reading; OPC UA carries flow and both source/server
# timestamps. Collectors must decode native BACnet units/enums before ingestion.
# Poll receive time is not a device timestamp. A selected UPS output line remains
# a line reading, not total output. No vendor-specific MIBs are guessed.
observations = pd.DataFrame(
    [
        {"asset": a["id"], "point": key, **value}
        for a in example["assets"]
        for key, value in a["observations"].items()
    ]
)
print(
    observations[["asset", "point", "value", "unit", "quality", "source_protocol"]].to_string(
        index=False
    )
)

# %%
# Step 5: separate signal quality, alarm lifecycle and control intent
# -----------------------------------------------------------------------------
# Old readings become stale without turning into zero. Invalid types/bounds
# become bad/null; incompatible units are binding errors. Counter resets and
# changing sources require reconciliation before differencing. The synthetic
# leak event is an alarm, not a broken sensor. The CDU setpoint record records
# required interlocks and expiry but cannot execute a write.
print("Stale reading:", example["stale_example"])
print("Alarm:", example["events"][0])
print("Design-only request:", example["control_intent"])
print("Simulator bridge:", next(a for a in example["assets"] if a["id"] == "sim-server-01"))

# %%
# Step 6: export the entire model and inspect every field
# -----------------------------------------------------------------------------
# Run ``python -m datacenter_simulator.analysis.scada --output outputs/scada``.
# Open ``outputs/scada/scada-model.html``. It contains all 50 searchable device
# cards, per-device JSON Schema downloads, the point and attribute dictionaries,
# mapping evidence, endpoints/bindings and the synthetic plant. The simulator
# bridge explicitly labels DC-terminal power; it does not invent an AC reading.
# The full export is also available in the documentation's linked catalogue.
plt.show()
