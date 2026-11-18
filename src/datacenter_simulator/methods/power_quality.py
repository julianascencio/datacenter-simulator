"""Quasi-static AC power quality and constrained short-duration storage replay.

No EMT, PLL, harmonics, UPS DC-link dynamics, unbalance or IEC flickermeter.
Voltage excursion is reported in pu; it is never labelled Pst.
"""

from dataclasses import dataclass, replace
from math import exp, isfinite, sqrt

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from datacenter_simulator.models.devices import finite
from datacenter_simulator.models.power_quality import EStatcom, WeakGrid


@dataclass(frozen=True)
class PCCSolution:
    voltage_pu: complex
    source_p_mw: float
    source_q_mvar: float
    grid_loss_mw: float


def solve_pcc(grid: WeakGrid, p_mw: float, q_mvar: float) -> PCCSolution:
    """High-voltage root of a balanced constant-PQ two-bus circuit.

    P/Q are net receiving-PCC demand, positive for consumption. Source power
    includes impedance losses. Raise if there is no positive high-voltage
    root. Solvability does not establish dynamic stability.
    """
    if not isfinite(p_mw) or not isfinite(q_mvar):
        raise ValueError("P and Q must be finite")
    s = complex(p_mw, q_mvar) / grid.base_mva
    z, e = grid.impedance_pu, grid.source_voltage_pu
    a = (z * s.conjugate()).real
    b = abs(z * s) ** 2
    discriminant = (e * e - 2 * a) ** 2 - 4 * b
    if discriminant < 0:
        raise ValueError("no high-voltage AC solution for this grid/load")
    y = (e * e - 2 * a + sqrt(discriminant)) / 2
    if y <= 0:
        raise ValueError("no positive PCC voltage")
    v = (y + z.conjugate() * s) / e
    loss = z * abs(s) ** 2 / y * grid.base_mva
    return PCCSolution(v, p_mw + loss.real, q_mvar + loss.imag, loss.real)


def validate_power_profile(profile: pd.DataFrame) -> float:
    """Return dt for uniform interval-start samples beginning at zero.

    Each row is held over [time_s, time_s + dt); the final row is a full
    interval, not an endpoint-only sample. At least two rows are required.
    """
    required = ["time_s", "load_mw", "load_mvar"]
    if not set(required).issubset(profile.columns) or len(profile) < 2:
        raise ValueError("need >=2 rows with time_s, load_mw and load_mvar")
    values = profile[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 1] < 0).any():
        raise ValueError("profile must be finite with nonnegative active demand")
    intervals = np.diff(values[:, 0])
    dt = float(intervals[0])
    if values[0, 0] != 0 or dt <= 0 or not np.allclose(intervals, dt, atol=1e-9, rtol=1e-9):
        raise ValueError("time_s must start at zero and have uniform positive spacing")
    return dt


@dataclass
class PowerQualityResult:
    timeseries: pd.DataFrame
    summary: dict[str, float]


def _summary(frame: pd.DataFrame, dt: float) -> dict[str, float]:
    v = frame.voltage_pu.to_numpy()
    return {
        "duration_s": len(frame) * dt,
        "pcc_active_swing_mw": float(np.ptp(frame.pcc_p_mw)),
        "source_active_swing_mw": float(np.ptp(frame.source_p_mw)),
        "pcc_ramp_max_mw_per_s": float(np.max(np.abs(np.diff(frame.pcc_p_mw))) / dt),
        "voltage_excursion_pu": float(np.ptp(v)),
        "voltage_min_pu": float(v.min()),
        "voltage_max_pu": float(v.max()),
        "grid_loss_mwh": float(frame.grid_loss_mw.sum() * dt / 3600),
    }


