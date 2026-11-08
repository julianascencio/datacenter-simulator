"""SCADA contract, protocol unit/quality, topology and reproducibility verification."""

import json
import struct
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from datacenter_simulator.analysis.scada import TIMESTAMP, export_scada_model, scada_example
from datacenter_simulator.connectors.scada import (
    RegisterBinding,
    bacnet_sample,
    modbus_sample,
    normalize_sample,
    opcua_sample,
    redfish_sensor,
    snmp_entity_sensor,
    snmp_ups_samples,
)
from datacenter_simulator.methods.scada import (
    apply_observation,
    commissioning_crosswalk,
    counter_delta,
    describe_control_intent,
    empty_asset,
    standards_evidence,
    with_freshness,
)
from datacenter_simulator.models.scada import (
    asset_schema,
    binding_schema,
    endpoint_schema,
    event_schema,
    validate_bindings,
    validate_event,
    validate_json,
    validate_plant,
)
from datacenter_simulator.models.scada_catalog import device_profiles


@pytest.fixture(scope="module")
def profiles():
    return device_profiles()


def sample(point, value, **kwargs):
    args = dict(native_unit=point.unit, received_at=TIMESTAMP, protocol="manual", address="fixture")
    args.update(kwargs)
    return normalize_sample(point, value, **args)


def test_catalogue_covers_each_infrastructure_and_it_device(profiles):
    assert {
        "server",
        "gpu",
        "cpu",
        "memory",
        "drive",
        "storage",
        "network_switch",
        "network_port",
        "rack",
        "rack_pdu",
        "floor_pdu",
        "pdu_outlet",
        "power_supply",
        "power_meter",
        "ups",
        "battery_bank",
        "battery_module",
        "generator",
        "ats",
        "sts",
        "switchgear",
        "transformer",
        "circuit_breaker",
        "protection_relay",
        "grid_connection",
        "chiller",
        "cooling_tower",
        "crac",
        "crah",
        "cdu",
        "pump",
        "fan",
        "valve",
        "heat_exchanger",
        "cooling_loop",
        "immersion_tank",
        "leak_detector",
        "environment_sensor",
        "fire_panel",
        "access_controller",
    } <= profiles.keys()
    assert len(profiles) == 50
    for profile in profiles.values():
        assert len(profile.points) >= 5
        schema = asset_schema(profile)
        Draft202012Validator.check_schema(schema)
        validate_json(empty_asset(profile, profile.key), schema)
        for point in profile.points:
            if point.role in {"command", "setpoint"}:
                assert point.interlocks
    # Do not invent schema names absent from the pinned Redfish resource release.
    assert profiles["ups"].redfish_resource is None
    assert profiles["generator"].redfish_resource is None
    assert profiles["valve"].redfish_resource is None


def test_unknown_points_wrong_units_and_missing_are_not_zeros(profiles):
    p = profiles["server"]
    a = empty_asset(p, "server")
    a["supported_points"] = ["active_power_kw"]
    missing = sample(p.point("active_power_kw"), None)
    assert missing["value"] is None and missing["quality"] == "missing"
    a = apply_observation(a, "active_power_kw", missing, p)
    a["observations"]["active_power_kw"]["unit"] = "W"
    with pytest.raises(ValidationError):
        validate_json(a, asset_schema(p))
    a["observations"] = {"invented_point": missing}
    with pytest.raises(ValidationError):
        validate_json(a, asset_schema(p))
    with pytest.raises(ValueError, match="unit conversion"):
        sample(p.point("active_power_kw"), 12, native_unit="Cel")


def test_redfish_reading_units_null_and_health_are_distinct(profiles):
    point = profiles["server"].point("active_power_kw")
    data = scada_example()["raw_inputs"]["redfish"]
    data["Status"]["Health"] = "Critical"
    r = redfish_sensor(point, data, received_at=TIMESTAMP)
    assert r["value"] == pytest.approx(1.2)
    assert r["quality"] == "good"  # An alarm does not invalidate a measured reading.
    assert r["source_timestamp"] == TIMESTAMP
    data["Reading"] = None
    assert redfish_sensor(point, data, received_at=TIMESTAMP)["quality"] == "missing"
    data["Reading"] = 10
    data["Status"]["State"] = "Disabled"
    assert redfish_sensor(point, data, received_at=TIMESTAMP)["quality"] == "uncertain"


