"""Reusable analyses behind gallery examples 07–12."""

from dataclasses import replace

import numpy as np
import pandas as pd

from datacenter_simulator.connectors.solar import pv_from_weather
from datacenter_simulator.connectors.weather import bundled_weather
from datacenter_simulator.methods.communications import CommunicationNetwork, Link
from datacenter_simulator.methods.cooling import ThermalZone
from datacenter_simulator.methods.design import Feeder, feeder_sweep
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.methods.microgrid import MicrogridResult, simulate_dc_microgrid
from datacenter_simulator.methods.resilience import (
    CoolingUnit,
    CriticalRack,
    FailureEvent,
    PowerFeed,
    ResilienceResult,
    simulate_contingencies,
)
from datacenter_simulator.methods.weather_cooling import cooling_year
from datacenter_simulator.methods.workloads import (
    ComputeDevice,
    Job,
    JobPhase,
    WorkloadResult,
    simulate_workloads,
)
from datacenter_simulator.models.devices import Electrical
from datacenter_simulator.use_cases.engineering import (
    engineering_converter,
    engineering_grid,
    engineering_layout,
)


def dc_design_study() -> pd.DataFrame:
    """Identical row demand and supplied installation ratings at each voltage."""
    length = max(
        c.route.length_m for c in engineering_layout().connections if c.domain == "electrical"
    )
    feeders = [
        Feeder(length, area, ampacity, 0.012, installation_derating=0.9)
        for area, ampacity in ((35, 160), (70, 240), (120, 320), (240, 500))
    ]
    return feeder_sweep([400, 800], feeders, 180, converter=engineering_converter())


def resilience_study(scenario: str = "feed", *, step_s: float = 2) -> ResilienceResult:
    if scenario not in {"feed", "module", "common", "cooling"}:
        raise ValueError("unknown resilience scenario")
    feeds = [
        PowerFeed(name, {f"{name}-{i}": 100 for i in range(3)}, ("upstream",))
        for name in ("feed-A", "feed-B")
    ]
    racks = [
        CriticalRack(
            f"rack-{i + 1:02d}",
            45,
            ("feed-A", "feed-B"),
            transfer_delay_s=2,
            hold_up_s=0.2,
            zone=ThermalZone(6000, 0.05),
        )
        for i in range(4)
    ]
    cooling = [CoolingUnit("cdu", "feed-B", 250, 8)]
    component = {"feed": "feed-A", "module": "feed-A-0", "common": "upstream", "cooling": "cdu"}[
        scenario
    ]
    return simulate_contingencies(
        feeds, racks, cooling, [FailureEvent(component, 60, 180)], duration_s=300, step_s=step_s
    )


def climate_study() -> pd.DataFrame:
    """Three attributed TMY snapshots, three heat-rejection choices, matched 200 kW IT."""
    rows = []
    for climate in ("frankfurt", "tenerife", "seville"):
        weather = bundled_weather(climate)
        heat_demand = pd.Series(np.maximum(0, 18 - weather.ambient_c) * 8, index=weather.index)
        for mode in ("dry", "evaporative", "hybrid"):
            _, summary = cooling_year(weather, 200, mode=mode)
            _, recovery = cooling_year(weather, 200, mode=mode, recovery_demand_kw=heat_demand)
            rows.append(
                {
                    "climate": climate,
                    "mode": mode,
                    **summary,
                    "recovery_useful_heat_kwh": recovery["useful_heat_kwh"],
                    "recovery_pue": recovery["pue"],
                }
            )
    return pd.DataFrame(rows)


def solar_study() -> tuple[pd.DataFrame, pd.Series, dict[str, MicrogridResult]]:
    """Two summer days, satellite/reanalysis TMY solar model and a six-hour outage."""
    weather = bundled_weather("tenerife").loc["2021-06-15":"2021-06-16"]
    generation = pv_from_weather(weather, latitude=28.46, longitude=-16.25, dc_rating_kw=400)
    hours = np.arange(len(weather))
    loads = pd.DataFrame(
        {f"rack-{i + 1:02d}": 40 + 8 * np.sin(hours * 2 * np.pi / 24) ** 2 for i in range(4)},
        index=weather.index,
    )
    limits = pd.Series(250.0, index=weather.index)
    limits.iloc[30:36] = 0
    battery = Battery(600, 200, 200, initial_soc=0.7)
    results = {
        kind: simulate_dc_microgrid(
            engineering_grid(),
            loads,
            generation.pv_dc_kw,
            battery=battery,
            grid_limit_ac_kw=limits,
            pv_coupling=kind,
        )
        for kind in ("dc", "ac")
    }
    return loads, generation.pv_dc_kw, results


