"""Comprehensive engineering profiles, composed from auditable point groups.

These are ASVA canonical profiles, not normative device lists from BACnet or
Modbus. Protocol support must be confirmed for each installed model/firmware.
"""

from datacenter_simulator.models.scada import DeviceProfile, FieldSpec


def fields(specification: str, *, role: str = "measurement") -> tuple[FieldSpec, ...]:
    """Compact catalogue notation: key|unit|meaning, one field per line."""
    result = []
    for line in specification.strip().splitlines():
        key, unit, meaning = line.strip().split("|", 2)
        result.append(
            FieldSpec(
                key,
                meaning,
                unit,
                role=role,
                data_type="integer" if unit in {"count", "byte", "U"} else "number",
                minimum=(
                    -273.15
                    if unit == "Cel"
                    else 0
                    if role in {"counter", "attribute"} or unit == "%"
                    else None
                ),
                maximum=100
                if key
                in {
                    "state_of_charge_percent",
                    "state_of_health_percent",
                    "relative_humidity_percent",
                    "supply_air_humidity_percent",
                    "return_air_humidity_percent",
                    "position_percent",
                    "utilization_percent",
                    "cpu_utilization_percent",
                    "memory_utilization_percent",
                    "level_percent",
                    "basin_level_percent",
                    "fuel_level_percent",
                    "fluid_level_percent",
                }
                else None,
            )
        )
    return tuple(result)


def flags(*names: str) -> tuple[FieldSpec, ...]:
    return tuple(
        FieldSpec(
            n,
            n.replace("_", " ").capitalize() + "; reported by device/controller.",
            data_type="boolean",
            role="alarm" if n.endswith("_alarm") else "status",
        )
        for n in names
    )


def enum(key: str, meaning: str, values: str) -> FieldSpec:
    return FieldSpec(key, meaning, data_type="string", role="status", choices=tuple(values.split()))


def control(key: str, unit: str, meaning: str, *, boolean: bool = False) -> FieldSpec:
    return FieldSpec(
        key,
        meaning,
        unit,
        data_type="boolean" if boolean else "number",
        role="command" if boolean else "setpoint",
        interlocks=(
            "site_authorization",
            "remote_mode",
            "equipment_permissives",
            "configured_engineering_limits",
            "feedback_verification",
        ),
    )


def attrs(spec: str) -> tuple[FieldSpec, ...]:
    return fields(spec, role="attribute")


