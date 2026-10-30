"""Read measured curves and replay environmental telemetry without live writes."""

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import pandas as pd

from datacenter_simulator.models.performance import PowerCurve, Provenance


def power_curve_from_csv(path: str | Path, provenance: Provenance) -> PowerCurve:
    frame = pd.read_csv(path)
    if not {"utilization", "power_kw"} <= set(frame):
        raise ValueError("curve CSV needs utilization and power_kw")
    return PowerCurve(tuple(frame.utilization), tuple(frame.power_kw), provenance)


def specpower_reference() -> PowerCurve:
    """Published Compal SR224-2A CPU benchmark; AC input, target throughput fraction.

    This benchmark is not a GPU profile and cannot be inserted as DC terminal power.
    """
    data = files("datacenter_simulator").joinpath("data/specpower_compal.json")
    metadata = json.loads(data.read_text())
    with files("datacenter_simulator").joinpath("data/specpower_compal.csv").open("r") as handle:
        frame = pd.read_csv(handle)
    return PowerCurve(
        tuple(frame.utilization), tuple(frame.power_kw), Provenance(**metadata["provenance"])
    )


def redfish_environment_metrics(payload: dict[str, Any], *, equipment_id: str) -> dict[str, Any]:
    """Normalize an already-retrieved EnvironmentMetrics payload, preserving nulls."""
    if not equipment_id:
        raise ValueError("equipment_id is required")
    output: dict[str, Any] = {"equipment_id": equipment_id, "source_id": payload.get("@odata.id")}
    for original, normalized in (
        ("PowerWatts", "power_w"),
        ("TemperatureCelsius", "temperature_c"),
        ("EnergykWh", "energy_kwh"),
    ):
        value = payload.get(original)
        output[normalized] = value.get("Reading") if isinstance(value, dict) else None
    return output
