"""Commissioning crosswalks, quality handling, control intent and simulator bridge."""

import json
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from importlib.resources import files
from typing import Any

from datacenter_simulator.connectors.scada import UPS_OUTPUT_LINES, UPS_SCALARS, normalize_sample
from datacenter_simulator.models.devices import Device
from datacenter_simulator.models.scada import (
    SCHEMA_VERSION,
    DeviceProfile,
    FieldSpec,
    asset_schema,
    utc_time,
    validate_json,
)
from datacenter_simulator.models.scada_catalog import device_profiles


def standards_evidence() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        files("datacenter_simulator")
        .joinpath("data/scada_standards.json")
        .read_text(encoding="utf-8")
    )
    return result


def commissioning_crosswalk(
    profiles: dict[str, DeviceProfile] | None = None,
) -> list[dict[str, Any]]:
    """Every point gets explicit mapping status for the profile's candidate interfaces.

    A standard property template is NOT a discovered device binding. Exact UPS
    MIB scalar semantics are distinguished from phase tables and vendor maps.
    No fabricated register, object instance or NodeId is emitted.
    """
    profiles = device_profiles() if profiles is None else profiles
    result = []
    scalar_by_point = {point: (oid, unit) for oid, (point, unit) in UPS_SCALARS.items()}
    lines_by_point = {point: (oid, unit) for oid, (point, unit) in UPS_OUTPUT_LINES.items()}
    for profile in profiles.values():
        for point in profile.points:
            for protocol in profile.preferred_protocols:
                locator: str | None = None
                status, source = "vendor_or_site_mapping_required", "canonical-engineering-profile"
                native_unit: str | None = None
                if protocol == "bacnet":
                    obj = (
                        "binary-value"
                        if point.data_type == "boolean"
                        else "multi-state-value"
                        if point.data_type == "string"
                        else "analog-value"
                    )
                    locator, status, source = (
                        f"{obj}.Present_Value",
                        "object_property_template",
                        "bacnet-ua",
                    )
                elif protocol == "opcua":
                    locator, status, source = (
                        "Variable.Value / DataValue",
                        "variable_template",
                        "opcua-datavalue",
                    )
                elif protocol == "modbus":
                    source = "modbus-1-1b3"
                elif protocol == "redfish":
                    source = "dmtf-model-2026-1"
                    if point.key == "health":
                        locator, status = "Status.Health", "property_template"
                    elif point.role in {"measurement", "counter"}:
                        locator, status = (
                            "Sensor.Reading + ReadingUnits",
                            "sensor_discovery_required",
                        )
                elif protocol == "snmp":
                    source = "rfc3433"
                    if profile.key == "ups" and point.key in scalar_by_point:
                        locator, native_unit = scalar_by_point[point.key]
                        status, source = "standard_scalar", "rfc1628"
                    elif profile.key == "ups" and point.key in lines_by_point:
                        root, native_unit = lines_by_point[point.key]
                        locator, status, source = (
                            root + ".{outputLineIndex}",
                            "standard_table_template",
                            "rfc1628",
                        )
                # Commands describe intent only; templates never confer write permission.
                if point.role in {"command", "setpoint"}:
                    status = "control_mapping_and_authorization_required"
                result.append(
                    dict(
                        profile=profile.key,
                        point=point.key,
                        protocol=protocol,
                        canonical_unit=point.unit,
                        native_unit=native_unit,
                        locator=locator,
                        mapping_status=status,
                        source_id=source,
                        requires_commissioning=True,
                        execution_supported=False,
                    )
                )
    return result


def empty_asset(
    profile: DeviceProfile, asset_id: str, *, parent_id: str | None = None
) -> dict[str, Any]:
    """Inventory skeleton: no fabricated manufacturer, ratings or observations."""
    return dict(
        schema_version=SCHEMA_VERSION,
        id=asset_id,
        name=profile.label,
        profile=profile.key,
        parent_id=parent_id,
        identity={},
        location={},
        attributes={},
        observations={},
        supported_points=[],
        extensions={},
    )


def apply_observation(
    asset: dict[str, Any], point_key: str, observation: dict[str, Any], profile: DeviceProfile
) -> dict[str, Any]:
    """Return a validated copy; out-of-order updates cannot replace a newer snapshot."""
    if asset["profile"] != profile.key:
        raise ValueError("asset/profile mismatch")
    if point_key not in asset["supported_points"]:
        raise ValueError("point was not commissioned as supported")
    previous = asset["observations"].get(point_key)
    if previous:
        # Source time is comparable only when both observations provide it.
        key = (
            "source_timestamp"
            if previous["source_timestamp"] and observation["source_timestamp"]
            else "received_at"
        )
        if utc_time(observation[key]) < utc_time(previous[key]):
            raise ValueError("out-of-order observation")
    result = deepcopy(asset)
    result["observations"][point_key] = deepcopy(observation)
    validate_json(result, asset_schema(profile))
    return result


