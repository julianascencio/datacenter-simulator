"""Device metadata and utilization-dependent terminal power (SI-derived units)."""

from dataclasses import dataclass, field
from math import isfinite


def finite(name: str, value: float, minimum: float = 0, *, strict: bool = False) -> None:
    """Reject non-finite and out-of-range model inputs."""
    if not isfinite(value) or value < minimum or (strict and value == minimum):
        raise ValueError(f"{name} must be finite and {'>' if strict else '>='} {minimum}")


def fraction(name: str, value: float, *, positive: bool = False) -> None:
    finite(name, value, strict=positive)
    if value > 1:
        raise ValueError(f"{name} must be <= 1")


@dataclass(frozen=True)
class Electrical:
    """Power measured at a device's DC input, including its internal PSU losses."""

    nominal_voltage_v: float
    idle_kw: float
    peak_kw: float
    power_exponent: float = 1.0
    minimum_voltage_pu: float = 0.90

    def __post_init__(self) -> None:
        finite("nominal_voltage_v", self.nominal_voltage_v, strict=True)
        finite("idle_kw", self.idle_kw)
        finite("peak_kw", self.peak_kw)
        finite("power_exponent", self.power_exponent, strict=True)
        fraction("minimum_voltage_pu", self.minimum_voltage_pu, positive=True)
        if self.peak_kw < self.idle_kw:
            raise ValueError("peak_kw must be >= idle_kw")

    def power_kw(self, utilization: float) -> float:
        fraction("utilization", utilization)
        return self.idle_kw + (self.peak_kw - self.idle_kw) * utilization**self.power_exponent


@dataclass(frozen=True)
class Communications:
    """Port and management metadata; protocols are descriptors, not live clients."""

    ports: int = 2
    port_speed_gbps: float = 100.0
    protocols: tuple[str, ...] = ("Ethernet", "Redfish")
    management_address: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ports, int) or self.ports < 1:
            raise ValueError("ports must be a positive integer")
        finite("port_speed_gbps", self.port_speed_gbps, strict=True)


@dataclass(frozen=True)
class Placement:
    """Equipment lower-left-front coordinates and dimensions, all in metres."""

    x_m: float = 0
    y_m: float = 0
    z_m: float = 0
    width_m: float = 0.6
    depth_m: float = 1.2
    height_m: float = 2.0

    def __post_init__(self) -> None:
        for name in ("x_m", "y_m", "z_m"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        for name in ("width_m", "depth_m", "height_m"):
            finite(name, getattr(self, name), strict=True)


@dataclass(frozen=True)
class Device:
    """A server, rack aggregate, switch or storage device linked to a DC bus."""

    id: str
    kind: str
    bus_id: str
    electrical: Electrical
    communications: Communications = field(default_factory=Communications)
    placement: Placement = field(default_factory=Placement)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.kind or not self.bus_id:
            raise ValueError("device id, kind and bus_id must be non-empty")

    def power_kw(self, utilization: float) -> float:
        return self.electrical.power_kw(utilization)
