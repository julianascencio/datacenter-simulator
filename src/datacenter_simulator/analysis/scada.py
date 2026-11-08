"""Export the complete device dictionary, schemas, crosswalk and offline worked example."""

import argparse
import json
from dataclasses import asdict
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Any

import pandas as pd

from datacenter_simulator.connectors.scada import (
    RegisterBinding,
    bacnet_sample,
    modbus_sample,
    opcua_sample,
    redfish_sensor,
    snmp_ups_samples,
)
from datacenter_simulator.methods.scada import (
    apply_observation,
    commissioning_crosswalk,
    describe_control_intent,
    empty_asset,
    simulator_device_asset,
    standards_evidence,
    with_freshness,
)
from datacenter_simulator.models.devices import Device, Electrical
from datacenter_simulator.models.scada import (
    DeviceProfile,
    asset_schema,
    binding_schema,
    endpoint_schema,
    event_schema,
    validate_bindings,
    validate_event,
    validate_plant,
)
from datacenter_simulator.models.scada_catalog import device_profiles

TIMESTAMP = "2026-01-01T12:00:00Z"


def scada_example() -> dict[str, Any]:
    """One inventory skeleton per family; six commissioned synthetic telemetry paths.

    Blank inventory fields indicate unknown data. Example IDs, addresses, input
    values and Modbus offsets are explicitly invented fixtures, not vendor maps.
    """
    profiles = device_profiles()
    assets = []
    for key, profile in profiles.items():
        parent = (
            None
            if key == "site"
            else "site-01"
            if key == "building"
            else "building-01"
            if key == "room"
            else "room-01"
        )
        if key in {"server", "network_switch", "rack_pdu", "storage"}:
            parent = "rack-01"
        if key in {"gpu", "cpu", "memory", "power_supply", "drive"}:
            parent = "server-01"
        if key == "network_port":
            parent = "network_switch-01"
        if key == "pdu_outlet":
            parent = "rack_pdu-01"
        if key == "battery_module":
            parent = "battery_bank-01"
        asset = empty_asset(profile, f"{key}-01", parent_id=parent)
        asset["extensions"] = {
            "asva:evidence_kind": "synthetic",
            "asva:fixture": "not a vendor product",
        }
        assets.append(asset)
    by_id = {a["id"]: a for a in assets}
    raw: dict[str, Any] = {
        "evidence_kind": "synthetic",
        "note": "All IDs, mappings and values are invented fixtures.",
        "redfish": {
            "@odata.type": "#Sensor.v1_11_0.Sensor",
            "@odata.id": "/redfish/v1/Chassis/demo/Sensors/power",
            "Reading": 1200.0,
            "ReadingUnits": "W",
            "ReadingTime": TIMESTAMP,
            "Status": {"State": "Enabled", "Health": "OK"},
        },
        "bacnet": {
            "device_instance": 100,
            "object_type": "analog-input",
            "object_instance": 7,
            "present_value": 18.5,
            "unit": "Cel",
            "status_flags": [False, False, False, False],
            "reliability": "no-fault-detected",
            "out_of_service": False,
        },
        "snmp": {
            "1.3.6.1.2.1.33.1.2.5.0": 5400,
            "1.3.6.1.2.1.33.1.2.4.0": 84,
            "1.3.6.1.2.1.33.1.2.3.0": 12,
            "1.3.6.1.2.1.33.1.4.1.0": 3,
            "1.3.6.1.2.1.33.1.4.4.1.4.1": 300000,
        },
        "modbus_registers": [0, 24500],
        "opcua": {
            "NodeId": "nsu=urn:asva:synthetic;s=CDU1.Flow",
            "Value": 240.0,
            "unit": "L/min",
            "StatusCode": 0,
            "SourceTimestamp": TIMESTAMP,
            "ServerTimestamp": TIMESTAMP,
        },
    }
    binding = RegisterBinding(
        100, 4, "uint32", "W", "Synthetic fixture; NOT a manufacturer register map"
    )
    raw["modbus_binding"] = asdict(binding)
    normalized = [
        (
            "server",
            "active_power_kw",
            redfish_sensor(
                profiles["server"].point("active_power_kw"), raw["redfish"], received_at=TIMESTAMP
            ),
        ),
        (
            "chiller",
            "supply_temperature_c",
            bacnet_sample(
                profiles["chiller"].point("supply_temperature_c"),
                raw["bacnet"],
                received_at=TIMESTAMP,
            ),
        ),
        (
            "rack_pdu",
            "active_power_kw",
            modbus_sample(
                profiles["rack_pdu"].point("active_power_kw"),
                raw["modbus_registers"],
                binding,
                received_at=TIMESTAMP,
            ),
        ),
        (
            "cdu",
            "flow_l_min",
            opcua_sample(profiles["cdu"].point("flow_l_min"), raw["opcua"], received_at=TIMESTAMP),
        ),
    ]
    normalized += [
        ("ups", key, value)
        for key, value in snmp_ups_samples(
            raw["snmp"], received_at=TIMESTAMP, output_line_index=1
        ).items()
    ]
    for family, point_key, value in normalized:
        asset_id = f"{family}-01"
        by_id[asset_id]["supported_points"].append(point_key)
        by_id[asset_id] = apply_observation(by_id[asset_id], point_key, value, profiles[family])
    device = Device("sim-server-01", "server", "rack-dc-bus", Electrical(48, 0.1, 1))
    simulated = simulator_device_asset(device, utilization=0.5, timestamp=TIMESTAMP)
    simulated["parent_id"] = "rack-01"
    assets = [*by_id.values(), simulated]
    relationships = [
        dict(source="grid_connection-01", target="transformer-01", kind="electrical_feed"),
        dict(source="transformer-01", target="switchgear-01", kind="electrical_feed"),
        dict(source="switchgear-01", target="ups-01", kind="electrical_feed"),
        dict(source="ups-01", target="rack_pdu-01", kind="electrical_feed"),
        dict(source="rack_pdu-01", target="server-01", kind="electrical_feed"),
        dict(source="chiller-01", target="cdu-01", kind="cooling_supply"),
        dict(source="cdu-01", target="server-01", kind="cooling_supply"),
        dict(source="network_switch-01", target="server-01", kind="network_link"),
    ]
    validate_plant(assets, relationships, profiles)
    endpoints, bindings = _synthetic_bindings()
    validate_bindings(bindings, endpoints, assets, profiles)
    event = dict(
        id="event-01",
        asset_id="leak_detector-01",
        point_key="leak_alarm",
        condition="Synthetic leak detection event",
        severity="warning",
        state="active",
        raised_at=TIMESTAMP,
        cleared_at=None,
        acknowledged_at=None,
        acknowledged_by=None,
        source="synthetic fixture",
    )
    validate_event(event, profiles["leak_detector"])
    intent = describe_control_intent(
        profiles["cdu"],
        "supply_temperature_setpoint_c",
        22.0,
        asset_id="cdu-01",
        requested_at=TIMESTAMP,
    )
    stale = with_freshness(
        normalized[0][2], profiles["server"].point("active_power_kw"), now="2026-01-01T12:06:00Z"
    )
    return dict(
        assets=assets,
        relationships=relationships,
        raw_inputs=raw,
        events=[event],
        control_intent=intent,
        stale_example=stale,
        endpoints=endpoints,
        bindings=bindings,
    )


