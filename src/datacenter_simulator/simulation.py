"""Couple device demand, DC distribution, cooling and facility energy dispatch."""

from dataclasses import asdict, dataclass
from typing import cast

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.generation import generation_from_series, validate_timeline
from datacenter_simulator.methods.communications import CommunicationNetwork
from datacenter_simulator.methods.cooling import CoolingPlant
from datacenter_simulator.methods.electrical import DCNetwork
from datacenter_simulator.methods.energy import Battery, dispatch
from datacenter_simulator.models import Device
from datacenter_simulator.models.devices import finite, fraction


@dataclass
class DataCenter:
    name: str
    devices: list[Device]
    electrical: DCNetwork
    communications: CommunicationNetwork
    cooling: CoolingPlant
    rectifier_efficiency: float = 0.97
    conditioned_loss_fraction: float = 1.0
    auxiliary_kw: float = 2.0

    def __post_init__(self) -> None:
        fraction("rectifier_efficiency", self.rectifier_efficiency, positive=True)
        fraction("conditioned_loss_fraction", self.conditioned_loss_fraction)
        finite("auxiliary_kw", self.auxiliary_kw)
        if not self.devices or len({d.id for d in self.devices}) != len(self.devices):
            raise ValueError("devices must be non-empty with unique ids")
        devices = {device.id: device for device in self.devices}
        if set(self.communications.nodes) - set(devices):
            raise ValueError("communication nodes must refer to devices")
        for device in self.devices:
            if device.bus_id not in self.electrical.buses:
                raise ValueError(f"unknown bus for {device.id}")
            nominal = self.electrical.buses[device.bus_id].nominal_voltage_v
            if not np.isclose(nominal, device.electrical.nominal_voltage_v):
                raise ValueError(f"device and bus voltage mismatch: {device.id}")
            links = [e for e in self.communications.links if device.id in (e.source, e.target)]
            if len(links) > device.communications.ports:
                raise ValueError(f"not enough communication ports: {device.id}")
            if any(e.capacity_gbps > device.communications.port_speed_gbps for e in links):
                raise ValueError(f"link exceeds device port speed: {device.id}")

    def bus_loads(self, utilization: float) -> dict[str, float]:
        loads = dict.fromkeys(self.electrical.buses, 0.0)
        for device in self.devices:
            loads[device.bus_id] += device.power_kw(utilization)
        return loads


@dataclass
class SimulationResult:
    timeseries: pd.DataFrame
    summary: dict[str, float]
    warnings: tuple[str, ...]


