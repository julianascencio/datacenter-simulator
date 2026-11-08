"""Offline, source-attributed Wyoming study fixtures; NOT the actual operator design."""

import json
from importlib.resources import files
from typing import Any

import pandas as pd

from datacenter_simulator.methods.project_recovery import validate_recovery_inputs
from datacenter_simulator.models.grid_management import Generator, SupplyOutage


def wyoming_inputs() -> dict[str, Any]:
    """Load a fresh editable copy of reported aggregate ratings and scenario assumptions."""
    cfg: dict[str, Any] = json.loads(
        files("datacenter_simulator")
        .joinpath("data/wyoming_recovery.json")
        .read_text(encoding="utf-8")
    )
    validate_recovery_inputs(cfg)
    return cfg


def wyoming_sources() -> list[dict[str, str]]:
    """Primary announcements and manufacturer benchmarks, with an evidence cutoff."""
    sources: list[dict[str, str]] = json.loads(
        files("datacenter_simulator")
        .joinpath("data/wyoming_sources.json")
        .read_text(encoding="utf-8")
    )
    return sources


def wyoming_generators(cfg: dict[str, Any] | None = None) -> tuple[Generator, ...]:
    """Map MW planning inputs to kW dispatch blocks; 26 MW market supply is separate.

    All gas assets share one hypothetical upstream-fuel group for stress testing.
    Generator partitions, fuel costs, O&M, capture loads and ramp limits are assumptions.
    Black Hills generation remains behind a utility path; the outage fixture below
    trips those generators as well as market import when that path is unavailable.
    """
    cfg = wyoming_inputs() if cfg is None else cfg
    validate_recovery_inputs(cfg)
    units = []
    for asset in cfg["assets"]:
        group = asset["group"]
        if group == "market":
            continue
        capture = group == "fuel_cell"
        units.append(
            Generator(
                asset["id"],
                asset["mw"] * 1000,
                fuel_group="shared_gas_supply",
                heat_rate_mmbtu_per_kwh=cfg["heat_rate_hhv_mmbtu_per_mwh"][group] / 1000,
                fuel_price_per_mmbtu=cfg["gas_usd_per_mmbtu"],
                variable_om_per_kwh=0.015 if capture else 0.006,
                fuel_carbon_kg_per_mmbtu=cfg["gas_co2_kg_per_mmbtu"],
                capture_fraction=cfg["capture_fraction"] if capture else 0,
                capture_availability=cfg["capture_availability"],
                capture_auxiliary_fraction=cfg["fuel_cell_capture_energy_penalty"]
                if capture
                else 0,
                capture_cost_per_tonne=cfg["capture_transport_storage_usd_per_tonne"],
                delivery_factor=cfg["delivery_factor"],
                ramp_kw_per_hour=asset["mw"] * 1000 * 0.5,
                commissioned_at=pd.Timestamp(asset["date"] + "-01", tz="UTC"),
            )
        )
    return tuple(units)


def wyoming_profiles(hours: int = 48) -> pd.DataFrame:
    """Synthetic 2030 operation; not weather, meter observations or a Google forecast."""
    if not isinstance(hours, int) or hours < 36:
        raise ValueError("Wyoming outage exercise requires at least 36 hours")
    cfg = wyoming_inputs()
    index = pd.date_range("2030-01-01", periods=hours, freq="h", tz="UTC")
    market = sum(a["mw"] for a in cfg["assets"] if a["group"] == "market")
    demand = cfg["facility_target_mw"] * 1000
    return pd.DataFrame(
        {
            "demand_kw": demand,
            "critical_demand_kw": 0.90 * demand,
            "renewable_kw": 0.0,
            "grid_limit_kw": market * 1000 * cfg["delivery_factor"],
            "import_price_per_kwh": [0.18 if 16 <= t.hour < 22 else 0.07 for t in index],
            "grid_carbon_kg_per_kwh": 0.4,
        },
        index=index,
    )


def wyoming_outages(index: pd.DatetimeIndex) -> dict[str, tuple[SupplyOutage, ...]]:
    """Controlled four-hour tests. The outages are invented, not reported events."""
    if len(index) < 24:
        raise ValueError("outage fixtures need at least 24 intervals")
    start, end = index[16], index[20]
    return {
        "normal": (),
        "generator_trip": (SupplyOutage(start, end, generator_ids=("CCGT1",)),),
        "utility_path_loss": (
            SupplyOutage(start, end, generator_ids=("BKH1", "BKH2", "BKH3"), grid=True),
        ),
        "common_gas_loss": (SupplyOutage(start, end, fuel_groups=("shared_gas_supply",)),),
    }
