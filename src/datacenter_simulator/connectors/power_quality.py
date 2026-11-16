"""Offline load-trace and externally computed line-to-line Pst contracts."""

from pathlib import Path

import numpy as np
import pandas as pd

from datacenter_simulator.methods.power_quality import validate_power_profile


def read_power_profile(path: str | Path) -> pd.DataFrame:
    """Read receiving-PCC MW/Mvar at uniform interval starts in seconds."""
    frame = pd.read_csv(path)
    validate_power_profile(frame)
    return frame


def summarize_line_to_line_pst(measurements: pd.DataFrame) -> pd.DataFrame:
    """Summarize external 600 s AB/BC/CA results, retaining the worst channel.

    Required fields: case, window_start_s, duration_s, channel, pst, meter,
    waveform_reference. ``meter`` must identify the external implementation /
    version; ``waveform_reference`` identifies the source waveform export.
    This checks the data contract, not IEC meter validation or grid compliance.
    Positive-sequence results and incomplete/duplicate channel sets are rejected.
    """
    columns = {
        "case",
        "window_start_s",
        "duration_s",
        "channel",
        "pst",
        "meter",
        "waveform_reference",
    }
    if measurements.empty or not columns.issubset(measurements.columns):
        raise ValueError(
            "external Pst data require case/window/channel/pst/meter/waveform metadata"
        )
    frame = measurements.reset_index(drop=True).copy()
    for column in ("case", "channel", "meter", "waveform_reference"):
        if (
            not frame[column]
            .map(lambda value: isinstance(value, str) and bool(value.strip()))
            .all()
        ):
            raise ValueError(f"{column} must contain nonempty strings")
    values = frame[["window_start_s", "duration_s", "pst"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Pst and window fields must be finite and nonnegative")
    if not np.allclose(values[:, 1], 600, rtol=0, atol=1e-9):
        raise ValueError("this importer requires complete 600 s Pst windows")
    frame["pst"] = values[:, 2]
    rows = []
    for (case, start), group in frame.groupby(["case", "window_start_s"], sort=True):
        if len(group) != 3 or set(group.channel) != {"AB", "BC", "CA"}:
            raise ValueError("each case/window needs exactly AB, BC and CA")
        if group.meter.nunique() != 1 or group.waveform_reference.nunique() != 1:
            raise ValueError("channels must share a meter and waveform reference")
        worst = group.iloc[int(group.pst.to_numpy().argmax())]
        rows.append(
            {
                "case": case,
                "window_start_s": start,
                "duration_s": 600,
                "worst_channel": worst.channel,
                "pst_max": float(worst.pst),
                "meter": worst.meter,
                "waveform_reference": worst.waveform_reference,
                "status": "external results; meter validation not checked",
            }
        )
    return pd.DataFrame(rows)