def test_ups_rfc1628_hand_calculated_units_and_phase_boundary():
    result = snmp_ups_samples(
        {
            "1.3.6.1.2.1.33.1.2.5.0": 5400,
            "1.3.6.1.2.1.33.1.2.3.0": 12,
            "1.3.6.1.2.1.33.1.4.2.0": 500,
            "1.3.6.1.2.1.33.1.4.1.0": 5,
            "1.3.6.1.2.1.33.1.4.4.1.4.2": 300000,
            "1.3.6.1.2.1.33.1.2.7.0": "noSuchInstance",
        },
        received_at=TIMESTAMP,
        output_line_index=2,
    )
    assert result["battery_voltage_v"]["value"] == 540
    assert result["remaining_runtime_s"]["value"] == 720
    assert result["frequency_hz"]["value"] == 50
    assert result["output_source"]["value"] == "battery"
    assert result["output_line_power_kw"]["value"] == 300
    assert "output_power_kw" not in result
    assert result["battery_temperature_c"]["value"] is None
    assert all(v["source_timestamp"] is None for v in result.values())


def test_entity_sensor_scale_precision_and_non_utc_timestamp(profiles):
    record = dict(
        index=8, type=8, scale=9, precision=1, value=253, status=1, value_timestamp_ticks=123456
    )
    r = snmp_entity_sensor(
        profiles["environment_sensor"].point("temperature_c"), record, received_at=TIMESTAMP
    )
    assert r["value"] == pytest.approx(25.3)
    assert r["source_timestamp"] is None
    assert r["raw_status"]["value_timestamp_ticks"] == 123456
    # milliWatts: 1,200,000 * 10^-3 W = 1.2 kW.
    record.update(type=6, scale=8, precision=0, value=1200000)
    r = snmp_entity_sensor(
        profiles["server"].point("active_power_kw"), record, received_at=TIMESTAMP
    )
    assert r["value"] == pytest.approx(1.2)
    # Negative precision reports accurate digits; it must not inflate the reading.
    record.update(type=8, scale=9, precision=-2, value=25)
    assert (
        snmp_entity_sensor(
            profiles["environment_sensor"].point("temperature_c"), record, received_at=TIMESTAMP
        )["value"]
        == 25
    )
    record.update(type=6, precision=0, value=1000000000)
    overflow = snmp_entity_sensor(
        profiles["server"].point("active_power_kw"), record, received_at=TIMESTAMP
    )
    assert overflow["quality"] == "bad" and overflow["value"] is None
    record["status"] = 2
    record["value"] = 0
    assert (
        snmp_entity_sensor(
            profiles["server"].point("active_power_kw"), record, received_at=TIMESTAMP
        )["quality"]
        == "missing"
    )


@pytest.mark.parametrize(
    "flags,reliability,expected",
    [
        ([True, False, False, False], "no-fault-detected", "good"),
        ([False, True, False, False], "no-fault-detected", "bad"),
        ([False, False, True, False], "no-fault-detected", "uncertain"),
        ([False, False, False, True], "no-fault-detected", "uncertain"),
        ([False, False, False, False], "no-sensor", "bad"),
    ],
)
def test_bacnet_alarm_is_not_quality_but_overrides_and_faults_are(
    profiles, flags, reliability, expected
):
    record = scada_example()["raw_inputs"]["bacnet"]
    record.update(status_flags=flags, reliability=reliability)
    r = bacnet_sample(
        profiles["chiller"].point("supply_temperature_c"), record, received_at=TIMESTAMP
    )
    assert r["value"] == 18.5
    assert r["quality"] == expected
    assert r["source_timestamp"] is None


