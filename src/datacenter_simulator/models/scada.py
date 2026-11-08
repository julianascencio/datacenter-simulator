"""Versioned canonical SCADA contracts; these are not native protocol schemas."""

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "1.0.0"
PROTOCOLS = ("redfish", "bacnet", "snmp", "modbus", "opcua", "simulator", "manual")
UNITS = {
    "1": "dimensionless",
    "%": "percent; valid bounds depend on the quantity",
    "kW": "kilowatt",
    "kWh": "kilowatt hour",
    "kVA": "kilovolt ampere",
    "kvar": "kilovar",
    "V": "volt",
    "A": "ampere",
    "Hz": "hertz",
    "Cel": "degree Celsius",
    "K": "kelvin difference",
    "kPa": "kilopascal",
    "rpm": "revolutions/min",
    "kg/s": "kilograms/second",
    "L/min": "litres/minute",
    "m3/h": "cubic metres/hour",
    "m3": "cubic metre",
    "L": "litre",
    "m": "metre",
    "mm": "millimetre",
    "s": "second",
    "h": "hour",
    "ms": "millisecond",
    "count": "count",
    "byte": "byte",
    "GiB": "2^30 bytes",
    "MiB": "2^20 bytes",
    "MHz": "megahertz",
    "Gbit/s": "gigabit/second",
    "bit/s": "bit/second",
    "Ohm": "ohm",
    "ppm": "parts per million",
    "uS/cm": "microsiemens/centimetre",
    "kg": "kilogram",
    "U": "rack unit",
    "dB": "decibel",
}


@dataclass(frozen=True)
class FieldSpec:
    """Project-selected engineering field, with explicit units and semantics.

    Bounds describe valid data, not alarm thresholds. Poll/stale intervals are
    commissioning suggestions, not protocol requirements or equipment guarantees.
    """

    key: str
    description: str
    unit: str = "1"
    data_type: str = "number"
    role: str = "measurement"
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    suggested_poll_s: int = 60
    stale_after_s: int = 300
    interlocks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key.isidentifier() or not self.description or self.unit not in UNITS:
            raise ValueError("field needs an identifier, description and registered unit")
        if self.data_type not in {"number", "integer", "boolean", "string"}:
            raise ValueError("unsupported field data type")
        if self.role not in {
            "attribute",
            "measurement",
            "counter",
            "status",
            "alarm",
            "setpoint",
            "command",
        }:
            raise ValueError("unsupported field role")
        if self.choices and self.data_type != "string":
            raise ValueError("enumerations require string values")
        for value in (self.minimum, self.maximum):
            if value is not None and not isfinite(value):
                raise ValueError("field bounds must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("inverted field bounds")
        if self.suggested_poll_s <= 0 or self.stale_after_s < self.suggested_poll_s:
            raise ValueError("invalid sampling/staleness suggestion")
        if self.role in {"setpoint", "command"} and not self.interlocks:
            raise ValueError("control definitions need explicit interlocks")

    def value_schema(self, *, nullable: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": [self.data_type, "null"] if nullable else self.data_type,
            "description": self.description,
            "x-unit": self.unit,
        }
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        if self.choices:
            result["enum"] = [*self.choices, None] if nullable else list(self.choices)
        return result


@dataclass(frozen=True)
class DeviceProfile:
    key: str
    label: str
    domain: str
    attributes: tuple[FieldSpec, ...]
    points: tuple[FieldSpec, ...]
    preferred_protocols: tuple[str, ...]
    redfish_resource: str | None = None
    boundary: str = "Device-local; reconcile child meters before aggregation."

    def __post_init__(self) -> None:
        if not self.key.isidentifier() or not self.label or not self.domain:
            raise ValueError("profile identity is required")
        for fields in (self.attributes, self.points):
            if len({f.key for f in fields}) != len(fields):
                raise ValueError(f"duplicate field in {self.key}")
        if not self.points or set(self.preferred_protocols) - set(PROTOCOLS):
            raise ValueError("profile needs points and known protocols")
        if any(f.role != "attribute" for f in self.attributes):
            raise ValueError("attribute role required")
        if any(f.role == "attribute" for f in self.points):
            raise ValueError("point cannot be a static attribute")

    def point(self, key: str) -> FieldSpec:
        try:
            return next(f for f in self.points if f.key == key)
        except StopIteration as error:
            raise ValueError(f"unknown point {self.key}.{key}") from error

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1}
STAMP = {"type": "string", "format": "date-time"}


