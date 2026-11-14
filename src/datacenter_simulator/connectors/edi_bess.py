"""Energy Data Insights PVGIS bridge with a hashed offline screening snapshot."""

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.generation import generation_from_series
from datacenter_simulator.models.devices import finite


def load_edi_solar_snapshot(
    *, dc_rating_kwp: float, directory: str | Path | None = None
) -> tuple[pd.Series, dict[str, Any]]:
    """Load the attributed EDI/PVGIS Madrid week, verify bytes, scale 1 kWp.

    Defaults to packaged data; runtime examples never require API credentials.
    Source timestamps are retained, including PVGIS's ten-minute offset. This
    is resource/model output used as hourly representative power, not telemetry.
    """
    finite("dc_rating_kwp", dc_rating_kwp)
    root = files("datacenter_simulator").joinpath("data") if directory is None else Path(directory)
    payload = root.joinpath("bess_madrid_pvgis.csv").read_bytes()
    metadata = json.loads(root.joinpath("bess_madrid_pvgis.json").read_text())
    if hashlib.sha256(payload).hexdigest() != metadata["csv_sha256"]:
        raise ValueError("EDI solar snapshot checksum mismatch")
    from io import BytesIO

    frame = pd.read_csv(BytesIO(payload))
    stamps = [pd.Timestamp(value) for value in frame.timestamp]
    if any(t.tzinfo is None for t in stamps):
        raise ValueError("solar snapshot timestamps must carry UTC offsets")
    index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True))
    power = pd.Series(frame.pv_kw_per_kwp.to_numpy() * dc_rating_kwp, index=index, name="solar_kw")
    power = generation_from_series(power, index)
    if len(index) < 2 or not np.all((index[1:] - index[:-1]).total_seconds() == 3600):
        raise ValueError("EDI snapshot must have complete hourly spacing")
    return power, metadata


def retrieve_edi_pvgis_year(output: str | Path, *, year: int = 2023) -> None:
    """Explicit opt-in refresh; save native EDI response and its provenance.

    Requires the optional ``edi`` extra (Python >=3.12). Native response stays
    separate: review inputs, time semantics and chosen window before replacing
    the packaged subset. This function does not silently mutate a reference set.
    """
    import os
    import ssl

    import httpx
    from energy_data_retrieval.sources.pvgis import PVGIS_HOSTS, PVGISClient
    from energy_data_retrieval.transport import HTTPClient

    transport = httpx.HTTPTransport(
        proxy=os.environ.get("HTTPS_PROXY"),
        verify=ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE")),
    )
    with HTTPClient(PVGIS_HOSTS, transport=transport) as http:
        response = PVGISClient(http).hourly(
            40.4168,
            -3.7038,
            startyear=year,
            endyear=year,
            pvcalculation=True,
            peakpower=1,
            loss=14,
            angle=30,
            aspect=0,
        )
        response.save(Path(output))
