"""Behavioral checks for data integrity, incident boundaries and model balances."""

import json
from dataclasses import replace

import numpy as np
import pytest
from jsonschema import ValidationError

from datacenter_simulator.analysis.telemetry import (
    SCENARIOS,
    START,
    example_plant,
    export_telemetry_study,
    incident_study,
    sampling_comparison,
)
from datacenter_simulator.connectors.scada import normalize_sample
from datacenter_simulator.connectors.telemetry import (
    TelemetryHistory,
    latest_at,
    line_protocol,
    sample_channel,
)
from datacenter_simulator.methods.telemetry import (
    capacity_plan,
    drain_time_s,
    evaluate_business_case,
    incident_timeline,
    potentially_affected_assets,
    quality_snapshot,
    rollup,
)
from datacenter_simulator.models.scada import validate_json, validate_plant
from datacenter_simulator.models.scada_catalog import device_profiles
from datacenter_simulator.models.telemetry import (
    AssetContext,
    CollectorChannel,
    ContextHistory,
    StreamBudget,
    TelemetryBusinessCase,
    TelemetryRecord,
    ThresholdRule,
    epoch_nanoseconds,
    telemetry_schema,
)


def record(value=60.0, *, second=0, quality="good", received_at=None, source_time=True):
    timestamp = f"2026-01-01T00:00:{second:02d}+00:00"
    point = device_profiles()["rack"].point("active_power_kw")
    return TelemetryRecord(
        "site",
        "rack",
        "rack",
        point.key,
        "EPMS",
        "epms-1",
        normalize_sample(
            point,
            value,
            native_unit="kW",
            protocol="simulator",
            address="rack",
            received_at=received_at or timestamp,
            source_timestamp=timestamp if source_time else None,
            quality=quality,
        ),
    )


def test_units_schema_and_command_boundary():
    point = device_profiles()["rack"].point("active_power_kw")
    obs = normalize_sample(
        point,
        60000,
        native_unit="W",
        protocol="simulator",
        address="meter",
        received_at=START,
        source_timestamp=START,
    )
    sample = replace(record(), observation=obs)
    assert sample.observation["value"] == 60
    validate_json(sample.as_dict(), telemetry_schema(device_profiles()["rack"]))
    with pytest.raises(ValueError, match="control"):
        replace(sample, profile="server", point_key="power_limit_kw")
    with pytest.raises(ValidationError):
        validate_json(
            {**sample.as_dict(), "point_key": "invented"},
            telemetry_schema(device_profiles()["rack"]),
        )
    with pytest.raises((ValueError, ValidationError)):
        replace(sample, observation={**obs, "received_at": "2026-01-01T00:00:00"})


def test_duplicates_do_not_silently_overwrite_and_copies_are_isolated():
    first = record()
    history = TelemetryHistory([first])
    assert not history.append(first)
    with pytest.raises(ValueError, match="conflicting duplicate"):
        history.append(record(80.0))
    first.observation["value"] = 999
    returned = history.records()
    returned[0].observation["value"] = -1
    assert history.records()[0].observation["value"] == 60
    assert history.append(replace(record(80), source_id="other-meter"))
    assert history.append(replace(record(80), site_id="second-site"))


def test_history_replay_and_receive_cutoff(tmp_path):
    early = record(60, second=1)
    late = record(70, second=2, received_at="2026-01-01T00:01:00Z")
    future = record(90, second=50)
    history = TelemetryHistory([future, late, early])
    path = tmp_path / "records.jsonl"
    history.write_jsonl(path)
    restored = TelemetryHistory.read_jsonl(path)
    assert restored.records() == history.records()
    assert latest_at(restored, time="2026-01-01T00:00:10Z")[0].observation["value"] == 70
    observed = latest_at(restored, time="2026-01-01T00:00:10Z", known_at="2026-01-01T00:00:10Z")
    assert observed[0].observation["value"] == 60


def test_context_half_open_intervals_and_site_scoping():
    a = AssetContext("site", "rack", "rack", START, "2026-01-01T00:01:00Z", "old")
    b = AssetContext("site", "rack", "rack", "2026-01-01T00:01:00Z", owner="new")
    history = ContextHistory([b, a])
    assert history.at("site", "rack", START).owner == "old"
    assert history.at("site", "rack", "2026-01-01T00:01:00Z").owner == "new"
    assert history.at("other-site", "rack", START) is None
    assert history.at("site", "rack", "2025-12-31T23:59:59Z") is None
    with pytest.raises(ValueError, match="overlapping"):
        ContextHistory([a, replace(b, valid_from=START)])
    rows = TelemetryHistory([record()]).frame(history)
    assert rows[0]["owner"] == "old"
    assert rows[0]["context_status"] == "matched"


