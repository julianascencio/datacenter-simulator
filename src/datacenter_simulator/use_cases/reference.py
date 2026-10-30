"""An eight-rack 400 V / 48 V facility, with deterministic synthetic generation."""

import numpy as np
import pandas as pd

from datacenter_simulator.methods.communications import CommunicationNetwork, Link
from datacenter_simulator.methods.cooling import cooling_alternatives
from datacenter_simulator.methods.electrical import DCBranch, DCBus, DCNetwork
from datacenter_simulator.models import Communications, Device, Electrical, Placement
from datacenter_simulator.simulation import DataCenter


def reference_center(cooling: str = "direct_to_chip", bus_voltage_v: float = 400) -> DataCenter:
    """Eight 40 kW rack aggregates, each with two network ports and a 48 V converter.

    bus_voltage_v is configurable for a 380/400/800 V comparison; bipolar conductors,
    grounding and neutral imbalance are not represented. Device rack aggregates are
    useful for a quick study; replace them with individual servers for detailed models.
    """
    buses = [DCBus("dc-source", bus_voltage_v), DCBus("dc-bus", bus_voltage_v)]
    edges = [DCBranch.copper_cable("main-feeder", "dc-source", "dc-bus", 12, 630, 1600)]
    devices, links = [], []
    for i in range(8):
        rack = f"rack-{i + 1:02d}"
        feed, shelf, terminal = f"{rack}-feed", f"{rack}-48V", f"{rack}-load"
        buses.extend([DCBus(feed, bus_voltage_v), DCBus(shelf, 48), DCBus(terminal, 48)])
        edges.extend(
            [
                DCBranch.copper_cable(f"{rack}-cable", "dc-bus", feed, 10 + 2 * i, 70, 160),
                DCBranch(
                    f"{rack}-converter",
                    feed,
                    shelf,
                    efficiency=0.97,
                    kind="converter",
                    rated_current_a=1000,
                    rated_power_kw=48,
                ),
                DCBranch.copper_cable(f"{rack}-busbar", shelf, terminal, 0.5, 600, 1000),
            ]
        )
        devices.append(
            Device(
                rack,
                "compute rack",
                terminal,
                Electrical(48, 12, 40),
                placement=Placement(2 + (i % 4) * 1.5, 2 + (i // 4) * 4),
                description="Illustrative aggregate of servers and in-rack fans",
            )
        )
        links.extend(
            [
                Link(f"{rack}-a", rack, "spine-a", 100),
                Link(f"{rack}-b", rack, "spine-b", 100, latency_ms=0.012),
            ]
        )
    for j, name in enumerate(("spine-a", "spine-b")):
        buses.append(DCBus(name, 48))
        edges.append(
            DCBranch(
                f"{name}-converter",
                "dc-bus",
                name,
                efficiency=0.95,
                kind="converter",
                rated_current_a=100,
            )
        )
        devices.append(
            Device(
                name,
                "network switch",
                name,
                Electrical(48, 0.8, 1.6),
                Communications(32, 400, ("Ethernet", "SNMP", "gNMI")),
                Placement(0.5, 2 + 4 * j, height_m=1.5),
            )
        )
    links.append(Link("spine-interconnect", "spine-a", "spine-b", 400, 0.005))
    return DataCenter(
        "ASVA • Reference DC lab",
        devices,
        DCNetwork(buses, edges, "dc-source"),
        CommunicationNetwork([device.id for device in devices], links),
        cooling_alternatives(400)[cooling],
    )


def reference_profiles(hours: int = 48) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Synthetic reproducible hourly profiles; no claim of measured data."""
    if not isinstance(hours, int) or hours < 1:
        raise ValueError("hours must be a positive integer")
    timeline = pd.date_range("2026-01-01", periods=hours, freq="h", tz="UTC")
    hour = np.arange(hours) % 24
    profiles = pd.DataFrame(
        {
            "utilization": 0.55 + 0.25 * np.sin((hour - 6) * np.pi / 12),
            "ambient_c": 23 + 8 * np.sin((hour - 8) * np.pi / 12),
        },
        index=timeline,
    )
    generation = {
        "PV": pd.Series(400 * np.maximum(0, np.sin((hour - 6) * np.pi / 12)), index=timeline),
        "Wind": pd.Series(25 + 10 * np.cos(hour * np.pi / 9), index=timeline),
        "Biogas": pd.Series(35.0, index=timeline),
    }
    return profiles, generation
