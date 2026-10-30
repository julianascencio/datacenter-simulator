"""Deterministic traffic routing, directional link loading and latency lower bounds."""

from dataclasses import dataclass
from heapq import heappop, heappush

import pandas as pd

from datacenter_simulator.models.devices import finite


@dataclass(frozen=True)
class Link:
    id: str
    source: str
    target: str
    capacity_gbps: float
    latency_ms: float = 0.01
    medium: str = "fiber"

    def __post_init__(self) -> None:
        if not self.id or self.source == self.target:
            raise ValueError("link needs an id and distinct endpoints")
        finite("capacity_gbps", self.capacity_gbps, strict=True)
        finite("latency_ms", self.latency_ms)


@dataclass(frozen=True)
class Traffic:
    source: str
    target: str
    demand_gbps: float
    packet_bytes: int = 1500

    def __post_init__(self) -> None:
        finite("demand_gbps", self.demand_gbps)
        if not isinstance(self.packet_bytes, int) or self.packet_bytes < 1:
            raise ValueError("packet_bytes must be a positive integer")


@dataclass
class CommunicationResult:
    links: pd.DataFrame
    flows: pd.DataFrame
    warnings: tuple[str, ...]


class CommunicationNetwork:
    """Full-duplex links. Shortest baseline-latency routing; no queuing/ECMP model."""

    def __init__(self, nodes: list[str], links: list[Link]):
        if len(set(nodes)) != len(nodes) or len({link.id for link in links}) != len(links):
            raise ValueError("node and link ids must be unique")
        self.nodes = list(nodes)
        self.links = list(links)
        for link in links:
            if link.source not in nodes or link.target not in nodes:
                raise ValueError("unknown communication endpoint")

    def evaluate(
        self,
        traffic: list[Traffic],
        *,
        failed_links: frozenset[str] = frozenset(),
        failed_nodes: frozenset[str] = frozenset(),
    ) -> CommunicationResult:
        """Report offered traffic, including overloads and disconnected flows."""
        if failed_links - {link.id for link in self.links} or failed_nodes - set(self.nodes):
            raise ValueError("unknown failed link or node")
        adjacency: dict[str, list[tuple[str, Link]]] = {node: [] for node in self.nodes}
        loading = {(link.id, direction): 0.0 for link in self.links for direction in (0, 1)}
        for link in self.links:
            if link.id in failed_links or {link.source, link.target} & failed_nodes:
                continue
            adjacency[link.source].append((link.target, link))
            adjacency[link.target].append((link.source, link))
        flows, warnings = [], []
        for flow in traffic:
            if flow.source not in adjacency or flow.target not in adjacency:
                raise ValueError("traffic contains unknown endpoints")
            # Unique sequence number avoids comparing Link objects for equal-cost paths.
            queue: list[tuple[float, int, str, list[tuple[Link, int]]]] = [(0, 0, flow.source, [])]
            visited: set[str] = set()
            sequence = 0
            found: list[tuple[Link, int]] | None = None
            baseline = 0.0
            while queue:
                cost, _, node, path = heappop(queue)
                if node in visited or node in failed_nodes:
                    continue
                visited.add(node)
                if node == flow.target:
                    found, baseline = path, cost
                    break
                for target, link in adjacency[node]:
                    sequence += 1
                    direction = 0 if node == link.source else 1
                    heappush(
                        queue,
                        (cost + link.latency_ms, sequence, target, path + [(link, direction)]),
                    )
            if found is None:
                warnings.append(f"No route: {flow.source} -> {flow.target}")
                latency = float("nan")
            else:
                latency = baseline
                for link, direction in found:
                    loading[link.id, direction] += flow.demand_gbps
                    latency += flow.packet_bytes * 8 / (link.capacity_gbps * 1e6)
            flows.append(
                {
                    "source": flow.source,
                    "target": flow.target,
                    "demand_gbps": flow.demand_gbps,
                    "reachable": found is not None,
                    "latency_lower_bound_ms": latency,
                    "path": tuple(link.id for link, _ in (found or [])),
                }
            )
        rows = []
        for link in self.links:
            for direction in (0, 1):
                utilization = loading[link.id, direction] / link.capacity_gbps
                if utilization > 1:
                    warnings.append(f"Link overloaded: {link.id} direction {direction}")
                rows.append(
                    {
                        "link": link.id,
                        "direction": direction,
                        "source": link.source if direction == 0 else link.target,
                        "target": link.target if direction == 0 else link.source,
                        "offered_gbps": loading[link.id, direction],
                        "capacity_gbps": link.capacity_gbps,
                        "utilization": utilization,
                        "available": link.id not in failed_links
                        and not bool({link.source, link.target} & failed_nodes),
                    }
                )
        return CommunicationResult(pd.DataFrame(rows), pd.DataFrame(flows), tuple(warnings))
