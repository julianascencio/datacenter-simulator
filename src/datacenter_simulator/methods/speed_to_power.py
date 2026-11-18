"""Speed-adjusted economics and physically bounded hourly power screening.

Based on Newkirk et al., arXiv:2611.17098v1. The native dispatcher is a
screening extension, not a port of the authors' optimization/degradation code.
"""

from dataclasses import dataclass
from math import prod

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.speed_to_power import (
    PUBLISHED_ARCHITECTURES,
    validate_power_profiles,
    validate_published_results,
)
from datacenter_simulator.methods.energy import Battery, dispatch
from datacenter_simulator.models.devices import finite, fraction
from datacenter_simulator.models.power_architecture import PowerStage
from datacenter_simulator.models.speed_to_power import ComputeFleet, PowerProject


@dataclass(frozen=True)
class SupplyPaths:
    """Paths relative to a common bus; battery ratings are at that bus.

    AC PV storage couples upstream of the shared inverter. DC PV storage
    couples to the MV spine. Stage efficiencies come from Figure 2; placement
    is idealized. Embedded protection storage and converter clipping omitted.
    """

    name: str
    pv_to_bus: tuple[PowerStage, ...]
    bus_to_it: tuple[PowerStage, ...]
    bus_to_cooling: tuple[PowerStage, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.bus_to_it or not self.bus_to_cooling:
            raise ValueError("named paths to both loads are required")

    @property
    def pv_efficiency(self) -> float:
        return prod(stage.efficiency for stage in self.pv_to_bus)

    @property
    def it_efficiency(self) -> float:
        return prod(stage.efficiency for stage in self.bus_to_it)

    @property
    def cooling_efficiency(self) -> float:
        return prod(stage.efficiency for stage in self.bus_to_cooling)


def paper_supply_paths() -> dict[str, SupplyPaths]:
    """Figure 2 paths; losses count once, separately for IT and cooling."""
    wire = PowerStage("wiring", 0.99)
    switch = PowerStage("switchgear", 0.99)
    pdu = PowerStage("IT PDU", 0.99)
    ac_psu = PowerStage("AC PSU", 0.94)
    dc_psu = PowerStage("DC PSU", 0.98)
    vfd = PowerStage("VFD", 0.97)
    esc = PowerStage("DC motor drive", 0.98)
    transformer = (
        PowerStage("step-up transformer", 0.98),
        PowerStage("step-down transformer", 0.98),
    )
    ac_common = (PowerStage("shared inverter", 0.98), *transformer, wire, switch)
    dc_common = (PowerStage("MVDC step-down", 0.98), wire, switch)
    utility_common = (*transformer, wire, switch, PowerStage("double-conversion UPS", 0.94))
    mppt = PowerStage("MPPT", 0.99)
    return {
        "ac_solar": SupplyPaths("ac_solar", (mppt,), (*ac_common, pdu, ac_psu), (*ac_common, vfd)),
        "dc_solar": SupplyPaths(
            "dc_solar",
            (mppt, PowerStage("MVDC step-up", 0.98)),
            (*dc_common, pdu, dc_psu),
            (*dc_common, esc),
        ),
        "gas": SupplyPaths("gas", (), (*utility_common, pdu, ac_psu), (*utility_common, vfd)),
        "grid": SupplyPaths("grid", (), (*utility_common, pdu, ac_psu), (*utility_common, vfd)),
    }


def facility_load_summary(profiles: pd.DataFrame, fleet: ComputeFleet) -> dict[str, float]:
    """Eq. S1 with thermal-only overhead; electrical conversion added by paths."""
    validate_power_profiles(profiles)
    if profiles.it_kw.max() > fleet.peak_it_kw * (1 + 1e-9):
        raise ValueError("IT profile exceeds the specified fleet peak")
    overhead = 1 + profiles.cooling_kw / profiles.it_kw
    return {
        "average_it_kw": float(profiles.it_kw.mean()),
        "average_terminal_kw": float((profiles.it_kw + profiles.cooling_kw).mean()),
        "thermal_overhead_p99": float(overhead.quantile(0.99)),
        "design_terminal_kw": fleet.peak_it_kw * float(overhead.quantile(0.99)) * fleet.contingency,
    }


def solar_drought_energy(profiles: pd.DataFrame, *, days: int = 5) -> float:
    """Minimum cyclic rolling DC yield, kWh/kWp, including year-end windows."""
    validate_power_profiles(profiles)
    if (
        isinstance(days, bool)
        or not isinstance(days, int)
        or days <= 0
        or days * 24 > len(profiles)
    ):
        raise ValueError("days must be positive and fit inside the profile")
    count = days * 24
    values = profiles.pv_dc_per_kwp.to_numpy(dtype=float)
    extended = np.concatenate([values, values[: count - 1]])
    cumulative = np.concatenate([[0.0], np.cumsum(extended)])
    return float(np.min(cumulative[count:] - cumulative[:-count]))


def pv_retention(operating_year: int) -> float:
    """Paper's linear PV derate: 1% in year 1, then 0.55 percentage points/year."""
    if (
        isinstance(operating_year, bool)
        or not isinstance(operating_year, int)
        or operating_year < 1
    ):
        raise ValueError("operating_year must be a positive integer")
    return max(0.0, 0.99 - 0.0055 * (operating_year - 1))


@dataclass
class SupplyDispatch:
    hourly: pd.DataFrame
    summary: dict[str, float]


def dispatch_solar_storage(
    profiles: pd.DataFrame,
    paths: SupplyPaths,
    *,
    pv_kwp: float,
    battery: Battery | None = None,
    pv_retained_fraction: float = 1,
) -> SupplyDispatch:
    """Reuse the package dispatcher with a periodic, energy-neutral starting SOC.

    Start from minimum SOC and repeat the profile until end inventory matches
    start inventory. No free initial battery energy is counted. Deficits shed
    IT and cooling proportionally. Full-load-hour uptime and energy served
    fraction are deliberately separate. One-hour resolution cannot prove SLA.
    """
    validate_power_profiles(profiles)
    finite("pv_kwp", pv_kwp)
    fraction("pv_retained_fraction", pv_retained_fraction, positive=True)
    it = profiles.it_kw.to_numpy(dtype=float)
    cooling = profiles.cooling_kw.to_numpy(dtype=float)
    bus_load = it / paths.it_efficiency + cooling / paths.cooling_efficiency
    pv_raw = profiles.pv_dc_per_kwp.to_numpy(dtype=float) * pv_kwp * pv_retained_fraction
    pv_bus = pv_raw * paths.pv_efficiency
    start = battery.capacity_kwh * battery.minimum_soc if battery else 0.0
    tolerance = max(1e-8, (battery.capacity_kwh if battery else 1) * 1e-10)
    rows: list[tuple[float, ...]] = []
    for _ in range(100):
        energy = start
        rows = []
        for demand, generation in zip(bus_load, pv_bus, strict=True):
            result = dispatch(
                float(demand),
                float(generation),
                1,
                battery=battery,
                energy_kwh=energy,
                grid_import_limit_kw=0,
            )
            # Large kWh values can leave a sub-nanowatt-hour negative residue.
            energy = result.battery_energy_kwh
            if battery is not None:
                energy = min(
                    battery.maximum_soc * battery.capacity_kwh,
                    max(battery.minimum_soc * battery.capacity_kwh, energy),
                )
            rows.append(
                (
                    result.charge_kw,
                    result.discharge_kw,
                    result.curtailed_kw,
                    result.unserved_kw,
                    energy,
                    result.battery_loss_kw,
                    result.balance_error_kw,
                )
            )
        if abs(energy - start) <= tolerance:
            break
        start = energy
    else:
        raise ValueError("periodic battery state did not converge")
    frame = pd.DataFrame(
        rows,
        index=profiles.index,
        columns=[
            "charge_bus_kw",
            "discharge_bus_kw",
            "curtailed_bus_kw",
            "unserved_bus_kw",
            "battery_energy_kwh",
            "battery_loss_kw",
            "bus_balance_error_kw",
        ],
    )
    frame["bus_load_kw"] = bus_load
    frame["pv_raw_kw"] = pv_raw
    frame["pv_bus_kw"] = pv_bus
    served_fraction = np.clip(1 - frame.unserved_bus_kw.to_numpy() / bus_load, 0, 1)
    frame["terminal_load_kw"] = it + cooling
    frame["terminal_served_kw"] = (it + cooling) * served_fraction
    frame["conversion_loss_kw"] = (
        pv_raw
        - pv_bus
        + (bus_load - frame.unserved_bus_kw.to_numpy() - frame.terminal_served_kw.to_numpy())
    )
    frame["unserved_terminal_kw"] = frame.terminal_load_kw - frame.terminal_served_kw
    previous = np.concatenate([[start], frame.battery_energy_kwh.to_numpy()[:-1]])
    frame["system_balance_error_kw"] = (
        frame.pv_raw_kw
        - frame.terminal_served_kw
        - frame.curtailed_bus_kw
        - frame.conversion_loss_kw
        - frame.battery_loss_kw
        - (frame.battery_energy_kwh - previous)
    )
    return SupplyDispatch(
        frame,
        {
            "full_load_hour_fraction": float((frame.unserved_terminal_kw <= 1e-7).mean()),
            "energy_served_fraction": float(
                frame.terminal_served_kw.sum() / frame.terminal_load_kw.sum()
            ),
            "delivered_kwh": float(frame.terminal_served_kw.sum()),
            "unserved_kwh": float(frame.unserved_terminal_kw.sum()),
            "curtailed_kwh": float(frame.curtailed_bus_kw.sum()),
            "conversion_loss_kwh": float(frame.conversion_loss_kw.sum()),
            "battery_loss_kwh": float(frame.battery_loss_kw.sum()),
            "periodic_inventory_error_kwh": float(energy - start),
            "maximum_balance_error_kw": float(frame.system_balance_error_kw.abs().max()),
        },
    )


def project_cashflows(
    project: PowerProject,
    *,
    gpu_count: int,
    horizon_years: int = 27,
    compute_ready_year: float = 0,
) -> pd.DataFrame:
    """Annual [t,t+1) buckets; partial construction/operation years are prorated.

    Horizon is common, exclusive (27 means [0,27)), not 27 operational years
    per architecture. Readiness delays both useful load and lost-compute
    accounting. O&M before useful operation and salvage are excluded.
    """
    if isinstance(horizon_years, bool) or not isinstance(horizon_years, int) or horizon_years < 1:
        raise ValueError("horizon_years must be a positive integer")
    if isinstance(gpu_count, bool) or not isinstance(gpu_count, int) or gpu_count <= 0:
        raise ValueError("gpu_count must be a positive integer")
    finite("compute_ready_year", compute_ready_year)
    deployment = project.deployment_years
    operation = max(deployment, compute_ready_year)
    if operation >= horizon_years:
        raise ValueError("project must deliver energy inside the common horizon")
    years = np.arange(horizon_years)
    construction = np.clip(deployment - years, 0, 1)
    if deployment <= 1:
        spending = np.zeros(horizon_years)
        spending[0] = 1
    elif deployment in (2, 3):
        spending = np.zeros(horizon_years)
        spending[: int(deployment)] = [0.4, 0.6] if deployment == 2 else [0.3, 0.4, 0.3]
    else:
        spending = construction / deployment
    operating = np.clip(years + 1 - operation, 0, 1)
    idle = np.maximum(0, np.minimum(years + 1, deployment) - np.maximum(years, compute_ready_year))
    replacement = np.zeros(horizon_years)
    replacement_time = operation + project.replacement_age_years
    if replacement_time < horizon_years:
        replacement[int(replacement_time)] = project.replacement_usd
    return pd.DataFrame(
        {
            "year": years,
            "capital_usd": spending * project.capital_usd,
            "replacement_usd": replacement,
            "operating_usd": operating * project.annual_operating_usd,
            "delivered_kwh": operating * project.annual_delivered_kwh,
            "idle_gpu_hours": idle * 8760 * gpu_count,
        }
    )


def levelized_power_cost(
    cashflows: pd.DataFrame, *, discount_rate: float = 0.07, gpu_hour_value_usd: float = 2.4
) -> dict[str, float]:
    """Eqs. 2/S18, midyear discounting of costs, energy and lost GPU-hours."""
    finite("discount_rate", discount_rate)
    finite("gpu_hour_value_usd", gpu_hour_value_usd)
    columns = [
        "year",
        "capital_usd",
        "replacement_usd",
        "operating_usd",
        "delivered_kwh",
        "idle_gpu_hours",
    ]
    if cashflows.empty or not set(columns) <= set(cashflows):
        raise ValueError("cashflows are empty or missing columns")
    values = cashflows[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("cashflows must be finite and nonnegative")
    if not np.array_equal(cashflows.year.to_numpy(), np.arange(len(cashflows))):
        raise ValueError("cashflow years must be contiguous from zero")
    weights = (1 + discount_rate) ** -(cashflows.year.to_numpy(dtype=float) + 0.5)
    energy = float(np.dot(weights, cashflows.delivered_kwh))
    if energy <= 0:
        raise ValueError("discounted delivered energy must be positive")
    costs = float(
        np.dot(weights, cashflows.capital_usd + cashflows.replacement_usd + cashflows.operating_usd)
    )
    idle = float(np.dot(weights, cashflows.idle_gpu_hours))
    return {
        "pv_energy_kwh": energy,
        "pv_energy_cost_usd": costs,
        "pv_idle_gpu_hours": idle,
        "pv_lost_compute_usd": idle * gpu_hour_value_usd,
        "base_lcoe_usd_per_kwh": costs / energy,
        "speed_premium_usd_per_kwh": idle * gpu_hour_value_usd / energy,
        "adjusted_lcoe_usd_per_kwh": (costs + idle * gpu_hour_value_usd) / energy,
        "gpu_value_slope": idle / energy,
    }


def break_even_gpu_value(
    base_a: float, slope_a: float, base_b: float, slope_b: float
) -> float | None:
    """Nonnegative crossing of base + slope * GPU value, or None if none/identical."""
    for name, value in (
        ("base_a", base_a),
        ("base_b", base_b),
        ("slope_a", slope_a),
        ("slope_b", slope_b),
    ):
        finite(name, value)
    denominator = slope_a - slope_b
    if abs(denominator) < 1e-14:
        return None
    value = (base_b - base_a) / denominator
    return value if value >= 0 else None


def published_cost_comparison(
    frame: pd.DataFrame, *, gpu_hour_value_usd: float = 2.4, accelerated_gas: bool = False
) -> pd.DataFrame:
    """Revalue fixed author designs using their $2.40/hour premium coefficient.

    This does not re-optimize capacities or change deployment time, readiness,
    weather, costs or discount rates. The accelerated gas column is a separate
    author-generated scenario with its own base cost.
    """
    validate_published_results(frame)
    finite("gpu_hour_value_usd", gpu_hour_value_usd)
    result = frame[
        ["h3_index", "gpu_count", "latitude", "longitude", "ac_topology", "dc_topology"]
    ].copy()
    for architecture in PUBLISHED_ARCHITECTURES:
        column = (
            "natural_gas_threeyr"
            if accelerated_gas and architecture == "natural_gas"
            else architecture
        )
        base = frame[f"{column}_base_lcoe"]
        slope = (frame[f"{column}_total_lcoe"] - base) / 2.4
        result[architecture] = base + slope * gpu_hour_value_usd
    costs = result[list(PUBLISHED_ARCHITECTURES)]
    result["winner"] = costs.idxmin(axis=1)
    ordered = np.sort(costs.to_numpy(), axis=1)
    result["winner_gap_usd_per_kwh"] = ordered[:, 1] - ordered[:, 0]
    result["near_tie_1cent"] = result.winner_gap_usd_per_kwh <= 0.01
    return result
