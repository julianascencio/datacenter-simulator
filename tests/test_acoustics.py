"""Independent limiting cases and reference coefficients for acoustic energy."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from datacenter_simulator.analysis.acoustics import export_noise_study, load_noise_case
from datacenter_simulator.methods.acoustics import (
    atmospheric_attenuation,
    levels_from_energy,
    room_acoustics,
    simulate_noise,
    source_energy,
    sum_decibels,
    validate_noise_receivers,
)
from datacenter_simulator.models.acoustics import (
    AcousticCase,
    AcousticReceiver,
    AcousticSettings,
    AcousticSource,
)
from datacenter_simulator.models.cfd import CFDGrid


def case():
    return AcousticCase(
        CFDGrid(12, 8, 4, 12, 8, 4),
        AcousticSettings(
            mode="free_field", atmospheric_absorption=False, propagation_standard_uncertainty_db=0
        ),
        (AcousticSource("machine", 1, 4, 2, (80,) * 8, standard_uncertainty_db=0),),
        (AcousticReceiver("near", 3, 4, 2), AcousticReceiver("far", 5, 4, 2)),
    )


def test_iso_atmosphere_against_published_spm9613_reference_table():
    # Power Acoustics SPM9613 manual section 3.9, 20 C, 70% RH, 101.325 kPa.
    # Exact base-10 octave centres explain the nominal 4/8 kHz rounding.
    expected = np.array([0.1, 0.3, 1.1, 2.8, 5, 9, 22.9, 76.6])
    actual = atmospheric_attenuation(AcousticSettings(relative_humidity_percent=70)) * 1000
    np.testing.assert_allclose(actual, expected, atol=0.06, rtol=0)
    with pytest.raises(ValueError):
        AcousticSettings(relative_humidity_percent=0.7)  # percent/fraction ambiguity rejected


def test_log_addition_and_exact_silence():
    assert sum_decibels(np.array([60.0, 60.0])) == pytest.approx(63.0102999566)
    assert sum_decibels(np.array([-np.inf, -np.inf])) == -np.inf
    assert sum_decibels(np.array([3000.0, 3000.0])) == pytest.approx(3003.0102999566)


def test_inverse_square_doubling_and_source_superposition():
    c = case()
    points = np.array([[3.0, 4, 2], [5, 4, 2]])
    energy, _ = source_energy(c, points)
    level = levels_from_energy(energy[:, 0])
    np.testing.assert_allclose(level[0] - level[1], 20 * np.log10(2))
    doubled = replace(c, sources=(*c.sources, replace(c.sources[0], name="second")))
    energy2, _ = source_energy(doubled, points)
    np.testing.assert_allclose(levels_from_energy(energy2.sum(axis=1)) - level, 10 * np.log10(2))


def test_directivity_duty_and_declared_insertion_loss():
    c = case()
    point = np.array([[3.0, 4, 2]])
    original, _ = source_energy(c, point)
    for field, value, delta in (
        ("directivity_q", 2, 3.0102999566),
        ("duty_fraction", 0.5, -3.0102999566),
        ("insertion_loss_db", (10,) * 8, -10),
    ):
        changed = replace(c, sources=(replace(c.sources[0], **{field: value}),))
        energy, _ = source_energy(changed, point)
        np.testing.assert_allclose(levels_from_energy(energy) - levels_from_energy(original), delta)


def test_room_constant_and_absorption_physics():
    c = replace(
        case(),
        grid=CFDGrid(12, 8, 4, 12, 8, 4),
        settings=AcousticSettings(
            atmospheric_absorption=False, surface_absorption=((0.2,) * 8,) * 6
        ),
    )
    area = 2 * (12 * 8 + 12 * 4 + 8 * 4)
    room = room_acoustics(c)
    np.testing.assert_allclose(room.room_constant_m2, area * 0.2 / 0.8)
    np.testing.assert_allclose(room.sabine_rt60_s, 0.161 * 12 * 8 * 4 / (area * 0.2), rtol=0.002)
    more = replace(c, settings=replace(c.settings, surface_absorption=((0.5,) * 8,) * 6))
    a, _ = source_energy(c, np.array([[5.0, 4, 2]]))
    b, _ = source_energy(more, np.array([[5.0, 4, 2]]))
    assert np.all(b < a)
    assert (room.eyring_rt60_s < room.sabine_rt60_s).all()


def test_uncertainty_repeatability_and_independent_measurement_metrics():
    c = case()
    result = simulate_noise(c, samples=500)
    np.testing.assert_allclose(result.receivers.input_p025_dba, result.receivers.laeq_dba)
    np.testing.assert_allclose(result.receivers.input_p975_dba, result.receivers.laeq_dba)
    varied = replace(c, sources=(replace(c.sources[0], standard_uncertainty_db=2),))
    a = simulate_noise(varied, samples=4000)
    b = simulate_noise(varied, samples=4000)
    pd.testing.assert_frame_equal(a.receivers, b.receivers)
    assert a.receivers.input_p975_dba.iloc[0] - a.receivers.input_p025_dba.iloc[0] == pytest.approx(
        7.84, abs=0.3
    )
    observations = pd.DataFrame(
        {"receiver": result.receivers.receiver, "observed_dba": result.receivers.laeq_dba - 1}
    )
    _, metrics = validate_noise_receivers(result, observations)
    assert metrics["bias"] == pytest.approx(1)
    assert metrics["rmse"] == pytest.approx(1)


def test_near_fields_are_masked_and_receiver_inside_rejected():
    c = case()
    _, valid = source_energy(c, np.array([[1.0, 4, 2], [3, 4, 2]]))
    assert valid.tolist() == [False, True]
    with pytest.raises(ValueError, match="near field"):
        replace(c, receivers=(AcousticReceiver("invalid", 1, 4, 2),))
    with pytest.raises(ValueError):
        replace(c.sources[0], sound_power_db=(80,))
    with pytest.raises(ValueError):
        replace(c.settings, surface_absorption=((1.0,) * 8,) * 6)


def test_noise_exports_are_reproducible_and_preserve_fields(tmp_path):
    c = case()
    results = export_noise_study(tmp_path, c, compare=False, samples=100)
    assert load_noise_case(tmp_path / "noise-0-inputs.json") == c
    with np.load(tmp_path / "noise-0-fields.npz") as data:
        np.testing.assert_allclose(data["laeq_dba"], results["Baseline"].laeq_dba, equal_nan=True)
        assert data["band_spl_db"].shape == (*c.grid.shape, 8)
    assert "__DATA__" not in (tmp_path / "noise-3d.html").read_text()
