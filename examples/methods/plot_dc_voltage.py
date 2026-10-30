"""
Compare 380, 400 and 800 V distribution
===============================================

Keep cable geometry, IT demand and 48 V rack terminals fixed. Changing distribution
voltage changes feeder current and resistive losses. The orange converters in the
interactive single-line regulate the racks; this is not a bipolar pole model.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.use_cases import reference_center

voltages = [380, 400, 800]
losses, currents = [], []
for voltage in voltages:
    center = reference_center(bus_voltage_v=voltage)
    result = center.electrical.solve(center.bus_loads(0.8))
    losses.append(result.loss_kw)
    currents.append(result.branches.loc["main-feeder", "current_a"])
    print(f"{voltage} V: load={result.load_kw:.2f} kW, losses={result.loss_kw:.2f} kW")

fig, axes = plt.subplots(1, 2, figsize=(9, 3.5), layout="constrained")
axes[0].bar([str(v) for v in voltages], losses, color="#148d83")
axes[0].set(xlabel="Distribution voltage [V]", ylabel="Total DC losses [kW]")
axes[1].bar([str(v) for v in voltages], currents, color="#376b9c")
axes[1].set(xlabel="Distribution voltage [V]", ylabel="Main feeder current [A]")

# %%
# Reuse the same topology for an interactive single-line or equipment view:
#
# .. code-block:: python
#
#    from datacenter_simulator.utilities.plotting import electrical_diagram, equipment_3d
#    electrical_diagram(center, result).write_html("single-line.html")
#    equipment_3d(center).write_html("equipment-3d.html")