@pytest.mark.parametrize(
    "word_order,byte_order",
    [("big", "big"), ("little", "big"), ("big", "little"), ("little", "little")],
)
def test_modbus_float_signedness_endianness(word_order, byte_order, profiles):
    data = struct.pack(">f", 12.5)
    words = [int.from_bytes(data[i : i + 2], byte_order) for i in range(0, 4, 2)]
    if word_order == "little":
        words.reverse()
    b = RegisterBinding(
        100, 4, "float32", "Cel", "synthetic", word_order=word_order, byte_order=byte_order
    )
    r = modbus_sample(
        profiles["environment_sensor"].point("temperature_c"), words, b, received_at=TIMESTAMP
    )
    assert r["value"] == 12.5
    signed = modbus_sample(
        profiles["environment_sensor"].point("temperature_c"),
        [65526],
        RegisterBinding(0, 3, "int16", "Cel", "synthetic"),
        received_at=TIMESTAMP,
    )
    assert signed["value"] == -10


def test_modbus_bad_sentinels_spans_and_nonfinite(profiles):
    p = profiles["server"].point("active_power_kw")
    b = RegisterBinding(1, 4, "uint16", "W", "synthetic", invalid_raw_values=(65535,))
    assert modbus_sample(p, [65535], b, received_at=TIMESTAMP)["quality"] == "missing"
    with pytest.raises(ValueError):
        modbus_sample(p, [1, 2], b, received_at=TIMESTAMP)
    with pytest.raises(ValueError):
        RegisterBinding(400001, 4, "uint16", "W", "synthetic")
    with pytest.raises(ValueError):
        RegisterBinding(0, 6, "uint16", "W", "synthetic")
    with pytest.raises(ValueError):
        modbus_sample(
            p, [0, 1], RegisterBinding(65535, 4, "uint32", "W", "synthetic"), received_at=TIMESTAMP
        )
    r = modbus_sample(
        p, [0x7F80, 0], RegisterBinding(1, 4, "float32", "W", "synthetic"), received_at=TIMESTAMP
    )
    assert r["quality"] == "bad" and r["value"] is None
    json.dumps(r, allow_nan=False)


@pytest.mark.parametrize(
    "code,quality", [(0, "good"), (0x40000000, "uncertain"), (0x80000000, "bad")]
)
def test_opcua_status_and_both_timestamps_preserved(profiles, code, quality):
    record = scada_example()["raw_inputs"]["opcua"]
    record["StatusCode"] = code
    r = opcua_sample(profiles["cdu"].point("flow_l_min"), record, received_at=TIMESTAMP)
    assert r["quality"] == quality
    assert r["source_timestamp"] == TIMESTAMP
    assert r["raw_status"]["ServerTimestamp"] == TIMESTAMP


def test_bad_values_bounds_and_unknown_enums(profiles):
    p = profiles["ups"].point("state_of_charge_percent")
    assert sample(p, 101)["quality"] == "bad"
    assert sample(p, True)["quality"] == "bad"
    assert sample(profiles["ups"].point("load_percent"), 130)["value"] == 130
    assert sample(profiles["power_meter"].point("current_thd_percent"), 150)["value"] == 150
    assert sample(profiles["server"].point("health"), "invented")["value"] is None
    with pytest.raises(ValueError):
        sample(p, 50, received_at="2026-01-01T12:00:00")
    with pytest.raises(ValueError):
        sample(p, 50, quality="pretend_good")


def test_quality_freshness_and_out_of_order_updates(profiles):
    p = profiles["server"]
    point = p.point("active_power_kw")
    r = sample(point, 1)
    assert with_freshness(r, point, now="2026-01-01T12:06:00Z")["quality"] == "stale"
    bad = {**r, "quality": "bad"}
    assert with_freshness(bad, point, now="2026-01-01T11:00:00Z")["quality"] == "bad"
    asset = empty_asset(p, "server")
    asset["supported_points"] = [point.key]
    asset = apply_observation(asset, point.key, r, p)
    older = sample(point, 0.8, received_at="2026-01-01T11:59:00Z")
    with pytest.raises(ValueError, match="out-of-order"):
        apply_observation(asset, point.key, older, p)


def test_counter_resets_and_source_boundaries(profiles):
    p = profiles["power_meter"].point("import_energy_kwh")
    old = sample(p, 10)
    new = sample(p, 15, received_at="2026-01-01T12:01:00Z")
    assert counter_delta(old, new) == 5
    for change in (
        {"value": 2},
        {"quality": "bad"},
        {"unit": "Wh"},
        {"source_address": "another-meter"},
    ):
        with pytest.raises(ValueError):
            counter_delta(old, {**new, **change})


