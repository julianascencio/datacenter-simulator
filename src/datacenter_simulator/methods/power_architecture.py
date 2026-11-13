"""Power-path accounting, backup sizing and limited DC fault-energy screening.

These methods do not calculate arc-flash incident energy, device selectivity,
certification, PPE or safe working distances. Steady-state and fault models are
separate; no claim is made that the RC screen simulates the operating network.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import expm1, prod
from typing import cast

import pandas as pd

from datacenter_simulator.methods.electrical import DCBranch, DCBus, DCNetwork
from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.power_architecture import (
    CapacitorPath,
    LimitedSourcePath,
    PowerArchitecture,
)


@dataclass
class PowerPathResult:
    stages: pd.DataFrame
    it_kw: float
    input_kw: float
    loss_kw: float
    efficiency: float
    balance_error_kw: float


def evaluate_power_path(architecture: PowerArchitecture, it_kw: float) -> PowerPathResult:
    """Work backwards from the same low-voltage DC IT terminal in every case.

    No cooling, cables, standby draw, load curves, or downstream chip regulator
    is included. The UPS block already includes its rectifier/inverter losses.
    """
    finite("it_kw", it_kw)
    downstream = it_kw
    rows = []
    for stage in reversed(architecture.stages):
        upstream = downstream / stage.efficiency
        rows.append(
            {
                "stage": stage.name,
                "input_kw": upstream,
                "output_kw": downstream,
                "loss_kw": upstream - downstream,
                "efficiency": stage.efficiency,
            }
        )
        downstream = upstream
    stages = pd.DataFrame(rows[::-1])
    losses = float(stages.loss_kw.sum())
    return PowerPathResult(
        stages,
        it_kw,
        downstream,
        losses,
        prod(stage.efficiency for stage in architecture.stages),
        downstream - it_kw - losses,
    )


def compare_dc_conductors(
    load_kw: float,
    voltages_v: Sequence[float] = (54, 380, 800),
    *,
    length_m: float = 2,
    area_mm2: float = 1000,
    rated_current_a: float = 2000,
    temperature_c: float = 20,
) -> pd.DataFrame:
    """Reuse DCNetwork with identical two-wire copper geometry at each voltage.

    Voltage is fixed at the sending bus; receiving power is constant. Overload
    flags are retained. These hypothetical conductors are not cable designs or
    an AC-versus-DC copper comparison. A nonconvergent scenario raises.
    """
    finite("load_kw", load_kw)
    if not voltages_v:
        raise ValueError("at least one voltage is required")
    rows = []
    for voltage in voltages_v:
        finite("voltage_v", voltage, strict=True)
        cable = DCBranch.copper_cable(
            "loop", "source", "load", length_m, area_mm2, rated_current_a, temperature_c
        )
        network = DCNetwork([DCBus("source", voltage), DCBus("load", voltage)], [cable], "source")
        result = network.solve({"load": load_kw})
        current = float(cast(float, result.branches.loc["loop", "current_a"]))
        rows.append(
            {
                "voltage_v": voltage,
                "ideal_current_a": load_kw * 1000 / voltage,
                "current_a": current,
                "receiving_voltage_v": float(cast(float, result.buses.loc["load", "voltage_v"])),
                "loop_resistance_ohm": cable.resistance_ohm,
                "loss_kw": result.loss_kw,
                "overloaded": current > rated_current_a,
                "warnings": "; ".join(result.warnings),
                "balance_error_kw": result.source_kw - load_kw - result.loss_kw,
            }
        )
    return pd.DataFrame(rows)


def dc_backup_requirements(
    bus_load_kw: float,
    duration_s: float,
    *,
    discharge_efficiency: float = 0.96,
    usable_soc_fraction: float = 0.8,
) -> dict[str, float]:
    """Energy and power minima for constant bus demand over a stated outage.

    Nominal energy accounts for the initially available SOC window; no ageing,
    redundancy, cooling, recharge, or transient overload margin is included.
    """
    finite("bus_load_kw", bus_load_kw)
    finite("duration_s", duration_s)
    fraction("discharge_efficiency", discharge_efficiency, positive=True)
    fraction("usable_soc_fraction", usable_soc_fraction, positive=True)
    delivered = bus_load_kw * duration_s / 3600
    return {
        "bus_load_kw": bus_load_kw,
        "duration_s": duration_s,
        "bus_energy_kwh": delivered,
        "minimum_nominal_kwh": delivered / discharge_efficiency / usable_soc_fraction,
        "minimum_bus_discharge_kw": bus_load_kw if duration_s > 0 else 0.0,
        "minimum_storage_discharge_kw": (
            bus_load_kw / discharge_efficiency if duration_s > 0 else 0.0
        ),
    }


def capacitor_hold_up_f(
    bus_load_kw: float, duration_s: float, initial_v: float, minimum_v: float
) -> float:
    """Ideal capacitance from P*t = C*(Vinitial² - Vminimum²)/2.

    Load is constant power at the bus. ESR/ESL, leakage, tolerance, converter
    dynamics and voltage-dependent capacity are excluded.
    """
    finite("bus_load_kw", bus_load_kw)
    finite("duration_s", duration_s)
    finite("minimum_v", minimum_v, strict=True)
    finite("initial_v", initial_v, minimum_v, strict=True)
    return 2 * bus_load_kw * 1000 * duration_s / (initial_v**2 - minimum_v**2)


@dataclass
class FaultEnergyScreen:
    contributions: pd.DataFrame
    capacitor_released_j: float
    source_envelope_j: float
    combined_screen_j: float
    capacitor_remaining_j: float


def fault_energy_screen(
    voltage_v: float,
    horizon_s: float,
    capacitors: Sequence[CapacitorPath] = (),
    sources: Sequence[LimitedSourcePath] = (),
) -> FaultEnergyScreen:
    """Independent RC energy release plus nominal-voltage source envelopes.

    RC release is 0.5*C*V²*(1-exp(-2*t/(R*C))). For a limited source the
    envelope is V*Ilimit*t, capped by its available bus-side energy. Each path
    stops at its own ideal isolation time, or at the observation horizon.

    The sum is a screening index, NOT dissipated arc energy or a guaranteed
    physical bound. There is no shared-bus solution, L, arc impedance, control
    response, restrike or protection coordination. In particular an upstream
    trip does not remove energy in a downstream capacitor.
    """
    finite("voltage_v", voltage_v, strict=True)
    finite("horizon_s", horizon_s)
    names = [p.name for p in capacitors] + [p.name for p in sources]
    if len(set(names)) != len(names):
        raise ValueError("fault contribution names must be unique")
    rows = []
    released = remaining = envelope = 0.0
    for cap in capacitors:
        duration = (
            min(horizon_s, cap.disconnect_after_s)
            if (cap.disconnect_after_s is not None)
            else horizon_s
        )
        stored = 0.5 * cap.capacitance_f * voltage_v**2
        energy = stored * -expm1(-2 * duration / (cap.resistance_ohm * cap.capacitance_f))
        released += energy
        remaining += stored - energy
        rows.append(
            {
                "path": cap.name,
                "kind": "rc_capacitor",
                "connected_s": duration,
                "screen_energy_j": energy,
                "capacitor_remaining_j": stored - energy,
            }
        )
    for source in sources:
        duration = min(horizon_s, source.disconnect_after_s)
        energy = voltage_v * source.current_limit_a * duration
        if source.available_energy_j is not None:
            energy = min(energy, source.available_energy_j)
        envelope += energy
        rows.append(
            {
                "path": source.name,
                "kind": "limited_source_envelope",
                "connected_s": duration,
                "screen_energy_j": energy,
                "capacitor_remaining_j": 0.0,
            }
        )
    return FaultEnergyScreen(
        pd.DataFrame(
            rows,
            columns=[
                "path",
                "kind",
                "connected_s",
                "screen_energy_j",
                "capacitor_remaining_j",
            ],
        ),
        released,
        envelope,
        released + envelope,
        remaining,
    )
