"""Quality-aware replay, incident evidence, retention and business-case arithmetic."""

from dataclasses import asdict
from datetime import timedelta
from math import ceil
from typing import Any

from datacenter_simulator.connectors.telemetry import TelemetryHistory, latest_at
from datacenter_simulator.methods.scada import with_freshness
from datacenter_simulator.models.devices import finite
from datacenter_simulator.models.scada import utc_time, validate_plant
from datacenter_simulator.models.scada_catalog import device_profiles
from datacenter_simulator.models.telemetry import (
    ContextHistory,
    StreamBudget,
    TelemetryBusinessCase,
    ThresholdRule,
)


def quality_snapshot(
    history: TelemetryHistory, *, time: str, known_at: str | None = None
) -> list[dict[str, Any]]:
    """Latest samples with catalogue freshness; expose clock and receive-only caveats."""
    profiles = device_profiles()
    result = []
    for record in latest_at(history, time=time, known_at=known_at):
        obs = with_freshness(
            record.observation, profiles[record.profile].point(record.point_key), now=time
        )
        clock_ahead = obs["source_timestamp"] is not None and utc_time(
            obs["source_timestamp"]
        ) > utc_time(obs["received_at"])
        if clock_ahead and obs["quality"] == "good":
            obs.update(
                quality="uncertain", quality_reason="Source clock is ahead of collector time."
            )
        result.append({**record.as_dict(), "observation": obs, "source_clock_ahead": clock_ahead})
    return result


