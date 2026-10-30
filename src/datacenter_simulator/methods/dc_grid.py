"""Nonlinear resistive DC grids with regulated, droop and bidirectional power ports.

Voltages are pole-pair voltages of a two-wire equivalent. Grounding, midpoint
imbalance and switching dynamics need a different model. No AC DC-flow approximation.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.optimize import least_squares

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class DCLine:
    id: str
    source: str
    target: str
    loop_resistance_ohm: float
    ampacity_a: float = 1000

    def __post_init__(self) -> None:
        if not self.id or not self.source or not self.target or self.source == self.target:
            raise ValueError("line requires distinct, named endpoints")
        finite("loop_resistance_ohm", self.loop_resistance_ohm, strict=True)
        finite("ampacity_a", self.ampacity_a, strict=True)


@dataclass(frozen=True)
class DCPort:
    """Converter interface; power positive into grid, negative into external storage.

    Power controls specify DC-bus kW. Voltage sources regulate their connected bus.
    Droop uses I=(Vref-V)/R, clipped to both power and current limits. Efficiency
    maps the solved bus power to the external source/storage boundary.
    """

    id: str
    bus: str
    mode: Literal["voltage", "power", "droop"] = "voltage"
    voltage_v: float = 400
    power_kw: float = 0
    max_source_kw: float = 1000
    max_sink_kw: float = 0
    max_current_a: float = 10000
    droop_ohm: float = 0.1
    efficiency: float = 0.97

    def __post_init__(self) -> None:
        if not self.id or not self.bus or self.mode not in {"voltage", "power", "droop"}:
            raise ValueError("invalid port identity/control")
        for name in ("voltage_v", "max_current_a", "droop_ohm"):
            finite(name, getattr(self, name), strict=True)
        for name in ("max_source_kw", "max_sink_kw"):
            finite(name, getattr(self, name))
        finite("power_kw", self.power_kw, -self.max_sink_kw)
        if self.power_kw > self.max_source_kw:
            raise ValueError("power setpoint exceeds port capacity")
        fraction("efficiency", self.efficiency, positive=True)

    def current(self, voltage_v: float) -> float:
        if self.mode == "power":
            return self.power_kw * 1000 / voltage_v
        if self.mode != "droop":
            raise ValueError("regulated source current is determined by the network")
        lower = -min(self.max_current_a, self.max_sink_kw * 1000 / voltage_v)
        upper = min(self.max_current_a, self.max_source_kw * 1000 / voltage_v)
        return float(np.clip((self.voltage_v - voltage_v) / self.droop_ohm, lower, upper))


@dataclass
class DCGridResult:
    buses: pd.DataFrame
    lines: pd.DataFrame
    ports: pd.DataFrame
    cable_loss_kw: float
    converter_loss_kw: float
    balance_error_kw: float
    maximum_kcl_error_a: float
    served_fraction: float
    unserved_kw: float
    warnings: tuple[str, ...]


class DCGrid:
    """Single-voltage DC graph, radial or meshed, with per-island voltage control.

    Newton/trust-region residual solve, initialized near nominal voltage. Power
    limits are checked after solving regulated sources; infeasibility is explicit.
    Different nominal voltages can occupy separate islands. Converter ports have
    external boundaries; coupling energy between islands is the caller's task.
    """

    def __init__(self, nominal_v: dict[str, float], lines: list[DCLine], ports: list[DCPort]):
        if not nominal_v or not ports:
            raise ValueError("grid needs buses and at least one converter port")
        self.nominal_v = dict(nominal_v)
        self.lines, self.ports = list(lines), list(ports)
        self.ids = list(nominal_v)
        self.index = {name: i for i, name in enumerate(self.ids)}
        for value in nominal_v.values():
            finite("nominal voltage", value, strict=True)
        if len({line.id for line in lines}) != len(lines) or len({p.id for p in ports}) != len(
            ports
        ):
            raise ValueError("line and port ids must be unique")
        self.conductance = np.zeros((len(self.ids), len(self.ids)))
        for line in lines:
            if line.source not in nominal_v or line.target not in nominal_v:
                raise ValueError("unknown line bus")
            if nominal_v[line.source] != nominal_v[line.target]:
                raise ValueError("different voltage levels need converter interfaces")
            i, j = self.index[line.source], self.index[line.target]
            g = 1 / line.loop_resistance_ohm
            self.conductance[i, i] += g
            self.conductance[j, j] += g
            self.conductance[i, j] -= g
            self.conductance[j, i] -= g
        if any(p.bus not in nominal_v for p in ports):
            raise ValueError("unknown port bus")
        regulated = [p.bus for p in ports if p.mode == "voltage"]
        if len(regulated) != len(set(regulated)):
            raise ValueError("only one ideal voltage controller per bus; use droop for sharing")
        unseen = set(self.ids)
        while unseen:
            component, frontier = set(), [next(iter(unseen))]
            while frontier:
                bus = frontier.pop()
                if bus in component:
                    continue
                component.add(bus)
                for line in lines:
                    if line.source == bus:
                        frontier.append(line.target)
                    if line.target == bus:
                        frontier.append(line.source)
            if not any(p.bus in component and p.mode in {"voltage", "droop"} for p in ports):
                raise ValueError("each energized island needs voltage or droop control")
            unseen -= component

    def solve(self, loads_kw: dict[str, float], *, tolerance_a: float = 1e-5) -> DCGridResult:
        if set(loads_kw) - set(self.ids):
            raise ValueError("unknown load bus")
        for value in loads_kw.values():
            finite("load_kw", value)
        finite("tolerance_a", tolerance_a, strict=True)
        load = np.asarray([loads_kw.get(bus, 0.0) for bus in self.ids]) * 1000
        nominal = np.asarray(list(self.nominal_v.values()), dtype=float)
        regulated = {self.index[p.bus]: p for p in self.ports if p.mode == "voltage"}
        unknown = [i for i in range(len(self.ids)) if i not in regulated]
        volts = nominal.copy()
        if any(p.mode == "droop" for p in self.ports):
            volts *= 0.98  # Start on the conducting side of the zero-current droop kink.
        for i, port in regulated.items():
            if not 0.5 * nominal[i] < port.voltage_v < 1.5 * nominal[i]:
                raise ValueError("regulated voltage outside study range")
            volts[i] = port.voltage_v

        def imbalance(v: NDArray[np.float64]) -> NDArray[np.float64]:
            residual = self.conductance @ v + load / v
            for p in self.ports:
                if p.mode != "voltage":
                    residual[self.index[p.bus]] -= p.current(float(v[self.index[p.bus]]))
            return residual

        if unknown:

            def residual(x: NDArray[np.float64]) -> NDArray[np.float64]:
                v = volts.copy()
                v[unknown] = x
                return imbalance(v)[unknown]

            solution = least_squares(
                residual,
                volts[unknown],
                bounds=(nominal[unknown] * 0.5, nominal[unknown] * 1.5),
                xtol=1e-12,
                ftol=1e-12,
                gtol=1e-12,
                max_nfev=2000,
            )
            volts[unknown] = solution.x
            if not solution.success or np.max(np.abs(residual(solution.x))) > tolerance_a:
                raise ValueError("DC grid infeasible/nonconvergent in 0.5–1.5 pu study range")
        required = imbalance(volts)
        source_rows = []
        for p in self.ports:
            i = self.index[p.bus]
            current = float(required[i]) if p.mode == "voltage" else p.current(float(volts[i]))
            power = current * volts[i] / 1000
            if (
                power > p.max_source_kw + 1e-6
                or power < -p.max_sink_kw - 1e-6
                or abs(current) > p.max_current_a + tolerance_a
            ):
                raise ValueError(f"port capacity exceeded: {p.id}")
            external = power / p.efficiency if power >= 0 else power * p.efficiency
            source_rows.append(
                {
                    "port": p.id,
                    "bus": p.bus,
                    "mode": p.mode,
                    "current_a": current,
                    "bus_kw": power,
                    "external_kw": external,
                    "loss_kw": external - power,
                }
            )
            if p.mode == "voltage":
                required[i] -= current
        line_rows, warnings = [], []
        for line in self.lines:
            a, b = self.index[line.source], self.index[line.target]
            current = float((volts[a] - volts[b]) / line.loop_resistance_ohm)
            loss = current**2 * line.loop_resistance_ohm / 1000
            if abs(current) > line.ampacity_a:
                warnings.append(f"line overload: {line.id}")
            line_rows.append(
                {
                    "line": line.id,
                    "source": line.source,
                    "target": line.target,
                    "current_a": current,
                    "loss_kw": loss,
                    "loading_pu": abs(current) / line.ampacity_a,
                }
            )
        bus_rows = [
            {
                "bus": bus,
                "voltage_v": float(volts[i]),
                "voltage_pu": float(volts[i] / nominal[i]),
                "load_kw": load[i] / 1000,
            }
            for i, bus in enumerate(self.ids)
        ]
        if np.any(volts / nominal < 0.9):
            warnings.append("bus undervoltage below 0.9 pu")
        lines_frame = pd.DataFrame(
            line_rows, columns=["line", "source", "target", "current_a", "loss_kw", "loading_pu"]
        ).set_index("line")
        ports_frame = pd.DataFrame(source_rows).set_index("port")
        losses = float(lines_frame.loss_kw.sum())
        return DCGridResult(
            pd.DataFrame(bus_rows).set_index("bus"),
            lines_frame,
            ports_frame,
            losses,
            float(ports_frame.loss_kw.sum()),
            float(ports_frame.bus_kw.sum() - load.sum() / 1000 - losses),
            float(np.max(np.abs(required))),
            1.0,
            0.0,
            tuple(warnings),
        )

    def solve_with_shedding(self, loads_kw: dict[str, float]) -> DCGridResult:
        """Explicit uniform demand shedding, using a monotone high-voltage feasibility search.

        For deficit studies only: surplus fixed generation must be curtailed by
        its controller first. The no-load endpoint must itself be feasible.
        """
        if set(loads_kw) - set(self.ids):
            raise ValueError("unknown load bus")
        for value in loads_kw.values():
            finite("load_kw", value)
        try:
            return self.solve(loads_kw)
        except ValueError:
            best = self.solve({bus: 0.0 for bus in loads_kw})
        low, high = 0.0, 1.0
        for _ in range(40):
            middle = (low + high) / 2
            try:
                candidate = self.solve({bus: p * middle for bus, p in loads_kw.items()})
                low, best = middle, candidate
            except ValueError:
                high = middle
        best.served_fraction = low
        best.unserved_kw = sum(loads_kw.values()) * (1 - low)
        best.warnings += ("uniform load shedding applied",)
        return best
