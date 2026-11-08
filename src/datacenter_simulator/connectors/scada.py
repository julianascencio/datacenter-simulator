"""Offline normalization of collected protocol records; no network I/O or writes.

Bindings are commissioned explicitly. Resource URIs, BACnet object instances,
Modbus registers and OPC UA NodeIds are never guessed from equipment names.
"""

import struct
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

from jsonschema import ValidationError

from datacenter_simulator.models.scada import FieldSpec, observation_schema, utc_time, validate_json

# Only explicit dimension-preserving conversions are supported. No unit guessing.
CONVERSIONS = {
    ("W", "kW"): (0.001, 0),
    ("Wh", "kWh"): (0.001, 0),
    ("J", "kWh"): (1 / 3_600_000, 0),
    ("Pa", "kPa"): (0.001, 0),
    ("bar", "kPa"): (100, 0),
    ("L/s", "L/min"): (60, 0),
    ("m3/min", "m3/h"): (60, 0),
    ("m3/s", "m3/h"): (3600, 0),
    ("min", "s"): (60, 0),
    ("degF", "Cel"): (5 / 9, -32 * 5 / 9),
    ("K", "Cel"): (1, -273.15),
    ("mW", "kW"): (1e-6, 0),
    ("V/10", "V"): (0.1, 0),
    ("A/10", "A"): (0.1, 0),
    ("Hz/10", "Hz"): (0.1, 0),
}


def normalize_sample(
    point: FieldSpec,
    value: Any,
    *,
    native_unit: str,
    received_at: str,
    protocol: str,
    address: str,
    source_timestamp: str | None = None,
    quality: str = "good",
    raw_status: Any = None,
    reason: str = "Source reported a usable value.",
    raw_value: Any = None,
) -> dict[str, Any]:
    """Preserve quality/provenance; invalid values become bad/null, never zero.

    Unit incompatibility is a binding error and raises. Bad source samples may
    retain an interpretable numeric value, but must not be used as good data.
    """
    utc_time(received_at)
    if quality not in {"good", "uncertain", "bad", "missing", "stale"}:
        raise ValueError("unknown sample quality")
    if source_timestamp is not None:
        utc_time(source_timestamp)
    if point.role in {"setpoint", "command"}:
        raise ValueError("control intents are not measured observations")
    original = value if raw_value is None else raw_value
    if native_unit != point.unit:
        if (native_unit, point.unit) not in CONVERSIONS:
            raise ValueError(f"unsupported unit conversion {native_unit} -> {point.unit}")
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                value, quality, reason = None, "bad", "Non-numeric value for engineering units."
            else:
                scale, offset = CONVERSIONS[native_unit, point.unit]
                value = value * scale + offset
    if value is None and quality == "good":
        quality, reason = "missing", "Source value is absent; not zero."
    if isinstance(value, float) and not isfinite(value):
        value, quality, reason = None, "bad", "Source number is not finite."
    if isinstance(original, float) and not isfinite(original):
        original = repr(original)  # Keep a JSON-safe diagnostic rather than NaN/Infinity.
    result = dict(
        value=value,
        unit=point.unit,
        quality=quality,
        source_timestamp=source_timestamp,
        received_at=received_at,
        source_protocol=protocol,
        source_address=address,
        raw_status=raw_status,
        raw_value=original,
        quality_reason=reason,
    )
    try:
        validate_json(result, observation_schema(point))
    except ValidationError:
        # Only value/type failures are data-quality events; envelope errors still fail.
        result.update(
            value=None, quality="bad", quality_reason="Value violates the point contract."
        )
        validate_json(result, observation_schema(point))
    return result