def test_equivalent_timezones_deduplicate_and_integer_epoch_precision():
    sample = record()
    obs = dict(
        sample.observation,
        received_at="2026-01-01T01:00:00+01:00",
        source_timestamp="2026-01-01T01:00:00+01:00",
    )
    assert not TelemetryHistory([sample]).append(replace(sample, observation=obs))
    assert epoch_nanoseconds("1970-01-01T00:00:00.000001Z") == 1000
    with pytest.raises(ValueError, match="sub-microsecond"):
        epoch_nanoseconds("2026-01-01T00:00:00.123456789Z")


def test_missing_does_not_resurrect_old_good_data_and_stale_is_not_zero():
    history = TelemetryHistory([record(60), record(None, second=10, quality="missing")])
    snapshot = quality_snapshot(history, time="2026-01-01T00:00:20Z")
    assert snapshot[0]["observation"]["quality"] == "missing"
    assert snapshot[0]["observation"]["value"] is None
    old = quality_snapshot(TelemetryHistory([record(60)]), time="2026-01-02T00:00:00Z")
    assert old[0]["observation"]["quality"] == "stale"
    assert old[0]["observation"]["value"] == 60


def test_future_clock_flag_and_receive_only_basis():
    skew = record(60, second=10, received_at=START)
    snapshot = quality_snapshot(TelemetryHistory([skew]), time="2026-01-01T00:00:20Z")
    assert snapshot[0]["source_clock_ahead"]
    assert snapshot[0]["observation"]["quality"] == "uncertain"
    assert TelemetryHistory([record(source_time=False)]).frame()[0]["timestamp_basis"] == "receive"


def test_rollups_preserve_peaks_quality_counts_and_unknown_bins():
    history = TelemetryHistory(
        [
            record(60),
            record(100, second=5),
            record(1000, second=10, quality="bad"),
            record(None, second=15, quality="missing"),
        ]
    )
    rows = rollup(history, interval_s=60)
    assert len(rows) == 1
    assert rows[0]["maximum"] == 100
    assert rows[0]["mean"] == 80
    assert rows[0]["good_count"] == 2
    assert rows[0]["total_count"] == 4
    assert rows[0]["good_fraction"] == 0.5
    assert rollup(TelemetryHistory([record(None, quality="missing")]))[0]["mean"] is None


def test_incident_gap_breaks_continuity_and_excludes_future_arrivals():
    history = TelemetryHistory(
        [
            record(60),
            record(100, second=5),
            record(None, second=10, quality="missing"),
            record(60, second=15),
            record(100, second=20, received_at="2026-01-02T00:00:00Z"),
        ]
    )
    rules = [ThresholdRule("rack", "active_power_kw", "EPMS", "epms-1", 90)]
    rows = incident_timeline(
        history,
        ContextHistory([]),
        rules,
        site_id="site",
        start=START,
        end="2026-01-01T00:01:00Z",
        known_at="2026-01-01T00:01:00Z",
    )
    assert [row["state"] for row in rows] == [
        "normal_observed",
        "threshold_crossed",
        "data_gap",
        "normal_observed",
    ]


def test_topology_reachability_excludes_monitoring_and_terminates_on_loops():
    assets, links, _ = example_plant()
    assert potentially_affected_assets(assets, links, "pump") == ["cdu", "rack", "server"]
    links += [dict(source="server", target="pump", kind="monitors")]
    assert potentially_affected_assets(assets, links, "server") == []
    links += [dict(source="rack", target="pump", kind="cooling_supply")]
    assert potentially_affected_assets(assets, links, "pump") == ["cdu", "rack", "server"]
    with pytest.raises(ValueError, match="unknown origin"):
        potentially_affected_assets(assets, links, "invented")


def test_line_protocol_escaping_typed_values_and_nulls():
    sample = replace(record(60), site_id="site north,a=b")
    line = line_protocol(TelemetryHistory([sample]))
    assert r"site=site\ north\,a\=b" in line
    assert "value_float=60.0" in line
    missing = line_protocol(TelemetryHistory([record(None, quality="missing")]))
    assert 'quality="missing"' in missing and "value_float=" not in missing
    assert "nan" not in missing.lower()
    with pytest.raises(ValueError):
        replace(sample, site_id="site\ninjection")


def test_collector_sampling_clock_transport_and_missing():
    channel = CollectorChannel("rack", "rack", "active_power_kw", "EPMS", "epms", 5, 2, -1)
    records = sample_channel(
        channel, [60.0] * 12, site_id="site", start=START, missing_seconds=(5,)
    )
    assert len(records) == 3
    assert records[0].event_time == "2025-12-31T23:59:59+00:00"
    assert records[0].observation["received_at"] == "2026-01-01T00:00:02+00:00"
    assert records[1].observation["quality"] == "missing"
    assert records[1].observation["value"] is None
    rows = sampling_comparison()
    assert rows[0]["observed_max_kw"] == 100
    assert rows[-1]["observed_max_kw"] == 60


