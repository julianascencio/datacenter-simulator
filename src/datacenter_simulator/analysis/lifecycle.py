"""Run an editable lifecycle plan and export its monthly ledger."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from datacenter_simulator.methods.lifecycle import simulate_lifecycle
from datacenter_simulator.models.lifecycle import (
    BuildStage,
    Cancellation,
    EquipmentDeposit,
    Gate,
    LifecyclePlan,
    PowerDelivery,
    ServiceLife,
    StageWork,
)
from datacenter_simulator.use_cases.lifecycle import reference_hall


def _load_plan(data: dict[str, Any]) -> LifecyclePlan:
    works = tuple(
        StageWork(
            **{
                **row,
                "stage": BuildStage(row["stage"]),
                "gates": tuple(Gate(**gate) for gate in row.get("gates", [])),
            }
        )
        for row in data["works"]
    )
    cancellation = (
        Cancellation(**data["cancellation"]) if data.get("cancellation") is not None else None
    )
    deliveries = data.get("power_deliveries")
    return LifecyclePlan(
        **{
            **data,
            "works": works,
            "service": ServiceLife(**data["service"]),
            "cancellation": cancellation,
            "equipment_deposit": EquipmentDeposit(**data["equipment_deposit"])
            if data.get("equipment_deposit") is not None
            else None,
            "power_deliveries": None
            if deliveries is None
            else tuple(PowerDelivery(**d) for d in deliveries),
        }
    )


def lifecycle_summary(ledger: pd.DataFrame) -> dict[str, str | float | int | None]:
    """Summarize one simulated tranche as of the last month in the ledger."""
    last = ledger.iloc[-1]

    def first_month(mask: pd.Series) -> str | None:
        months = ledger.loc[mask, "month"]
        return str(months.iloc[0]) if len(months) else None

    active = ledger.status == "active"
    return {
        "project": last.project,
        "through": last.month,
        "status": last.status,
        "phase": last.phase,
        "reason": last.reason,
        "commissioning_start_month": first_month(
            active & (ledger.phase == BuildStage.COMMISSIONING)
        ),
        "it_installation_month": first_month(active & (ledger.phase == BuildStage.IT_INSTALLATION)),
        "first_service_month": first_month(ledger.status == "in service"),
        "months_stalled": int((ledger.status == "stalled").sum()),
        "commissioned_it_mw": float(last.commissioned_it_mw),
        "facility_mwh": float(ledger.facility_mwh.sum()),
        "spend_usd": float(ledger.spend_usd.sum()),
    }


def main() -> None:
    """Replay the bundled hall or a user-edited JSON plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, help="Previously exported inputs.json")
    parser.add_argument("--through", help="Override the inclusive YYYY-MM reporting month")
    parser.add_argument("--output", type=Path, default=Path("outputs/lifecycle"))
    args = parser.parse_args()
    if args.inputs:
        data = json.loads(args.inputs.read_text())
        plan, through = _load_plan(data["plan"]), data["through"]
    else:
        plan, through = reference_hall(), "2047-12"
    through = args.through or through
    ledger = simulate_lifecycle(plan, through)
    summary = lifecycle_summary(ledger)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "inputs.json").write_text(
        json.dumps({"plan": asdict(plan), "through": through}, indent=2)
    )
    ledger.to_csv(args.output / "monthly.csv", index=False)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
