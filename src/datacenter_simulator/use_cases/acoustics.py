"""Illustrative data-center noise scenarios and explicit geometry integration."""

from dataclasses import replace

from datacenter_simulator.models.acoustics import (
    AcousticCase,
    AcousticReceiver,
    AcousticSettings,
    AcousticSource,
)
from datacenter_simulator.models.cfd import CFDCase, CFDGrid


def noise_from_cfd(
    case: CFDCase,
    sound_power_by_rack: dict[str, tuple[float, ...]],
    receivers: tuple[AcousticReceiver, ...],
    *,
    settings: AcousticSettings | None = None,
    provenance: str,
) -> AcousticCase:
    """Reuse rack centres, requiring measured/declarative acoustic inputs.

    Steady CFD pressure and rack thermal watts are not acoustic sound power.
    A separate spectrum is mandatory for each rack; no acoustic analogy is claimed.
    """
    if set(sound_power_by_rack) != {s.name for s in case.sources}:
        raise ValueError(
            "provide an octave-band Lw spectrum for every CFD rack, with matching names"
        )
    sources = tuple(
        AcousticSource(
            s.name,
            s.x_m + s.width_m / 2,
            s.y_m + s.depth_m / 2,
            s.z_m + s.height_m / 2,
            sound_power_by_rack[s.name],
            radius_m=max(s.width_m, s.depth_m) / 2,
            provenance=provenance,
        )
        for s in case.sources
    )
    return AcousticCase(
        case.grid, AcousticSettings() if settings is None else settings, sources, receivers
    )


def reference_noise_case() -> AcousticCase:
    """Four rack sources plus an air-handler; all acoustic spectra are illustrative."""
    sources = tuple(
        AcousticSource(f"Rack {i + 1}", x, y, 1.1, (65, 70, 75, 79, 81, 79, 75, 70))
        for i, (x, y) in enumerate(((3, 2), (3, 6), (7, 2), (7, 6)))
    )
    sources += (
        AcousticSource("Air handler", 10, 4, 1.5, (80, 84, 86, 84, 81, 78, 74, 68), radius_m=0.8),
    )
    settings = AcousticSettings(
        surface_absorption=((0.08, 0.10, 0.12, 0.15, 0.2, 0.25, 0.3, 0.3),) * 4
        + (
            (0.04, 0.05, 0.05, 0.06, 0.07, 0.08, 0.1, 0.1),
            (0.15, 0.25, 0.4, 0.55, 0.65, 0.7, 0.7, 0.65),
        ),
        background_db=(40, 38, 36, 34, 32, 30, 28, 26),
        criterion_dba=75,
    )
    return AcousticCase(
        CFDGrid(12, 8, 3.5, 30, 20, 10),
        settings,
        sources,
        (
            AcousticReceiver("Operator aisle", 5, 4, 1.5),
            AcousticReceiver("Room entrance", 0.8, 4, 1.5),
            AcousticReceiver("Cooling service", 9, 6, 1.5),
        ),
    )


def noise_scenarios(case: AcousticCase | None = None) -> dict[str, AcousticCase]:
    """Baseline, source treatment and surface treatment; no implied product rating."""
    case = reference_noise_case() if case is None else case
    treated = replace(
        case,
        sources=tuple(
            replace(
                s,
                insertion_loss_db=tuple(
                    min(100, a + b)
                    for a, b in zip(s.insertion_loss_db, (3, 4, 5, 7, 8, 8, 7, 5), strict=True)
                ),
            )
            for s in case.sources
        ),
    )
    absorption = tuple(
        tuple(min(0.9, a + 0.25) for a in row) for row in case.settings.surface_absorption
    )
    return {
        "Baseline": case,
        "Source treatment": treated,
        "Room absorption": replace(
            case, settings=replace(case.settings, surface_absorption=absorption)
        ),
    }


def acoustic_evidence() -> dict[str, object]:
    return {
        "sources": [
            {
                "title": "ASHRAE Handbook: Sound and Vibration",
                "url": "https://handbook.ashrae.org/Handbooks/F17/IP/f17_ch08/f17_ch08_ip.aspx",
            },
            {
                "title": "ISO 9613-1: atmospheric absorption",
                "url": "https://www.iso.org/standard/17426.html",
            },
            {
                "title": "SPM9613 manual: independent atmospheric coefficient reference",
                "url": "https://www.poweracoustics.com/UsersMan.pdf",
            },
        ],
        "equations": {
            "direct_gain_per_m2": "Q/(4*pi*r^2) * 10^(-alpha_db_per_m*r/10)",
            "room_gain_per_m2": "4 / (S*mean_absorption/(1-mean_absorption) + 4*m*V)",
            "air_energy_absorption_per_m": "m = alpha_db_per_m * ln(10)/10",
            "sound_pressure": "p_squared = rho*c*sum(W_source*(direct_gain+room_gain))",
            "octave_sum": "LAeq = 10*log10(sum(10^((Lp_band+A_band)/10)))",
        },
        "scope": "Incoherent band-energy model. No wave phase, diffraction, ground interference, "
        "obstacle shielding, room modes, duct transmission or structureborne vibration. "
        "ISO 9613-1 band-centre absorption only; not an ISO 9613-2 compliance implementation.",
        "uncertainty": "Independent Gaussian source offsets, correlated across bands; common "
        "propagation offset. Fixed background. Conditional 2.5-97.5 percentiles, "
        "not a validated total prediction-accuracy interval.",
    }