def observation_schema(point: FieldSpec) -> dict[str, Any]:
    """Quality is data usability, distinct from asset health and alarm severity."""
    result = object_schema(
        {
            "value": point.value_schema(nullable=True),
            "unit": {"const": point.unit},
            "quality": {"enum": ["good", "uncertain", "bad", "missing", "stale"]},
            "source_timestamp": {"type": ["string", "null"], "format": "date-time"},
            "received_at": STAMP,
            "source_protocol": {"enum": list(PROTOCOLS)},
            "source_address": TEXT,
            "raw_status": {},
            "raw_value": {},
            "quality_reason": TEXT,
        },
        (
            "value",
            "unit",
            "quality",
            "source_timestamp",
            "received_at",
            "source_protocol",
            "source_address",
            "raw_status",
            "quality_reason",
        ),
    )
    result["allOf"] = [
        {
            "if": {"properties": {"quality": {"const": "good"}}},
            "then": {"properties": {"value": {"not": {"type": "null"}}}},
        }
    ]
    return result


def asset_schema(profile: DeviceProfile) -> dict[str, Any]:
    """JSON Schema 2020-12 for inventory plus an optional timestamped snapshot.

    Unsupported/unknown points are omitted, never filled with zero. The profile
    is a superset; installed assets declare only discovered capabilities.
    """
    result = object_schema(
        {
            "schema_version": {"const": SCHEMA_VERSION},
            "id": TEXT,
            "name": TEXT,
            "profile": {"const": profile.key},
            "parent_id": {"type": ["string", "null"]},
            "identity": object_schema(
                {
                    key: {"type": ["string", "null"]}
                    for key in (
                        "manufacturer",
                        "model",
                        "serial_number",
                        "asset_tag",
                        "firmware_version",
                        "hardware_revision",
                        "commissioned_at",
                        "owner",
                        "maintenance_reference",
                    )
                }
            ),
            "location": object_schema(
                {
                    **{
                        key: {"type": ["string", "null"]}
                        for key in ("site", "building", "floor", "room", "rack", "feed")
                    },
                    **{key: {"type": ["number", "null"]} for key in ("x_m", "y_m", "z_m")},
                    "rack_unit": {"type": ["integer", "null"], "minimum": 1},
                }
            ),
            "attributes": object_schema({f.key: f.value_schema() for f in profile.attributes}),
            "observations": object_schema(
                {
                    f.key: observation_schema(f)
                    for f in profile.points
                    if f.role not in {"command", "setpoint"}
                }
            ),
            "supported_points": {
                "type": "array",
                "uniqueItems": True,
                "items": {"enum": [f.key for f in profile.points]},
            },
            "extensions": {"type": "object", "propertyNames": {"pattern": "^[a-z][a-z0-9_]*:"}},
        },
        (
            "schema_version",
            "id",
            "name",
            "profile",
            "parent_id",
            "identity",
            "location",
            "attributes",
            "observations",
            "supported_points",
            "extensions",
        ),
    )
    result.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"urn:asva:datacenter:scada:{SCHEMA_VERSION}:{profile.key}",
            "title": profile.label,
            "description": profile.boundary,
        }
    )
    return result