def test_topology_validates_containment_without_forbidding_meshes(profiles):
    example = scada_example()
    assets = example["assets"]
    validate_plant(assets, example["relationships"], profiles)
    with pytest.raises(ValueError):
        validate_plant([*assets, assets[0]], example["relationships"], profiles)
    cycle = deepcopy(assets)
    cycle[0]["parent_id"] = cycle[1]["id"]
    with pytest.raises(ValueError, match="cyclic"):
        validate_plant(cycle, [], profiles)
    with pytest.raises(ValueError, match="dangling"):
        validate_plant(
            assets,
            [dict(source="absent", target=assets[0]["id"], kind="electrical_feed")],
            profiles,
        )


def test_event_lifecycle_and_control_intents(profiles):
    example = scada_example()
    event = example["events"][0]
    validate_event(event, profiles["leak_detector"])
    with pytest.raises(ValueError):
        validate_event({**event, "state": "cleared"}, profiles["leak_detector"])
    with pytest.raises(ValueError):
        validate_event({**event, "acknowledged_by": "operator"}, profiles["leak_detector"])
    intent = example["control_intent"]
    assert intent["execution_supported"] is False
    assert intent["expires_at"] == "2026-01-01T12:00:30+00:00"
    assert "equipment_permissives" in intent["required_interlocks"]
    with pytest.raises(ValueError):
        describe_control_intent(
            profiles["server"], "active_power_kw", 1, asset_id="x", requested_at=TIMESTAMP
        )


def test_binding_schemas_require_concrete_commissioning(profiles):
    example = scada_example()
    endpoint = dict(
        id="endpoint",
        protocol="modbus",
        address="synthetic.invalid:502",
        security_profile="synthetic offline fixture",
        credential_reference=None,
    )
    binding = dict(
        id="binding",
        asset_id="rack_pdu-01",
        point_key="active_power_kw",
        endpoint_id="endpoint",
        protocol="modbus",
        native_unit="W",
        scale=1,
        offset=0,
        source_document="synthetic, not vendor",
        evidence_kind="synthetic",
        access="read",
        locator=dict(
            unit_id=1,
            function_code=4,
            address_zero_based=100,
            data_type="uint32",
            byte_order="big",
            word_order="big",
        ),
    )
    validate_bindings([binding], [endpoint], example["assets"], profiles)
    missing = deepcopy(binding)
    del missing["locator"]["address_zero_based"]
    with pytest.raises(ValidationError):
        validate_bindings([missing], [endpoint], example["assets"], profiles)
    with pytest.raises(ValueError):
        validate_bindings(
            [binding], [{**endpoint, "protocol": "snmp"}], example["assets"], profiles
        )
    for schema in (endpoint_schema(), binding_schema(), event_schema()):
        Draft202012Validator.check_schema(schema)


def test_crosswalk_preserves_unknowns_and_source_evidence(profiles):
    rows = commissioning_crosswalk(profiles)
    assert len(rows) > 3000
    assert all(r["requires_commissioning"] and not r["execution_supported"] for r in rows)
    assert all(r["locator"] is None for r in rows if r["protocol"] == "modbus")
    scalars = [r for r in rows if r["mapping_status"] == "standard_scalar"]
    assert len(scalars) == 6
    assert all(r["profile"] == "ups" and r["locator"].endswith(".0") for r in scalars)
    sources = {s["id"] for s in standards_evidence()["sources"]}
    assert {r["source_id"] for r in rows} <= sources | {"canonical-engineering-profile"}


def test_every_export_schema_and_synthetic_asset_validates(tmp_path, profiles):
    summary = export_scada_model(tmp_path)
    assert summary["profiles"] == 50 and summary["points"] > 900
    for path in (tmp_path / "schemas").glob("*.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text()))
    data = json.loads((tmp_path / "example_plant.json").read_text())
    validate_plant(data["assets"], data["relationships"], profiles)
    assert "50 profiles" in (tmp_path / "scada-model.html").read_text()
