"""
Cooling failure and a lumped thermal zone
=================================================

A 200 kW heat load loses active cooling after five minutes. This standalone
thermal-mass example predicts mean zone temperature, not individual rack inlets.
Use site-calibrated heat capacity and envelope conductance for a real scenario.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.methods.cooling import ThermalZone

zone = ThermalZone(capacitance_kj_k=100_000, conductance_kw_k=0.5)
temperature = 24.0
temperatures = [temperature]
for minute in range(30):
    removed = 200 if minute < 5 else 0
    temperature = zone.advance(temperature, 24, 200, removed, 1 / 60)
    temperatures.append(temperature)

fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.plot(range(31), temperatures, color="#b2414e", linewidth=2)
ax.axvline(5, color="#555555", linestyle="--", label="Cooling failure")
ax.set(xlabel="Elapsed time [min]", ylabel="Mean zone temperature [°C]")
ax.legend()
