"""Balanced AC planning models; powers are three-phase MW/Mvar/MVA."""

from dataclasses import dataclass
from math import hypot

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class WeakGrid:
    """Thevenin source, with SCR defined on ``base_mva`` at nominal voltage.

    X/R, source voltage and defaults beyond 200 MVA/35 kV/SCR 4 are
    illustrative. The source impedance terminates at the PCC; downstream
    transformer/UPS dynamics are outside this model.
    """

    base_mva: float = 200
    nominal_kv: float = 35
    scr: float = 4
    x_over_r: float = 10
    source_voltage_pu: float = 1.05

    def __post_init__(self) -> None:
        for name in ("base_mva", "nominal_kv", "scr", "source_voltage_pu"):
            finite(name, getattr(self, name), strict=True)
        finite("x_over_r", self.x_over_r)

    @property
    def impedance_pu(self) -> complex:
        r = 1 / (self.scr * hypot(1, self.x_over_r))
        return complex(r, r * self.x_over_r)

    @property
    def impedance_ohm(self) -> complex:
        return self.impedance_pu * self.nominal_kv**2 / self.base_mva

    @property
    def short_circuit_mva(self) -> float:
        return self.scr * self.base_mva


@dataclass(frozen=True)
class EStatcom:
    """P-priority converter and finite supercapacitor energy inventory.

    Positive P/Q inject into the PCC; negative Q absorbs. Energy is DC-side.
    Default 452 MJ assumes H=E_nom/S_converter=4.52 s at 100 MVA; the post
    does not establish that H basis or the usable window. Voltage gain is
    algebraic proportional droop, not a dynamic vendor controller. Losses
    cover active charge/discharge only.
    """

    rating_mva: float = 100
    active_limit_mw: float = 100
    nominal_energy_mj: float = 452
    minimum_soc: float = 0.1
    maximum_soc: float = 0.9
    initial_soc: float = 0.5
    charge_efficiency: float = 0.98
    discharge_efficiency: float = 0.98
    smoothing_tau_s: float = 1
    recovery_tau_s: float = 20
    voltage_reference_pu: float = 1.0
    voltage_gain_mvar_per_pu: float = 800

    def __post_init__(self) -> None:
        for name in ("rating_mva", "smoothing_tau_s", "recovery_tau_s", "voltage_reference_pu"):
            finite(name, getattr(self, name), strict=True)
        for name in ("active_limit_mw", "nominal_energy_mj", "voltage_gain_mvar_per_pu"):
            finite(name, getattr(self, name))
        for name in ("minimum_soc", "maximum_soc", "initial_soc"):
            fraction(name, getattr(self, name))
        for name in ("charge_efficiency", "discharge_efficiency"):
            fraction(name, getattr(self, name), positive=True)
        if not self.minimum_soc <= self.initial_soc <= self.maximum_soc:
            raise ValueError("initial SOC must be inside the operating window")
        if self.minimum_soc >= self.maximum_soc:
            raise ValueError("SOC operating window must have positive width")
        if self.active_limit_mw > self.rating_mva:
            raise ValueError("active limit must not exceed converter rating")

    @property
    def usable_energy_mj(self) -> float:
        return self.nominal_energy_mj * (self.maximum_soc - self.minimum_soc)

    @property
    def nominal_energy_kwh(self) -> float:
        return self.nominal_energy_mj / 3.6