COMMON = (
    enum(
        "health",
        "Equipment condition; not the quality of a telemetry sample.",
        "ok warning critical unknown",
    ),
    enum(
        "operating_state",
        "Canonical operating state; retain the native status in observations.",
        "running stopped standby starting stopping maintenance fault disabled unknown",
    ),
    *flags("alarm_active", "remote_mode"),
)
DIMENSIONS = attrs("""
width_m|m|Equipment enclosure width.
depth_m|m|Equipment enclosure depth.
height_m|m|Equipment enclosure height.
mass_kg|kg|Installed equipment mass.
""")
ELECTRICAL_RATING = attrs("""
rated_power_kw|kW|Nameplate active-power rating; identify input versus output boundary.
rated_apparent_power_kva|kVA|Nameplate apparent-power rating.
rated_voltage_v|V|Nameplate voltage; phase/line/DC interpretation declared at commissioning.
rated_current_a|A|Nameplate continuous current rating.
rated_frequency_hz|Hz|Nominal AC frequency; omit for DC equipment.
phase_count|count|Number of AC phases; omit for DC equipment.
""")
THERMAL_RATING = attrs("""
rated_thermal_kw|kW|Nameplate thermal duty, distinct from electric demand.
rated_flow_l_min|L/min|Design liquid volume flow.
maximum_pressure_kpa|kPa|Declared maximum working pressure; not a universal setpoint.
design_supply_temperature_c|Cel|Engineering design supply temperature.
design_return_temperature_c|Cel|Engineering design return temperature.
""")
POWER = fields("""
active_power_kw|kW|Real power; positive consumption except at an explicit generator/export boundary.
apparent_power_kva|kVA|Total apparent power at the declared AC boundary.
reactive_power_kvar|kvar|Signed reactive power; inductive-positive convention must be commissioned.
power_factor|1|Signed true power factor; leading/lagging convention must be commissioned.
frequency_hz|Hz|Measured AC frequency.
""")
PHASES = fields(
    "\n".join(
        [f"voltage_l{i}_n_v|V|RMS voltage phase L{i} to neutral." for i in (1, 2, 3)]
        + [
            f"voltage_{pair}_v|V|RMS line-to-line voltage {pair.upper()}."
            for pair in ("l1_l2", "l2_l3", "l3_l1")
        ]
        + [f"current_l{i}_a|A|RMS current in phase L{i}." for i in (1, 2, 3)]
        + [
            "neutral_current_a|A|RMS neutral-conductor current.",
            "voltage_thd_percent|%|Voltage total harmonic distortion; can exceed 100%.",
            "current_thd_percent|%|Current total harmonic distortion; can exceed 100%.",
        ]
    )
)
ENERGY = fields(
    """
import_energy_kwh|kWh|Cumulative imported energy; counter resets must be tracked.
export_energy_kwh|kWh|Cumulative exported energy; do not subtract before validation.
""",
    role="counter",
)
TEMP = fields("temperature_c|Cel|Local equipment temperature; sensor location must be identified.")
RUNTIME = fields(
    "run_hours|h|Accumulated running hours; counter may reset after replacement.", role="counter"
)
DC = fields("""
dc_voltage_v|V|Measured DC terminal voltage.
dc_current_a|A|Signed DC terminal current; polarity needs commissioning.
dc_power_kw|kW|Signed DC terminal power with the commissioned boundary convention.
""")
WATER = fields("""
supply_temperature_c|Cel|Leaving supply temperature at this equipment boundary.
return_temperature_c|Cel|Entering return temperature at this equipment boundary.
supply_pressure_kpa|kPa|Supply pressure; gauge or absolute reference must be documented.
return_pressure_kpa|kPa|Return pressure with the same reference as supply.
differential_pressure_kpa|kPa|Measured differential pressure across the declared device/loop.
flow_l_min|L/min|Measured liquid volume flow at the declared side of the device.
thermal_power_kw|kW|Thermal duty; measured or derived provenance must be preserved.
""")
AIR = fields("""
supply_air_temperature_c|Cel|Air temperature leaving the unit.
return_air_temperature_c|Cel|Air temperature entering the unit.
supply_air_humidity_percent|%|Supply relative humidity.
return_air_humidity_percent|%|Return relative humidity.
airflow_m3_h|m3/h|Air volume flow at the declared measuring conditions.
filter_differential_pressure_kpa|kPa|Pressure drop across the air filter.
fan_speed_rpm|rpm|Measured fan speed; use child fans for multiple independent fans.
""")
MOTOR = (
    *TEMP,
    *RUNTIME,
    *fields("speed_rpm|rpm|Measured rotating speed."),
    *flags("overload_alarm", "drive_fault_alarm"),
    control("speed_setpoint_percent", "%", "Requested drive speed as percent of configured range."),
)
# Vibration displacement is separate from velocity; never attach a length unit to velocity.
VIBRATION = fields(
    "vibration_displacement_mm|mm|Measured vibration displacement; not velocity RMS."
)
BATTERY = (
    *DC,
    *TEMP,
    *fields("""
state_of_charge_percent|%|Estimated stored charge as percent of full charge.
state_of_health_percent|%|Vendor health/capacity estimate; identify its algorithm.
remaining_runtime_s|s|Predicted autonomy at the currently reported load.
cell_voltage_min_v|V|Minimum observed cell voltage.
cell_voltage_max_v|V|Maximum observed cell voltage.
cell_temperature_min_c|Cel|Minimum observed cell temperature.
cell_temperature_max_c|Cel|Maximum observed cell temperature.
insulation_resistance_ohm|Ohm|Measured DC isolation resistance to ground.
"""),
    *fields(
        "cycle_count|count|Battery cycle counter; full-equivalent definition is vendor-specific.",
        role="counter",
    ),
    *flags("low_charge_alarm", "overtemperature_alarm", "cell_imbalance_alarm", "isolation_alarm"),
)
BATTERY_RATING = attrs("""
nominal_energy_kwh|kWh|Declared nominal stored energy at specified test conditions.
usable_energy_kwh|kWh|Configured usable energy within the allowed SOC range.
series_cell_count|count|Number of series-connected cells.
parallel_string_count|count|Number of parallel strings.
""")
THERMAL_CONTROLS = (
    control("supply_temperature_setpoint_c", "Cel", "Requested leaving-fluid/air temperature."),
    control(
        "enable_command", "1", "Request unit enable; no execution is implemented.", boolean=True
    ),
)


