"""Offline unified history, JSONL replay and InfluxDB line-protocol export.

No service credentials, network clients or protocol writes are required.
"""

import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

from datacenter_simulator.connectors.scada import normalize_sample
from datacenter_simulator.models.scada import utc_time
from datacenter_simulator.models.scada_catalog import device_profiles
from datacenter_simulator.models.telemetry import (
    CollectorChannel,
    ContextHistory,
    TelemetryRecord,
    epoch_nanoseconds,
)


def sample_channel(
    channel: CollectorChannel,
    values: list[Any],
    *,
    site_id: str,
    start: str,
    missing_seconds: tuple[int, ...] = (),
) -> list[TelemetryRecord]:
    """Sample a one-second synthetic trace, preserving missing values and two clocks."""
    point = device_profiles()[channel.profile].point(channel.point_key)
    begin = utc_time(start)
    output = []
    for second in range(0, len(values), channel.poll_interval_s):
        missing = second in missing_seconds
        source_time = begin + timedelta(seconds=second + channel.clock_offset_s)
        received = begin + timedelta(seconds=second + channel.transport_delay_s)
        obs = normalize_sample(
            point,
            None if missing else values[second],
            native_unit=point.unit,
            source_timestamp=source_time.isoformat(),
            received_at=received.isoformat(),
            protocol="simulator",
            address=f"synthetic/{channel.asset_id}/{channel.point_key}",
            quality="missing" if missing else "good",
            reason="Synthetic collector channel.",
        )
        output.append(
            TelemetryRecord(
                site_id,
                channel.asset_id,
                channel.profile,
                channel.point_key,
                channel.source_system,
                channel.source_id,
                obs,
            )
        )
    return output


class TelemetryHistory:
    """Append-only semantic history with strict duplicate conflict detection.

    Identity includes site, asset, point, source system, source ID and event time.
    Equivalent replays are ignored. Conflicting payloads at the same identity
    raise instead of relying on a database's overwrite order. Different sources
    remain separate series; reconciliation requires an explicit source choice.
    """

    def __init__(self, records: list[TelemetryRecord] | None = None) -> None:
        self._records: dict[tuple[str, ...], TelemetryRecord] = {}
        for record in records or []:
            self.append(record)

    def append(self, record: TelemetryRecord) -> bool:
        # Revalidate copies, because a frozen dataclass can still contain a mutable dict.
        record = TelemetryRecord(**deepcopy(record.as_dict()))
        key = (*record.series, record.event_time)
        previous = self._records.get(key)
        if previous is not None:
            if previous.as_dict() != record.as_dict():
                raise ValueError(f"conflicting duplicate telemetry: {key}")
            return False
        self._records[key] = record
        return True

    def records(self) -> list[TelemetryRecord]:
        return deepcopy(sorted(self._records.values(), key=lambda r: (r.event_time, r.series)))

    def frame(self, contexts: ContextHistory | None = None) -> list[dict[str, Any]]:
        """Flat rows suitable for CSV/Parquet without dropping provenance or nulls."""
        result = []
        for record in self.records():
            context = (
                contexts.at(record.site_id, record.asset_id, record.event_time)
                if contexts
                else None
            )
            if context is not None and context.profile != record.profile:
                raise ValueError("observation profile disagrees with time-valid DCIM context")
            result.append(
                {
                    **{k: v for k, v in record.as_dict().items() if k != "observation"},
                    **record.observation,
                    "event_time": record.event_time,
                    "timestamp_basis": "source"
                    if record.observation["source_timestamp"]
                    else "receive",
                    "owner": context.owner if context else None,
                    "rack_id": context.rack_id if context else None,
                    "context_status": "matched" if context else "unknown",
                }
            )
        return result

    def write_jsonl(self, path: str | Path) -> None:
        Path(path).write_text(
            "".join(json.dumps(r.as_dict(), allow_nan=False) + "\n" for r in self.records()),
            encoding="utf-8",
        )

    @classmethod
    def read_jsonl(cls, path: str | Path) -> "TelemetryHistory":
        return cls(
            [
                TelemetryRecord(**json.loads(line))
                for line in Path(path).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        )


def _tag(value: str) -> str:
    if any(c in value for c in "\r\n\\"):
        raise ValueError(
            "line-protocol tags cannot contain newlines or backslashes in this exporter"
        )
    return value.replace(",", r"\,").replace(" ", r"\ ").replace("=", r"\=")


def _string(value: str) -> str:
    if any(c in value for c in "\r\n"):
        raise ValueError("line protocol cannot encode newline characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def line_protocol(history: TelemetryHistory) -> str:
    """Render one point per observation; numeric/bool/text fields have stable types.

    The point key is a tag, so a temperature and power reading never collide.
    Bad/missing samples retain quality and omit the value field if null. Owner
    and raw protocol payloads stay in the canonical JSONL, not in series tags.
    The history must be reconciled across batches before database ingestion.
    """
    lines = []
    profiles = device_profiles()
    for record in history.records():
        obs = record.observation
        tags = dict(zip(("site", "asset", "point", "system", "source"), record.series, strict=True))
        fields = [
            f"unit={_string(obs['unit'])}",
            f"quality={_string(obs['quality'])}",
            f"profile={_string(record.profile)}",
            f"received_at_ns={epoch_nanoseconds(obs['received_at'])}i",
            f"timestamp_basis={_string('source' if obs['source_timestamp'] else 'receive')}",
        ]
        value = obs["value"]
        if isinstance(value, bool):
            fields.append(f"value_bool={str(value).lower()}")
        elif (
            isinstance(value, int)
            and profiles[record.profile].point(record.point_key).data_type == "integer"
        ):
            if not -(2**63) <= value < 2**63:
                raise ValueError("integer exceeds line-protocol signed 64-bit range")
            fields.append(f"value_int={value}i")
        elif isinstance(value, (int, float)):
            fields.append(f"value_float={float(value)!r}")
        elif isinstance(value, str):
            fields.append(f"value_text={_string(value)}")
        timestamp = epoch_nanoseconds(record.event_time)
        received = epoch_nanoseconds(obs["received_at"])
        if not -(2**63) + 2 <= timestamp <= 2**63 - 2 or not -(2**63) <= received < 2**63:
            raise ValueError("timestamp exceeds line-protocol range")
        lines.append(
            "facility_telemetry,"
            + ",".join(f"{k}={_tag(v)}" for k, v in tags.items())
            + " "
            + ",".join(fields)
            + f" {timestamp}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def latest_at(
    history: TelemetryHistory, *, time: str, known_at: str | None = None
) -> list[TelemetryRecord]:
    """Backward-only event-time snapshot with optional receive-time cutoff.

    Quality is not filtered: a newer missing sample must not resurrect an older
    good reading. Use quality_snapshot to apply freshness rules afterwards.
    """
    result: dict[tuple[str, ...], TelemetryRecord] = {}
    for record in history.records():
        if utc_time(record.event_time) > utc_time(time):
            continue
        if known_at is not None and utc_time(record.observation["received_at"]) > utc_time(
            known_at
        ):
            continue
        result[record.series] = record
    return list(result.values())