def validate_json(document: Any, schema: dict[str, Any]) -> None:
    """Reject Python's non-JSON NaN/Infinity in addition to schema/format errors."""

    def finite_tree(value: Any) -> None:
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("JSON numbers must be finite")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("JSON object keys must be strings")
            for item in value.values():
                finite_tree(item)
        elif isinstance(value, list):
            for item in value:
                finite_tree(item)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError("value is not a JSON primitive, array or object")

    finite_tree(document)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def validate_plant(
    assets: list[dict[str, Any]],
    relationships: list[dict[str, str]],
    profiles: dict[str, DeviceProfile],
) -> None:
    """Validate capabilities, UTC-aware observations, containment and typed links.

    Power/cooling/network links may form loops. Containment may not form cycles.
    Relationships do not authorize summing overlapping parent and child meters.
    """
    by_id = {a["id"]: a for a in assets}
    if not assets or len(by_id) != len(assets):
        raise ValueError("assets must be nonempty with unique ids")
    for asset in assets:
        if asset["profile"] not in profiles:
            raise ValueError("unknown device profile")
        validate_json(asset, asset_schema(profiles[asset["profile"]]))
        if set(asset["observations"]) - set(asset["supported_points"]):
            raise ValueError("observation must belong to a declared supported point")
        visited = {asset["id"]}
        parent = asset["parent_id"]
        while parent is not None:
            if parent not in by_id or parent in visited:
                raise ValueError("dangling or cyclic containment")
            visited.add(parent)
            parent = by_id[parent]["parent_id"]
    seen = set()
    for link in relationships:
        if set(link) != {"source", "target", "kind"}:
            raise ValueError("relationship requires source, target, kind")
        key = (link["source"], link["target"], link["kind"])
        if key in seen or link["source"] == link["target"]:
            raise ValueError("duplicate or self relationship")
        seen.add(key)
        if link["source"] not in by_id or link["target"] not in by_id:
            raise ValueError("dangling relationship")
        if link["kind"] not in {
            "electrical_feed",
            "cooling_supply",
            "network_link",
            "monitors",
            "controls",
        }:
            raise ValueError("unknown relationship kind")


def utc_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def event_schema() -> dict[str, Any]:
    """Portable alarm lifecycle; thresholds are site-configured, not preset limits."""
    return object_schema(
        {
            "id": TEXT,
            "asset_id": TEXT,
            "point_key": TEXT,
            "condition": TEXT,
            "severity": {"enum": ["info", "warning", "critical"]},
            "state": {"enum": ["active", "cleared"]},
            "raised_at": STAMP,
            "cleared_at": {"type": ["string", "null"], "format": "date-time"},
            "acknowledged_at": {"type": ["string", "null"], "format": "date-time"},
            "acknowledged_by": {"type": ["string", "null"]},
            "source": TEXT,
        },
        (
            "id",
            "asset_id",
            "point_key",
            "condition",
            "severity",
            "state",
            "raised_at",
            "cleared_at",
            "acknowledged_at",
            "acknowledged_by",
            "source",
        ),
    )


def validate_event(event: dict[str, Any], profile: DeviceProfile) -> None:
    validate_json(event, event_schema())
    profile.point(event["point_key"])
    raised = utc_time(event["raised_at"])
    if (event["state"] == "cleared") != (event["cleared_at"] is not None):
        raise ValueError("cleared event needs a clear timestamp")
    if (event["acknowledged_at"] is None) != (event["acknowledged_by"] is None):
        raise ValueError("acknowledgement requires time and actor")
    for key in ("cleared_at", "acknowledged_at"):
        if event[key] is not None and utc_time(event[key]) < raised:
            raise ValueError("event lifecycle cannot precede raise time")


def endpoint_schema() -> dict[str, Any]:
    """Connection metadata with external credential references, never credentials."""
    return object_schema(
        {
            "id": TEXT,
            "protocol": {"enum": list(PROTOCOLS[:5])},
            "address": TEXT,
            "security_profile": TEXT,
            "credential_reference": {"type": ["string", "null"]},
        },
        ("id", "protocol", "address", "security_profile", "credential_reference"),
    )


