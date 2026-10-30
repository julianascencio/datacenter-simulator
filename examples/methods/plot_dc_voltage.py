"""
03. Compare 380, 400 and 800 V distribution
=================================================

**Level:** Intermediate | **Subject:** DC electrical design

Prerequisite: understand voltage, current and power at a DC terminal.

Keep cable geometry, IT demand and 48 V rack terminals fixed. Changing distribution
voltage changes feeder current and resistive losses. The orange converters in the
interactive single-line regulate the racks; this is not a bipolar pole model.
"""

import matplotlib.pyplot as plt

from datacenter_simulator.use_cases import reference_center
from datacenter_simulator.utilities.single_line import dc_single_line

# %%
# Step 1: change distribution voltage while preserving rack equipment
# ---------------------------------------------------------------------------
# Regulated converters keep the rack terminals near 48 V. All IT load, cable
# geometry and converter efficiencies remain fixed across the three cases.
voltages = [380, 400, 800]
losses, currents = [], []
for voltage in voltages:
    center = reference_center(bus_voltage_v=voltage)
    result = center.electrical.solve(center.bus_loads(0.8))
    losses.append(result.loss_kw)
    currents.append(result.branches.loc["main-feeder", "current_a"])
    print(f"{voltage} V: load={result.load_kw:.2f} kW, losses={result.loss_kw:.2f} kW")

# %%
# Step 2: compare current and losses at identical utilization
# -------------------------------------------------------------------
# Higher distribution voltage reduces feeder current and cable loss in this
# fixed-resistance study. Converter losses remain part of the total.
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

# %%
# Step 3: inspect receiving-bus voltage in the 400 V case
# ---------------------------------------------------------------
# Per-unit values use each bus's own nominal voltage, so 400 V and 48 V nodes
# can be compared. A regulated converter resets voltage; it does not remove
# downstream busbar drop.
center = reference_center(bus_voltage_v=400)
result = center.electrical.solve(center.bus_loads(0.8))
rack_buses = [bus for bus in center.electrical.order if bus.startswith("rack-01")]
fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
ax.plot(rack_buses, result.buses.loc[rack_buses, "voltage_pu"], marker="o", color="#2f6fdb")
ax.axhline(1, linestyle="--", color="#555555", label="Nominal voltage")
ax.set(ylabel="Voltage [pu]", xlabel="First rack power path")
ax.legend()
print("Power balance residual [kW]:", result.source_kw - result.load_kw - result.loss_kw)

# %%
# Step 4: inspect the DC design single-line
# -------------------------------------------------
# Generate the schematic from this exact 400 V, 80% utilization solution.
# Each blue cable carries a loop-resistance label; amber blocks are regulated
# DC/DC converters. Busbars connect outgoing circuits, and load boxes show
# local terminal demand. Both current and power ratings are checked for colour.
diagram = dc_single_line(center.electrical, result)
print("Diagram branches:", len(diagram.layout.meta["branch_ids"]))
print("Overloaded branches:", diagram.layout.meta["overloaded_branches"])

# %%
# Export this solution as an interactive HTML file or a standalone vector:
#
# .. code-block:: python
#
#    from datacenter_simulator.utilities.single_line import write_single_line_svg
#    diagram.write_html("dc-design.html")
#    write_single_line_svg(center.electrical, result, "dc-design.svg")
#
# The published preview below is the lab's separate **70% utilization** snapshot
# of the same 400 V topology. Open its SVG for readable zoom at any scale.
#
# .. image:: /_static/lab/reference-lab-single-line.svg
#    :alt: DC single-line showing the source, common bus, eight rack circuits and two switches
#    :target: ../../_static/lab/reference-lab-single-line.svg
#
# :doc:`../../user_guide/dc_single_line` explains the symbols, units and scope.
# Protection coordination, earthing and multi-source DC connections are not
# inferred by this schematic; those models are not implemented.
