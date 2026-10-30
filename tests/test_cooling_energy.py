import numpy as np
import pytest

from datacenter_simulator.methods.cooling import CoolingPlant, ThermalZone, cooling_alternatives
from datacenter_simulator.methods.energy import Battery, dispatch


@pytest.mark.parametrize("kind", list(cooling_alternatives()))
def test_cooling_energy_and_fluid_balances(kind: str) -> None:
    plant = cooling_alternatives(400)[kind]
    r = plant.evaluate(200, 35)
    assert r.heat_removed_kw == 200
    assert r.rejected_heat_kw == pytest.approx(200 + r.electric_kw)
    assert r.liquid_heat_kw + r.air_heat_kw == pytest.approx(200)
    assert r.liquid_flow_kg_s * plant.coolant_cp_kj_kgk * plant.liquid_delta_k == pytest.approx(
        r.liquid_heat_kw
    )
    assert r.air_flow_m3_s * 1.2 * 1.006 * plant.air_delta_k == pytest.approx(r.air_heat_kw)


def test_economizer_keeps_residual_air_cooling_and_pump_power() -> None:
    plant = cooling_alternatives()["direct_to_chip"]
    cold = plant.evaluate(200, 15)
    hot = plant.evaluate(200, 40)
    assert cold.economizer_active and not hot.economizer_active
    assert 0 < cold.compressor_kw < hot.compressor_kw
    assert cold.auxiliaries_kw > 0
    assert cold.electric_kw < hot.electric_kw


def test_capacity_shortfall_and_off_state() -> None:
    plant = CoolingPlant("small", 100, 4)
    assert plant.evaluate(160, 30).unmet_heat_kw == 60
    assert plant.evaluate(0, 30).electric_kw == 0


def test_adiabatic_thermal_mass() -> None:
    zone = ThermalZone(3600, 0)
    assert zone.advance(20, 10, 15, 10, 1) == pytest.approx(25)


def test_thermal_equilibrium() -> None:
    zone = ThermalZone(10000, 2)
    assert zone.advance(30, 20, 50, 30, 1) == pytest.approx(30)


def test_exact_battery_boundary_and_bus_balance() -> None:
    battery = Battery(100, 100, 100, 0.9, 0.8, 0.1, 0.9, 0.5)
    r = dispatch(100, 0, 1, battery=battery, energy_kwh=50, grid_import_limit_kw=0)
    assert r.discharge_kw == pytest.approx(32)
    assert r.unserved_kw == pytest.approx(68)
    assert r.battery_energy_kwh == pytest.approx(10)
    r = dispatch(0, 100, 1, battery=battery, energy_kwh=50)
    assert r.charge_kw == pytest.approx(40 / 0.9)
    assert r.battery_energy_kwh == pytest.approx(90)
    assert r.balance_error_kw == pytest.approx(0)


def test_random_dispatch_conserves_energy_across_timesteps() -> None:
    rng = np.random.default_rng(71)
    battery = Battery(300, 80, 90)
    energy = 150.0
    for _ in range(200):
        demand, generated = rng.uniform(0, 300, 2)
        dt = float(rng.uniform(0.05, 2))
        r = dispatch(
            demand,
            generated,
            dt,
            battery=battery,
            energy_kwh=energy,
            grid_import_limit_kw=80,
            grid_export_limit_kw=30,
            backup_capacity_kw=40,
        )
        assert abs(r.balance_error_kw) < 1e-10
        stored_change = (r.charge_kw - r.discharge_kw - r.battery_loss_kw) * dt
        assert r.battery_energy_kwh - energy == pytest.approx(stored_change, abs=1e-10)
        assert 30 - 1e-8 <= r.battery_energy_kwh <= 285 + 1e-8
        assert r.charge_kw * r.discharge_kw == 0
        assert r.grid_import_kw * r.grid_export_kw == 0
        energy = r.battery_energy_kwh


def test_grid_backup_and_unserved() -> None:
    r = dispatch(100, 10, 1, grid_import_limit_kw=30, backup_capacity_kw=40)
    assert r.grid_import_kw == 30
    assert r.backup_kw == 40
    assert r.unserved_kw == 20


@pytest.mark.parametrize("capacity", [-1, 0, float("nan"), float("inf")])
def test_invalid_battery(capacity: float) -> None:
    with pytest.raises(ValueError):
        Battery(capacity, 10, 10)