def redfish_sensor(
    point: FieldSpec, payload: dict[str, Any], *, received_at: str
) -> dict[str, Any]:
    """Normalize Sensor.Reading using ReadingUnits and optional ReadingTime.

    Sensor-to-equipment association/physical context must already be discovered.
    Status.Health describes equipment condition, not measurement validity.
    """
    if not str(payload.get("@odata.type", "")).startswith("#Sensor."):
        raise ValueError("a Redfish Sensor resource is required")
    if not payload.get("@odata.id") or "ReadingUnits" not in payload:
        raise ValueError("sensor identity and ReadingUnits are required")
    state = payload.get("Status", {}).get("State")
    quality = "uncertain" if state in {"Disabled", "UnavailableOffline", "Absent"} else "good"
    return normalize_sample(
        point,
        payload.get("Reading"),
        native_unit=payload["ReadingUnits"],
        received_at=received_at,
        protocol="redfish",
        address=payload["@odata.id"],
        source_timestamp=payload.get("ReadingTime"),
        quality=quality,
        raw_status=payload.get("Status"),
        reason="Sensor resource state retained.",
    )


# RFC 1628 scalars include .0. Table instances are added only after line discovery.
UPS_SCALARS = {
    "1.3.6.1.2.1.33.1.2.3.0": ("remaining_runtime_s", "min"),
    "1.3.6.1.2.1.33.1.2.4.0": ("state_of_charge_percent", "%"),
    "1.3.6.1.2.1.33.1.2.5.0": ("battery_voltage_v", "V/10"),
    "1.3.6.1.2.1.33.1.2.7.0": ("battery_temperature_c", "Cel"),
    "1.3.6.1.2.1.33.1.4.2.0": ("frequency_hz", "Hz/10"),
    "1.3.6.1.2.1.33.1.4.1.0": ("output_source", "1"),
}
UPS_OUTPUT_LINES = {
    "1.3.6.1.2.1.33.1.4.4.1.2": ("output_line_voltage_v", "V"),
    "1.3.6.1.2.1.33.1.4.4.1.3": ("output_line_current_a", "A/10"),
    "1.3.6.1.2.1.33.1.4.4.1.4": ("output_line_power_kw", "W"),
}
UPS_SOURCES = {
    1: "other",
    2: "none",
    3: "normal",
    4: "bypass",
    5: "battery",
    6: "booster",
    7: "reducer",
}


def snmp_ups_samples(
    varbinds: dict[str, Any], *, received_at: str, output_line_index: int | None = None
) -> dict[str, dict[str, Any]]:
    """Import known UPS-MIB fields; unknown/vendor OIDs are deliberately ignored.

    A selected output line remains a line measurement. The caller must discover
    all lines before calculating a total. SNMP poll time is not source time.
    """
    from datacenter_simulator.models.scada_catalog import device_profiles

    profile = device_profiles()["ups"]
    mapping = dict(UPS_SCALARS)
    if output_line_index is not None:
        if type(output_line_index) is not int or output_line_index < 1:
            raise ValueError("output line index must be a discovered positive integer")
        mapping.update(
            {f"{oid}.{output_line_index}": target for oid, target in UPS_OUTPUT_LINES.items()}
        )
    result = {}
    for oid, raw in varbinds.items():
        normalized_oid = oid.lstrip(".")
        if normalized_oid not in mapping:
            continue
        key, unit = mapping[normalized_oid]
        value = None if raw in ("noSuchObject", "noSuchInstance", "endOfMibView") else raw
        if key == "output_source" and value is not None:
            value = UPS_SOURCES.get(value, "unrecognized") if type(value) is int else "unrecognized"
        result[key] = normalize_sample(
            profile.point(key),
            value,
            native_unit=unit,
            received_at=received_at,
            protocol="snmp",
            address=normalized_oid,
            raw_status="poll_result",
            raw_value=raw,
        )
    return result


