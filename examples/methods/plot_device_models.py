"""
01. Device models and spatial layouts
=============================================

**Level:** Beginner | **Subject:** Equipment and visualization

Define electrical and communication metadata, evaluate utilization-dependent
power, then inspect a reference hall in 2D and 3D. Familiarity with Python
objects is sufficient; no network solver knowledge is required.

All ratings and geometry below are illustrative. The three device curves are
individual-device examples; the hall is a separate eight-rack reference layout.
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from datacenter_simulator.models import Communications, Device, Electrical
from datacenter_simulator.use_cases import reference_center

# %%
# Step 1: describe individual equipment
# ---------------------------------------------
# Power is measured at the DC input, including internal PSU/fan demand. Port
# metadata describe the equipment; they do not create live network connections.
devices = [
    Device("cpu-server", "server", "rack-48V", Electrical(48, 0.08, 0.60), Communications(2, 25)),
    Device(
        "gpu-server",
        "GPU server",
        "rack-48V",
        Electrical(48, 0.50, 2.50, 1.2),
        Communications(4, 100),
    ),
    Device(
        "top-of-rack",
        "switch",
        "rack-48V",
        Electrical(48, 0.04, 0.10),
        Communications(32, 100, ("Ethernet", "SNMP", "gNMI")),
    ),
]
for device in devices:
    print(
        f"{device.id}: {device.electrical.nominal_voltage_v:g} V DC; "
        f"{device.communications.ports} ports × {device.communications.port_speed_gbps:g} Gbps"
    )

# %%
# Step 2: compare power curves
# ------------------------------------
# Utilization zero still consumes idle power. The GPU example uses an exponent
# of 1.2; it is an assumed curve shape, not a calibrated GPU performance model.
utilization = np.linspace(0, 1, 101)
fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
for device in devices:
    ax.plot(utilization * 100, [device.power_kw(float(u)) for u in utilization], label=device.id)
ax.set(xlabel="Utilization [%]", ylabel="DC terminal power [kW]")
ax.legend()
ax.grid(alpha=0.2)

# %%
# Step 3: plot the same physical geometry in 2D and 3D
# ------------------------------------------------------------
# The reference system's rack and switch positions/dimensions drive both views.
# These are geometry views, not airflow or electromagnetic simulations.
center = reference_center()
fig = plt.figure(figsize=(11, 4.5), layout="constrained")
floor = fig.add_subplot(121)
scene = fig.add_subplot(122, projection="3d")
for device in center.devices:
    p = device.placement
    color = "#2f6fdb" if "rack" in device.kind else "#d99241"
    floor.add_patch(Rectangle((p.x_m, p.y_m), p.width_m, p.depth_m, color=color, alpha=0.8))
    floor.text(p.x_m + p.width_m / 2, p.y_m + p.depth_m + 0.15, device.id, ha="center", fontsize=7)
    scene.bar3d(
        p.x_m, p.y_m, p.z_m, p.width_m, p.depth_m, p.height_m, color=color, alpha=0.85, shade=True
    )
floor.set(xlim=(0, 8), ylim=(1, 8), xlabel="X [m]", ylabel="Y [m]", title="Equipment footprint")
floor.set_aspect("equal")
scene.set(xlabel="X [m]", ylabel="Y [m]", zlabel="Z [m]", title="Dimensioned equipment")
scene.set_box_aspect((8, 7, 3))

# %%
# Continue with :doc:`plot_dc_voltage` to connect these devices to DC buses.
# The interactive hall uses the same placement model:
#
# .. code-block:: python
#
#    from datacenter_simulator.utilities.plotting import equipment_3d
#    equipment_3d(center).write_html("equipment-3d.html")
