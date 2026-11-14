"""Compare revenue/reserve trade-offs without assigning system-wide market revenue."""

from dataclasses import dataclass

import pandas as pd

from datacenter_simulator.methods.bess_value import (
    BESSValueResult,
    optimize_bess_value,
    replay_outage,
)
from datacenter_simulator.models.bess_value import BESSValuePolicy
from datacenter_simulator.use_cases.bess_value import spain_bess_inputs


@dataclass
class BESSValueStudy:
    comparison: pd.DataFrame
    schedules: dict[str, BESSValueResult]
    outage_sweep: pd.DataFrame


def spain_bess_study() -> BESSValueStudy:
    """One summer week, two reserve policies, every complete two-hour outage.

    Both policies start/end at the same SOC. Outages use pre-dispatch SOC from
    each normal schedule with no anticipation, critical load only, and zero PV
    as a conservative stress. Uniform start times are a sensitivity sweep, not
    an outage probability distribution. No unserved-energy monetary benefit is
    stacked onto the normal operating savings.
    """
    frame, battery = spain_bess_inputs()
    schedules = {}
    comparisons = []
    stress_rows = []
    for name, reserve in (("economic", 0.1), ("reserve_80pct", 0.8)):
        result = optimize_bess_value(
            frame.demand_kw,
            frame.solar_kw,
            frame.import_eur_per_kwh,
            battery,
            BESSValuePolicy(6000, reserve_soc=reserve, peak_eur_per_kw_period=2.0),
        )
        schedules[name] = result
        for start in range(len(frame) - 1):
            window = frame.iloc[start : start + 2]
            outage = replay_outage(
                window.critical_kw,
                window.solar_kw * 0,
                battery,
                initial_energy_kwh=float(result.timeseries.energy_start_kwh.iloc[start]),
            )
            stress_rows.append(
                {
                    "policy": name,
                    "start": window.index[0],
                    "unserved_kwh": outage.summary["unserved_kwh"],
                }
            )
        stress = [float(row["unserved_kwh"]) for row in stress_rows if row["policy"] == name]
        comparisons.append(
            {
                "policy": name,
                **result.summary,
                "worst_outage_unserved_kwh": max(stress),
                "outage_starts_fully_served_fraction": sum(v < 1e-6 for v in stress) / len(stress),
            }
        )
    return BESSValueStudy(
        pd.DataFrame(comparisons).set_index("policy"), schedules, pd.DataFrame(stress_rows)
    )


def break_even_installed_cost(
    annual_net_operating_saving_eur: float,
    *,
    years: int,
    discount_rate: float,
    annual_fixed_om_eur: float = 0,
) -> float:
    """Maximum upfront cost for a supplied constant annual saving, no subsidies.

    Annual savings must be explicitly supplied, never inferred from a sample
    week here. Excludes replacement, financing, tax and salvage; a negative
    return means no non-negative capital budget meets break-even.
    """
    from math import isfinite

    from datacenter_simulator.models.devices import finite

    if not isfinite(annual_net_operating_saving_eur):
        raise ValueError("annual saving must be finite")
    if type(years) is not int or years < 1:
        raise ValueError("years must be a positive integer")
    finite("discount_rate", discount_rate)
    finite("annual_fixed_om_eur", annual_fixed_om_eur)
    net = annual_net_operating_saving_eur - annual_fixed_om_eur
    return sum(net / (1 + discount_rate) ** year for year in range(1, years + 1))
