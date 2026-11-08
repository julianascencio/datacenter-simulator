"""Run and export the infographic-inspired study with installed package APIs."""

import argparse
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from datacenter_simulator.methods.infrastructure import (
    capital_breakdown,
    infrastructure_balance,
    size_modules,
    ups_energy_required,
)
from datacenter_simulator.models.infrastructure import CapitalScenario, ModularEquipment, UPSBattery
from datacenter_simulator.use_cases.infrastructure import (
    InfrastructureCase,
    infrastructure_cost_items,
    infrastructure_evidence,
)


@dataclass
class InfrastructureStudy:
    case: InfrastructureCase
    costs: pd.DataFrame
    sizing: pd.DataFrame
    hourly: pd.DataFrame
    cost_sensitivity: pd.DataFrame
    cooling_sensitivity: pd.DataFrame
    scale_sensitivity: pd.DataFrame
    design: dict[str, float]
    summary: dict[str, float]


def _balance(case: InfrastructureCase, it_kw: float, ambient_c: float) -> dict[str, float]:
    return infrastructure_balance(
        it_kw,
        case.cooling_plant(),
        ambient_c=ambient_c,
        downstream_efficiency=case.downstream_efficiency,
        ups_efficiency=case.ups_efficiency,
        main_efficiency=case.main_efficiency,
        auxiliary_kw=case.it_mw * 1000 * case.auxiliary_fraction_of_it_rating,
    )


