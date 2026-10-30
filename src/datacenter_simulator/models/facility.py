"""Shared equipment identities and routed connections across model/visual layers."""

from dataclasses import dataclass
from typing import Literal

from datacenter_simulator.methods.design import Route
from datacenter_simulator.models.devices import Placement


@dataclass(frozen=True)
class Asset:
    id: str
    kind: str
    placement: Placement


@dataclass(frozen=True)
class Connection:
    id: str
    source: str
    target: str
    domain: Literal["electrical", "cooling", "communications"]
    route: Route


@dataclass(frozen=True)
class FacilityLayout:
    assets: tuple[Asset, ...]
    connections: tuple[Connection, ...]

    def __post_init__(self) -> None:
        ids = {a.id for a in self.assets}
        if (
            not self.assets
            or len(ids) != len(self.assets)
            or any(not a.id or not a.kind for a in self.assets)
        ):
            raise ValueError("assets need unique nonempty ids and kinds")
        if len({c.id for c in self.connections}) != len(self.connections):
            raise ValueError("connection ids must be unique")
        for c in self.connections:
            if not c.id or c.source not in ids or c.target not in ids or c.source == c.target:
                raise ValueError("connection refers to invalid equipment")
            if c.domain not in {"electrical", "cooling", "communications"}:
                raise ValueError("unknown connection domain")

    def connected(self, equipment_id: str) -> tuple[str, ...]:
        if equipment_id not in {a.id for a in self.assets}:
            raise ValueError("unknown equipment")
        return tuple(
            sorted(
                {equipment_id}
                | {c.source for c in self.connections if c.target == equipment_id}
                | {c.target for c in self.connections if c.source == equipment_id}
            )
        )
