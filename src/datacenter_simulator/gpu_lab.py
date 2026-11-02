"""CLI for read-only collection, CPU replay, hardware benchmarking and policy reports."""

import argparse
import json
from pathlib import Path

import pandas as pd

from datacenter_simulator.connectors.gpu import GPUTrace, NVMLCollector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="read-only NVML telemetry; no configuration writes")
    collect.add_argument("--device", default="0", help="physical NVML index or GPU UUID")
    collect.add_argument("--duration", type=float, default=60)
    collect.add_argument("--interval", type=float, default=0.2)
    collect.add_argument("--output", type=Path, required=True)
    replay = sub.add_parser(
        "replay", help="CPU-only trace integration; synthetic fixture by default"
    )
    replay.add_argument("--trace", type=Path)
    replay.add_argument("--step", type=float, default=1)
    replay.add_argument("--max-gap", type=float, default=5)
    replay.add_argument("--output", type=Path, default=Path("outputs/gpu-replay"))
    benchmark = sub.add_parser("benchmark", help="fixed-quality CUDA batch inference with Zeus")
    benchmark.add_argument("--device", default="0", help="physical NVML index or GPU UUID")
    benchmark.add_argument("--cuda-device", type=int, default=0)
    benchmark.add_argument("--batch-size", type=int, default=128)
    benchmark.add_argument("--repetitions", type=int, default=1000)
    benchmark.add_argument("--warmup", type=int, default=100)
    benchmark.add_argument("--windows", type=int, default=3)
    benchmark.add_argument("--interval", type=float, default=0.2)
    benchmark.add_argument("--power-limit", type=float)
    benchmark.add_argument("--allow-power-control", action="store_true")
    benchmark.add_argument("--output", type=Path, required=True)
    build_model = sub.add_parser("build-model", help="same-configuration measured benchmark curve")
    build_model.add_argument("benchmarks", nargs="+", type=Path)
    build_model.add_argument("--idle-board-w", type=float, required=True)
    build_model.add_argument("--idle-source", required=True)
    build_model.add_argument("--output", type=Path, required=True)
    study = sub.add_parser("study", help="offline synthetic facility comparison and sensitivity")
    study.add_argument("--output", type=Path, default=Path("outputs/gpu-lab"))
    study.add_argument("--performance-model", type=Path)
    study.add_argument(
        "--sensitivity",
        action="store_true",
        help="synthetic reference sensitivity (not custom model)",
    )
    args = parser.parse_args()
    if args.command == "collect":
        selector = int(args.device) if args.device.isdigit() else args.device
        with NVMLCollector(selector) as collector:
            trace = collector.collect(args.duration, interval_s=args.interval)
        trace.write_csv(args.output)
        print(args.output)
    elif args.command == "replay":
        from datacenter_simulator.use_cases.gpu_lab import synthetic_trace

        trace = GPUTrace.read_csv(args.trace) if args.trace else synthetic_trace()
        args.output.mkdir(parents=True, exist_ok=True)
        trace.write_csv(args.output / "trace.csv")
        profile = trace.replay(step_s=args.step, max_gap_s=args.max_gap)
        profile.to_csv(args.output / "profile.csv", index_label="timestamp")
        summary = {
            "kind": trace.metadata["kind"],
            "boundary": trace.metadata["boundary"],
            "energy_j": float(profile.sum() * args.step * 1000),
            "source_duration_s": float(trace.samples.elapsed_s.iloc[-1]),
            "output_duration_s": len(profile) * args.step,
            "tail_padding": "explicit zero only after trace end; never missing telemetry",
        }
        (args.output / "replay.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    elif args.command == "benchmark":
        from datacenter_simulator.gpu_benchmark import run_benchmark

        benchmark_result = run_benchmark(
            args.output,
            nvml_device=int(args.device) if args.device.isdigit() else args.device,
            cuda_device=args.cuda_device,
            batch_size=args.batch_size,
            repetitions=args.repetitions,
            warmup=args.warmup,
            windows=args.windows,
            interval_s=args.interval,
            power_limit_w=args.power_limit,
            allow_control=args.allow_power_control,
        )
        print(json.dumps({"kind": benchmark_result["kind"], "output": str(args.output)}, indent=2))
    elif args.command == "build-model":
        from datacenter_simulator.gpu_benchmark import (
            model_from_benchmarks,
            write_performance_model,
        )

        built_model = model_from_benchmarks(
            args.benchmarks, idle_board_w=args.idle_board_w, idle_source=args.idle_source
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_performance_model(built_model, args.output)
        print(args.output)
    elif args.command == "study":
        from datacenter_simulator.gpu_benchmark import read_performance_model
        from datacenter_simulator.use_cases.gpu_lab import (
            compare_policies,
            gpu_scenario,
            sensitivity_study,
        )
        from datacenter_simulator.utilities.report import write_report

        if args.performance_model and args.sensitivity:
            parser.error(
                "--sensitivity uses the synthetic reference; run it separately from a custom model"
            )
        model = read_performance_model(args.performance_model) if args.performance_model else None
        results = compare_policies(performance_model=model)
        args.output.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([r.summary for r in results.values()]).to_csv(
            args.output / "comparison.csv", index=False
        )
        center, _, _, _, _ = gpu_scenario()
        for name, result in results.items():
            result.jobs.to_csv(args.output / f"{name}-jobs.csv")
            write_report(center, result.facility, args.output / f"{name}.html")
        if args.sensitivity:
            sensitivity_study().to_csv(args.output / "sensitivity.csv", index=False)
        manifest = {
            "result_kind": "simulated",
            "facility_inputs": "synthetic",
            "performance_evidence": model.evidence_kind if model else "synthetic",
            "hardware_validation": "not performed by offline study",
            "perfect_foresight": True,
            "terminal_soc": "equal to initial for every policy",
            "performance_model": str(args.performance_model) if model else "built-in synthetic",
            "attribution": "ASVA Consulting; AI-assisted development; no NVIDIA endorsement",
        }
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(
            pd.DataFrame([r.summary for r in results.values()])[
                ["policy", "feasible", "completed_tasks", "energy_cost", "facility_kwh"]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()