def _reactive_dispatch(grid: WeakGrid, p: float, q_load: float, limit: float, c: EStatcom) -> float:
    if limit == 0 or c.voltage_gain_mvar_per_pu == 0:
        return 0.0

    def residual(q: float) -> float:
        v = abs(solve_pcc(grid, p, q_load - q).voltage_pu)
        return q - c.voltage_gain_mvar_per_pu * (c.voltage_reference_pu - v)

    # Positive Q is injection. Restrict absorption to the solvable branch.
    high = limit
    high_residual = residual(high)
    low = -limit
    try:
        low_residual = residual(low)
    except ValueError:
        invalid, valid = low, high
        for _ in range(60):
            middle = (invalid + valid) / 2
            try:
                residual(middle)
                valid = middle
            except ValueError:
                invalid = middle
        low = valid
        low_residual = residual(low)
        if low_residual > 0:
            raise ValueError("voltage droop requests an unsolvable operating point") from None
    if low_residual >= 0:
        return low
    if high_residual <= 0:
        return high
    return float(brentq(residual, low, high, xtol=1e-10))


def simulate_power_quality(
    profile: pd.DataFrame, grid: WeakGrid, compensator: EStatcom | None = None
) -> PowerQualityResult:
    """Replay no support, Q-only STATCOM (zero energy), or finite E-STATCOM.

    Exact first-order smoothing of held load; SOC bias restores inventory
    towards initial SOC. P is clipped by AC power and interval energy, then
    Q receives the remaining MVA circle. Positive P discharges storage.
    Response is ideal within an interval; no converter delay is represented.
    """
    dt = validate_power_profile(profile)
    profile = profile[["time_s", "load_mw", "load_mvar"]].astype(float)
    c = compensator
    energy = 0.0 if c is None else c.initial_soc * c.nominal_energy_mj
    initial = energy
    filtered = float(profile.load_mw.iloc[0])
    rows = []
    for time, load, reactive in profile[["time_s", "load_mw", "load_mvar"]].itertuples(
        index=False, name=None
    ):
        start = energy
        p = q = loss = requested = 0.0
        p_limited = q_limited = False
        if c is not None:
            filtered += (1 - exp(-dt / c.smoothing_tau_s)) * (load - filtered)
            requested = load - filtered + (energy - initial) / c.recovery_tau_s
            discharge = max(0.0, energy - c.minimum_soc * c.nominal_energy_mj)
            charge = max(0.0, c.maximum_soc * c.nominal_energy_mj - energy)
            p = float(
                np.clip(
                    requested,
                    -min(c.active_limit_mw, charge / (c.charge_efficiency * dt)),
                    min(c.active_limit_mw, discharge * c.discharge_efficiency / dt),
                )
            )
            p_limited = abs(p - requested) > 1e-8
            q_limit = sqrt(max(0.0, c.rating_mva**2 - p**2))
            q = _reactive_dispatch(grid, load - p, reactive, q_limit, c)
            loss = max(p, 0) * (1 / c.discharge_efficiency - 1) + max(-p, 0) * (
                1 - c.charge_efficiency
            )
            energy -= (p + loss) * dt
        solution = solve_pcc(grid, load - p, reactive - q)
        v = abs(solution.voltage_pu)
        if c is not None:
            q_limited = abs(q - c.voltage_gain_mvar_per_pu * (c.voltage_reference_pu - v)) > 1e-7
        rows.append(
            {
                "time_s": time,
                "load_mw": load,
                "load_mvar": reactive,
                "pcc_p_mw": load - p,
                "pcc_q_mvar": reactive - q,
                "source_p_mw": solution.source_p_mw,
                "grid_loss_mw": solution.grid_loss_mw,
                "voltage_pu": v,
                "support_p_mw": p,
                "support_q_mvar": q,
                "requested_p_mw": requested,
                "converter_mva": abs(complex(p, q)),
                "energy_start_mj": start,
                "energy_end_mj": energy,
                "converter_loss_mw": loss,
                "energy_balance_error_mj": energy - start + (p + loss) * dt,
                "p_limited": p_limited,
                "q_limited": q_limited,
            }
        )
    frame = pd.DataFrame(rows)
    summary = _summary(frame, dt)
    summary.update(
        {
            "initial_energy_mj": initial,
            "terminal_energy_mj": energy,
            "net_storage_depletion_mj": initial - energy,
            "converter_loss_mwh": float(frame.converter_loss_mw.sum() * dt / 3600),
            "p_limited_fraction": float(frame.p_limited.mean()),
            "q_limited_fraction": float(frame.q_limited.mean()),
            "converter_peak_mva": float(frame.converter_mva.max()),
            "energy_swing_mj": float(
                max(initial, frame.energy_end_mj.max()) - min(initial, frame.energy_end_mj.min())
            ),
            "energy_balance_error_max_mj": float(frame.energy_balance_error_mj.abs().max()),
        }
    )
    return PowerQualityResult(frame, summary)