def infrastructure_study(case: InfrastructureCase | None = None) -> InfrastructureStudy:
    """Reconcile cost, hot-day capacity, 48 hourly balances and isolated sensitivities.

    Engineering counts DO NOT change the source's per-MW rates. Cooling heat
    allocations DO NOT change the source's air/liquid cost allocations. Neither
    rates nor synthetic power fractions imply a GPU count or compute throughput.
    """
    case = InfrastructureCase() if case is None else case
    design = _balance(case, case.it_mw * 1000, case.design_ambient_c)
    items = infrastructure_cost_items()
    scenario = CapitalScenario(case.it_mw, design["facility_kw"] / 1000)
    costs, totals = capital_breakdown(items, scenario)

    # Fixed tutorial unit sizes are planning envelopes, not manufacturer products.
    # A 1 MW / 1 MVA UPS is limited to 0.95 MW at the default load power factor.
    specifications = (
        (ModularEquipment("IT racks", case.rack_kw, 0), design["it_kw"]),
        (ModularEquipment("UPS", 1000, derating=case.load_power_factor), design["ups_output_kw"]),
        (ModularEquipment("Generators", 3000, derating=0.9), design["facility_kw"]),
        (ModularEquipment("Main switchgear envelope", 5000), design["facility_kw"]),
        (ModularEquipment("IT power distribution", 2000), design["ups_output_kw"]),
        (ModularEquipment("Chillers", 3000, domain="thermal"), design["hall_heat_kw"]),
        (ModularEquipment("Liquid CDUs", 2000, domain="thermal"), design["liquid_heat_kw"]),
        (ModularEquipment("Air handlers", 250, domain="thermal"), design["air_heat_kw"]),
        (
            ModularEquipment("Heat rejection / towers", 3000, domain="thermal"),
            design["rejected_heat_kw"],
        ),
    )
    sizing_rows = [size_modules(equipment, duty) for equipment, duty in specifications]
    sizing = pd.DataFrame(sizing_rows)
    ups = next(row for row in sizing_rows if row["id"] == "UPS")
    battery_kwh = ups_energy_required(
        design["ups_output_kw"],
        case.ups_autonomy_minutes,
        inverter_efficiency=case.battery_inverter_efficiency,
        usable_fraction=case.battery_usable_fraction,
        end_of_life_fraction=case.battery_end_of_life_fraction,
    )
    battery = UPSBattery(
        battery_kwh,
        float(ups["duty_units"]) * 1000,
        float(ups["duty_units"]) * 1000,
        case.battery_inverter_efficiency,
        case.battery_usable_fraction,
        case.battery_end_of_life_fraction,
    )

    # Hour-start timestamps; each row represents exactly one hour.
    index = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    rows = []
    for time in index:
        phase = 2 * np.pi * (time.hour - 8) / 24
        load_fraction = float(0.725 + 0.175 * np.sin(phase))
        ambient = float(case.design_ambient_c - 5 + 5 * np.sin(phase))
        balance = _balance(case, case.it_mw * 1000 * load_fraction, ambient)
        rows.append(
            {
                "ambient_c": ambient,
                "it_load_fraction": load_fraction,
                "duration_h": 1.0,
                "server_kw": balance["it_kw"] * (1 - case.network_power_fraction),
                "network_kw": balance["it_kw"] * case.network_power_fraction,
                **balance,
            }
        )
    hourly = pd.DataFrame(rows, index=index)
    hourly.index.name = "timestamp"
    facility_kwh = float((hourly.facility_kw * hourly.duration_h).sum())
    it_kwh = float((hourly.it_kw * hourly.duration_h).sum())

    scenarios = [
        ("Baseline: IT MW", scenario, {}),
        ("Alternative denominator: facility MW", replace(scenario, mw_basis="facility"), {}),
        ("Servers -20%", scenario, {"servers": 0.8}),
        ("Servers +20%", scenario, {"servers": 1.2}),
        ("Networking +20%", scenario, {"networking": 1.2}),
        (
            "Infrastructure +20%",
            scenario,
            {item.id: 1.2 for item in items if item.group == "Infrastructure"},
        ),
        ("10% contingency on listed scope", replace(scenario, contingency_fraction=0.1), {}),
    ]
    sensitivity = pd.DataFrame(
        [
            {
                "scenario": name,
                "mw_basis": spec.mw_basis,
                **capital_breakdown(items, spec, multipliers=factors)[1],
            }
            for name, spec, factors in scenarios
        ]
    )
    cooling = pd.DataFrame(
        [
            {
                "liquid_heat_fraction": fraction,
                **_balance(
                    replace(case, liquid_heat_fraction=fraction),
                    case.it_mw * 1000,
                    case.design_ambient_c,
                ),
            }
            for fraction in (0.0, 0.5, 0.85, 1.0)
        ]
    )
    scales = []
    for mw in (1, 5, 10, 20, 50, 100):
        scaled = replace(case, it_mw=float(mw))
        power = _balance(scaled, mw * 1000, scaled.design_ambient_c)
        generator = size_modules(
            ModularEquipment("Generators", 3000, derating=0.9), power["facility_kw"]
        )
        _, capital = capital_breakdown(items, CapitalScenario(mw, power["facility_kw"] / 1000))
        scales.append(
            {
                "it_mw": mw,
                "facility_mw": power["facility_kw"] / 1000,
                "generator_units": generator["installed_units"],
                **capital,
            }
        )

    return InfrastructureStudy(
        case,
        costs,
        sizing,
        hourly,
        sensitivity,
        cooling,
        pd.DataFrame(scales),
        design,
        {
            **totals,
            "design_facility_mw": design["facility_kw"] / 1000,
            "design_instantaneous_pue": design["instantaneous_pue"],
            "ups_nominal_battery_kwh": battery_kwh,
            "ups_runtime_minutes": battery.runtime_minutes(
                design["ups_output_kw"], load_power_factor=case.load_power_factor
            ),
            "period_hours": float(hourly.duration_h.sum()),
            "period_it_kwh": it_kwh,
            "period_facility_kwh": facility_kwh,
            "period_energy_pue": facility_kwh / it_kwh,
            "period_electricity_usd": facility_kwh * case.electricity_usd_per_kwh,
            "period_unmet_heat_kwh": float((hourly.unmet_heat_kw * hourly.duration_h).sum()),
        },
    )


def export_infrastructure_study(
    output: str | Path,
    case: InfrastructureCase | None = None,
) -> InfrastructureStudy:
    """Write offline HTML plus audit-friendly assumptions, sources and CSV tables."""
    from datacenter_simulator.utilities.infrastructure import write_infrastructure_report

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    study = infrastructure_study(case)
    for name in (
        "costs",
        "sizing",
        "hourly",
        "cost_sensitivity",
        "cooling_sensitivity",
        "scale_sensitivity",
    ):
        frame = getattr(study, name)
        frame.to_csv(output / f"{name}.csv", index=name == "hourly")
    for name, data in (
        ("assumptions", asdict(study.case)),
        ("evidence", infrastructure_evidence()),
        ("design", study.design),
        ("summary", study.summary),
    ):
        (output / f"{name}.json").write_text(
            json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    write_infrastructure_report(study, output / "infrastructure-study.html")
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/infrastructure"))
    parser.add_argument("--it-mw", type=float, default=20)
    args = parser.parse_args()
    study = export_infrastructure_study(args.output, InfrastructureCase(it_mw=args.it_mw))
    print(json.dumps(study.summary, indent=2))
    print(f"Report: {args.output / 'infrastructure-study.html'}")


if __name__ == "__main__":
    main()
