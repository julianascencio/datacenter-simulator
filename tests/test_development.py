"""Independent branch arithmetic and input-boundary checks."""

import json
from dataclasses import replace

import pytest

from datacenter_simulator.analysis.development import run_study
from datacenter_simulator.methods.development import evaluate_development
from datacenter_simulator.models.development import DevelopmentScenario
from datacenter_simulator.use_cases.development import development_scenarios


def test_zero_discount_cash_accounting():
    s = replace(development_scenarios()[0], annual_discount_rate=0)
    r = evaluate_development(s)
    assert r.approved_npv_usd == -500e6 - 24 * 250_000 + 15 * 85e6
    assert r.canceled_npv_usd == -20e6 - 24 * 250_000 + 5e6 - 3e6
    assert r.expected_npv_usd == pytest.approx(0.7 * r.approved_npv_usd + 0.3 * r.canceled_npv_usd)


@pytest.mark.parametrize("probability", [0, 1])
def test_branch_endpoints(probability):
    r = evaluate_development(
        replace(development_scenarios()[0], cancellation_probability=probability)
    )
    assert r.expected_npv_usd == (r.canceled_npv_usd if probability else r.approved_npv_usd)


def test_one_year_discount_and_no_double_count():
    s = replace(
        development_scenarios()[0],
        permit_months=0,
        delay_months=0,
        operating_years=1,
        annual_discount_rate=0.1,
        cancellation_probability=0,
    )
    assert evaluate_development(s).expected_npv_usd == pytest.approx(-500e6 + 85e6 / 1.1)


def test_no_assumed_mitigation_effect():
    base, _, _, no_benefit = development_scenarios()
    assert evaluate_development(no_benefit).expected_npv_usd == pytest.approx(
        evaluate_development(base).expected_npv_usd - 8e6
    )


@pytest.mark.parametrize(
    "change",
    [
        {"delay_months": -1},
        {"delay_months": 1.5},
        {"operating_years": 0},
        {"cancellation_probability": 1.1},
        {"cancellation_probability": float("nan")},
        {"annual_discount_rate": float("inf")},
        {"predevelopment_usd": 501e6},
        {"recovery_usd": 21e6},
        {"assumption_basis": ""},
    ],
)
def test_invalid_inputs(change):
    with pytest.raises(ValueError):
        replace(development_scenarios()[0], **change)


def test_replay(tmp_path):
    run_study(tmp_path, development_scenarios())
    replay = [
        DevelopmentScenario(**row) for row in json.loads((tmp_path / "inputs.json").read_text())
    ]
    run_study(tmp_path / "replay", replay)
    assert (tmp_path / "results.csv").read_bytes() == (tmp_path / "replay/results.csv").read_bytes()
    assert (tmp_path / "development-risk.html").exists()