def ideal_source_benchmark(
    profile: pd.DataFrame, grid: WeakGrid, *, auxiliary_impedance_ratio: float = 1.0
) -> PowerQualityResult:
    """Unlimited auxiliary voltage source behind finite impedance at the PCC.

    Sources have the SAME phasor. Z_aux = ratio * Z_grid. Original-grid power
    is separated from total demand. The auxiliary supplies sustained energy;
    it is not a zero-energy STATCOM or a physically sized storage device.
    """
    dt = validate_power_profile(profile)
    profile = profile[["time_s", "load_mw", "load_mvar"]].astype(float)
    finite("auxiliary_impedance_ratio", auxiliary_impedance_ratio, strict=True)
    ratio = auxiliary_impedance_ratio
    equivalent = replace(grid, scr=grid.scr * (1 + 1 / ratio))
    grid_share = ratio / (1 + ratio)
    rows = []
    for time, p, q in profile[["time_s", "load_mw", "load_mvar"]].itertuples(
        index=False, name=None
    ):
        solution = solve_pcc(equivalent, p, q)
        rows.append(
            {
                "time_s": time,
                "load_mw": p,
                "load_mvar": q,
                "pcc_p_mw": p * grid_share,
                "pcc_q_mvar": q * grid_share,
                "source_p_mw": solution.source_p_mw * grid_share,
                "grid_loss_mw": solution.grid_loss_mw * grid_share,
                "voltage_pu": abs(solution.voltage_pu),
                "auxiliary_p_mw": p * (1 - grid_share),
                "auxiliary_q_mvar": q * (1 - grid_share),
            }
        )
    frame = pd.DataFrame(rows)
    summary = _summary(frame, dt)
    summary["auxiliary_delivered_mwh"] = float(frame.auxiliary_p_mw.sum() * dt / 3600)
    return PowerQualityResult(frame, summary)


def sizing_sweep(
    profiles: dict[str, pd.DataFrame],
    grids: tuple[WeakGrid, ...],
    candidates: tuple[EStatcom, ...],
    *,
    maximum_swing_mw: float,
    maximum_voltage_excursion_pu: float,
) -> pd.DataFrame:
    """Evaluate every profile/grid/candidate; infeasible AC cases stay failed.

    Thresholds are user-selected screens, not flicker emission limits. A
    candidate passes the envelope only if every tested case passes. Cost and
    untested combinations are not inferred; several sizes may be non-dominated.
    """
    finite("maximum_swing_mw", maximum_swing_mw)
    finite("maximum_voltage_excursion_pu", maximum_voltage_excursion_pu)
    if not profiles or not grids or not candidates:
        raise ValueError("profiles, grids and candidates must be nonempty")
    for profile in profiles.values():
        validate_power_profile(profile)
    rows = []
    for number, candidate in enumerate(candidates):
        for grid in grids:
            for name, profile in profiles.items():
                row: dict[str, object] = {
                    "candidate": number,
                    "rating_mva": candidate.rating_mva,
                    "nominal_energy_mj": candidate.nominal_energy_mj,
                    "usable_energy_mj": candidate.usable_energy_mj,
                    "scr": grid.scr,
                    "profile": name,
                }
                try:
                    result = simulate_power_quality(profile, grid, candidate)
                    row.update(result.summary)
                    row["screen_pass"] = (
                        result.summary["pcc_active_swing_mw"] <= maximum_swing_mw
                        and result.summary["voltage_excursion_pu"] <= maximum_voltage_excursion_pu
                    )
                    row["status"] = "solved"
                except ValueError as error:
                    row.update(screen_pass=False, status=str(error))
                rows.append(row)
    frame = pd.DataFrame(rows)
    frame["passes_all_tested_cases"] = frame.groupby("candidate").screen_pass.transform("all")
    return frame
