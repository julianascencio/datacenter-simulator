"""A reproducible room CFD case and conversion from the facility design workflow."""

from dataclasses import replace

from datacenter_simulator.methods.facility_design import FacilityDesign
from datacenter_simulator.models.cfd import CFDCase, CFDGrid, CFDSettings, CFDSource
from datacenter_simulator.models.devices import fraction


def reference_cfd_case() -> CFDCase:
    """Four 3 kW air-heat zones, low supply slot and opposite-wall pressure return.

    The 12 kW room-air load could represent part of a larger liquid-cooled IT
    installation. Dimensions, loads, drag and mixing are illustrative assumptions.
    """
    sources = tuple(
        CFDSource(f"Rack {i + 1}", x, y, 0, 0.8, 1.0, 2.1, 3)
        for i, (x, y) in enumerate(((2.4, 1.5), (2.4, 3.5), (4.4, 1.5), (4.4, 3.5)))
    )
    return CFDCase(CFDGrid(), CFDSettings(), sources)


def cfd_from_design(
    design: FacilityDesign,
    *,
    air_heat_fraction: float,
    settings: CFDSettings | None = None,
    cells: tuple[int, int, int] = (24, 24, 12),
    room_height_m: float = 3.5,
) -> CFDCase:
    """Transfer exact rack geometry/IT loads; require the room-air heat fraction.

    Facility cooling's liquid-loop fraction is deliberately not used here: a
    chilled-water CRAH still receives rack heat through room air. The caller must
    specify direct-to-liquid bypass explicitly. Non-rack electrical losses are
    excluded. Airflow is user-specified through settings, not silently optimized.
    """
    fraction("air_heat_fraction", air_heat_fraction)
    grid = CFDGrid(
        design.summary["hall_width_m"], design.summary["hall_depth_m"], room_height_m, *cells
    )
    sources = tuple(
        CFDSource(
            str(r["rack"]),
            float(r["x_m"]),
            float(r["y_m"]),
            0,
            float(r["width_m"]),
            float(r["depth_m"]),
            float(r["height_m"]),
            float(r["it_kw"]) * air_heat_fraction,
        )
        for r in design.racks.to_dict("records")
    )
    return CFDCase(grid, CFDSettings() if settings is None else settings, sources)


def airflow_scenarios(case: CFDCase | None = None) -> dict[str, CFDCase]:
    """Same geometry/heat, normal versus half ventilation volume flow."""
    case = reference_cfd_case() if case is None else case
    return {
        "Normal airflow": case,
        "Half airflow": replace(
            case,
            settings=replace(case.settings, supply_flow_m3_s=case.settings.supply_flow_m3_s / 2),
        ),
    }


def cfd_evidence() -> dict[str, object]:
    return {
        "sources": [
            {
                "title": "Chorin (1968), Numerical solution of the Navier-Stokes equations",
                "url": "https://math.berkeley.edu/~chorin/chorin68.pdf",
                "use": "Projection-method lineage; implementation is original and simplified.",
            },
            {
                "title": "Notus: models and equations",
                "url": "https://doc.notus-cfd.org/d3/d7d/models.html",
                "use": "Incompressible momentum, energy and Boussinesq coupling.",
            },
            {
                "title": "NISTIR 8298 (2020), CFD verification, validation and uncertainty",
                "url": "https://www.nist.gov/publications/summary-industrial-verification-validation-and-uncertainty-quantification-procedures",
                "use": "Numerical verification and mesh sensitivity are distinct "
                "from physical validation.",
            },
        ],
        "equations": {
            "mass": "div(u)=0",
            "momentum": "du/dt + u.grad(u) = -grad(p)/rho + nu_eff*laplacian(u) "
            "+ g*beta*(T-T_supply)*e_z - drag*u",
            "heat": "dT/dt + div(u*T) = alpha_eff*laplacian(T) + q/(rho*cp)",
            "projection": "laplacian(p_kinematic) = div(u_star)/dt; "
            "u = u_star-dt*grad(p_kinematic)",
            "energy_audit": "stored sensible heat + integrated outward heat - input heat*time = 0",
        },
        "boundaries": [
            "Supply: full-width low slot on x=0, prescribed volume flow and temperature.",
            "Return: entire opposite x=L wall, zero gauge pressure, zero diffusive heat flux.",
            "Return backflow uses supply temperature and is reported explicitly.",
            "Other walls: no slip, no penetration and adiabatic; no wall conduction or radiation.",
            "Racks are permeable heat/resistance zones; "
            "no resolved server fans or solid heat capacity.",
            "Constant effective viscosity/diffusivity are assumptions, not a RANS/LES closure.",
            "Fields are finite-time transient results; "
            "numerical verification is not facility validation.",
        ],
    }
