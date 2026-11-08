"""Monthly development, firm-power, carbon and cost screening methods.

All commissioning dates and financial parameters are scenario inputs, not forecasts.
This module uses MW/MWh; operational grid-management APIs use kW/kWh.
"""

import calendar
import math
from typing import Any

from datacenter_simulator.models.devices import finite, fraction


def month_id(value: str) -> int:
    year, month = map(int, value.split("-"))
    if not 1 <= month <= 12:
        raise ValueError("month must be in 1..12")
    return year * 12 + month - 1


def month_label(value: int) -> str:
    year, month = divmod(value, 12)
    return f"{year:04d}-{month + 1:02d}"


def hours_in_month(value: int) -> int:
    year, month = divmod(value, 12)
    return 24 * calendar.monthrange(year, month + 1)[1]


def firm_capacity(
    capacities: list[float], delivery_factor: float, extra_firm_mw: float = 0
) -> float:
    """Single largest modeled block unavailable, with an explicit delivery haircut."""
    fraction("delivery_factor", delivery_factor, positive=True)
    finite("extra_firm_mw", extra_firm_mw)
    for value in capacities:
        finite("capacity", value)
    return delivery_factor * (sum(capacities) - max(capacities, default=0)) + extra_firm_mw


def simulate_case(
    cfg: dict[str, Any], name: str, staged: bool = False, extra: bool = False, delayed: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validate_recovery_inputs(cfg)
    target = cfg["facility_target_mw"] / cfg["pue"]
    start, end = month_id(cfg["start"]), month_id(cfg["end"])
    extension = cfg["building_lead_months"]
    steps = []
    for month in range(start, end + extension + 1):
        active = [
            a
            for a in cfg["assets"]
            if month
            >= month_id(a["date"]) + (cfg["delayed_months"].get(a["group"], 0) if delayed else 0)
        ]
        capacities = [
            a["mw"]
            * (1 - cfg["fuel_cell_capture_energy_penalty"] if a["group"] == "fuel_cell" else 1)
            for a in active
        ]
        add = (
            cfg["firm_addition_mw"] if extra and month >= month_id(cfg["firm_addition_date"]) else 0
        )
        firm = firm_capacity(capacities, cfg["delivery_factor"], add)
        continuous_it = min(target, firm / cfg["pue"])
        commissioned = math.floor((continuous_it + 1e-8) / cfg["pod_it_mw"]) * cfg["pod_it_mw"]
        steps.append(
            {
                "month": month_label(month),
                "hours": hours_in_month(month),
                "identified_capacity_mw": sum(a["mw"] for a in active),
                "additional_firm_mw": add,
                "firm_facility_mw": firm,
                "continuous_it_mw": continuous_it,
                "commissioned_it_mw": commissioned,
            }
        )
    rows = []
    for i, step in enumerate(steps[: end - start + 1]):
        # Planning benchmark: stage facility investment three months before power certification.
        # This grants perfect schedule knowledge, not a claim that a building takes three months.
        built = steps[i + extension]["commissioned_it_mw"] if staged else target
        idle = max(0, built - step["commissioned_it_mw"])
        row = dict(
            step,
            case=name,
            built_it_mw=built,
            idle_it_mw=idle,
            deferred_it_mw=target - step["commissioned_it_mw"],
            firm_it_energy_mwh=step["commissioned_it_mw"] * step["hours"],
            idle_capital_carry_usd=idle
            * cfg["facility_capex_usd_per_it_mw"]
            * cfg["annual_carry_rate"]
            / 12,
        )
        rows.append(row)
    summary = {
        "case": name,
        "final_commissioned_it_mw": rows[-1]["commissioned_it_mw"],
        "final_firm_facility_mw": rows[-1]["firm_facility_mw"],
        "firm_it_energy_twh": sum(r["firm_it_energy_mwh"] for r in rows) / 1e6,
        "idle_capital_carry_usd": sum(r["idle_capital_carry_usd"] for r in rows),
        "first_full_target_month": next(
            (r["month"] for r in rows if r["commissioned_it_mw"] >= target), None
        ),
    }
    return rows, summary


def capacity_sensitivity(cfg: dict[str, Any]) -> list[dict[str, float]]:
    """Test source groups and PUE/delivery sensitivities using supplied asset ratings."""
    validate_recovery_inputs(cfg)
    total = sum(a["mw"] for a in cfg["assets"])
    fc = sum(a["mw"] for a in cfg["assets"] if a["group"] == "fuel_cell")
    ccgt = [a["mw"] for a in cfg["assets"] if a["group"] == "ccgt"]
    utility = sum(a["mw"] for a in cfg["assets"] if a["group"] in {"black_hills", "market"})
    gas = sum(a["mw"] for a in cfg["assets"] if a["group"] != "market")
    losses = [
        (0, False),
        (max(ccgt, default=0), False),
        (utility, False),
        (fc, True),
        (sum(ccgt), False),
        (gas, True),
    ]
    rows = []
    for delivery in (0.90, 0.95, 1.0):
        for loss, loses_fc in losses:
            for pue in (1.10, 1.20, 1.30):
                fc_penalty = 0 if loses_fc else fc * cfg["fuel_cell_capture_energy_penalty"]
                firm = max(0, total - loss - fc_penalty) * delivery
                rows.append(
                    {
                        "delivery_factor": delivery,
                        "lost_block_mw": loss,
                        "pue": pue,
                        "remaining_facility_mw": firm,
                        "supported_it_mw": firm / pue,
                        "facility_shortfall_mw": max(0, cfg["facility_target_mw"] - firm),
                    }
                )
    return rows


def emissions(
    cfg: dict[str, Any], fc_capture: float, ccgt_capture: float, penalty: float
) -> dict[str, float]:
    """Steady load screening; captures only actual dispatched source emissions.

    No upstream methane, embodied emissions, power ramp, outage chronology, or offsets.
    Capture penalty reduces fuel-cell output at fixed gross generation; its replacement
    energy is dispatched from other resources. Capture availability is annual-weighted.
    """
    validate_recovery_inputs(cfg)
    for name, value in (
        ("fc_capture", fc_capture),
        ("ccgt_capture", ccgt_capture),
        ("penalty", penalty),
    ):
        fraction(name, value)
    if penalty >= 1:
        raise ValueError("capture penalty must leave positive output")
    capacities = {
        group: sum(a["mw"] for a in cfg["assets"] if a["group"] == group)
        for group in ("fuel_cell", "ccgt", "black_hills")
    }
    demand = cfg["facility_target_mw"]
    factor = cfg["delivery_factor"]
    fc_pre = capacities["fuel_cell"] * factor
    fc_net = fc_pre * (1 - penalty)
    fc_net = min(fc_net, demand)
    fc_pre = fc_net / (1 - penalty)
    ccgt = min(capacities["ccgt"] * factor, max(0, demand - fc_net))
    bkh = max(0, demand - fc_net - ccgt)
    if bkh > capacities["black_hills"] * factor + 1e-8:
        raise ValueError("Scenario requires unavailable residual generation")
    generation = {"fuel_cell": fc_pre, "ccgt": ccgt, "black_hills": bkh}
    raw = {
        k: v * 8760 * cfg["heat_rate_hhv_mmbtu_per_mwh"][k] * cfg["gas_co2_kg_per_mmbtu"] / 1000
        for k, v in generation.items()
    }
    captured = (raw["fuel_cell"] * fc_capture + raw["ccgt"] * ccgt_capture) * cfg[
        "capture_availability"
    ]
    residual = sum(raw.values()) - captured
    return {
        "fuel_cell_net_mw": fc_net,
        "ccgt_mw": ccgt,
        "black_hills_mw": bkh,
        "captured_mt_year": captured / 1e6,
        "residual_mt_year": residual / 1e6,
        "kg_co2_per_facility_mwh": residual * 1000 / (demand * 8760),
        "kg_co2_per_it_mwh": residual * 1000 / (demand / cfg["pue"] * 8760),
        "gas_million_mmbtu_year": sum(
            generation[k] * 8760 * cfg["heat_rate_hhv_mmbtu_per_mwh"][k] for k in generation
        )
        / 1e6,
    }


def cost_screen(cfg: dict[str, Any]) -> list[dict[str, float]]:
    """Annualized fuel-cell project-cost sensitivities, not a contracted PPA tariff."""
    validate_recovery_inputs(cfg)
    capacity = sum(a["mw"] for a in cfg["assets"] if a["group"] == "fuel_cell")
    finite("fuel_cell capacity", capacity, strict=True)
    rows = []
    n = cfg["fuel_cell_economic_life_years"]
    ef = cfg["gas_co2_kg_per_mmbtu"] / 1000
    hr = cfg["heat_rate_hhv_mmbtu_per_mwh"]["fuel_cell"]
    for rate in (0.06, 0.08, 0.10, 0.12):
        crf = rate * (1 + rate) ** n / ((1 + rate) ** n - 1)
        capital = (
            cfg["fuel_cell_capex_usd"] * crf / (capacity * 8760 * cfg["fuel_cell_capacity_factor"])
        )
        for gas in (2, 4, 6, 8):
            fuel = gas * hr
            ccs = (
                hr
                * ef
                * cfg["capture_fraction"]
                * cfg["capture_availability"]
                * cfg["capture_transport_storage_usd_per_tonne"]
            )
            total = (capital + fuel + cfg["fuel_cell_om_usd_per_mwh"] + ccs) / (
                1 - cfg["fuel_cell_capture_energy_penalty"]
            )
            rows.append(
                {
                    "discount_rate": rate,
                    "gas_usd_per_mmbtu": gas,
                    "capital_usd_per_pre_capture_mwh": capital,
                    "screening_usd_per_net_mwh": total,
                }
            )
    return rows


def validate_recovery_inputs(cfg: dict[str, Any]) -> None:
    """Validate the editable study contract before running monthly calculations."""
    for key in ("facility_target_mw", "pue", "pod_it_mw", "fuel_cell_economic_life_years"):
        finite(key, cfg[key], strict=True)
    if cfg["pue"] < 1 or month_id(cfg["end"]) < month_id(cfg["start"]):
        raise ValueError("PUE must be >= 1 and end must not precede start")
    for key in ("delivery_factor", "fuel_cell_capacity_factor"):
        fraction(key, cfg[key], positive=True)
    for key in ("capture_fraction", "capture_availability", "fuel_cell_capture_energy_penalty"):
        fraction(key, cfg[key])
    if cfg["fuel_cell_capture_energy_penalty"] >= 1:
        raise ValueError("capture auxiliaries must leave positive output")
    for key in (
        "facility_capex_usd_per_it_mw",
        "annual_carry_rate",
        "firm_addition_mw",
        "gas_usd_per_mmbtu",
        "gas_co2_kg_per_mmbtu",
        "fuel_cell_capex_usd",
        "fuel_cell_om_usd_per_mwh",
        "capture_transport_storage_usd_per_tonne",
    ):
        finite(key, cfg[key])
    month_id(cfg["firm_addition_date"])
    for value in (cfg["building_lead_months"], *cfg["delayed_months"].values()):
        if not isinstance(value, int) or value < 0:
            raise ValueError("lead times and delays must be nonnegative integer months")
    assets = cfg["assets"]
    if not assets or len({a["id"] for a in assets}) != len(assets):
        raise ValueError("assets need unique ids and cannot be empty")
    for asset in assets:
        if not asset["id"]:
            raise ValueError("asset id cannot be empty")
        finite("asset capacity", asset["mw"])
        month_id(asset["date"])
    for rate in cfg["heat_rate_hhv_mmbtu_per_mwh"].values():
        finite("heat rate", rate, strict=True)