def device_profiles() -> dict[str, DeviceProfile]:
    """Fresh profiles covering spaces, IT, electrical, cooling and safety devices."""
    result: dict[str, DeviceProfile] = {}
    rf: str | None

    def add(
        key: str,
        label: str,
        domain: str,
        a: tuple[FieldSpec, ...],
        p: tuple[FieldSpec, ...],
        rf: str | None = None,
        boundary: str = "",
    ) -> None:
        protocols = ("redfish", "snmp") if domain == "IT" else ("bacnet", "modbus", "snmp")
        if rf and "redfish" not in protocols:
            protocols = ("redfish", *protocols)
        result[key] = DeviceProfile(
            key,
            label,
            domain,
            (*DIMENSIONS, *a),
            (*COMMON, *p),
            (*protocols, "opcua"),
            rf,
            boundary or "Device-local; reconcile parent and child meters before aggregation.",
        )

    for key, label in (
        ("site", "Data center site"),
        ("building", "Building"),
        ("room", "Data hall / room"),
    ):
        add(
            key,
            label,
            "Space",
            attrs("design_it_power_kw|kW|Design IT terminal capacity, not facility import."),
            (
                *fields("""
facility_power_kw|kW|Measured whole-facility demand at a declared meter boundary.
it_power_kw|kW|Measured IT demand at a distinct declared boundary.
ambient_temperature_c|Cel|Outdoor or room ambient temperature; identify sensor location.
relative_humidity_percent|%|Relative humidity at the identified location.
"""),
                *flags("fire_alarm", "water_leak_alarm"),
            ),
            "Facility",
        )
    add(
        "rack",
        "IT rack",
        "IT",
        (*ELECTRICAL_RATING, *attrs("rack_capacity_u|U|Usable mounting height.")),
        (
            *POWER,
            *ENERGY,
            *fields(
                """
inlet_temperature_c|Cel|Rack inlet air temperature.
exhaust_temperature_c|Cel|Rack exhaust air temperature.
"""
            ),
            *flags("door_open", "water_leak_alarm"),
        ),
        "Chassis",
    )
    add(
        "server",
        "Compute server",
        "IT",
        (
            *ELECTRICAL_RATING,
            *attrs("""
processor_count|count|Installed processor packages.
gpu_count|count|Installed accelerators.
memory_capacity_gib|GiB|Installed memory capacity.
"""),
        ),
        (
            *fields("""
active_power_kw|kW|Whole-server input power; never add child GPU power again.
inlet_temperature_c|Cel|Server inlet temperature.
exhaust_temperature_c|Cel|Server exhaust temperature.
cpu_utilization_percent|%|CPU busy fraction over a declared sampling window.
memory_utilization_percent|%|Used-memory fraction over a declared sampling window.
fan_speed_rpm|rpm|Aggregate fan sensor only; enumerate child fans where exposed.
"""),
            enum(
                "power_state",
                "Reported server power state.",
                "on off powering_on powering_off paused unknown",
            ),
            control("power_limit_kw", "kW", "Requested whole-server power cap."),
            control(
                "reset_command", "1", "Requested server reset; descriptive only.", boolean=True
            ),
        ),
        "ComputerSystem",
    )
    for key, label in (("cpu", "Processor"), ("gpu", "GPU / accelerator")):
        add(
            key,
            label,
            "IT",
            attrs(
                """
rated_power_kw|kW|Package/board power limit.
core_count|count|Installed cores.
memory_capacity_gib|GiB|Local memory capacity.
"""
            ),
            (
                *TEMP,
                *fields("""
active_power_kw|kW|Package/board electrical power; overlaps its parent server input.
utilization_percent|%|Busy fraction; operation and averaging window must be specified.
clock_mhz|MHz|Reported processor/graphics clock.
memory_clock_mhz|MHz|Reported local memory clock.
memory_used_gib|GiB|Used local memory.
"""),
                *fields(
                    """
corrected_error_count|count|Cumulative corrected errors.
uncorrected_error_count|count|Cumulative uncorrected errors.
""",
                    role="counter",
                ),
                *flags("thermal_throttling", "power_throttling"),
                control("power_limit_kw", "kW", "Requested package/board power cap."),
            ),
            "Processor",
        )
    add(
        "memory",
        "Memory module",
        "IT",
        attrs("""
capacity_mib|MiB|Installed module memory.
rated_speed_mhz|MHz|Rated memory clock.
"""),
        (
            *TEMP,
            *fields(
                """
corrected_error_count|count|Corrected ECC errors.
uncorrected_error_count|count|Uncorrected ECC errors.
""",
                role="counter",
            ),
        ),
        "Memory",
    )
    for key, label, rf in (
        ("storage", "Storage system", "Storage"),
        ("drive", "Storage drive", "Drive"),
    ):
        add(
            key,
            label,
            "IT",
            attrs(
                """
capacity_bytes|byte|Usable or raw capacity; identify boundary.
rated_power_kw|kW|Input rating.
"""
            ),
            (
                *TEMP,
                *fields("""
read_throughput_bit_s|bit/s|Read throughput, bits per second.
write_throughput_bit_s|bit/s|Write throughput, bits per second.
latency_ms|ms|Operation latency; statistic/window must be supplied by source.
remaining_life_percent|%|Vendor-reported remaining media life.
"""),
                *fields(
                    """
read_bytes|byte|Cumulative bytes read.
written_bytes|byte|Cumulative bytes written.
media_error_count|count|Cumulative media errors.
""",
                    role="counter",
                ),
                *flags("predictive_failure_alarm", "degraded_redundancy_alarm"),
            ),
            rf,
        )
    add(
        "network_switch",
        "Network switch",
        "IT",
        (*ELECTRICAL_RATING, *attrs("port_count|count|Installed physical ports.")),
        (
            *TEMP,
            *fields(
                """
active_power_kw|kW|Switch input power.
cpu_utilization_percent|%|Management CPU busy fraction.
memory_utilization_percent|%|Management memory use.
"""
            ),
            *flags("fan_fault_alarm", "redundancy_lost_alarm"),
        ),
        "Switch",
    )
    add(
        "network_port",
        "Network port",
        "IT",
        attrs("rated_speed_gbit_s|Gbit/s|Maximum supported link rate."),
        (
            enum("link_state", "Physical link state.", "up down testing unknown"),
            *fields(
                """
link_speed_gbit_s|Gbit/s|Negotiated link speed.
receive_rate_bit_s|bit/s|Receive rate.
transmit_rate_bit_s|bit/s|Transmit rate.
"""
            ),
            *fields(
                """
receive_bytes|byte|Receive-octet counter.
transmit_bytes|byte|Transmit-octet counter.
error_count|count|Error counter.
discard_count|count|Discard counter.
""",
                role="counter",
            ),
        ),
        "Port",
    )
    add(
        "power_supply",
        "IT power supply",
        "IT",
        ELECTRICAL_RATING,
        (
            *TEMP,
            *DC,
            *fields(
                """
input_power_kw|kW|AC input real power.
output_power_kw|kW|DC output real power.
efficiency_percent|%|Output/input power ratio.
"""
            ),
            *flags("input_lost_alarm", "redundancy_lost_alarm"),
        ),
        "PowerSupply",
    )
    for key, label, rf in (
        ("grid_connection", "Utility connection", None),
        ("transformer", "Transformer", None),
        ("switchgear", "Switchgear", "PowerDistribution"),
        ("busbar", "Busbar / busway", "PowerDistribution"),
        ("floor_pdu", "Floor PDU", "PowerDistribution"),
        ("rack_pdu", "Rack PDU", "PowerDistribution"),
        ("power_meter", "Power quality / energy meter", "Circuit"),
    ):
        p = (*POWER, *PHASES, *ENERGY, *TEMP, *flags("overload_alarm", "ground_fault_alarm"))
        if key == "transformer":
            p += (
                *fields(
                    """
winding_temperature_c|Cel|Winding temperature.
oil_temperature_c|Cel|Insulating oil temperature when oil-filled.
tap_position|count|Tap-changer position.
"""
                ),
                *flags("gas_relay_alarm", "cooling_fault_alarm"),
            )
        add(key, label, "Electrical", ELECTRICAL_RATING, p, rf)
    add(
        "pdu_outlet",
        "PDU outlet",
        "Electrical",
        ELECTRICAL_RATING,
        (
            *fields(
                """
voltage_v|V|Outlet RMS voltage.
current_a|A|Outlet RMS current.
active_power_kw|kW|Outlet load power.
"""
            ),
            *ENERGY,
            *flags("energized", "breaker_tripped", "overload_alarm"),
            control("outlet_enable_command", "1", "Request outlet enable.", boolean=True),
        ),
        "Outlet",
    )
    for key, label in (
        ("circuit_breaker", "Circuit breaker"),
        ("protection_relay", "Protection relay"),
    ):
        add(
            key,
            label,
            "Electrical",
            ELECTRICAL_RATING,
            (
                *PHASES,
                *flags("closed", "tripped", "ground_fault_alarm", "protection_lockout"),
                *fields("operation_count|count|Accumulated switching operations.", role="counter"),
                control(
                    "open_command",
                    "1",
                    "Request circuit opening; no protection execution.",
                    boolean=True,
                ),
                control(
                    "close_command",
                    "1",
                    "Request circuit closing subject to site interlocks.",
                    boolean=True,
                ),
            ),
            "Circuit" if key == "circuit_breaker" else None,
        )
    for key, label in (("ats", "Automatic transfer switch"), ("sts", "Static transfer switch")):
        add(
            key,
            label,
            "Electrical",
            ELECTRICAL_RATING,
            (
                *POWER,
                *fields(
                    """
source_a_voltage_v|V|Source A RMS voltage.
source_b_voltage_v|V|Source B RMS voltage.
source_a_frequency_hz|Hz|Source A frequency.
source_b_frequency_hz|Hz|Source B frequency.
last_transfer_time_ms|ms|Last measured transfer duration.
"""
                ),
                enum("selected_source", "Connected supply source.", "a b none unknown"),
                *flags("source_a_available", "source_b_available", "transfer_failed_alarm"),
                control(
                    "transfer_to_b_command",
                    "1",
                    "Request transfer; synchronism/permissives are site-specific.",
                    boolean=True,
                ),
            ),
            "PowerDistribution",
        )
    add(
        "ups",
        "Uninterruptible power supply",
        "Electrical",
        (*ELECTRICAL_RATING, *BATTERY_RATING),
        (
            *POWER,
            *PHASES,
            *ENERGY,
            *BATTERY,
            *fields("""
input_power_kw|kW|UPS input real power.
output_power_kw|kW|UPS total output real power; do not substitute one phase.
output_line_power_kw|kW|One explicitly indexed output line; RFC 1628 table measurement.
output_line_voltage_v|V|One explicitly indexed output line RMS voltage.
output_line_current_a|A|One explicitly indexed output line RMS current.
load_percent|%|UPS load relative to rating; overload may exceed 100%.
bypass_voltage_v|V|Bypass-source RMS voltage.
battery_voltage_v|V|UPS battery voltage.
battery_temperature_c|Cel|Battery casing/ambient sensor as described by the source.
"""),
            enum(
                "output_source",
                "Source currently supplying UPS output.",
                "other none normal bypass battery booster reducer",
            ),
            *flags("on_battery", "bypass_active", "overload_alarm", "redundancy_lost_alarm"),
            control(
                "battery_test_command",
                "1",
                "Request a battery test; descriptive only.",
                boolean=True,
            ),
        ),
        None,
    )
    for key, label in (
        ("battery_bank", "Battery bank / BESS"),
        ("battery_module", "Battery module / string"),
    ):
        add(key, label, "Electrical", (*ELECTRICAL_RATING, *BATTERY_RATING), BATTERY, "Battery")
    add(
        "generator",
        "Standby generator",
        "Electrical",
        ELECTRICAL_RATING,
        (
            *POWER,
            *PHASES,
            *ENERGY,
            *RUNTIME,
            *fields("""
engine_speed_rpm|rpm|Engine shaft speed.
coolant_temperature_c|Cel|Engine coolant temperature.
oil_pressure_kpa|kPa|Lubricating-oil pressure; reference must be commissioned.
fuel_level_percent|%|Fuel tank level.
"""),
            *fields(
                """
fuel_flow_l_min|L/min|Liquid fuel use rate.
starting_battery_voltage_v|V|Starting-battery voltage.
"""
            ),
            *flags(
                "fail_to_start_alarm",
                "low_oil_pressure_alarm",
                "overspeed_alarm",
                "emergency_stop_active",
            ),
            control(
                "start_command",
                "1",
                "Request engine start; not a dispatch instruction.",
                boolean=True,
            ),
            control(
                "stop_command",
                "1",
                "Request engine stop subject to cooldown/site control.",
                boolean=True,
            ),
        ),
        None,
    )
    add(
        "solar_inverter",
        "PV inverter",
        "Electrical",
        ELECTRICAL_RATING,
        (
            *POWER,
            *PHASES,
            *ENERGY,
            *DC,
            *TEMP,
            *flags("isolation_alarm", "grid_fault_alarm"),
            control("active_power_limit_kw", "kW", "Requested inverter output limit."),
        ),
    )
    for key, label in (
        ("chiller", "Chiller"),
        ("heat_exchanger", "Heat exchanger"),
        ("cdu", "Coolant distribution unit"),
    ):
        p = (
            *WATER,
            *TEMP,
            *RUNTIME,
            *fields(
                """
active_power_kw|kW|Total unit electric demand.
secondary_flow_l_min|L/min|Secondary-side coolant flow.
secondary_supply_temperature_c|Cel|Secondary supply temperature.
secondary_return_temperature_c|Cel|Secondary return temperature.
"""
            ),
            *flags("flow_failure_alarm", "water_leak_alarm", "high_pressure_alarm"),
            *THERMAL_CONTROLS,
        )
        if key == "chiller":
            p += fields(
                """
compressor_power_kw|kW|Compressor electric demand.
refrigerant_suction_pressure_kpa|kPa|Refrigerant suction pressure.
refrigerant_discharge_pressure_kpa|kPa|Refrigerant discharge pressure.
"""
            )
        add(
            key,
            label,
            "Cooling",
            (*THERMAL_RATING, *ELECTRICAL_RATING),
            p,
            "CoolingUnit" if key in {"cdu", "heat_exchanger"} else None,
        )
    for key, label in (("cooling_tower", "Cooling tower"), ("dry_cooler", "Dry cooler")):
        add(
            key,
            label,
            "Cooling",
            THERMAL_RATING,
            (
                *WATER,
                *RUNTIME,
                *fields(
                    """
fan_speed_rpm|rpm|Fan speed.
active_power_kw|kW|Fan and pump electrical demand.
ambient_temperature_c|Cel|Ambient dry-bulb temperature.
wet_bulb_temperature_c|Cel|Ambient wet-bulb temperature.
basin_level_percent|%|Basin level, only if a wet basin exists.
water_conductivity_us_cm|uS/cm|Water conductivity, where applicable.
makeup_flow_l_min|L/min|Makeup water flow, where applicable.
blowdown_flow_l_min|L/min|Blowdown flow, where applicable.
"""
                ),
                *flags("fan_fault_alarm", "low_level_alarm"),
                *THERMAL_CONTROLS,
            ),
        )
    for key, label in (
        ("crac", "Computer room air conditioner"),
        ("crah", "Computer room air handler"),
        ("in_row_cooler", "In-row cooler"),
        ("rear_door_hx", "Rear-door heat exchanger"),
    ):
        add(
            key,
            label,
            "Cooling",
            (*THERMAL_RATING, *ELECTRICAL_RATING),
            (
                *AIR,
                *WATER,
                *RUNTIME,
                *fields("active_power_kw|kW|Whole-unit electrical demand."),
                *flags("fan_fault_alarm", "filter_alarm", "condensate_alarm", "water_leak_alarm"),
                *THERMAL_CONTROLS,
            ),
        )
    add(
        "immersion_tank",
        "Immersion cooling tank",
        "Cooling",
        THERMAL_RATING,
        (
            *WATER,
            *fields(
                """
fluid_level_percent|%|Dielectric fluid level.
fluid_temperature_c|Cel|Bath temperature.
active_power_kw|kW|Tank auxiliaries, excluding immersed IT.
"""
            ),
            *flags("low_level_alarm", "water_leak_alarm"),
            *THERMAL_CONTROLS,
        ),
        "CoolingUnit",
    )
    add(
        "pump",
        "Liquid pump / VFD",
        "Cooling",
        (*THERMAL_RATING, *ELECTRICAL_RATING),
        (
            *WATER,
            *MOTOR,
            *VIBRATION,
            *fields("active_power_kw|kW|Pump/VFD electrical demand."),
            *flags("cavitation_alarm", "seal_leak_alarm"),
        ),
        "Pump",
    )
    add(
        "fan",
        "Fan / VFD",
        "Cooling",
        ELECTRICAL_RATING,
        (
            *MOTOR,
            *VIBRATION,
            *fields(
                """
airflow_m3_h|m3/h|Fan volume flow.
static_pressure_kpa|kPa|Fan static pressure rise.
active_power_kw|kW|Fan/VFD demand.
"""
            ),
        ),
        "Fan",
    )
    add(
        "valve",
        "Control / isolation valve",
        "Cooling",
        THERMAL_RATING,
        (
            *fields(
                """
position_percent|%|Measured valve travel.
flow_l_min|L/min|Flow through valve.
differential_pressure_kpa|kPa|Valve pressure drop.
"""
            ),
            *flags("open_limit", "closed_limit", "actuator_fault_alarm"),
            control("position_setpoint_percent", "%", "Requested valve travel."),
        ),
        None,
    )
    add(
        "cooling_loop",
        "Facility / technology cooling loop",
        "Cooling",
        THERMAL_RATING,
        (
            *WATER,
            *fields(
                """
water_conductivity_us_cm|uS/cm|Coolant conductivity.
ph|1|Coolant pH.
glycol_percent|%|Glycol concentration; specify mass/volume basis.
"""
            ),
            *flags("water_leak_alarm", "low_pressure_alarm"),
        ),
        "CoolingLoop",
    )
    for key, label in (("water_tank", "Water tank / reservoir"), ("fuel_tank", "Fuel tank")):
        add(
            key,
            label,
            "Auxiliary",
            attrs("capacity_l|L|Nominal tank volume."),
            (
                *TEMP,
                *fields(
                    """
level_percent|%|Tank level.
volume_l|L|Estimated stored volume.
inlet_flow_l_min|L/min|Inflow.
outlet_flow_l_min|L/min|Outflow.
"""
                ),
                *flags("low_level_alarm", "high_level_alarm", "leak_alarm"),
            ),
            "Reservoir" if key == "water_tank" else None,
        )
    add(
        "environment_sensor",
        "Environmental sensor",
        "Monitoring",
        (),
        (
            *TEMP,
            *fields(
                """
relative_humidity_percent|%|Relative humidity.
dewpoint_c|Cel|Air dewpoint.
pressure_kpa|kPa|Ambient absolute pressure.
co2_ppm|ppm|Carbon dioxide concentration.
noise_db|dB|Sound level; weighting/time window must be specified.
"""
            ),
        ),
        "Sensor",
    )
    add(
        "leak_detector",
        "Leak detector",
        "Monitoring",
        attrs("cable_length_m|m|Sensing cable length if cable-type."),
        (
            *flags("leak_alarm", "cable_fault_alarm"),
            *fields("leak_distance_m|m|Distance along sensing cable; omit if unsupported."),
        ),
        "LeakDetector",
    )
    add(
        "fire_panel",
        "Fire detection / suppression panel",
        "Safety",
        (),
        (
            *flags(
                "fire_alarm",
                "smoke_alarm",
                "system_trouble_alarm",
                "suppression_released",
                "zone_disabled",
            ),
            *fields("smoke_obscuration_percent|%|Smoke obscuration; document path length."),
        ),
    )
    add(
        "access_controller",
        "Door / access controller",
        "Safety",
        (),
        (
            *flags(
                "door_open", "door_forced_alarm", "door_held_alarm", "lock_engaged", "tamper_alarm"
            ),
            *fields(
                "access_denied_count|count|Aggregate denied events; no person identifiers.",
                role="counter",
            ),
        ),
    )
    return result