def binding_schema() -> dict[str, Any]:
    """Concrete read-only deployment bindings; templates remain in the crosswalk."""

    def integer(maximum: int) -> dict[str, Any]:
        return {"type": "integer", "minimum": 0, "maximum": maximum}

    locators = {
        "redfish": object_schema(
            {
                "resource_uri": {"type": "string", "pattern": "^/redfish/"},
                "json_pointer": {"type": "string", "pattern": "^/"},
            },
            ("resource_uri", "json_pointer"),
        ),
        "bacnet": object_schema(
            {
                "device_instance": integer(4194302),
                "object_type": TEXT,
                "object_instance": integer(4194302),
                "property_name": TEXT,
            },
            ("device_instance", "object_type", "object_instance", "property_name"),
        ),
        "snmp": object_schema(
            {"oid": {"type": "string", "pattern": r"^\.?[0-9]+(\.[0-9]+)+$"}}, ("oid",)
        ),
        "modbus": object_schema(
            {
                "unit_id": {"type": "integer", "minimum": 1, "maximum": 247},
                "function_code": {"enum": [3, 4]},
                "address_zero_based": integer(65535),
                "data_type": {"enum": ["int16", "uint16", "int32", "uint32", "float32", "float64"]},
                "word_order": {"enum": ["big", "little"]},
                "byte_order": {"enum": ["big", "little"]},
            },
            (
                "unit_id",
                "function_code",
                "address_zero_based",
                "data_type",
                "word_order",
                "byte_order",
            ),
        ),
        "opcua": object_schema(
            {"namespace_uri": TEXT, "identifier": TEXT, "attribute": {"const": "Value"}},
            ("namespace_uri", "identifier", "attribute"),
        ),
    }
    schema = object_schema(
        {
            "id": TEXT,
            "asset_id": TEXT,
            "point_key": TEXT,
            "endpoint_id": TEXT,
            "protocol": {"enum": list(locators)},
            "locator": {"type": "object"},
            "native_unit": TEXT,
            "scale": {"type": "number", "not": {"const": 0}},
            "offset": {"type": "number"},
            "source_document": TEXT,
            "evidence_kind": {"enum": ["standard", "vendor", "site", "synthetic"]},
            "access": {"const": "read"},
        },
        (
            "id",
            "asset_id",
            "point_key",
            "endpoint_id",
            "protocol",
            "locator",
            "native_unit",
            "scale",
            "offset",
            "source_document",
            "evidence_kind",
            "access",
        ),
    )
    schema["allOf"] = [
        {
            "if": {"properties": {"protocol": {"const": protocol}}},
            "then": {"properties": {"locator": locator}},
        }
        for protocol, locator in locators.items()
    ]
    return schema


def validate_bindings(
    bindings: list[dict[str, Any]],
    endpoints: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    profiles: dict[str, DeviceProfile],
) -> None:
    """Validate resolvable identities and explicit mappings; never probe an endpoint."""
    endpoint_map = {endpoint["id"]: endpoint for endpoint in endpoints}
    asset_map = {asset["id"]: asset for asset in assets}
    if len(endpoint_map) != len(endpoints) or len({b["id"] for b in bindings}) != len(bindings):
        raise ValueError("endpoint and binding IDs must be unique")
    for endpoint in endpoints:
        validate_json(endpoint, endpoint_schema())
    for binding in bindings:
        validate_json(binding, binding_schema())
        if binding["endpoint_id"] not in endpoint_map or binding["asset_id"] not in asset_map:
            raise ValueError("binding references an unknown endpoint or asset")
        if endpoint_map[binding["endpoint_id"]]["protocol"] != binding["protocol"]:
            raise ValueError("binding/endpoint protocol mismatch")
        asset = asset_map[binding["asset_id"]]
        if binding["point_key"] not in asset["supported_points"]:
            raise ValueError("binding requires a commissioned point")
        point = profiles[asset["profile"]].point(binding["point_key"])
        if point.role in {"command", "setpoint"}:
            raise ValueError("read-only bindings cannot execute control definitions")