def network_workload_study() -> dict[str, WorkloadResult]:
    devices = [
        ComputeDevice(f"rack-{i + 1:02d}", Electrical(400, 5, 25), 30, zone=ThermalZone(1000, 0))
        for i in range(4)
    ]
    nodes = ["storage", "switch", *[d.id for d in devices]]
    jobs = [
        Job(
            f"job-{i + 1}",
            d.id,
            (
                JobPhase("compute", 15),
                JobPhase("transfer", 20, "storage", d.id),
                JobPhase("compute", 15),
            ),
            deadline_s=80,
        )
        for i, d in enumerate(devices)
    ]
    results = {}
    for name, capacity, failures in (
        ("100 Gbps", 100, []),
        ("10 Gbps", 10, []),
        ("10 Gbps + link failure", 10, [FailureEvent("uplink-a", 25, 55)]),
    ):
        links = [
            Link("uplink-a", "storage", "switch", capacity / 2),
            Link("uplink-b", "storage", "switch", capacity / 2),
        ]
        links += [Link(f"link-{d.id}", "switch", d.id, 100) for d in devices]
        network = CommunicationNetwork(nodes, links)
        results[name] = simulate_workloads(network, devices, jobs, events=failures, duration_s=200)
    # Demonstrate power/thermal constraints through the same method.
    network = CommunicationNetwork(
        nodes,
        [Link("uplink", "storage", "switch", 100)]
        + [Link(f"link-{d.id}", "switch", d.id, 100) for d in devices],
    )
    constrained = [
        replace(d, cooling_capacity_kw=10, throttle_c=25, power_cap_kw=20) for d in devices
    ]
    results["Power + thermal cap"] = simulate_workloads(network, constrained, jobs, duration_s=200)
    return results


def export_engineering_study(output: str = "outputs/engineering") -> None:
    """Export the linked lab, solved single-line, numerical tables and provenance.

    No optional solar dependency or network connection is needed for this export.
    """
    import json
    from importlib.metadata import version
    from pathlib import Path

    from datacenter_simulator.methods.hydraulics import Pump, solve_cdu
    from datacenter_simulator.use_cases.engineering import engineering_cooling
    from datacenter_simulator.utilities.engineering import (
        dc_grid_single_line,
        write_engineering_lab,
    )

    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    layout = engineering_layout()
    scenario = resilience_study()
    write_engineering_lab(layout, scenario, destination / "engineering-lab.html")
    grid = engineering_grid()
    solution = grid.solve({f"rack-{i + 1:02d}": 45 for i in range(4)})
    dc_grid_single_line(grid, solution).write_html(destination / "dc-grid.html")
    solution.buses.to_csv(destination / "dc-buses.csv")
    solution.lines.to_csv(destination / "dc-lines.csv")
    scenario.racks.to_csv(destination / "rack-events.csv", index=False)
    scenario.timeline.to_csv(destination / "event-timeline.csv", index=False)
    dc_design_study().to_csv(destination / "feeder-design.csv", index=False)
    solve_cdu(engineering_cooling(), Pump(150000, 2500)).branches.to_csv(
        destination / "cdu-branches.csv"
    )
    (destination / "study.json").write_text(
        json.dumps(
            {
                "package_version": version("datacenter-simulator"),
                "inputs": "datacenter_simulator.use_cases.engineering",
                "resilience": scenario.summary,
                "dc_kcl_residual_a": solution.maximum_kcl_error_a,
                "assumptions": "Illustrative equipment and geometry; deterministic feed outage",
                "models": "Steady resistive DC, steady hydraulics, event-resolved capacity/thermal",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export the offline engineering study")
    parser.add_argument("--output", default="outputs/engineering")
    export_engineering_study(parser.parse_args().output)
