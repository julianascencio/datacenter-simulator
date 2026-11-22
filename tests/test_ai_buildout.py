from dataclasses import replace

import pandas as pd
import pytest

from datacenter_simulator.methods.ai_buildout import ComputePhase, simulate_buildout

PHASE = ComputePhase(2025, 1000, 3, 1, 100, 2, 0.25)


def build(*phases: ComputePhase, ready: int = 2025) -> pd.DataFrame:
    return simulate_buildout(
        phases,
        start_year=2026,
        end_year=2031,
        power_ready_year=ready,
        pue=1.2,
        it_load_factor=0.5,
        construction_usd_per_it_mw=1e6,
        new_power_fraction=0.5,
        power_usd_per_kw=2000,
    )


def test_power_delay_and_repeated_renewal() -> None:
    rows = build(PHASE, ready=2027)
    assert (rows.loc[2026] == 0).all()
    first = rows.loc[2027]
    assert first.installed_it_mw == 4
    assert first.facility_mwh == pytest.approx(4.8 * 0.5 * 8760)
    assert first.new_power_kw == 2400
    assert first.total_capex_usd == 100_000 + 3e6 + 2400 * 2000
    assert list(rows.replacement_compute_usd) == [0, 0, 0, 100_000, 0, 100_000]
    assert rows.construction_usd.sum() == 3e6
    assert rows.power_usd.sum() == 4.8e6


def test_carry_in_and_brownfield_cohort_are_independent() -> None:
    second = replace(PHASE, ready_year=2027, brownfield_fraction=1, life_years=3)
    rows = build(PHASE, second)
    assert rows.loc[2026, "installed_it_mw"] == 4
    assert rows.loc[2027, "installed_it_mw"] == 8
    assert rows.loc[2027, "initial_compute_usd"] == 100_000
    assert rows.loc[2027, "replacement_compute_usd"] == 100_000
    assert rows.loc[2030, "replacement_compute_usd"] == 100_000
    assert rows.construction_usd.sum() == 0
    assert rows.power_usd.sum() == 4.8e6


@pytest.mark.parametrize("life", [0, -1, True, 2.5])
def test_reject_invalid_renewal_period(life: int) -> None:
    with pytest.raises(ValueError, match="life_years"):
        replace(PHASE, life_years=life)


def test_reject_impossible_power_inputs() -> None:
    with pytest.raises(ValueError, match="package_kw"):
        replace(PHASE, package_kw=float("nan"))
    with pytest.raises(ValueError, match="brownfield_fraction"):
        replace(PHASE, brownfield_fraction=1.1)
