"""Strict hourly weather CSV/PVGIS adapters; explicit TMY calendar remapping."""

import json
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.generation import validate_timeline
from datacenter_simulator.models.devices import finite


def validate_weather(frame: pd.DataFrame) -> None:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("weather needs a DatetimeIndex")
    validate_timeline(frame.index)
    required = ["ambient_c", "relative_humidity", "pressure_pa"]
    if not set(required) <= set(frame):
        raise ValueError("weather needs ambient_c, relative_humidity and pressure_pa")
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("weather values must be finite")
    if ((frame.ambient_c < -30) | (frame.ambient_c > 60)).any():
        raise ValueError("weather outside psychrometric study range")
    if ((frame.relative_humidity <= 0) | (frame.relative_humidity > 1)).any():
        raise ValueError("relative humidity must be a fraction in (0, 1]")
    if (frame.pressure_pa <= 30000).any():
        raise ValueError("pressure must be in Pa and above 30000")
    if len(frame) > 1 and not np.allclose(
        (frame.index[1:] - frame.index[:-1]).total_seconds(), 3600
    ):
        raise ValueError("weather must have regular hourly intervals")


def weather_from_csv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True)
    validate_weather(frame)
    return frame


def weather_from_pvgis(payload: dict[str, Any], *, calendar_year: int = 2021) -> pd.DataFrame:
    """Map selected TMY months to a non-leap synthetic year, preserving source time.

    PVGIS TMY is a composite climatological year, not a historical measurement.
    """
    rows = pd.DataFrame(payload["outputs"]["tmy_hourly"])
    if len(rows) != 8760 or pd.Timestamp(calendar_year, 12, 31).dayofyear != 365:
        raise ValueError("TMY requires 8760 records and a non-leap calendar")
    source = pd.to_datetime(rows["time(UTC)"], format="%Y%m%d:%H%M", utc=True)
    mapped = pd.DatetimeIndex([t.replace(year=calendar_year) for t in source])
    frame = pd.DataFrame(
        {
            "ambient_c": rows.T2m.to_numpy(),
            "relative_humidity": rows.RH.to_numpy() / 100,
            "pressure_pa": rows.SP.to_numpy(),
            "ghi_w_m2": rows["G(h)"].to_numpy(),
            "dni_w_m2": rows["Gb(n)"].to_numpy(),
            "dhi_w_m2": rows["Gd(h)"].to_numpy(),
            "wind_speed_m_s": rows.WS10m.to_numpy(),
            "source_timestamp": source.astype(str),
        },
        index=mapped,
    )
    frame.index.name = "timestamp"
    frame = frame.sort_index()
    validate_weather(frame)
    return frame


def fetch_pvgis_tmy(
    latitude: float, longitude: float, *, timeout_s: float = 30
) -> tuple[pd.DataFrame, dict[str, Any]]:
    finite("latitude", latitude, -90)
    finite("longitude", longitude, -180)
    finite("timeout_s", timeout_s, strict=True)
    if latitude > 90 or longitude > 180:
        raise ValueError("invalid coordinates")
    url = "https://re.jrc.ec.europa.eu/api/v5_3/tmy?" + urlencode(
        {"lat": latitude, "lon": longitude, "outputformat": "json"}
    )
    with urlopen(url, timeout=timeout_s) as response:
        payload = json.load(response)
    return weather_from_pvgis(payload), {
        "url": url,
        "inputs": payload["inputs"],
        "months_selected": payload["outputs"]["months_selected"],
    }


def bundled_weather(name: str) -> pd.DataFrame:
    """Load an attributed offline TMY snapshot: tenerife, frankfurt or seville."""
    if name not in {"tenerife", "frankfurt", "seville"}:
        raise ValueError("unknown bundled climate")
    resource = files("datacenter_simulator").joinpath(f"data/weather_{name}.csv")
    with resource.open("r") as handle:
        frame = pd.read_csv(handle)
    frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True)
    validate_weather(frame)
    return frame