def snmp_entity_sensor(
    point: FieldSpec, record: dict[str, Any], *, received_at: str
) -> dict[str, Any]:
    """RFC 3433: raw × 10**(scale exponent - max(precision, 0)).

    sysUpTime-based ValueTimeStamp is retained as metadata, never labelled UTC.
    Types other/unknown and uncommissioned unit conversions are rejected.
    Negative precision describes accuracy, not a multiplier. Overflow/underflow
    sentinel values are invalid measurements, even when status says 'ok'.
    """
    kind, scale, precision = (record[k] for k in ("type", "scale", "precision"))
    if any(type(v) is not int for v in (kind, scale, precision)):
        raise ValueError("sensor type/scale/precision must be integers")
    if not 1 <= scale <= 17 or not -8 <= precision <= 9:
        raise ValueError("invalid ENTITY-SENSOR scaling metadata")
    unit = {
        3: "V",
        4: "V",
        5: "A",
        6: "W",
        7: "Hz",
        8: "Cel",
        9: "%",
        10: "rpm",
        11: "m3/min",
        12: "1",
    }.get(kind)
    if unit is None:
        raise ValueError("unknown sensor unit; vendor metadata required")
    if kind in {9, 10, 12} and (scale != 9 or precision != 0):
        raise ValueError("non-fixed-point sensor requires units scale and zero precision")
    raw = record["value"]
    if type(raw) is not int:
        raise ValueError("ENTITY-SENSOR value must be an integer")
    if type(record["index"]) is not int or not 1 <= record["index"] <= 2147483647:
        raise ValueError("sensor index must identify a discovered physical entity")
    fixed_point = kind in {3, 4, 5, 6, 7, 8, 11}
    value: Any = raw * 10.0 ** (3 * (scale - 9) - max(precision, 0)) if fixed_point else raw
    if kind == 12:
        value = {1: True, 2: False}.get(raw)
    quality = {1: "good", 2: "missing", 3: "bad"}.get(record["status"], "bad")
    invalid = (
        abs(raw) > 999999999
        or (kind == 9 and not 0 <= raw <= 100)
        or (kind == 12 and raw not in {1, 2})
    )
    if invalid:
        value, quality = None, "bad"
    if quality == "missing":
        value = None
    return normalize_sample(
        point,
        value,
        native_unit=unit,
        received_at=received_at,
        protocol="snmp",
        address=f"1.3.6.1.2.1.99.1.1.1.4.{record['index']}",
        quality=quality,
        raw_status={k: v for k, v in record.items() if k != "value"},
        raw_value=raw,
    )


def bacnet_sample(point: FieldSpec, record: dict[str, Any], *, received_at: str) -> dict[str, Any]:
    """Normalize a discovered BACnet object's Present_Value and quality properties.

    Input record is a collector interchange, not a BACnet APDU. Four Status_Flags
    are in_alarm, fault, overridden, out_of_service. Alarm alone is not bad quality.
    Unit strings, binary values and multi-state values are already decoded by
    the collector. Canonical enum meanings require explicit commissioned maps.
    """
    status = record["status_flags"]
    if not isinstance(status, list) or len(status) != 4 or any(type(v) is not bool for v in status):
        raise ValueError("four BACnet Boolean status flags are required")
    for key in ("device_instance", "object_instance"):
        if type(record[key]) is not int or not 0 <= record[key] <= 4194302:
            raise ValueError("invalid discovered BACnet instance")
    if "out_of_service" in record and type(record["out_of_service"]) is not bool:
        raise ValueError("out_of_service must be a Boolean")
    if record["object_type"] not in {
        "analog-input",
        "analog-value",
        "binary-input",
        "binary-value",
        "multi-state-input",
        "multi-state-value",
        "accumulator",
    }:
        raise ValueError("unsupported BACnet observation object type")
    quality = "good"
    if status[1] or record.get("reliability", "no-fault-detected") != "no-fault-detected":
        quality = "bad"
    elif status[2] or status[3] or record.get("out_of_service", False):
        quality = "uncertain"
    return normalize_sample(
        point,
        record.get("present_value"),
        native_unit=record["unit"],
        received_at=received_at,
        protocol="bacnet",
        quality=quality,
        address=f"{record['device_instance']}/{record['object_type']}/{record['object_instance']}/present-value",
        source_timestamp=record.get("source_timestamp"),
        raw_status={
            k: record.get(k)
            for k in (
                "status_flags",
                "reliability",
                "out_of_service",
                "priority_array",
                "relinquish_default",
            )
        },
        reason="BACnet status/reliability preserved; overrides are not normal measured values.",
    )