def rollup(history: TelemetryHistory, *, interval_s: int = 60) -> list[dict[str, Any]]:
    """UTC-aligned bins for numeric measurement points only.

    Keep min/max, usable and total counts. Mean is sample-weighted, never an
    energy integral; absent bins are absent. Counters, states and clocks ahead
    of receive time are not silently treated as valid numeric measurements.
    """
    if type(interval_s) is not int or interval_s < 1:
        raise ValueError("interval_s must be a positive integer")
    profiles = device_profiles()
    bins: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in history.records():
        point = profiles[record.profile].point(record.point_key)
        if point.role != "measurement" or point.data_type not in {"number", "integer"}:
            continue
        time = utc_time(record.event_time)
        # Epoch alignment supports intervals which do not divide a day.
        epoch = utc_time("1970-01-01T00:00:00Z")
        delta = time - epoch
        bin_time = epoch + timedelta(seconds=(delta // timedelta(seconds=interval_s)) * interval_s)
        key = (*record.series, bin_time.isoformat())
        row = bins.setdefault(
            key,
            {
                "site_id": record.site_id,
                "asset_id": record.asset_id,
                "point_key": record.point_key,
                "source_system": record.source_system,
                "source_id": record.source_id,
                "bin_start": bin_time.isoformat(),
                "unit": point.unit,
                "total_count": 0,
                "good_count": 0,
                "values": [],
            },
        )
        row["total_count"] += 1
        obs = record.observation
        if obs["quality"] == "good" and time <= utc_time(obs["received_at"]):
            row["values"].append(float(obs["value"]))
            row["good_count"] += 1
    result = []
    for row in bins.values():
        values = row.pop("values")
        row.update(
            minimum=min(values) if values else None,
            maximum=max(values) if values else None,
            mean=sum(values) / len(values) if values else None,
            good_fraction=row["good_count"] / row["total_count"],
        )
        result.append(row)
    return result


def incident_timeline(
    history: TelemetryHistory,
    contexts: ContextHistory,
    rules: list[ThresholdRule],
    *,
    site_id: str,
    start: str,
    end: str,
    known_at: str | None = None,
) -> list[dict[str, Any]]:
    """Observed threshold transitions across sources, not causal diagnosis.

    Missing/bad samples or long gaps break continuity. A subsequent good sample
    is labelled observed, not an inferred onset/clear. Thresholds apply to the
    canonical unit; no cross-source interpolation or extrapolation is performed.
    """
    if utc_time(end) <= utc_time(start):
        raise ValueError("incident window must have positive duration")
    profiles = device_profiles()
    output: list[dict[str, Any]] = []
    for rule in rules:
        previous: bool | None = None
        last_time = None
        for record in history.records():
            if (
                record.site_id,
                record.asset_id,
                record.point_key,
                record.source_system,
                record.source_id,
            ) != (site_id, rule.asset_id, rule.point_key, rule.source_system, rule.source_id):
                continue
            time = utc_time(record.event_time)
            if not utc_time(start) <= time < utc_time(end):
                continue
            if known_at is not None and utc_time(record.observation["received_at"]) > utc_time(
                known_at
            ):
                continue
            point = profiles[record.profile].point(record.point_key)
            if point.role != "measurement" or point.data_type not in {"number", "integer"}:
                raise ValueError("threshold timeline requires numeric measurements")
            if last_time is not None and (time - last_time).total_seconds() > point.stale_after_s:
                previous = None
            last_time = time
            obs = record.observation
            if obs["quality"] != "good" or time > utc_time(obs["received_at"]):
                previous = None
                output.append(
                    dict(
                        time=record.event_time,
                        asset_id=record.asset_id,
                        point_key=record.point_key,
                        state="data_gap",
                        source_system=record.source_system,
                        source_id=record.source_id,
                        quality=obs["quality"],
                    )
                )
                continue
            active = (
                obs["value"] > rule.threshold
                if rule.direction == "above"
                else obs["value"] < rule.threshold
            )
            if previous is None or active != previous:
                context = contexts.at(site_id, record.asset_id, record.event_time)
                output.append(
                    dict(
                        time=record.event_time,
                        asset_id=record.asset_id,
                        point_key=record.point_key,
                        state=("active_observed" if active else "normal_observed")
                        if previous is None
                        else ("threshold_crossed" if active else "returned_normal"),
                        value=obs["value"],
                        unit=obs["unit"],
                        threshold=rule.threshold,
                        source_system=record.source_system,
                        source_id=record.source_id,
                        owner=context.owner if context else None,
                        timestamp_basis="source" if obs["source_timestamp"] else "receive",
                    )
                )
            previous = active
    return sorted(output, key=lambda row: (row["time"], row["asset_id"], row["point_key"]))


def potentially_affected_assets(
    assets: list[dict[str, Any]], relationships: list[dict[str, str]], origin: str
) -> list[str]:
    """Forward reachability through supply links and containment at one snapshot.

    Reachability indicates dependency exposure, not proven service loss; redundant
    supplies and protective actions may prevent impact. Monitoring/control/network
    links do not propagate a cooling or electrical disturbance here.
    """
    validate_plant(assets, relationships, device_profiles())
    if origin not in {asset["id"] for asset in assets}:
        raise ValueError("unknown origin asset")
    edges = [(a["parent_id"], a["id"]) for a in assets if a["parent_id"] is not None]
    edges += [
        (r["source"], r["target"])
        for r in relationships
        if r["kind"] in {"electrical_feed", "cooling_supply"}
    ]
    seen, pending = {origin}, [origin]
    while pending:
        current = pending.pop()
        for source, target in edges:
            if source == current and target not in seen:
                seen.add(target)
                pending.append(target)
    return sorted(seen - {origin})


def capacity_plan(
    streams: list[StreamBudget], *, outage_s: float, buffer_observations: int
) -> dict[str, float]:
    """Steady-rate payload/storage estimate; raw and rollup retention coexist.

    Assumed bytes include caller-selected compression/index overhead. No server
    throughput guarantee, product license quote or durable-queue implementation.
    Buffer is empty at outage start; normal ingestion continues during recovery.
    """
    finite("outage_s", outage_s)
    if type(buffer_observations) is not int or buffer_observations < 0:
        raise ValueError("buffer_observations must be a nonnegative integer")
    rate = sum(s.series_count / s.interval_s for s in streams)
    raw = sum(
        s.series_count
        / s.interval_s
        * 86400
        * s.raw_retention_days
        * s.bytes_per_observation
        * s.replication_factor
        for s in streams
    )
    aggregate = sum(
        s.series_count
        / s.aggregate_interval_s
        * 86400
        * s.aggregate_retention_days
        * s.bytes_per_aggregate
        * s.replication_factor
        for s in streams
    )
    required = ceil(rate * outage_s)
    return dict(
        observations_per_second=rate,
        estimated_ingress_bytes_per_second=sum(
            s.series_count / s.interval_s * s.bytes_per_observation for s in streams
        ),
        raw_storage_gb=raw / 1e9,
        aggregate_storage_gb=aggregate / 1e9,
        total_storage_gb=(raw + aggregate) / 1e9,
        required_buffer_observations=required,
        expected_dropped_observations=max(0, required - buffer_observations),
        buffered_observations=min(required, buffer_observations),
    )


def drain_time_s(backlog: float, *, ingest_rate: float, write_rate: float) -> float | None:
    """Time to drain while new data arrives; None means backlog cannot shrink."""
    for key, value in (
        ("backlog", backlog),
        ("ingest_rate", ingest_rate),
        ("write_rate", write_rate),
    ):
        finite(key, value)
    if backlog == 0:
        return 0.0
    return backlog / (write_rate - ingest_rate) if write_rate > ingest_rate else None


def evaluate_business_case(case: TelemetryBusinessCase) -> dict[str, Any]:
    """Transparent scenario arithmetic; no claimed measured ROI or failure prevention."""
    hours = (
        case.incidents_per_year * (case.baseline_triage_minutes - case.unified_triage_minutes) / 60
    )
    labor = hours * case.responders * case.labor_cost_per_hour
    downtime = hours * case.downtime_realization_fraction * case.downtime_value_per_hour
    energy = case.energy_saving_kwh_per_year * case.energy_price_per_kwh
    gross = labor + downtime + energy
    net = gross - case.annual_operating_cost
    npv = -case.implementation_cost + sum(
        net / (1 + case.discount_rate) ** year for year in range(1, case.horizon_years + 1)
    )
    # Energy savings are independent of incident count.
    incident_value = (
        (case.baseline_triage_minutes - case.unified_triage_minutes)
        / 60
        * (
            case.responders * case.labor_cost_per_hour
            + case.downtime_realization_fraction * case.downtime_value_per_hour
        )
    )
    return dict(
        assumptions=asdict(case),
        saved_triage_hours_per_year=hours,
        labor_saving_per_year=labor,
        assumed_avoided_downtime_value_per_year=downtime,
        assumed_energy_saving_per_year=energy,
        gross_benefit_per_year=gross,
        net_benefit_per_year=net,
        npv=npv,
        simple_payback_years=case.implementation_cost / net if net > 0 else None,
        operating_break_even_incidents_per_year=max(0, case.annual_operating_cost - energy)
        / incident_value
        if incident_value > 0
        else (0 if energy >= case.annual_operating_cost else None),
    )
