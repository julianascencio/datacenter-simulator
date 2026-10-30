"""Radial constant-power DC load flow with cables and regulated DC/DC converters.

This is a steady-state resistive model, not the AC-system 'DC power-flow' approximation.
"""

from dataclasses import dataclass
from math import isclose

import pandas as pd

from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.performance import ConverterMap


@dataclass(frozen=True)
class DCBus:
    id: str
    nominal_voltage_v: float
    minimum_voltage_pu: float = 0.90

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("bus id must be non-empty")
        finite("nominal_voltage_v", self.nominal_voltage_v, strict=True)
        fraction("minimum_voltage_pu", self.minimum_voltage_pu, positive=True)


@dataclass(frozen=True)
class DCBranch:
    """Cable or regulated converter; rating is at the receiving/output terminal.

    For cables, resistance_ohm includes the complete outgoing AND return path.
    Converter efficiency is constant; its output is regulated to the child bus nominal V.
    """

    id: str
    source: str
    target: str
    resistance_ohm: float = 0
    rated_current_a: float = 1000
    efficiency: float = 1
    kind: str = "cable"
    rated_power_kw: float | None = None
    performance: ConverterMap | None = None
    converter_temperature_c: float = 25

    def __post_init__(self) -> None:
        if not self.id or self.source == self.target:
            raise ValueError("branch needs an id and distinct endpoints")
        if self.kind not in {"cable", "converter"}:
            raise ValueError("kind must be cable or converter")
        finite("resistance_ohm", self.resistance_ohm)
        finite("rated_current_a", self.rated_current_a, strict=True)
        fraction("efficiency", self.efficiency, positive=True)
        if self.kind == "cable" and self.efficiency != 1:
            raise ValueError("cable losses use resistance, not efficiency")
        if self.kind == "converter" and self.resistance_ohm != 0:
            raise ValueError("converter losses use efficiency; model cables as separate branches")
        if self.rated_power_kw is not None:
            finite("rated_power_kw", self.rated_power_kw, strict=True)
        if self.performance is not None and self.kind != "converter":
            raise ValueError("performance maps apply only to converter branches")

    @classmethod
    def copper_cable(
        cls,
        id: str,
        source: str,
        target: str,
        length_m: float,
        area_mm2: float,
        rated_current_a: float,
        temperature_c: float = 20,
    ) -> "DCBranch":
        """Round-trip resistance using Cu rho20 = 0.01724 ohm mm²/m, alpha = 0.00393/K.

        Ampacity is an explicit user input: no installation/derating standard is inferred.
        """
        finite("length_m", length_m)
        finite("area_mm2", area_mm2, strict=True)
        finite("temperature_c", temperature_c, -100)
        resistance = 2 * 0.01724 * length_m / area_mm2 * (1 + 0.00393 * (temperature_c - 20))
        return cls(id, source, target, resistance, rated_current_a)


@dataclass
class ElectricalResult:
    buses: pd.DataFrame
    branches: pd.DataFrame
    source_kw: float
    load_kw: float
    loss_kw: float
    iterations: int
    warnings: tuple[str, ...]


