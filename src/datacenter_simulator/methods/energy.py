"""Facility-bus dispatch with explicit battery state and conservation accounting."""

from dataclasses import dataclass

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class Battery:
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    charge_efficiency: float = 0.96
    discharge_efficiency: float = 0.96
    minimum_soc: float = 0.10
    maximum_soc: float = 0.95
    initial_soc: float = 0.5

    def __post_init__(self) -> None:
        finite("capacity_kwh", self.capacity_kwh, strict=True)
        finite("max_charge_kw", self.max_charge_kw)
        finite("max_discharge_kw", self.max_discharge_kw)
        for name in ("charge_efficiency", "discharge_efficiency"):
            fraction(name, getattr(self, name), positive=True)
        for name in ("minimum_soc", "maximum_soc", "initial_soc"):
            fraction(name, getattr(self, name))
        if not self.minimum_soc <= self.initial_soc <= self.maximum_soc:
            raise ValueError("initial SOC must lie within battery bounds")
        if self.minimum_soc >= self.maximum_soc:
            raise ValueError("minimum_soc must be smaller than maximum_soc")


@dataclass(frozen=True)
class DispatchResult:
    generation_kw: float
    charge_kw: float
    discharge_kw: float
    grid_import_kw: float
    grid_export_kw: float
    backup_kw: float
    curtailed_kw: float
    unserved_kw: float
    battery_energy_kwh: float
    battery_loss_kw: float
    balance_error_kw: float


def dispatch(
    demand_kw: float,
    generation_kw: float,
    dt_hours: float,
    *,
    battery: Battery | None = None,
    energy_kwh: float = 0,
    grid_import_limit_kw: float = 1e9,
    grid_export_limit_kw: float = 0,
    backup_capacity_kw: float = 0,
) -> DispatchResult:
    """Generation -> storage -> grid -> backup; surplus charges then exports/curtails.

    Charge/discharge are powers at the common facility bus. Grid outage is limit=0.
    Backup is ideal available electrical capacity (no start delay, fuel or ramp model).
    """
    for name, value in (
        ("demand_kw", demand_kw),
        ("generation_kw", generation_kw),
        ("energy_kwh", energy_kwh),
        ("grid_import_limit_kw", grid_import_limit_kw),
        ("grid_export_limit_kw", grid_export_limit_kw),
        ("backup_capacity_kw", backup_capacity_kw),
    ):
        finite(name, value)
    finite("dt_hours", dt_hours, strict=True)
    if battery is None and energy_kwh != 0:
        raise ValueError("energy_kwh requires a battery")
    if battery is not None and not (
        battery.minimum_soc * battery.capacity_kwh - 1e-8
        <= energy_kwh
        <= battery.maximum_soc * battery.capacity_kwh + 1e-8
    ):
        raise ValueError("battery energy outside SOC bounds")
    residual = demand_kw - generation_kw
    charge = discharge = battery_loss = 0.0
    if battery is not None:
        if residual > 0:
            available = max(0, energy_kwh - battery.minimum_soc * battery.capacity_kwh)
            discharge = min(
                residual,
                battery.max_discharge_kw,
                available * battery.discharge_efficiency / dt_hours,
            )
            energy_kwh -= discharge * dt_hours / battery.discharge_efficiency
            battery_loss = discharge * (1 / battery.discharge_efficiency - 1)
        else:
            room = max(0, battery.maximum_soc * battery.capacity_kwh - energy_kwh)
            charge = min(
                -residual, battery.max_charge_kw, room / (battery.charge_efficiency * dt_hours)
            )
            energy_kwh += charge * dt_hours * battery.charge_efficiency
            battery_loss = charge * (1 - battery.charge_efficiency)
    residual += charge - discharge
    imported = min(max(0, residual), grid_import_limit_kw)
    backup = min(max(0, residual - imported), backup_capacity_kw)
    unserved = max(0, residual - imported - backup)
    exported = min(max(0, -residual), grid_export_limit_kw)
    curtailed = max(0, -residual - exported)
    balance = (
        generation_kw
        + discharge
        + imported
        + backup
        + unserved
        - (demand_kw + charge + exported + curtailed)
    )
    return DispatchResult(
        generation_kw,
        charge,
        discharge,
        imported,
        exported,
        backup,
        curtailed,
        unserved,
        energy_kwh,
        battery_loss,
        balance,
    )
