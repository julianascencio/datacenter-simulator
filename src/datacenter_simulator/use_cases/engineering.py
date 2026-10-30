"""Shared, deliberately illustrative equipment for the engineering gallery."""

from typing import Literal, cast

from datacenter_simulator.methods.dc_grid import DCGrid, DCLine, DCPort
from datacenter_simulator.methods.design import Route
from datacenter_simulator.methods.hydraulics import CoolingBranch, Pipe
from datacenter_simulator.models.devices import Placement
from datacenter_simulator.models.facility import Asset, Connection, FacilityLayout
from datacenter_simulator.models.performance import ConverterMap, Provenance


def engineering_layout() -> FacilityLayout:
    assets = [
        Asset("feed-A", "power", Placement(0, 0)),
        Asset("feed-B", "power", Placement(0, 5)),
        Asset("cdu", "cooling", Placement(8, 0, width_m=1.2)),
        Asset("switch", "communications", Placement(8, 5)),
    ]
    for i in range(4):
        assets.append(Asset(f"rack-{i + 1:02d}", "rack", Placement(2 + 1.4 * i, 2.5)))
    by_id = {a.id: a for a in assets}
    connections = []
    for asset in assets:
        if asset.kind != "rack":
            continue
        p = asset.placement
        target = (p.x_m + p.width_m / 2, p.y_m + p.depth_m / 2, p.height_m)
        for source, domain in (
            ("feed-A", "electrical"),
            ("feed-B", "electrical"),
            ("cdu", "cooling"),
            ("switch", "communications"),
        ):
            q = by_id[source].placement
            origin = (q.x_m + q.width_m / 2, q.y_m + q.depth_m / 2, q.height_m)
            height = 3 if domain != "cooling" else 0.2
            route = Route(
                f"{source}:{asset.id}",
                (
                    origin,
                    (origin[0], origin[1], height),
                    (target[0], origin[1], height),
                    (target[0], target[1], height),
                    target,
                ),
            )
            connections.append(
                Connection(
                    route.id,
                    source,
                    asset.id,
                    cast(Literal["electrical", "cooling", "communications"], domain),
                    route,
                )
            )
    return FacilityLayout(tuple(assets), tuple(connections))


def engineering_converter() -> ConverterMap:
    return ConverterMap(
        250,
        (0, 0.1, 0.25, 0.5, 1),
        (15, 35, 55),
        (
            (0.85, 0.93, 0.96, 0.975, 0.97),
            (0.83, 0.92, 0.955, 0.97, 0.965),
            (0.8, 0.90, 0.94, 0.96, 0.95),
        ),
        Provenance("Developer-selected sensitivity map", "250 kW converter; illustrative"),
        standby_kw=0.05,
        derating=(1, 1, 0.8),
    )


def engineering_grid(voltage_v: float = 400) -> DCGrid:
    layout = engineering_layout()
    lines = [
        DCLine(c.id, c.source, c.target, 2 * 0.01724 * c.route.length_m / 120, 300)
        for c in layout.connections
        if c.domain == "electrical" and c.source == "feed-A"
    ]
    buses = {"feed-A": voltage_v, **{a.id: voltage_v for a in layout.assets if a.kind == "rack"}}
    return DCGrid(buses, lines, [DCPort("grid", "feed-A", voltage_v=voltage_v, max_source_kw=500)])


def engineering_cooling() -> list[CoolingBranch]:
    layout = engineering_layout()
    return [
        CoolingBranch(c.target, Pipe(2 * c.route.length_m, 0.04, minor_loss_k=8), 10000, 50)
        for c in layout.connections
        if c.domain == "cooling"
    ]
