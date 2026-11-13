"""Illustrative migration paths; source context is not parameter calibration."""

from datacenter_simulator.models.power_architecture import (
    PowerArchitecture,
    PowerStage,
    PowerStudyInputs,
)


def illustrative_power_architectures(
    inputs: PowerStudyInputs | None = None,
) -> tuple[PowerArchitecture, ...]:
    """Four paths ending at the same low-voltage IT DC input.

    Sidecar and row presets deliberately retain the AC UPS and have identical
    conversion efficiencies. Their cable geometry and fault domains differ in
    real facilities, but are not silently inferred from the architecture name.
    """
    p = inputs or PowerStudyInputs()
    transformer = PowerStage("MV/LV AC transformer", p.transformer_efficiency)
    ups = PowerStage("AC UPS (rectifier + inverter)", p.ups_efficiency)
    dc_dc = PowerStage("800 V to IT DC converter", p.rack_dc_dc_efficiency)
    return (
        PowerArchitecture(
            "conventional_ac",
            (transformer, ups, PowerStage("Rack AC/DC PSU", p.rack_rectifier_efficiency)),
            "AC UPS internally; final AC/DC at rack PSU",
            "AC UPS battery",
        ),
        PowerArchitecture(
            "sidecar_800v",
            (transformer, ups, PowerStage("Sidecar AC/DC", p.sidecar_rectifier_efficiency), dc_dc),
            "AC UPS internally; final AC/DC beside racks",
            "AC UPS battery retained",
        ),
        PowerArchitecture(
            "row_800v",
            (transformer, ups, PowerStage("Row AC/DC", p.sidecar_rectifier_efficiency), dc_dc),
            "AC UPS internally; final AC/DC at row",
            "AC UPS battery retained in this preset",
        ),
        PowerArchitecture(
            "central_sst_800v",
            (PowerStage("MV AC to 800 V DC SST (aggregate)", p.sst_efficiency), dc_dc),
            "Medium-voltage facility boundary",
            "DC bus storage via protected bidirectional DC/DC; backup still required",
        ),
    )
