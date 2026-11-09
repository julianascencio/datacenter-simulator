"""Offline design tutorial inputs and primary-source methodology references."""

from datacenter_simulator.models.design import OperatingBin


def illustrative_operating_bins() -> tuple[OperatingBin, ...]:
    """Synthetic histogram, not measured weather or a production load forecast."""
    return (
        OperatingBin(1500, 0.45, 12),
        OperatingBin(3000, 0.65, 20),
        OperatingBin(3000, 0.8, 28),
        OperatingBin(1260, 1.0, 35),
    )


def design_evidence() -> dict[str, object]:
    """Sources support methods; numerical defaults remain developer assumptions."""
    return {
        "input_status": "Illustrative defaults; replace with measured loads and vendor data.",
        "sources": [
            {
                "id": "doe-femp-2024",
                "title": "Best Practices Guide for Energy-Efficient Data Center Design (2024)",
                "url": "https://www.energy.gov/sites/default/files/2024-07/"
                "best-practice-guide-data-center-design_0.pdf",
                "use": "Sections 4-6: cooling and future/partial-load sizing; "
                "section 8: energy PUE.",
            },
            {
                "id": "vertiv-system-sizing",
                "title": "Liebert Datawave technical data manual: system sizing",
                "url": "https://www.vertiv.com/globalassets/products/critical-power/"
                "uninterruptible-power-supplies-ups/discontinued---liebert-datawave/"
                "liebert-datawave-technical-data-manual.pdf",
                "use": "kVA = kW/PF and balanced three-phase current; no product sizing defaults.",
            },
        ],
        "equations": {
            "it_design_kw": "current IT peak * (1 + growth fraction)",
            "racks": "ceil(design IT kW / rack limit kW)",
            "usable_module_kw": "min(kW rating, kVA rating * power factor) * derating",
            "N": "ceil(duty / usable module capacity)",
            "N+1": "N + one reserve module",
            "2N": "two independent trains of N modules, each able to carry full duty",
            "battery_kwh_per_bank": "UPS output kW * minutes / 60 / inverter / usable / EOL",
            "current_a": "facility kW * 1000 / (sqrt(3) * line-line V * facility PF)",
            "energy_pue": "sum(facility kW * bin hours) / sum(IT kW * bin hours)",
            "liquid_flow_kg_s": "liquid heat kW / (coolant cp kJ/kg/K * delta T K)",
            "air_flow_m3_s": "air heat kW / (1.2 kg/m3 * 1.006 kJ/kg/K * delta T K)",
        },
        "boundaries": [
            "Cooling and site auxiliaries are outside the UPS branch.",
            "UPS and main losses dissipate outside the hall; downstream losses heat the hall.",
            "Spare equipment and the second cooling train have zero standby demand in this model.",
            "N+1 UPS shares one battery bank; 2N allocates one full-duty bank per train.",
            "Demand bins describe a synthetic 8760-hour year unless replaced by user inputs.",
            "Grid exceedance is a capacity gap, not a dispatch or outage-energy prediction.",
            "No battery discharge curve, generator starting, fault/protection, CFD, structural,"
            " egress, availability or Tier certification is calculated.",
            "Floor area is a rack geometry plus support allowance, not a complete building design.",
        ],
    }