def test_capacity_plan_units_buffer_boundary_and_recovery():
    budget = StreamBudget(10, 2, 100, 1, 60, 1, 200, 2)
    result = capacity_plan([budget], outage_s=10, buffer_observations=50)
    assert result["observations_per_second"] == 5
    assert result["raw_storage_gb"] == pytest.approx(5 * 86400 * 100 * 2 / 1e9)
    assert result["aggregate_storage_gb"] == pytest.approx(10 / 60 * 86400 * 200 * 2 / 1e9)
    assert result["expected_dropped_observations"] == 0
    assert (
        capacity_plan([budget], outage_s=11, buffer_observations=50)[
            "expected_dropped_observations"
        ]
        == 5
    )
    assert drain_time_s(50, ingest_rate=5, write_rate=10) == 10
    assert drain_time_s(50, ingest_rate=5, write_rate=5) is None
    assert drain_time_s(0, ingest_rate=5, write_rate=0) == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(interval_s=0),
        dict(series_count=0),
        dict(bytes_per_observation=float("nan")),
        dict(aggregate_interval_s=0.5),
        dict(replication_factor=0),
    ],
)
def test_invalid_capacity_inputs(kwargs):
    with pytest.raises(ValueError):
        StreamBudget(
            **{
                **dict(
                    series_count=10,
                    interval_s=1,
                    bytes_per_observation=100,
                    raw_retention_days=1,
                    aggregate_interval_s=60,
                    aggregate_retention_days=365,
                    bytes_per_aggregate=160,
                ),
                **kwargs,
            }
        )


def test_cash_flow_against_hand_calculation_and_downside():
    case = TelemetryBusinessCase(
        incidents_per_year=10,
        baseline_triage_minutes=120,
        unified_triage_minutes=60,
        responders=2,
        labor_cost_per_hour=50,
        downtime_value_per_hour=1000,
        downtime_realization_fraction=0.5,
        implementation_cost=10000,
        annual_operating_cost=1000,
        horizon_years=2,
        discount_rate=0,
    )
    result = evaluate_business_case(case)
    assert result["labor_saving_per_year"] == 1000
    assert result["assumed_avoided_downtime_value_per_year"] == 5000
    assert result["net_benefit_per_year"] == 5000
    assert result["npv"] == 0
    assert result["simple_payback_years"] == 2
    downside = evaluate_business_case(TelemetryBusinessCase())
    assert downside["npv"] < 0
    assert downside["simple_payback_years"] is None
    assert downside["assumed_avoided_downtime_value_per_year"] == 0


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_incident_scenarios_balance_and_expected_signals(scenario):
    study = incident_study(scenario)
    validate_plant(study["assets"], study["relationships"], device_profiles())
    trace = study["traces"]
    assert np.allclose(trace.facility_power_kw, trace.rack_power_kw + trace.cooling_power_kw)
    # Analytic conservation for the zero-conductance lumped thermal zone, one-second steps.
    assert np.allclose(
        np.diff(trace.inlet_temperature_c) * 500,
        (trace.rack_power_kw - trace.removed_heat_kw).to_numpy()[:-1],
    )
    crossings = [row for row in study["timeline"] if row["state"] == "threshold_crossed"]
    if scenario == "cooling_failure":
        assert [row["asset_id"] for row in crossings] == ["pump", "rack"]
        assert trace.inlet_temperature_c.max() > 28
    elif scenario == "workload_step":
        assert [row["point_key"] for row in crossings] == ["active_power_kw"]
        assert trace.inlet_temperature_c.max() == 24
    else:
        assert [row["asset_id"] for row in crossings] == ["utility"]
        assert trace.rack_power_kw.min() == trace.rack_power_kw.max()
        assert "battery" in set(trace.ups_source)


def test_export_replays_all_sources_and_contains_provenance(tmp_path):
    result = export_telemetry_study(tmp_path)
    assert len(result["scenarios"]) == 3
    assert len(list((tmp_path / "schemas").glob("*.json"))) == len(device_profiles())
    assert len(result["economics"]) == 9
    for scenario in SCENARIOS:
        history = TelemetryHistory.read_jsonl(tmp_path / scenario / "telemetry.jsonl")
        assert {r.source_system for r in history.records()} == {"BMS", "EPMS", "DCIM"}
        assert (tmp_path / scenario / "telemetry.lp").read_text() == line_protocol(history)
        manifest = json.loads((tmp_path / scenario / "incident.json").read_text())
        contexts = ContextHistory([AssetContext(**c) for c in manifest["contexts"]])
        rules = [ThresholdRule(**r) for r in manifest["rules"]]
        replayed = incident_timeline(
            history, contexts, rules, site_id="demo-site", start=START, end="2026-01-01T00:03:00Z"
        )
        assert replayed == manifest["timeline"]
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["sources"][0]["available_pages"] == [1, 2, 3, 4]
    html = (tmp_path / "telemetry.html").read_text()
    assert "cdn.plot.ly" not in html.split("plotly.js v")[0]
    assert "Five-year NPV" in html
