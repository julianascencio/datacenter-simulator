"""Weak-grid E-STATCOM planning, device sizing and external flicker evidence."""

import argparse
import json
from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from pathlib import Path

import pandas as pd

from datacenter_simulator.connectors.power_quality import (
    read_power_profile,
    summarize_line_to_line_pst,
)
from datacenter_simulator.methods.power_quality import (
    PowerQualityResult,
    ideal_source_benchmark,
    simulate_power_quality,
    sizing_sweep,
)
from datacenter_simulator.models.power_quality import EStatcom, WeakGrid
from datacenter_simulator.use_cases.power_quality import synthetic_ai_load


@dataclass
class PowerQualityStudy:
    cases: dict[str, PowerQualityResult]
    comparison: pd.DataFrame
    sizing: pd.DataFrame
    candidates: tuple[EStatcom, ...]
    profiles: dict[str, pd.DataFrame]
    grids: tuple[WeakGrid, ...]


def power_quality_study(
    grid: WeakGrid | None = None,
    compensator: EStatcom | None = None,
    profile: pd.DataFrame | None = None,
) -> PowerQualityStudy:
    """Compare identical loads; screen 9 sizes across 3 SCRs and 2 profiles.

    The finite-impedance ideal-source benchmark is unlimited-energy and is
    excluded from converter sizing. The sustained-step case is an explicit
    stress test, excluded from the pulsed/bursty screening envelope.
    """
    grid, c = grid or WeakGrid(), compensator or EStatcom()
    profile = synthetic_ai_load() if profile is None else profile
    cases = {
        "uncompensated": simulate_power_quality(profile, grid),
        "statcom_q_only": simulate_power_quality(profile, grid, replace(c, nominal_energy_mj=0)),
        "estatcom": simulate_power_quality(profile, grid, c),
        "ideal_auxiliary_source": ideal_source_benchmark(profile, grid),
    }
    comparison = pd.DataFrame([{"case": name, **r.summary} for name, r in cases.items()])
    base = cases["uncompensated"].summary
    for metric in ("pcc_active_swing_mw", "voltage_excursion_pu"):
        if base[metric] > 0:
            comparison[metric + "_reduction_pct"] = 100 * (1 - comparison[metric] / base[metric])
    profiles = {"input": profile, "bursty_synthetic": synthetic_ai_load(shape="bursty")}
    grids = tuple(replace(grid, scr=scr) for scr in sorted({2.0, grid.scr, 8.0}))
    candidates = tuple(
        replace(
            c,
            rating_mva=rating,
            active_limit_mw=min(c.active_limit_mw, rating),
            nominal_energy_mj=energy,
        )
        for rating in (25.0, 50.0, 100.0)
        for energy in (50.0, 225.0, 452.0)
    )
    sizing = sizing_sweep(
        profiles, grids, candidates, maximum_swing_mw=60, maximum_voltage_excursion_pu=0.025
    )
    return PowerQualityStudy(cases, comparison, sizing, candidates, profiles, grids)