@dataclass(frozen=True)
class RegisterBinding:
    """A supplied vendor/site register definition, never an industry-wide address."""

    address_zero_based: int
    function_code: int
    data_type: str
    native_unit: str
    source_document: str
    unit_id: int = 1
    word_order: Literal["big", "little"] = "big"
    byte_order: Literal["big", "little"] = "big"
    scale: float = 1
    offset: float = 0
    invalid_raw_values: tuple[int | float, ...] = ()

    def __post_init__(self) -> None:
        if type(self.address_zero_based) is not int or not 0 <= self.address_zero_based <= 65535:
            raise ValueError("register address must be explicitly zero-based")
        if self.function_code not in (3, 4) or type(self.function_code) is not int:
            raise ValueError("only read holding/input registers are supported")
        if type(self.unit_id) is not int or not 1 <= self.unit_id <= 247:
            raise ValueError("unit id must be 1..247")
        if self.data_type not in {"int16", "uint16", "int32", "uint32", "float32", "float64"}:
            raise ValueError("unsupported register data type")
        if self.word_order not in {"big", "little"} or self.byte_order not in {"big", "little"}:
            raise ValueError("explicit word/byte orders are required")
        if (
            not self.source_document
            or not self.native_unit
            or not all(isfinite(v) for v in (self.scale, self.offset))
        ):
            raise ValueError("binding needs source, units and finite calibration")
        if self.scale == 0:
            raise ValueError("zero calibration scale destroys measurements")


def modbus_sample(
    point: FieldSpec, registers: list[int], binding: RegisterBinding, *, received_at: str
) -> dict[str, Any]:
    """Decode exact register width, signedness, byte/word order, scale and units."""
    code = {
        "int16": "h",
        "uint16": "H",
        "int32": "i",
        "uint32": "I",
        "float32": "f",
        "float64": "d",
    }[binding.data_type]
    count = struct.calcsize(">" + code) // 2
    if len(registers) != count or binding.address_zero_based + count > 65536:
        raise ValueError("register span does not match declared data type/address space")
    if any(type(v) is not int or not 0 <= v <= 65535 for v in registers):
        raise ValueError("registers must contain unsigned 16-bit integers")
    words = registers[::-1] if binding.word_order == "little" else registers
    data = b"".join(v.to_bytes(2, binding.byte_order) for v in words)
    raw = struct.unpack(">" + code, data)[0]
    value = None if raw in binding.invalid_raw_values else raw * binding.scale + binding.offset
    return normalize_sample(
        point,
        value,
        native_unit=binding.native_unit,
        received_at=received_at,
        protocol="modbus",
        address=f"unit={binding.unit_id};fc={binding.function_code};offset={binding.address_zero_based}",
        raw_status={
            "registers": registers,
            "source_document": binding.source_document,
            "word_order": binding.word_order,
            "byte_order": binding.byte_order,
        },
        raw_value=raw,
        reason="Vendor/site register mapping; device source timestamp unavailable.",
    )


def opcua_sample(point: FieldSpec, record: dict[str, Any], *, received_at: str) -> dict[str, Any]:
    """Preserve DataValue source/server timestamps and StatusCode severity bits.

    This accepts a decoded interchange object, not a wire-level OPC UA message.
    NodeId and EngineeringUnits must come from server metadata/commissioning.
    """
    code = record["StatusCode"]
    if type(code) is not int or not 0 <= code <= 0xFFFFFFFF or code >> 30 == 3:
        raise ValueError("invalid OPC UA StatusCode")
    if record.get("ServerTimestamp") is not None:
        utc_time(record["ServerTimestamp"])
    return normalize_sample(
        point,
        record.get("Value"),
        native_unit=record["unit"],
        received_at=received_at,
        protocol="opcua",
        address=record["NodeId"],
        source_timestamp=record.get("SourceTimestamp"),
        quality={0: "good", 1: "uncertain", 2: "bad"}[code >> 30],
        raw_status={"StatusCode": code, "ServerTimestamp": record.get("ServerTimestamp")},
    )
