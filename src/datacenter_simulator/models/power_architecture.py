"""Explicit boundaries for illustrative AC/800 VDC architecture studies."""

from dataclasses import dataclass

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class PowerStage:
    """Constant-efficiency equipment block, ordered from source to IT terminal.

    A block may contain several internal conversions (e.g. an SST or AC UPS).
    Efficiency is an assumption at the study load, not a product rating.
    """

    name: str
    efficiency: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("stage name is required")
        fraction("efficiency", self.efficiency, positive=True)


@dataclass(frozen=True)
class PowerArchitecture:
    id: str
    stages: tuple[PowerStage, ...]
    ac_dc_location: str
    backup_location: str

    def __post_init__(self) -> None:
        if not self.id or not self.ac_dc_location or not self.backup_location:
            raise ValueError("architecture identity and boundary descriptions are required")
        if not self.stages or len({s.name for s in self.stages}) != len(self.stages):
            raise ValueError("architecture needs nonempty, uniquely named stages")


@dataclass(frozen=True)
class CapacitorPath:
    """Independent RC discharge path to a fault; resistance includes the loop.

    None means the capacitor remains connected throughout the observation.
    Use None for a local load-side capacitor that an upstream breaker cannot
    isolate. Ideal reverse blocking is represented by omitting a remote path.
    """

    name: str
    capacitance_f: float
    resistance_ohm: float
    disconnect_after_s: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("capacitor path name is required")
        finite("capacitance_f", self.capacitance_f, strict=True)
        finite("resistance_ohm", self.resistance_ohm, strict=True)
        if self.disconnect_after_s is not None:
            finite("disconnect_after_s", self.disconnect_after_s)


@dataclass(frozen=True)
class LimitedSourcePath:
    """Nominal-voltage energy envelope for a current-limited converter or storage.

    Current limiting is assumed effective immediately. An energy cap is at the
    bus-side boundary after conversion losses. This is not a battery short-
    circuit model: directly coupled batteries require a different model.
    """

    name: str
    current_limit_a: float
    disconnect_after_s: float
    available_energy_j: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("source path name is required")
        finite("current_limit_a", self.current_limit_a)
        finite("disconnect_after_s", self.disconnect_after_s)
        if self.available_energy_j is not None:
            finite("available_energy_j", self.available_energy_j)


@dataclass(frozen=True)
class PowerStudyInputs:
    """Synthetic 5 MW hall; every numerical default is illustrative."""

    it_kw: float = 5000
    operating_hours: float = 8760
    electricity_per_kwh: float = 0.10
    transformer_efficiency: float = 0.99
    ups_efficiency: float = 0.97
    rack_rectifier_efficiency: float = 0.965
    sidecar_rectifier_efficiency: float = 0.985
    rack_dc_dc_efficiency: float = 0.975
    sst_efficiency: float = 0.975
    bus_voltage_v: float = 800
    minimum_bus_voltage_v: float = 720
    capacitor_hold_s: float = 0.020
    backup_duration_s: float = 60
    backup_efficiency: float = 0.96
    usable_soc_fraction: float = 0.80

    def __post_init__(self) -> None:
        finite("it_kw", self.it_kw, strict=True)
        finite("operating_hours", self.operating_hours)
        if self.operating_hours > 8760:
            raise ValueError("operating_hours must be <= 8760 for this annual study")
        finite("electricity_per_kwh", self.electricity_per_kwh)
        for name in (
            "transformer_efficiency",
            "ups_efficiency",
            "rack_rectifier_efficiency",
            "sidecar_rectifier_efficiency",
            "rack_dc_dc_efficiency",
            "sst_efficiency",
            "backup_efficiency",
            "usable_soc_fraction",
        ):
            fraction(name, getattr(self, name), positive=True)
        for name in ("bus_voltage_v", "minimum_bus_voltage_v"):
            finite(name, getattr(self, name), strict=True)
        if self.minimum_bus_voltage_v >= self.bus_voltage_v:
            raise ValueError("minimum bus voltage must be below initial bus voltage")
        for name in ("capacitor_hold_s", "backup_duration_s"):
            finite(name, getattr(self, name))