def export_power_quality_study(
    output: str | Path,
    grid: WeakGrid | None = None,
    compensator: EStatcom | None = None,
    profile: pd.DataFrame | None = None,
    flicker: pd.DataFrame | None = None,
) -> PowerQualityStudy:
    """Write replay inputs, traces, sizing, evidence and an offline HTML report."""
    from plotly import graph_objects as go
    from plotly.subplots import make_subplots

    grid, c = grid or WeakGrid(), compensator or EStatcom()
    # Validate optional evidence before creating files.
    external = None if flicker is None else summarize_line_to_line_pst(flicker)
    study = power_quality_study(grid, c, profile)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    study.comparison.to_csv(output / "comparison.csv", index=False)
    study.sizing.to_csv(output / "sizing.csv", index=False)
    for name, result in study.cases.items():
        result.timeseries.to_csv(output / f"{name}.csv", index=False)
    for name, trace in study.profiles.items():
        trace.to_csv(output / f"profile_{name}.csv", index=False)
    stress_profile = synthetic_ai_load(shape="sustained")
    stress = simulate_power_quality(stress_profile, grid, c)
    stress.timeseries.to_csv(output / "sustained_stress.csv", index=False)
    if external is not None and flicker is not None:
        flicker.to_csv(output / "external_pst_input.csv", index=False)
        external.to_csv(output / "external_pst_summary.csv", index=False)
    scope = {
        "model": "balanced quasi-static constant-PQ AC; ideal within-interval converter response",
        "profile_status": "synthetic"
        if profile is None
        else "user-supplied; not independently verified",
        "pcc_boundary": "facility demand; downstream transformer/UPS dynamics excluded",
        "pst_status": "not computed; voltage excursion is not Pst",
        "no_compliance_claim": True,
        "sizing_targets": {"maximum_swing_mw": 60, "maximum_voltage_excursion_pu": 0.025},
        "sizing_grids": [asdict(g) for g in study.grids],
        "sizing_candidates": [asdict(candidate) for candidate in study.candidates],
        "sizing_profiles": list(study.profiles),
        "stress_test_in_sizing_envelope": False,
        "ideal_benchmark": "identical source phasors; Z_aux=Z_grid; unlimited energy",
        "h_interpretation": "452 MJ assumes H=E_nom/100 MVA=4.52 s; source H basis unconfirmed",
        "exclusions": [
            "EMT",
            "harmonics",
            "unbalance",
            "frequency/PLL stability",
            "protection",
            "UPS battery dispatch",
            "Pst/Plt computation",
            "vendor calibration",
            "economics",
        ],
        "stress_summary": stress.summary,
    }
    for name, value in (
        ("inputs", {"grid": asdict(grid), "compensator": asdict(c)}),
        ("scope", scope),
    ):
        (output / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    evidence = files("datacenter_simulator").joinpath("data/power_quality_sources.json")
    (output / "evidence.json").write_text(evidence.read_text(encoding="utf-8"), encoding="utf-8")
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=(
            "Original-grid PCC active power",
            "Balanced PCC voltage (not Pst)",
            "Finite E-STATCOM energy inventory",
        ),
    )
    for name, result in study.cases.items():
        trace = result.timeseries
        for row, column in ((1, "pcc_p_mw"), (2, "voltage_pu")):
            fig.add_trace(
                go.Scatter(
                    x=trace.time_s,
                    y=trace[column],
                    name=name,
                    legendgroup=name,
                    showlegend=row == 1,
                ),
                row=row,
                col=1,
            )
    trace = study.cases["estatcom"].timeseries
    fig.add_trace(
        go.Scatter(x=trace.time_s, y=trace.energy_end_mj, name="Energy at interval end"),
        row=3,
        col=1,
    )
    fig.add_hline(y=c.minimum_soc * c.nominal_energy_mj, row=3, col=1, line_dash="dot")
    fig.add_hline(y=c.maximum_soc * c.nominal_energy_mj, row=3, col=1, line_dash="dot")
    fig.update_yaxes(title_text="MW", row=1, col=1)
    fig.update_yaxes(title_text="pu", row=2, col=1)
    fig.update_yaxes(title_text="MJ", row=3, col=1)
    fig.update_xaxes(title_text="Interval start [s]", row=3, col=1)
    fig.update_layout(height=950, template="plotly_white", legend={"orientation": "h", "y": -0.12})
    sizes = (
        study.sizing.groupby(["rating_mva", "nominal_energy_mj"])
        .agg(
            passed_cases=("screen_pass", "sum"),
            tested_cases=("screen_pass", "size"),
            passes_all=("passes_all_tested_cases", "all"),
        )
        .reset_index()
    )
    sizes.to_csv(output / "candidate_summary.csv", index=False)
    columns = [
        "case",
        "pcc_active_swing_mw",
        "voltage_excursion_pu",
        "voltage_min_pu",
        "voltage_max_pu",
    ]
    feasible_count = int(sizes.passes_all.sum())
    sizing_outcome = (
        f"{feasible_count} tested candidate(s) pass every case."
        if feasible_count
        else "No tested candidate passes every case; no adequate size has been established."
    )
    description = (
        "<h1>AI load swings on a weak grid</h1>"
        "<p>Quasi-static planning study. Input load is "
        + ("synthetic" if profile is None else "user-supplied, unverified")
        + ". Balanced voltage excursions are <strong>not Pst</strong>. "
        "The supplied post's 59% flicker and 44% power-swing reductions are unverified external "
        "reports; this study does not reproduce them.</p>"
        "<p>The ideal-source benchmark supplies sustained energy through finite impedance. "
        "It is not an achievable storage specification. Q-only STATCOM cannot buffer active "
        "load energy; E-STATCOM shares its MVA limit between P and Q.</p>"
        + study.comparison[columns].to_html(index=False, float_format=lambda x: f"{x:.5g}")
        + "<h2>Converter and energy candidates</h2>"
        "<p>Screen: PCC swing ≤60 MW and voltage excursion ≤0.025 pu across the exported "
        "input/bursty profiles and SCR cases. These are illustrative targets. Passing does "
        "not establish flicker compliance, stability or a globally minimum design.</p>"
        + f"<p><strong>{sizing_outcome}</strong></p>"
        + sizes.to_html(index=False)
        + "<h2>Sustained-load stress test</h2><p>Excluded from the pulse-sizing envelope. "
        f"PCC swing: {stress.summary['pcc_active_swing_mw']:.2f} MW; "
        f"terminal energy: {stress.summary['terminal_energy_mj']:.2f} MJ. "
        "Smoothing cannot indefinitely hide a higher mean load. Review sustained_stress.csv.</p>"
        + "<h2>Flicker evidence</h2>"
        + (
            "<p>No external line-to-line Pst results supplied.</p>"
            if external is None
            else external.to_html(index=False)
        )
        + "<p>Replay inputs, per-interval energy balances, limitations, source ledger and "
        "candidate results are supplied as JSON/CSV alongside this report.</p>"
    )
    html = fig.to_html(include_plotlyjs=True, full_html=True)
    html = html.replace(
        "</head>",
        "<style>body{font-family:system-ui;max-width:1200px;margin:24px auto;"
        "padding:0 16px;color:#18394b;line-height:1.5}table{border-collapse:collapse;"
        "display:block;overflow-x:auto}td,th{padding:6px 10px}</style></head>",
    )
    (output / "power-quality.html").write_text(
        html.replace("<body>", "<body>" + description), encoding="utf-8"
    )
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/power-quality"))
    parser.add_argument("--inputs", type=Path, help="JSON with grid and compensator parameters")
    parser.add_argument("--profile", type=Path, help="time_s/load_mw/load_mvar CSV")
    parser.add_argument("--flicker", type=Path, help="External 600 s AB/BC/CA Pst results CSV")
    args = parser.parse_args()
    try:
        values = {} if args.inputs is None else json.loads(args.inputs.read_text())
        study = export_power_quality_study(
            args.output,
            WeakGrid(**values.get("grid", {})),
            EStatcom(**values.get("compensator", {})),
            None if args.profile is None else read_power_profile(args.profile),
            None if args.flicker is None else pd.read_csv(args.flicker),
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    print(
        study.comparison[["case", "pcc_active_swing_mw", "voltage_excursion_pu"]].to_string(
            index=False
        )
    )
    print("Voltage excursion is not Pst; synthetic defaults are not PSCAD validation.")
    print(f"Report: {args.output / 'power-quality.html'}")


if __name__ == "__main__":
    main()