def with_freshness(observation: dict[str, Any], point: FieldSpec, *, now: str) -> dict[str, Any]:
    """Mark usable but old values stale; preserve bad/missing/uncertain quality.

    Use device source time if supplied, otherwise collector receive time. A
    receive-only observation cannot prove how fresh the device's cache was.
    """
    result = deepcopy(observation)
    stamp = observation["source_timestamp"] or observation["received_at"]
    age = (utc_time(now) - utc_time(stamp)).total_seconds()
    if age < 0 and result["quality"] in {"good", "uncertain"}:
        result.update(quality="uncertain", quality_reason="Timestamp is ahead of evaluation time.")
    elif age > point.stale_after_s and result["quality"] == "good":
        result.update(
            quality="stale", quality_reason=f"Age {age:g}s exceeds {point.stale_after_s}s."
        )
    return result


def counter_delta(previous: dict[str, Any], current: dict[str, Any]) -> float:
    """Only comparable good counters; resets/wraps require explicit reconciliation."""
    if previous["quality"] != "good" or current["quality"] != "good":
        raise ValueError("counter differences require good-quality samples")
    if bool(previous["source_timestamp"]) != bool(current["source_timestamp"]):
        raise ValueError("counter timestamp bases must match")
    if (previous["unit"], previous["source_protocol"], previous["source_address"]) != (
        current["unit"],
        current["source_protocol"],
        current["source_address"],
    ):
        raise ValueError("counter source/unit mismatch")
    previous_time = previous["source_timestamp"] or previous["received_at"]
    current_time = current["source_timestamp"] or current["received_at"]
    if utc_time(current_time) <= utc_time(previous_time):
        raise ValueError("counter timestamps must increase")
    difference = float(current["value"] - previous["value"])
    if difference < 0:
        raise ValueError("counter reset/wrap; split or reconcile before differencing")
    return difference


def describe_control_intent(
    profile: DeviceProfile,
    point_key: str,
    value: Any,
    *,
    asset_id: str,
    requested_at: str,
    expires_in_s: int = 30,
) -> dict[str, Any]:
    """Construct a non-executable control record; no actuator or credentials exist.

    Site limits, local/remote mode, interlocks, priority (BACnet where applicable),
    authorization and readback must be implemented by a real control system.
    """
    point = profile.point(point_key)
    if point.role not in {"command", "setpoint"}:
        raise ValueError("not a control point")
    if type(expires_in_s) is not int or expires_in_s <= 0 or not asset_id:
        raise ValueError("control needs a target and positive integer validity")
    validate_json(value, point.value_schema())
    stamp = utc_time(requested_at)
    return dict(
        schema_version=SCHEMA_VERSION,
        asset_id=asset_id,
        point_key=point_key,
        value=value,
        unit=point.unit,
        requested_at=stamp.isoformat(),
        expires_at=(stamp + timedelta(seconds=expires_in_s)).isoformat(),
        required_interlocks=list(point.interlocks),
        execution_supported=False,
        state="design_only",
    )


def simulator_device_asset(
    device: Device, *, utilization: float, timestamp: str, profile_key: str = "server"
) -> dict[str, Any]:
    """Bridge the existing DC-terminal model without claiming an AC meter reading."""
    profile = device_profiles()[profile_key]
    point = profile.point("active_power_kw")
    asset = empty_asset(profile, device.id)
    asset["name"] = device.description or device.id
    asset["attributes"] = {
        "rated_power_kw": device.electrical.peak_kw,
        "rated_voltage_v": device.electrical.nominal_voltage_v,
    }
    asset["location"] = {key: getattr(device.placement, key) for key in ("x_m", "y_m", "z_m")}
    asset["supported_points"] = [point.key]
    asset["extensions"] = {
        "asva:power_boundary": "dc_terminal",
        "asva:bus_id": device.bus_id,
        "asva:placement": asdict(device.placement),
    }
    value = normalize_sample(
        point,
        device.power_kw(utilization),
        native_unit="kW",
        received_at=timestamp,
        source_timestamp=timestamp,
        protocol="simulator",
        address=f"simulation/{device.id}/dc_terminal",
        raw_status="synthetic",
        reason="Existing simulator DC-terminal result.",
    )
    return apply_observation(asset, point.key, value, profile)
