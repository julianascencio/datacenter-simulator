"""Vendor-neutral operational telemetry contracts, reusing the SCADA catalogue.

These are project engineering contracts, not schemas published by InfluxData.
DCIM exports remain authoritative for identity, ownership and topology.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from math import isfinite
from re import search
from typing import Any

from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.scada import (
    DeviceProfile,
    object_schema,
    observation_schema,
    utc_time,
    validate_json,
)
from datacenter_simulator.models.scada_catalog import device_profiles

SYSTEMS = ("BMS", "EPMS", "DCIM", "IT")


@lru_cache(maxsize=1)
def _profiles() -> dict[str, DeviceProfile]:
    return device_profiles()


def stamp(value: str) -> str:
    """Normalize aware timestamps to UTC at Python datetime microsecond resolution."""
    if search(r"[.,]\d{7,}", value):
        raise ValueError("sub-microsecond timestamps are not supported; do not silently truncate")
    return utc_time(value).astimezone(UTC).isoformat()


def text_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("identity must be nonempty text without control characters")


@dataclass(frozen=True)
class AssetContext:
    """Half-open validity interval [valid_from, valid_to) from a DCIM export.

    Asset IDs are scoped to site. Supply relationships live in a separately
    versioned SCADA plant snapshot, not in the ownership history.
    """

    site_id: str
    asset_id: str
    profile: str
    valid_from: str
    valid_to: str | None = None
    owner: str | None = None
    rack_id: str | None = None
    source_reference: str = "synthetic DCIM export"

    def __post_init__(self) -> None:
        for value in (self.site_id, self.asset_id, self.source_reference):
            text_id(value)
        for optional_value in (self.owner, self.rack_id):
            if optional_value is not None:
                text_id(optional_value)
        if self.profile not in _profiles():
            raise ValueError("unknown device profile")
        object.__setattr__(self, "valid_from", stamp(self.valid_from))
        if self.valid_to is not None:
            object.__setattr__(self, "valid_to", stamp(self.valid_to))
            if utc_time(self.valid_to) <= utc_time(self.valid_from):
                raise ValueError("context interval must have positive duration")


class ContextHistory:
    """Time-valid context join; gaps stay unknown and overlapping versions fail."""

    def __init__(self, contexts: list[AssetContext]) -> None:
        self.contexts = tuple(contexts)
        groups: dict[tuple[str, str], list[AssetContext]] = {}
        for item in contexts:
            groups.setdefault((item.site_id, item.asset_id), []).append(item)
        for versions in groups.values():
            versions.sort(key=lambda c: utc_time(c.valid_from))
            for previous, current in zip(versions, versions[1:], strict=False):
                if previous.valid_to is None or utc_time(previous.valid_to) > utc_time(
                    current.valid_from
                ):
                    raise ValueError("overlapping DCIM context versions")

    def at(self, site_id: str, asset_id: str, timestamp: str) -> AssetContext | None:
        time = utc_time(timestamp)
        return next(
            (
                item
                for item in self.contexts
                if (item.site_id, item.asset_id) == (site_id, asset_id)
                and utc_time(item.valid_from) <= time
                and (item.valid_to is None or time < utc_time(item.valid_to))
            ),
            None,
        )


@dataclass(frozen=True)
class TelemetryRecord:
    """One numeric, boolean or textual observation plus its facility provenance.

    Source time is preferred; receive-only observations retain that limitation.
    There is deliberately no mutable latest-value slot or actuator interface.
    """

    site_id: str
    asset_id: str
    profile: str
    point_key: str
    source_system: str
    source_id: str
    observation: dict[str, Any]
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported telemetry schema version")
        for value in (self.site_id, self.asset_id, self.source_id):
            text_id(value)
        if self.source_system not in SYSTEMS:
            raise ValueError("unknown source system")
        profile = _profiles().get(self.profile)
        if profile is None:
            raise ValueError("unknown profile")
        point = profile.point(self.point_key)
        if point.role in {"command", "setpoint"}:
            raise ValueError("telemetry cannot contain control intents")
        validate_json(self.observation, observation_schema(point))
        obs = dict(self.observation)
        obs["received_at"] = stamp(obs["received_at"])
        if obs["source_timestamp"] is not None:
            obs["source_timestamp"] = stamp(obs["source_timestamp"])
        object.__setattr__(self, "observation", obs)

    @property
    def event_time(self) -> str:
        return str(self.observation["source_timestamp"] or self.observation["received_at"])

    @property
    def series(self) -> tuple[str, str, str, str, str]:
        return self.site_id, self.asset_id, self.point_key, self.source_system, self.source_id

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def telemetry_schema(profile: DeviceProfile) -> dict[str, Any]:
    """JSON Schema for a history record with a point-dependent SCADA observation."""
    text = {"type": "string", "minLength": 1}
    fields = dict(
        site_id=text,
        asset_id=text,
        profile={"const": profile.key},
        point_key=text,
        source_system={"enum": list(SYSTEMS)},
        source_id=text,
        observation={"type": "object"},
        schema_version={"const": "1.0.0"},
    )
    result = object_schema(fields, tuple(fields))
    result.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"urn:asva:datacenter:telemetry:1.0.0:{profile.key}",
            "oneOf": [
                {
                    "properties": {
                        "point_key": {"const": point.key},
                        "observation": observation_schema(point),
                    }
                }
                for point in profile.points
                if point.role not in {"command", "setpoint"}
            ],
        }
    )
    return result


@dataclass(frozen=True)
class CollectorChannel:
    """Synthetic sensor/collector device model with a commissioned sampling period.

    Clock offset affects source time; transport delay affects receive time.
    This emulates observation behavior, not the physical sensor's calibration.
    """

    asset_id: str
    profile: str
    point_key: str
    source_system: str
    source_id: str
    poll_interval_s: int = 5
    transport_delay_s: float = 1
    clock_offset_s: float = 0

    def __post_init__(self) -> None:
        for value in (self.asset_id, self.source_id):
            text_id(value)
        if self.profile not in _profiles():
            raise ValueError("unknown profile")
        point = _profiles()[self.profile].point(self.point_key)
        if point.role in {"command", "setpoint"} or self.source_system not in SYSTEMS:
            raise ValueError("channel must observe a known source and point")
        if type(self.poll_interval_s) is not int or self.poll_interval_s < 1:
            raise ValueError("poll_interval_s must be a positive integer")
        finite("transport_delay_s", self.transport_delay_s)
        if not isfinite(self.clock_offset_s):
            raise ValueError("clock offset must be finite")


@dataclass(frozen=True)
class StreamBudget:
    """Scalar-observation planning assumptions, not a database benchmark."""

    series_count: int
    interval_s: float
    bytes_per_observation: float
    raw_retention_days: float
    aggregate_interval_s: float
    aggregate_retention_days: float
    bytes_per_aggregate: float
    replication_factor: int = 1

    def __post_init__(self) -> None:
        for name in ("series_count", "replication_factor"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "interval_s",
            "bytes_per_observation",
            "aggregate_interval_s",
            "bytes_per_aggregate",
        ):
            finite(name, getattr(self, name), strict=True)
        for name in ("raw_retention_days", "aggregate_retention_days"):
            finite(name, getattr(self, name))
        if self.aggregate_interval_s < self.interval_s:
            raise ValueError("aggregation interval cannot be finer than source sampling")


@dataclass(frozen=True)
class TelemetryBusinessCase:
    """Single-currency, constant annual cash-flow scenario with explicit assumptions.

    Faster diagnosis does not imply avoided downtime. The realization fraction
    expresses the assumed fraction of saved triage time that reduces downtime.
    Labor and downtime value must cover disjoint costs to avoid double counting.
    """

    incidents_per_year: float = 12
    baseline_triage_minutes: float = 90
    unified_triage_minutes: float = 30
    responders: int = 2
    labor_cost_per_hour: float = 80
    downtime_value_per_hour: float = 5000
    downtime_realization_fraction: float = 0
    energy_saving_kwh_per_year: float = 0
    energy_price_per_kwh: float = 0.15
    implementation_cost: float = 40000
    annual_operating_cost: float = 12000
    horizon_years: int = 5
    discount_rate: float = 0.08
    currency: str = "EUR"

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if isinstance(value, (int, float)):
                finite(key, value)
        for key in ("responders", "horizon_years"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f"{key} must be a positive integer")
        fraction("downtime_realization_fraction", self.downtime_realization_fraction)
        if self.unified_triage_minutes > self.baseline_triage_minutes:
            raise ValueError("unified triage cannot exceed baseline in this savings model")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter code; no FX conversion is performed")


@dataclass(frozen=True)
class ThresholdRule:
    """Site-selected numeric threshold, not a vendor or standards limit."""

    asset_id: str
    point_key: str
    source_system: str
    source_id: str
    threshold: float
    direction: str = "above"

    def __post_init__(self) -> None:
        for value in (self.asset_id, self.point_key, self.source_id):
            text_id(value)
        if self.source_system not in SYSTEMS or self.direction not in {"above", "below"}:
            raise ValueError("invalid threshold source or direction")
        if not isfinite(self.threshold):
            raise ValueError("threshold must be finite")


def epoch_nanoseconds(timestamp: str) -> int:
    """Integer conversion avoids floating epoch precision loss; input resolution is us."""
    delta = utc_time(stamp(timestamp)) - datetime(1970, 1, 1, tzinfo=UTC)
    return ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000
