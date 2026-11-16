"""Published-result replay plus an independent native engineering screen."""

import argparse
import json
from dataclasses import asdict, dataclass, replace
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.speed_to_power import (
    PUBLISHED_ARCHITECTURES,
    bundled_published_results,
    power_profiles_from_csv,
    speed_power_sources,
    validate_power_profiles,
)
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.speed_to_power import (
    SupplyDispatch,
    break_even_gpu_value,
    dispatch_solar_storage,
    facility_load_summary,
    levelized_power_cost,
    paper_supply_paths,
    project_cashflows,
    published_cost_comparison,
    solar_drought_energy,
)
from datacenter_simulator.models.speed_to_power import ComputeFleet, PowerProject, SpeedPowerInputs
from datacenter_simulator.use_cases.speed_to_power import synthetic_power_profiles


@dataclass
class SpeedPowerStudy:
    inputs: SpeedPowerInputs
    profiles: pd.DataFrame
    candidates: pd.DataFrame
    selected: pd.DataFrame
    cashflows: pd.DataFrame
    sensitivity: pd.DataFrame
    dispatches: dict[str, SupplyDispatch]
    load: dict[str, float]


def speed_power_study(
    inputs: SpeedPowerInputs | None = None, profiles: pd.DataFrame | None = None
) -> SpeedPowerStudy:
    """Nine finite PV/BESS candidates per topology, then gas and grid baselines.

    Solar: repeat conservative, derated design-year dispatch for annual costs.
    Select minimum base LCOE only among candidates meeting full-load-hour uptime.
    Gas/grid: ideal firm supply, no outage/fuel scarcity model; capacity and fuel
    use include conversion losses. Both meet the same minimum service criterion,
    with actual served energy retained in each denominator. Infeasible designs
    stay visible and are excluded from selection, never silently promoted.
    """
    p = inputs or SpeedPowerInputs()
    fleet = ComputeFleet(gpu_count=p.gpu_count)
    profiles = synthetic_power_profiles(fleet) if profiles is None else profiles.copy()
    validate_power_profiles(profiles, annual=True)
    load = facility_load_summary(profiles, fleet)
    load["worst_five_day_yield_kwh_per_kwp"] = solar_drought_energy(profiles)
    load["annual_yield_kwh_per_kwp"] = float(profiles.pv_dc_per_kwp.sum())
    rows, cashflows, selected, sensitivity = [], [], [], []
    dispatches: dict[str, SupplyDispatch] = {}
    projects: dict[str, PowerProject] = {}
    paths = paper_supply_paths()

    def evaluate(project: PowerProject) -> tuple[pd.DataFrame, dict[str, float]]:
        flows = project_cashflows(
            project,
            gpu_count=p.gpu_count,
            horizon_years=p.horizon_years,
            compute_ready_year=p.compute_ready_year,
        )
        return flows, levelized_power_cost(
            flows, discount_rate=p.discount_rate, gpu_hour_value_usd=p.gpu_hour_value_usd
        )

    for name in ("ac_solar", "dc_solar"):
        best = float("inf")
        for ratio in (5, 9, 12):
            for hours in (18, 36, 72):
                pv = fleet.average_it_kw * ratio
                nominal_battery = load["average_terminal_kw"] * hours
                # Usable capacity after the stated derate; no extra hidden SOC window.
                storage = Battery(
                    nominal_battery * p.battery_retained_fraction,
                    nominal_battery / 4,
                    nominal_battery / 4,
                    charge_efficiency=0.98 * np.sqrt(0.9),
                    discharge_efficiency=0.98 * np.sqrt(0.9),
                    minimum_soc=0,
                    maximum_soc=1,
                    initial_soc=0,
                )
                dispatch = dispatch_solar_storage(
                    profiles,
                    paths[name],
                    pv_kwp=pv,
                    battery=storage,
                    pv_retained_fraction=p.pv_retained_fraction,
                )
                if dispatch.summary["delivered_kwh"] <= 0:
                    rows.append(
                        {
                            "architecture": name,
                            "pv_kwp": pv,
                            "battery_nominal_kwh": nominal_battery,
                            "deployment_years": p.solar_deployment_years,
                            "feasible": False,
                            "exclusion_reason": "zero delivered energy",
                            **dispatch.summary,
                        }
                    )
                    continue
                capital = pv * (p.ac_pv_usd_per_kw if name == "ac_solar" else p.dc_pv_usd_per_kw)
                capital += nominal_battery * p.battery_usd_per_kwh
                project = PowerProject(
                    name,
                    p.solar_deployment_years,
                    capital,
                    capital * p.solar_om_fraction,
                    dispatch.summary["delivered_kwh"],
                    nominal_battery * p.battery_replacement_usd_per_kwh,
                )
                flows, economics = evaluate(project)
                feasible = dispatch.summary["full_load_hour_fraction"] >= p.minimum_uptime
                row = {
                    "architecture": name,
                    "pv_kwp": pv,
                    "battery_nominal_kwh": nominal_battery,
                    "deployment_years": project.deployment_years,
                    "feasible": feasible,
                    **dispatch.summary,
                    **economics,
                }
                rows.append(row)
                if feasible and economics["base_lcoe_usd_per_kwh"] < best:
                    best = economics["base_lcoe_usd_per_kwh"]
                    projects[name] = project
                    dispatches[name] = dispatch
                    best_row = row
        if name in projects:
            selected.append(best_row)

    terminal_energy = float((profiles.it_kw + profiles.cooling_kw).sum())
    for name in ("gas", "grid"):
        path = paths[name]
        source_load = (
            profiles.it_kw / path.it_efficiency + profiles.cooling_kw / path.cooling_efficiency
        )
        source_energy = float(source_load.sum())
        # Use peak IT and worst thermal overhead at the source, not average MW.
        peak_cooling = fleet.peak_it_kw * load["thermal_overhead_p99"] - fleet.peak_it_kw
        source_design = (
            fleet.peak_it_kw / path.it_efficiency + peak_cooling / path.cooling_efficiency
        ) * fleet.contingency
        if name == "gas":
            capital = source_design * p.gas_usd_per_kw
            cost_per_kwh = p.gas_heat_rate_mmbtu_per_mwh * p.gas_usd_per_mmbtu / 1000
            operating = source_energy * (cost_per_kwh + p.gas_variable_om_usd_per_kwh)
            operating += source_design * p.gas_fixed_om_usd_per_kw_year
            delay = p.gas_deployment_years
        else:
            capital = source_design * p.grid_usd_per_kw
            operating = source_energy * p.grid_usd_per_kwh
            delay = p.grid_deployment_years
        project = PowerProject(name, delay, capital, operating, terminal_energy)
        _, economics = evaluate(project)
        projects[name] = project
        row = {
            "architecture": name,
            "pv_kwp": 0.0,
            "battery_nominal_kwh": 0.0,
            "deployment_years": delay,
            "source_design_kw": source_design,
            "source_energy_kwh": source_energy,
            "feasible": True,
            "full_load_hour_fraction": 1.0,
            "energy_served_fraction": 1.0,
            "delivered_kwh": terminal_energy,
            "unserved_kwh": 0.0,
            "conversion_loss_kwh": source_energy - terminal_energy,
            **economics,
        }
        rows.append(row)
        selected.append(row)

    for name, project in projects.items():
        flows, _ = evaluate(project)
        cashflows.append(flows.assign(architecture=name))
        for timeline_factor in (0.5, 1.0, 1.5):
            delay = project.deployment_years * timeline_factor
            if max(delay, p.compute_ready_year) >= p.horizon_years:
                continue
            adjusted = replace(project, deployment_years=delay)
            flows, _ = evaluate(adjusted)
            for value in (0.0, 1.0, 2.4, 4.0):
                sensitivity.append(
                    {
                        "architecture": name,
                        "timeline_factor": timeline_factor,
                        "gpu_hour_value_usd": value,
                        "deployment_years": delay,
                        **levelized_power_cost(
                            flows, discount_rate=p.discount_rate, gpu_hour_value_usd=value
                        ),
                    }
                )
    return SpeedPowerStudy(
        p,
        profiles,
        pd.DataFrame(rows),
        pd.DataFrame(selected),
        pd.concat(cashflows, ignore_index=True),
        pd.DataFrame(sensitivity),
        dispatches,
        load,
    )