def simulate(
    center: DataCenter,
    profiles: pd.DataFrame,
    *,
    generation: dict[str, pd.Series] | None = None,
    battery: Battery | None = None,
    dt_hours: float = 1,
    grid_import_limit_kw: float = 1e9,
    grid_export_limit_kw: float = 0,
    backup_capacity_kw: float = 0,
) -> SimulationResult:
    """Evaluate interval-average profiles (utilization, ambient_c) on a regular timeline.

    PUE uses gross facility demand before generation/storage. Insufficient power or
    cooling is reported as unmet demand; there is no implicit IT load shedding or
    thermal throttling. All IT terminal power becomes heat; facility auxiliaries and
    rectifier are outside the conditioned room in this first model.
    """
    if not isinstance(profiles.index, pd.DatetimeIndex):
        raise ValueError("profiles require a DatetimeIndex")
    validate_timeline(profiles.index)
    finite("dt_hours", dt_hours, strict=True)
    if len(profiles) > 1:
        # pandas may store datetime values in s/ms/us/ns; use timedeltas, not raw integers.
        spacing = (profiles.index[1:] - profiles.index[:-1]).total_seconds().to_numpy() / 3600
        if not np.allclose(spacing, dt_hours, rtol=0, atol=1e-9):
            raise ValueError("profile intervals must match dt_hours")
    if not {"utilization", "ambient_c"} <= set(profiles.columns):
        raise ValueError("profiles need utilization and ambient_c columns")
    values = profiles[["utilization", "ambient_c"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("profile values must be finite")
    sources = {
        name: generation_from_series(series, profiles.index)
        for name, series in (generation or {}).items()
    }
    energy = battery.initial_soc * battery.capacity_kwh if battery else 0.0
    rows = []
    warnings: set[str] = set()
    for position, sample in enumerate(values):
        electrical = center.electrical.solve(center.bus_loads(float(sample[0])))
        warnings.update(electrical.warnings)
        for device in center.devices:
            pu = cast(float, electrical.buses.at[device.bus_id, "voltage_pu"])
            if pu < device.electrical.minimum_voltage_pu:
                warnings.add(f"Device input undervoltage: {device.id}")
        room_heat = electrical.load_kw + electrical.loss_kw * center.conditioned_loss_fraction
        cooling = center.cooling.evaluate(room_heat, float(sample[1]))
        rectifier_loss = electrical.source_kw * (1 / center.rectifier_efficiency - 1)
        facility = electrical.source_kw + rectifier_loss + cooling.electric_kw + center.auxiliary_kw
        generated = sum(float(series.iloc[position]) for series in sources.values())
        balance = dispatch(
            facility,
            generated,
            dt_hours,
            battery=battery,
            energy_kwh=energy,
            grid_import_limit_kw=grid_import_limit_kw,
            grid_export_limit_kw=grid_export_limit_kw,
            backup_capacity_kw=backup_capacity_kw,
        )
        energy = balance.battery_energy_kwh
        if cooling.unmet_heat_kw > 1e-8:
            warnings.add("Cooling capacity insufficient; requested IT demand is retained")
        if balance.unserved_kw > 1e-8:
            warnings.add("Electrical supply insufficient; requested IT demand is retained")
        row = {
            "it_kw": electrical.load_kw,
            "dc_loss_kw": electrical.loss_kw,
            "rectifier_loss_kw": rectifier_loss,
            "room_heat_kw": room_heat,
            "cooling_kw": cooling.electric_kw,
            "auxiliary_kw": center.auxiliary_kw,
            "facility_kw": facility,
            "heat_rejected_kw": cooling.rejected_heat_kw,
            "unmet_heat_kw": cooling.unmet_heat_kw,
            "economizer_active": cooling.economizer_active,
            "minimum_voltage_pu": float(electrical.buses["voltage_pu"].min()),
            "liquid_flow_kg_s": cooling.liquid_flow_kg_s,
            "air_flow_m3_s": cooling.air_flow_m3_s,
            "pue": facility / electrical.load_kw if electrical.load_kw else float("nan"),
            **asdict(balance),
        }
        row.update(
            {
                f"generation:{name}:kw": float(series.iloc[position])
                for name, series in sources.items()
            }
        )
        rows.append(row)
    frame = pd.DataFrame(rows, index=profiles.index)
    summary = {
        column.removesuffix("_kw") + "_kwh": float(frame[column].sum() * dt_hours)
        for column in (
            "it_kw",
            "dc_loss_kw",
            "rectifier_loss_kw",
            "cooling_kw",
            "facility_kw",
            "generation_kw",
            "grid_import_kw",
            "grid_export_kw",
            "unserved_kw",
            "unmet_heat_kw",
            "curtailed_kw",
            "backup_kw",
            "charge_kw",
            "discharge_kw",
            "battery_loss_kw",
        )
    }
    summary["pue"] = (
        summary["facility_kwh"] / summary["it_kwh"] if summary["it_kwh"] else float("nan")
    )
    summary["peak_facility_kw"] = float(frame.facility_kw.max())
    summary["final_battery_energy_kwh"] = energy
    summary["max_balance_error_kw"] = float(frame.balance_error_kw.abs().max())
    return SimulationResult(frame, summary, tuple(sorted(warnings)))
