"""Generate the complete reproducible reference experiment and offline dashboard."""

import argparse
from dataclasses import replace
from pathlib import Path

from datacenter_simulator.methods.communications import Traffic
from datacenter_simulator.methods.cooling import cooling_alternatives
from datacenter_simulator.methods.energy import Battery
from datacenter_simulator.simulation import simulate
from datacenter_simulator.use_cases import reference_center, reference_profiles
from datacenter_simulator.utilities.report import write_report


def generate_reference(output: str | Path, hours: int = 48) -> Path:
    center = reference_center()
    profiles, generation = reference_profiles(hours)
    battery = Battery(500, 150, 150)
    result = simulate(center, profiles, generation=generation, battery=battery)
    alternatives = {
        plant.name: simulate(
            replace(center, cooling=plant), profiles, generation=generation, battery=battery
        )
        for plant in cooling_alternatives(400).values()
    }
    traffic = [Traffic(f"rack-{i + 1:02d}", f"rack-{(i + 1) % 8 + 1:02d}", 25) for i in range(8)]
    return write_report(
        center,
        result,
        Path(output) / "reference-lab.html",
        comparisons=alternatives,
        traffic=traffic,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs", help="Output directory")
    parser.add_argument(
        "--hours", type=int, default=48, help="Number of synthetic hourly intervals"
    )
    args = parser.parse_args(argv)
    print(generate_reference(args.output, args.hours).resolve())


if __name__ == "__main__":
    main()