def export_speed_power_study(
    output: str | Path,
    inputs: SpeedPowerInputs | None = None,
    profiles: pd.DataFrame | None = None,
) -> SpeedPowerStudy:
    """Export offline report, inputs, profiles, evidence and auditable CSV tables."""
    import plotly.graph_objects as go

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    study = speed_power_study(inputs, profiles)
    source = speed_power_sources()
    published = bundled_published_results()
    published_rows, shares = [], []
    for accelerated in (False, True):
        for value in (0.0, 1.0, 2.4, 4.0):
            comparison = published_cost_comparison(
                published, gpu_hour_value_usd=value, accelerated_gas=accelerated
            )
            counts = comparison.winner.value_counts()
            for name in PUBLISHED_ARCHITECTURES:
                shares.append(
                    {
                        "accelerated_gas": accelerated,
                        "gpu_hour_value_usd": value,
                        "architecture": name,
                        "locations": int(counts.get(name, 0)),
                        "share_pct": 100 * counts.get(name, 0) / len(comparison),
                    }
                )
            if value == 2.4:
                published_rows.append(comparison.assign(accelerated_gas=accelerated))
    share_table = pd.DataFrame(shares)
    for name in ("candidates", "selected", "cashflows", "sensitivity"):
        getattr(study, name).to_csv(output / f"{name}.csv", index=False)
    study.profiles.to_csv(output / "profiles.csv", index_label="timestamp")
    (output / "inputs.json").write_text(json.dumps(asdict(study.inputs), indent=2) + "\n")
    (output / "sources.json").write_text(json.dumps(source, indent=2) + "\n")
    (output / "load_summary.json").write_text(json.dumps(study.load, indent=2) + "\n")
    share_table.to_csv(output / "published_shares.csv", index=False)
    pd.concat(published_rows).to_csv(output / "published_rankings.csv", index=False)
    for name, dispatch in study.dispatches.items():
        dispatch.hourly.to_csv(output / f"hourly_{name}.csv", index_label="timestamp")

    charts = []
    figure = go.Figure()
    for name in PUBLISHED_ARCHITECTURES:
        data = share_table[(share_table.architecture == name) & ~share_table.accelerated_gas]
        figure.add_scatter(
            x=data.gpu_hour_value_usd, y=data.share_pct, name=name, mode="lines+markers"
        )
    figure.update_layout(
        title="Published model results<br>Baseline deployment",
        xaxis_title="Assumed USD/GPU-hour",
        yaxis_title="Locations ranked lowest [%]",
    )
    charts.append(figure)
    figure = go.Figure()
    s = study.selected
    figure.add_bar(x=s.architecture, y=s.base_lcoe_usd_per_kwh, name="Energy cost")
    figure.add_bar(x=s.architecture, y=s.speed_premium_usd_per_kwh, name="Lost compute premium")
    figure.update_layout(
        barmode="stack",
        title="Native synthetic scenario<br>Feasible designs",
        yaxis_title="Illustrative USD / delivered kWh",
    )
    charts.append(figure)
    figure = go.Figure()
    for name in s.architecture:
        data = study.sensitivity[
            (study.sensitivity.architecture == name)
            & (study.sensitivity.gpu_hour_value_usd == study.inputs.gpu_hour_value_usd)
        ]
        # Include an arbitrary user valuation, even if it is outside the canned grid.
        if data.empty:
            data = study.sensitivity[
                (study.sensitivity.architecture == name)
                & (study.sensitivity.gpu_hour_value_usd == 2.4)
            ].copy()
            data["adjusted_lcoe_usd_per_kwh"] = (
                data.base_lcoe_usd_per_kwh + data.gpu_value_slope * study.inputs.gpu_hour_value_usd
            )
        figure.add_scatter(
            x=data.deployment_years,
            y=data.adjusted_lcoe_usd_per_kwh,
            name=name,
            mode="lines+markers",
        )
    figure.update_layout(
        title="Native deployment sensitivity<br>Fixed capacities and costs",
        xaxis_title="Years to power",
        yaxis_title="Speed-adjusted USD/kWh",
    )
    charts.append(figure)
    plots = []
    for i, fig in enumerate(charts):
        fig.update_layout(
            template="plotly_white",
            autosize=True,
            margin={"l": 55, "r": 15, "t": 80, "b": 100},
            height=460,
            title_font_size=16,
            legend={"orientation": "h", "y": -0.2},
        )
        plots.append(
            fig.to_html(full_html=False, include_plotlyjs=i == 0, config={"responsive": True})
        )

    baseline = share_table[(share_table.gpu_hour_value_usd == 2.4)]
    table_columns = [
        "architecture",
        "full_load_hour_fraction",
        "energy_served_fraction",
        "base_lcoe_usd_per_kwh",
        "adjusted_lcoe_usd_per_kwh",
    ]
    crossing: float | None = None
    if "dc_solar" in set(s.architecture):
        dc = s[s.architecture == "dc_solar"].iloc[0]
        grid = s[s.architecture == "grid"].iloc[0]
        crossing = break_even_gpu_value(
            dc.base_lcoe_usd_per_kwh,
            dc.gpu_value_slope,
            grid.base_lcoe_usd_per_kwh,
            grid.gpu_value_slope,
        )
    downloads = [
        "inputs.json",
        "profiles.csv",
        "sources.json",
        "load_summary.json",
        "candidates.csv",
        "selected.csv",
        "cashflows.csv",
        "sensitivity.csv",
        "published_shares.csv",
        "published_rankings.csv",
    ]
    links = " · ".join(f'<a href="{name}">{name}</a>' for name in downloads)
    crossing_text = (
        "no nonnegative crossing" if crossing is None else f"{crossing:.3f} USD/GPU-hour"
    )
    baseline_html = baseline.to_html(index=False, float_format=lambda x: f"{x:.4f}")
    selected_html = s[table_columns].to_html(index=False, float_format=lambda x: f"{x:.4f}")
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Speed to power</title>
<style>body{{font:16px system-ui;color:#203044;background:#f4f7fa;margin:0}}
main{{max-width:1140px;margin:auto;padding:24px}}h1{{font-size:clamp(28px,5vw,44px)}}
section{{background:white;padding:20px;margin:22px 0;border-radius:12px}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;font-size:13px}}
th,td{{padding:8px;text-align:left;border-bottom:1px solid #ddd}}
a{{color:#126d83}}.downloads{{overflow-wrap:anywhere}}
.plotly-graph-div{{width:100%}}p{{line-height:1.6}}</style></head>
<body><main><h1>Speed to power</h1>
<p>Energy infrastructure cost and the value of earlier compute.</p>
<section><h2>1. Published model results</h2><p>Newkirk et al., arXiv:2611.17098v1.
4,317 locations, 100,000 GPUs, MV topology, 2022 USD. These are imported author-generated
results, not an independent rerun or measurements. GPU valuation changes retain fixed designs.</p>
<div class="scroll">{baseline_html}</div>{plots[0]}</section>
<section><h2>2. Native synthetic engineering scenario</h2><p>Illustrative hourly solar and cooling;
nine PV/storage candidates per architecture. Reject candidates below the full-load-hour requirement.
Gas and grid are ideal firm supply baselines.
Actual delivered energy is retained in each denominator.
Battery SOC is periodic; no free initial energy. Repeated conservative design year
with explicit PV/BESS derates and one battery replacement; no BLAST-Lite degradation,
turbine fleet optimization or SLA certification.</p>
<p>DC/grid break-even GPU value: {escape(crossing_text)}.
Rental value is an opportunity-cost assumption, not guaranteed net profit.</p>
<div class="scroll">{selected_html}</div>{plots[1]}{plots[2]}</section>
<section><h2>Replay and audit</h2><p class="downloads">{links}</p>
<p>Run with --inputs inputs.json --profiles profiles.csv. All scenario costs are illustrative;
source findings and their 2022 price basis remain separate. Hourly reliability does not capture
training restarts, correlated outages, grid-forming transients, extreme-weather ensembles,
protection, or GPU replacement economics.</p></section>
</main></body></html>"""
    (output / "speed-to-power.html").write_text(html)
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/speed-to-power"))
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--profiles", type=Path)
    args = parser.parse_args()
    inputs = SpeedPowerInputs(**json.loads(args.inputs.read_text())) if args.inputs else None
    profiles = power_profiles_from_csv(args.profiles) if args.profiles else None
    study = export_speed_power_study(args.output, inputs, profiles)
    print(
        study.selected[
            ["architecture", "base_lcoe_usd_per_kwh", "adjusted_lcoe_usd_per_kwh"]
        ].to_string(index=False)
    )
    print(f"Report: {args.output / 'speed-to-power.html'}")


if __name__ == "__main__":
    main()
