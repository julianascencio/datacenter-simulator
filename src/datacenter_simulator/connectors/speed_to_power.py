"""Offline profiles and a version-pinned connector to the authors' result CSV.

No upstream Python or pickle is imported or executed. Published result tables
remain distinct from locally simulated engineering scenarios.
"""

import hashlib
import io
import json
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.generation import validate_timeline
from datacenter_simulator.models.devices import finite

PUBLISHED_ARCHITECTURES = ("ac_coupled", "dc_coupled", "natural_gas", "grid")


def speed_power_sources() -> dict[str, Any]:
    """Return paper sections, source commit, hashes, assumptions and limitations."""
    return json.loads(
        files("datacenter_simulator").joinpath("data/speed_to_power_sources.json").read_text()
    )  # type: ignore[no-any-return]


def validate_published_results(frame: pd.DataFrame) -> None:
    """Reject missing results, unknown topologies, invalid units and duplicate sites."""
    costs = [f"{a}_{kind}_lcoe" for a in PUBLISHED_ARCHITECTURES for kind in ("base", "total")]
    costs += ["natural_gas_threeyr_base_lcoe", "natural_gas_threeyr_total_lcoe"]
    numeric = ["gpu_count", "latitude", "longitude", "annual_pue", "annual_energy_mwh"] + costs
    required = set(numeric + ["h3_index", "ac_topology", "dc_topology"])
    if frame.empty or not required <= set(frame):
        raise ValueError("published results are empty or missing required columns")
    if not np.isfinite(frame[numeric].to_numpy(dtype=float)).all():
        raise ValueError("published results must be finite")
    if (frame[costs] < 0).any().any() or (frame.annual_pue < 1).any():
        raise ValueError("invalid published costs or PUE")
    if (frame.annual_energy_mwh <= 0).any() or (frame.gpu_count <= 0).any():
        raise ValueError("published energy and GPU counts must be positive")
    if (frame.gpu_count % 1 != 0).any():
        raise ValueError("GPU count must be integral")
    if (frame.latitude.abs() > 90).any() or (frame.longitude.abs() > 180).any():
        raise ValueError("invalid coordinates")
    if frame.h3_index.isna().any() or frame.duplicated(["h3_index", "gpu_count"]).any():
        raise ValueError("published site/GPU pairs must be unique and identified")
    for col in ("ac_topology", "dc_topology"):
        if not frame[col].isin(["lv_direct", "mv_coupled"]).all():
            raise ValueError("unrecognized upstream topology")
    for architecture in (*PUBLISHED_ARCHITECTURES, "natural_gas_threeyr"):
        if (frame[f"{architecture}_total_lcoe"] < frame[f"{architecture}_base_lcoe"]).any():
            raise ValueError("speed-adjusted LCOE cannot be below base LCOE")


def published_results_from_csv(path: str | Path) -> pd.DataFrame:
    """Read the authors' wide schema, retaining topology and auxiliary columns."""
    frame = pd.read_csv(path)
    validate_published_results(frame)
    return frame


def bundled_published_results() -> pd.DataFrame:
    """All 4,317 MV, 100,000-GPU locations, with a verified snapshot hash."""
    payload = (
        files("datacenter_simulator").joinpath("data/speed_to_power_published.csv").read_bytes()
    )
    if hashlib.sha256(payload).hexdigest() != speed_power_sources()["snapshot_sha256"]:
        raise ValueError("published snapshot hash mismatch")
    frame = pd.read_csv(io.BytesIO(payload))
    validate_published_results(frame)
    return frame


def fetch_published_results(*, timeout_s: float = 30) -> pd.DataFrame:
    """Explicit opt-in fetch of the pinned full upstream CSV, verified by SHA-256.

    Returns all GPU scales. Filter GPU count/topology before summarizing. No
    credentials, current rental-price API, or hidden network calls are used.
    """
    finite("timeout_s", timeout_s, strict=True)
    source = speed_power_sources()
    url = (
        "https://raw.githubusercontent.com/acnewkirk/AI-Datacenter-Microgrid-Analysis/"
        f"{source['upstream_commit']}/{source['upstream_path']}"
    )
    with urlopen(url, timeout=timeout_s) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != source["upstream_sha256"]:
        raise ValueError("upstream result hash mismatch")
    frame = pd.read_csv(io.BytesIO(payload))
    validate_published_results(frame)
    return frame


def validate_power_profiles(frame: pd.DataFrame, *, annual: bool = False) -> None:
    """Hourly IT kW, cooling-terminal kW and pre-conversion PV DC kW/kWp.

    The cooling column excludes electrical conversion losses, avoiding PUE
    double counting. Missing, naive, duplicate or irregular hours are rejected.
    """
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("profiles need a DatetimeIndex")
    validate_timeline(frame.index)
    if len(frame) > 1 and not np.allclose(
        (frame.index[1:] - frame.index[:-1]).total_seconds(), 3600
    ):
        raise ValueError("profiles must be regularly hourly")
    columns = ["it_kw", "cooling_kw", "pv_dc_per_kwp"]
    if not set(columns) <= set(frame):
        raise ValueError("profiles need it_kw, cooling_kw and pv_dc_per_kwp")
    values = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (frame.it_kw <= 0).any():
        raise ValueError("profiles require finite nonnegative values and positive IT load")
    if annual and len(frame) != 8760:
        raise ValueError("annual economics require exactly 8760 hourly intervals")


def power_profiles_from_csv(path: str | Path, *, annual: bool = True) -> pd.DataFrame:
    frame = pd.read_csv(path)
    stamps = [pd.Timestamp(value) for value in frame.pop("timestamp")]
    if any(s.tzinfo is None for s in stamps):
        raise ValueError("timestamps require an explicit timezone")
    frame.index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True), name="timestamp")
    validate_power_profiles(frame, annual=annual)
    return frame


def profiles_from_components(
    it_kw: pd.Series, cooling_kw: pd.Series, pv_dc_kw: pd.Series, *, pv_rating_kwp: float
) -> pd.DataFrame:
    """Connect weather/cooling, SCADA or existing pvlib outputs without resampling.

    ``pv_dc_kw`` is the existing ``pv_from_weather`` adapter's DC output, never
    its inverter AC output. Each input must use precisely the same timeline.
    """
    finite("pv_rating_kwp", pv_rating_kwp, strict=True)
    if not it_kw.index.equals(cooling_kw.index) or not it_kw.index.equals(pv_dc_kw.index):
        raise ValueError("component profiles must have exactly aligned timestamps")
    frame = pd.DataFrame(
        {"it_kw": it_kw, "cooling_kw": cooling_kw, "pv_dc_per_kwp": pv_dc_kw / pv_rating_kwp}
    )
    validate_power_profiles(frame)
    return frame