def _synthetic_bindings() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Invented commissioning fixture for five interfaces; no network is contacted."""
    targets = [
        (
            "redfish",
            "server",
            "active_power_kw",
            "W",
            dict(resource_uri="/redfish/v1/Chassis/demo/Sensors/power", json_pointer="/Reading"),
        ),
        (
            "bacnet",
            "chiller",
            "supply_temperature_c",
            "Cel",
            dict(
                device_instance=100,
                object_type="analog-input",
                object_instance=7,
                property_name="present-value",
            ),
        ),
        ("snmp", "ups", "battery_voltage_v", "V/10", dict(oid="1.3.6.1.2.1.33.1.2.5.0")),
        (
            "modbus",
            "rack_pdu",
            "active_power_kw",
            "W",
            dict(
                unit_id=1,
                function_code=4,
                address_zero_based=100,
                data_type="uint32",
                word_order="big",
                byte_order="big",
            ),
        ),
        (
            "opcua",
            "cdu",
            "flow_l_min",
            "L/min",
            dict(namespace_uri="urn:asva:synthetic", identifier="s=CDU1.Flow", attribute="Value"),
        ),
    ]
    endpoints, bindings = [], []
    for protocol, asset, point, unit, locator in targets:
        endpoints.append(
            dict(
                id=protocol,
                protocol=protocol,
                address=f"{protocol}.synthetic.invalid",
                security_profile="offline fixture; deployment security must be commissioned",
                credential_reference=None,
            )
        )
        bindings.append(
            dict(
                id=f"{protocol}-binding",
                asset_id=f"{asset}-01",
                point_key=point,
                endpoint_id=protocol,
                protocol=protocol,
                locator=locator,
                native_unit=unit,
                scale=1,
                offset=0,
                source_document="Synthetic fixture, not a vendor mapping",
                evidence_kind="synthetic",
                access="read",
            )
        )
    return endpoints, bindings


def dictionary_tables(profiles: dict[str, DeviceProfile] | None = None) -> dict[str, pd.DataFrame]:
    profiles = device_profiles() if profiles is None else profiles
    return {
        group: pd.DataFrame(
            [
                {"profile": p.key, "label": p.label, "domain": p.domain, **asdict(f)}
                for p in profiles.values()
                for f in getattr(p, group)
            ]
        )
        for group in ("attributes", "points")
    }


def _write_catalog_html(
    profiles: dict[str, DeviceProfile], tables: dict[str, pd.DataFrame], output: Path
) -> None:
    sections = []
    for profile in profiles.values():
        points = tables["points"].query("profile == @profile.key")
        attributes = tables["attributes"].query("profile == @profile.key")

        def table(rows: pd.DataFrame, keys: list[str]) -> str:
            return rows[keys].to_html(index=False, escape=True, na_rep="—")

        point_table = table(
            points,
            [
                "key",
                "description",
                "data_type",
                "unit",
                "role",
                "choices",
                "minimum",
                "maximum",
                "suggested_poll_s",
                "stale_after_s",
                "interlocks",
            ],
        )
        attribute_table = table(attributes, ["key", "description", "data_type", "unit"])
        protocols = ", ".join(profile.preferred_protocols)
        redfish = profile.redfish_resource or "No direct resource asserted in the pinned release"
        sections.append(
            f'''<details class="profile" data-domain="{escape(profile.domain)}">
<summary>{escape(profile.label)}
<small>{len(profile.points)} points · {escape(profile.domain)}</small>
</summary>
<p>{escape(profile.boundary)}</p><p>Candidate interfaces: {escape(protocols)}.
Redfish resource association: {escape(redfish)}.</p>
<p><a href="schemas/{profile.key}.schema.json" download>Device JSON Schema</a></p>
<h3>Identity and nameplate attributes</h3><div class="table">{attribute_table}</div>
<h3>Telemetry, counters, alarms and controls</h3>
<div class="table">{point_table}</div></details>'''
        )
    source_rows = standards_evidence()["selected"]
    selection = pd.DataFrame(
        [{k: r[k] for k in ("name", "role", "limitations")} for r in source_rows]
    )
    source_links = "".join(
        f'<li><a href="{escape(s["url"])}">{escape(s["title"])}</a></li>'
        for s in standards_evidence()["sources"]
    )
    html = (
        files("datacenter_simulator").joinpath("utilities/scada.html").read_text(encoding="utf-8")
    )
    files_to_link = [
        "device_profiles.json",
        "points.csv",
        "attributes.csv",
        "commissioning_crosswalk.csv",
        "standards.json",
        "example_plant.json",
        "example_raw_inputs.json",
        "example_events.json",
        "example_control_intent.json",
        "example_endpoints.json",
        "example_bindings.json",
        "schemas/alarm_event.schema.json",
        "schemas/endpoint.schema.json",
        "schemas/binding.schema.json",
    ]
    values = {
        "MODEL_COUNTS": f"{len(profiles)} profiles · {len(tables['points'])} point definitions · "
        f"{len(tables['attributes'])} attribute definitions.",
        "STANDARDS_TABLE": selection.to_html(index=False, escape=True),
        "DOMAIN_OPTIONS": "".join(
            f"<option>{escape(d)}</option>" for d in sorted({p.domain for p in profiles.values()})
        ),
        "DEVICE_SECTIONS": "".join(sections),
        "SOURCE_LINKS": source_links,
        "DOWNLOADS": " · ".join(f'<a href="{name}" download>{name}</a>' for name in files_to_link),
    }
    for key, value in values.items():
        html = html.replace(key, value)
    (output / "scada-model.html").write_text(html, encoding="utf-8")


def export_scada_model(output: str | Path) -> dict[str, Any]:
    """Export all profiles, individual JSON Schemas and a complete worked integration."""
    output = Path(output)
    schemas = output / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    profiles = device_profiles()
    tables = dictionary_tables(profiles)
    example = scada_example()
    documents = {
        "device_profiles": {k: p.as_dict() for k, p in profiles.items()},
        "standards": standards_evidence(),
        "example_plant": {k: example[k] for k in ("assets", "relationships")},
        "example_raw_inputs": example["raw_inputs"],
        "example_events": example["events"],
        "example_control_intent": example["control_intent"],
        "example_stale_reading": example["stale_example"],
        "example_endpoints": example["endpoints"],
        "example_bindings": example["bindings"],
        "schemas/alarm_event.schema": event_schema(),
        "schemas/endpoint.schema": endpoint_schema(),
        "schemas/binding.schema": binding_schema(),
        **{f"schemas/{k}.schema": asset_schema(p) for k, p in profiles.items()},
    }
    for name, data in documents.items():
        (output / f"{name}.json").write_text(
            json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=False)
    crosswalk = commissioning_crosswalk(profiles)
    pd.DataFrame(crosswalk).to_csv(output / "commissioning_crosswalk.csv", index=False)
    _write_catalog_html(profiles, tables, output)
    return dict(
        profiles=len(profiles),
        points=len(tables["points"]),
        attributes=len(tables["attributes"]),
        mapping_rows=len(crosswalk),
        synthetic_assets=len(example["assets"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/scada"))
    args = parser.parse_args()
    print(json.dumps(export_scada_model(args.output), indent=2))
    print(args.output / "scada-model.html")


if __name__ == "__main__":
    main()
