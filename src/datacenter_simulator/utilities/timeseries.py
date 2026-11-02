"""Conservative resampling shared by workload and measured-trace replay."""

import numpy as np
import pandas as pd

from datacenter_simulator.models.devices import finite


def resample_intervals(
    intervals: pd.DataFrame,
    start: pd.Timestamp,
    *,
    step_s: float,
) -> pd.Series:
    """Integrate contiguous interval-average kW by overlap, with zero tail padding.

    Columns: time_s, duration_s, power_kw. No gaps, overlaps or missing power are
    silently filled. The final regular interval includes an explicitly zero tail.
    Input time zero is aligned to ``start``; timestamps identify interval starts.
    """
    finite("step_s", step_s, strict=True)
    if start.tzinfo is None or pd.isna(start):
        raise ValueError("start must be timezone-aware")
    required = ["time_s", "duration_s", "power_kw"]
    if not set(required) <= set(intervals) or intervals.empty:
        raise ValueError("nonempty time_s, duration_s, power_kw intervals required")
    values = intervals[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (values[:, 1] <= 0).any():
        raise ValueError("intervals need finite nonnegative power/time and positive durations")
    begins, durations, powers = values.T
    ends = begins + durations
    if abs(begins[0]) > 1e-9 or not np.allclose(begins[1:], ends[:-1], atol=1e-9, rtol=0):
        raise ValueError("intervals must start at zero and be contiguous without overlap")
    count = int(np.ceil(ends[-1] / step_s))
    energy = np.zeros(count)
    for begin, end, power in zip(begins, ends, powers, strict=True):
        for slot in range(int(begin // step_s), min(count, int(np.ceil(end / step_s)))):
            overlap = max(0.0, min(end, (slot + 1) * step_s) - max(begin, slot * step_s))
            energy[slot] += power * overlap
    return pd.Series(
        energy / step_s,
        name="power_kw",
        index=pd.date_range(start, periods=count, freq=pd.Timedelta(seconds=step_s)),
    )