class DCNetwork:
    """One slack source and a connected radial tree; invalid topologies fail explicitly."""

    def __init__(self, buses: list[DCBus], branches: list[DCBranch], source_bus: str):
        self.buses = {b.id: b for b in buses}
        self.branches = list(branches)
        self.source_bus = source_bus
        if len(self.buses) != len(buses) or len({e.id for e in branches}) != len(branches):
            raise ValueError("bus and branch ids must be unique")
        if source_bus not in self.buses:
            raise ValueError("source bus is missing")
        self.children: dict[str, list[DCBranch]] = {b: [] for b in self.buses}
        parents: dict[str, str] = {}
        for edge in branches:
            if edge.source not in self.buses or edge.target not in self.buses:
                raise ValueError(f"unknown endpoint on {edge.id}")
            if edge.target == source_bus or edge.target in parents:
                raise ValueError("radial networks require one parent per non-source bus")
            parents[edge.target] = edge.source
            self.children[edge.source].append(edge)
            if edge.kind == "cable" and not isclose(
                self.buses[edge.source].nominal_voltage_v,
                self.buses[edge.target].nominal_voltage_v,
            ):
                raise ValueError("different nominal voltages require a converter")
        self.order = [source_bus]
        for bus in self.order:
            self.order.extend(edge.target for edge in self.children[bus])
        if set(self.order) != set(self.buses):
            raise ValueError("network is disconnected or contains a cycle")

    def solve(
        self,
        loads_kw: dict[str, float],
        *,
        tolerance_v: float = 1e-8,
        max_iterations: int = 1000,
    ) -> ElectricalResult:
        """Backward power / forward voltage sweeps; return overload and voltage flags."""
        finite("tolerance_v", tolerance_v, strict=True)
        if not isinstance(max_iterations, int) or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if set(loads_kw) - set(self.buses):
            raise ValueError("loads contain unknown buses")
        for power in loads_kw.values():
            finite("load_kw", power)
        volts = {b: model.nominal_voltage_v for b, model in self.buses.items()}
        send: dict[str, float] = {}
        current: dict[str, float] = {}
        losses: dict[str, float] = {}
        for iteration in range(1, max_iterations + 1):  # noqa: B007 -- returned on convergence
            demand = {b: loads_kw.get(b, 0.0) for b in self.buses}
            for bus in reversed(self.order):
                for edge in self.children[bus]:
                    current[edge.id] = demand[edge.target] * 1000 / volts[edge.target]
                    loss = (
                        demand[edge.target] * (1 / edge.efficiency - 1)
                        if edge.kind == "converter"
                        else current[edge.id] ** 2 * edge.resistance_ohm / 1000
                    )
                    if edge.performance is not None:
                        loss = (
                            edge.performance.input_kw(
                                demand[edge.target], edge.converter_temperature_c
                            )
                            - demand[edge.target]
                        )
                    losses[edge.id] = loss
                    send[edge.id] = demand[edge.target] + loss
                    demand[bus] += send[edge.id]
            updated = dict(volts)
            for bus in self.order:
                for edge in self.children[bus]:
                    updated[edge.target] = (
                        self.buses[edge.target].nominal_voltage_v
                        if edge.kind == "converter"
                        else updated[bus] - current[edge.id] * edge.resistance_ohm
                    )
                    if updated[edge.target] <= 0:
                        raise ValueError("DC load flow collapsed: non-positive bus voltage")
            delta = max(abs(updated[b] - volts[b]) for b in volts)
            volts = updated
            if delta < tolerance_v:
                break
        else:
            raise ValueError("DC load flow did not converge; reduce load or cable impedance")
        warnings: list[str] = []
        bus_rows = []
        for bus, model in self.buses.items():
            pu = volts[bus] / model.nominal_voltage_v
            if pu < model.minimum_voltage_pu:
                warnings.append(f"Undervoltage at {bus}: {pu:.3f} pu")
            bus_rows.append(
                {
                    "bus": bus,
                    "voltage_v": volts[bus],
                    "voltage_pu": pu,
                    "load_kw": loads_kw.get(bus, 0),
                }
            )
        rows = []
        for edge in self.branches:
            receiving = send[edge.id] - losses[edge.id]
            loading = current[edge.id] / edge.rated_current_a
            if loading > 1:
                warnings.append(f"Current overload on {edge.id}: {loading:.1%}")
            if edge.rated_power_kw is not None and receiving > edge.rated_power_kw:
                warnings.append(f"Power overload on {edge.id}")
            rows.append(
                {
                    "branch": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "current_a": current[edge.id],
                    "input_current_a": send[edge.id] * 1000 / volts[edge.source],
                    "loading_pu": loading,
                    "sending_kw": send[edge.id],
                    "receiving_kw": receiving,
                    "loss_kw": losses[edge.id],
                }
            )
        branch_frame = pd.DataFrame(
            rows,
            columns=[
                "branch",
                "source",
                "target",
                "current_a",
                "input_current_a",
                "loading_pu",
                "sending_kw",
                "receiving_kw",
                "loss_kw",
            ],
        ).set_index("branch")
        return ElectricalResult(
            pd.DataFrame(bus_rows).set_index("bus"),
            branch_frame,
            demand[self.source_bus],
            sum(loads_kw.values()),
            sum(losses.values()),
            iteration,
            tuple(warnings),
        )
