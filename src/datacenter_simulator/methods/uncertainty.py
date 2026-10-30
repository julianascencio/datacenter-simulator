"""Seeded bounded parameter studies; input bounds are assumptions, not confidence intervals."""

from collections.abc import Callable

import numpy as np
import pandas as pd

from datacenter_simulator.models.devices import finite


def sample_study(
    bounds: dict[str, tuple[float, float]],
    evaluate: Callable[[dict[str, float]], float],
    *,
    samples: int = 100,
    seed: int = 0,
) -> pd.DataFrame:
    """Independent uniform input draws, retaining infeasible runs explicitly."""
    if not bounds or not isinstance(samples, int) or samples < 1:
        raise ValueError("nonempty bounds and positive sample count required")
    for name, (low, high) in bounds.items():
        finite(name, low, -1e12)
        finite(name, high, low, strict=True)
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(samples):
        params = {name: float(rng.uniform(low, high)) for name, (low, high) in bounds.items()}
        try:
            value = float(evaluate(params))
            if not np.isfinite(value):
                raise ValueError("non-finite output")
            rows.append({**params, "value": value, "feasible": True, "reason": ""})
        except ValueError as error:
            rows.append({**params, "value": float("nan"), "feasible": False, "reason": str(error)})
    return pd.DataFrame(rows)
