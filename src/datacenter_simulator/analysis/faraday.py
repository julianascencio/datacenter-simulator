"""Faraday / Eagle Mountain: off-site utility storage and hourly supply matching."""

import argparse
import json
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path

import pandas as pd

from datacenter_simulator.connectors.generation import generation_from_csv
from datacenter_simulator.methods.utility_storage import UtilityStorageResult, match_utility_storage
from datacenter_simulator.models.utility_storage import FaradayInputs, contracted_storage
from datacenter_simulator.use_cases.faraday import faraday_profiles

SCOPE = {
    "case": "Faraday / Eagle Mountain utility-linked storage",
    "facts_as_of": "2026-11-13",
    "dispatch": "causal greedy hourly matching; solar-only charging; initially empty usable window",
    "boundary": "separate generation-site POI and customer utility meter; no private wire assumed",
    "default_synthetic_assumptions": [
        "160 MW IT x constant 1.25 PUE = 200 MW facility; actual Meta load undisclosed",
        "525 MW treated as AC solar peak; source does not resolve AC/DC basis",
        "all modeled solar and storage allocated to one illustrative customer",
        "525 MW shared POI export limit; actual interconnection rating undisclosed",
        "90% round-trip efficiency; no auxiliary, transmission or standby losses",
        "600 MWh interpreted as AC deliverable usable window, not cell nameplate",
    ],
    "exclusions": [
        "Schedule 34 bill calculation, contract economics and ownership of energy attributes",
        "physical power-flow tracing, transmission congestion and distribution outages",
        "on-site UPS, islanding, reliability accreditation and capacity-market qualification",
        "grid charging, degradation, augmentation and ancillary-service commitments",
    ],
    "interpretation": [
        "Facility utility imports remain full demand in every case.",
        "Residual unmatched energy is not unserved load or a physical meter reading.",
        "Hourly matching is an illustrative energy metric, not certified 24/7 clean energy.",
        "Unmatched exports and final stored energy do not count as matched customer demand.",
        "733 MWh is an alternative sensitivity; its relation to 600 MWh is unresolved.",
        "Phase 2 is proposed, not operating; combined ratings are an additive scenario.",
        "The $689m financing covered three projects and is not Faraday BESS CAPEX.",
    ],
}


@dataclass
class FaradayStudy:
    inputs: FaradayInputs
    profiles: pd.DataFrame
    results: dict[str, UtilityStorageResult]
    comparison: pd.DataFrame
    sensitivity: pd.DataFrame


def faraday_study(
    inputs: FaradayInputs | None = None, profiles: pd.DataFrame | None = None
) -> FaradayStudy:
    """Compare common profiles and an explicit low-solar stress with traceable KPIs."""
    p = inputs or FaradayInputs()
    frame = faraday_profiles(p) if profiles is None else profiles.copy()
    if not {"demand_kw", "solar_kw"} <= set(frame):
        raise ValueError("profiles require demand_kw and solar_kw")
    results = {}
    rows = []
    scenarios = (
        ("grid_only", 0, 0, 0.0),
        ("solar_only", 0, 0, 1.0),
        ("phase1_600mwh", 150, 600, 1.0),
        ("energy_sensitivity_733mwh", 150, 733, 1.0),
        ("proposed_combined_2100mwh", 525, 2100, 1.0),
        ("low_solar_phase1", 150, 600, 0.25),
    )
    for name, power, energy, solar_scale in scenarios:
        battery = contracted_storage(power, energy, p.round_trip_efficiency) if power else None
        result = match_utility_storage(
            frame.demand_kw,
            frame.solar_kw * solar_scale,
            battery=battery,
            poi_export_limit_kw=p.poi_export_mw * 1000,
        )
        results[name] = result
        rows.append(
            {
                "scenario": name,
                "battery_power_mw": power,
                "deliverable_energy_mwh": energy,
                "solar_multiplier": solar_scale,
                **result.summary,
            }
        )
    sensitivities = []
    for demand_scale in (0.5, 1.0, 1.5):
        for poi_scale in (0.3, 0.6, 1.0):
            result = match_utility_storage(
                frame.demand_kw * demand_scale,
                frame.solar_kw,
                battery=contracted_storage(150, 600, p.round_trip_efficiency),
                poi_export_limit_kw=p.poi_export_mw * poi_scale * 1000,
            )
            sensitivities.append(
                {
                    "load_multiplier": demand_scale,
                    "poi_export_mw": p.poi_export_mw * poi_scale,
                    **result.summary,
                }
            )
    return FaradayStudy(p, frame, results, pd.DataFrame(rows), pd.DataFrame(sensitivities))


def export_faraday_study(
    output: str | Path,
    inputs: FaradayInputs | None = None,
    profiles: pd.DataFrame | None = None,
) -> FaradayStudy:
    """Write replay inputs, hourly CSVs, source ledger and a self-contained report."""
    from datacenter_simulator.utilities.faraday import write_faraday_report

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    study = faraday_study(inputs, profiles)
    study.profiles.to_csv(out / "profiles.csv", index_label="timestamp")
    study.comparison.to_csv(out / "comparison.csv", index=False)
    study.sensitivity.to_csv(out / "sensitivity.csv", index=False)
    for name, result in study.results.items():
        result.timeseries.to_csv(out / f"{name}.csv", index_label="timestamp")
    scope = {
        **SCOPE,
        "profile_origin": "synthetic" if profiles is None else "user-supplied; verify provenance",
        "active_inputs": asdict(study.inputs),
        "profile_hours": len(study.profiles),
        "profile_note": "profiles.csv overrides synthetic demand/solar when replayed",
    }
    for name, value in (("inputs", asdict(study.inputs)), ("scope", scope)):
        (out / f"{name}.json").write_text(
            json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    evidence = files("datacenter_simulator").joinpath("data/faraday_sources.json")
    (out / "evidence.json").write_text(evidence.read_text(encoding="utf-8"), encoding="utf-8")
    write_faraday_report(study, out / "faraday-storage.html")
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/faraday"))
    parser.add_argument("--inputs", type=Path, help="JSON FaradayInputs overrides")
    parser.add_argument("--hours", type=int, help="Synthetic horizon; default 168")
    parser.add_argument("--profiles", type=Path, help="CSV: timestamp,demand_kw,solar_kw")
    args = parser.parse_args()
    try:
        values = {} if args.inputs is None else json.loads(args.inputs.read_text(encoding="utf-8"))
        if args.hours is not None:
            values["hours"] = args.hours
        p = FaradayInputs(**values)
        profiles = None
        if args.profiles is not None:
            raw = pd.read_csv(args.profiles)
            timeline = pd.DatetimeIndex(pd.to_datetime(raw.timestamp, utc=True))
            profiles = pd.DataFrame(
                {
                    name: generation_from_csv(args.profiles, timeline, power_column=name)
                    for name in ("demand_kw", "solar_kw")
                }
            )
        study = export_faraday_study(args.output, p, profiles)
    except (KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(
        study.comparison[
            ["scenario", "hourly_matched_fraction", "residual_unmatched_mwh", "battery_loss_mwh"]
        ].to_string(index=False)
    )
    print("Illustrative off-site matching; actual customer meter imports remain full demand.")
    print(f"Report: {args.output / 'faraday-storage.html'}")


if __name__ == "__main__":
    main()
