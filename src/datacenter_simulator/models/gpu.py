"""Quality-specific GPU throughput curves and explicit board/server boundaries."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.performance import Provenance


@dataclass(frozen=True)
class GPUOperatingPoint:
    power_limit_w: float
    board_power_w: float
    tasks_per_s: float

    def __post_init__(self) -> None:
        for name in ("power_limit_w", "board_power_w", "tasks_per_s"):
            finite(name, getattr(self, name), strict=True)


@dataclass(frozen=True)
class GPUPerformanceModel:
    """Bounded interpolation at ONE hardware/workload/quality configuration.

    Power limits are settings, not measured consumption. Throughput and board
    power are separate observations. No extrapolation or cross-batch interpolation.
    """

    points: tuple[GPUOperatingPoint, ...]
    provenance: Provenance
    configuration_id: str
    quality_id: str
    idle_board_w: float
    default_limit_w: float | None = None
    evidence_kind: Literal["measured", "imported", "synthetic"] = "synthetic"

    def __post_init__(self) -> None:
        if not self.configuration_id or not self.quality_id or not self.points:
            raise ValueError("points and fixed configuration/quality identities are required")
        finite("idle_board_w", self.idle_board_w)
        limits = [p.power_limit_w for p in self.points]
        if np.any(np.diff(limits) <= 0):
            raise ValueError("power limits must strictly increase")
        if any(p.board_power_w < self.idle_board_w for p in self.points):
            raise ValueError("active board power must be at least idle power")
        if self.provenance.boundary != "component":
            raise ValueError("GPU performance observations require component provenance")
        if self.evidence_kind not in {"measured", "imported", "synthetic"}:
            raise ValueError("unknown evidence kind")
        if self.default_limit_w is not None:
            _ = self.default_point
        if self.evidence_kind == "synthetic" and self.provenance.kind != "illustrative":
            raise ValueError("synthetic evidence must be illustrative")

    def evaluate(
        self, limit_w: float, *, configuration_id: str, quality_id: str
    ) -> GPUOperatingPoint:
        finite("power limit", limit_w, strict=True)
        if (configuration_id, quality_id) != (self.configuration_id, self.quality_id):
            raise ValueError("workload configuration or quality mismatch")
        x = [p.power_limit_w for p in self.points]
        if not x[0] <= limit_w <= x[-1]:
            raise ValueError("power limit outside measured/declared interpolation bounds")
        return GPUOperatingPoint(
            limit_w,
            float(np.interp(limit_w, x, [p.board_power_w for p in self.points])),
            float(np.interp(limit_w, x, [p.tasks_per_s for p in self.points])),
        )

    @property
    def default_point(self) -> GPUOperatingPoint:
        if self.default_limit_w is None:
            return self.points[-1]
        matches = [p for p in self.points if p.power_limit_w == self.default_limit_w]
        if not matches:
            raise ValueError("default setting must be an observed operating point")
        return matches[0]

    @property
    def efficient_point(self) -> GPUOperatingPoint:
        """Lowest BOARD joules/task among observations; not a facility optimum."""
        return min(self.points, key=lambda p: p.board_power_w / p.tasks_per_s)


def server_terminal_power(
    power_kw: pd.Series,
    *,
    boundary: Literal["gpu_board", "server_dc", "server_ac"],
    other_server_kw: float | pd.Series | None = None,
    internal_efficiency: float = 1,
    ac_psu_efficiency: float | None = None,
) -> pd.Series:
    """Translate a trace to the existing simulate(device_power_kw=...) DC boundary.

    Board + separately declared other components pass through an internal DC
    converter exactly once. Whole-server DC already includes those loads/losses.
    AC input needs an explicit original AC PSU efficiency to strip that conversion
    before applying the simulated DC architecture (a modelled counterfactual).
    """
    fraction("internal_efficiency", internal_efficiency, positive=True)
    if not np.isfinite(power_kw.to_numpy()).all() or (power_kw < 0).any():
        raise ValueError("power must be finite and nonnegative; missing telemetry is not zero")
    if boundary == "gpu_board":
        if other_server_kw is None or ac_psu_efficiency is not None:
            raise ValueError("board traces require separate server assumptions, not AC conversion")
        if isinstance(other_server_kw, pd.Series):
            if not other_server_kw.index.equals(power_kw.index):
                raise ValueError("other server telemetry timestamps must match")
            if not np.isfinite(other_server_kw.to_numpy()).all() or (other_server_kw < 0).any():
                raise ValueError("other server power must be finite and nonnegative")
        else:
            finite("other_server_kw", other_server_kw)
        return (power_kw + other_server_kw) / internal_efficiency
    if other_server_kw is not None or internal_efficiency != 1:
        raise ValueError(
            "whole-server power already includes GPU, other devices and internal losses"
        )
    if boundary == "server_dc":
        if ac_psu_efficiency is not None:
            raise ValueError("DC trace must not receive AC conversion")
        return power_kw.copy()
    if boundary == "server_ac":
        if ac_psu_efficiency is None:
            raise ValueError(
                "AC trace needs declared original PSU efficiency for DC reconstruction"
            )
        fraction("ac_psu_efficiency", ac_psu_efficiency, positive=True)
        return power_kw * ac_psu_efficiency
    raise ValueError("unknown boundary")
