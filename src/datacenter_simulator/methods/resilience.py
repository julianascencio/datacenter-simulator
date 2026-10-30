"""Event-resolved A/B transfer, module contingencies and powered cooling."""

from dataclasses import dataclass, field

import pandas as pd

from datacenter_simulator.methods.cooling import ThermalZone
from datacenter_simulator.models.devices import finite


@dataclass(frozen=True)
class FailureEvent:
    component: str
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if not self.component:
            raise ValueError("event needs a component")
        finite("start_s", self.start_s)
        finite("end_s", self.end_s, self.start_s, strict=True)


@dataclass(frozen=True)
class PowerFeed:
    """Parallel converter modules behind shared dependencies, delivered DC kW."""

    id: str
    modules_kw: dict[str, float]
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.modules_kw:
            raise ValueError("feed needs an id and modules")
        for capacity in self.modules_kw.values():
            finite("module capacity", capacity, strict=True)

    def available_kw(self, failed: set[str]) -> float:
        if self.id in failed or failed.intersection(self.dependencies):
            return 0.0
        return sum(capacity for name, capacity in self.modules_kw.items() if name not in failed)


@dataclass(frozen=True)
class CriticalRack:
    id: str
    demand_kw: float
    feeds: tuple[str, ...]
    transfer_delay_s: float = 0
    hold_up_s: float = 0
    initial_temperature_c: float = 24
    zone: ThermalZone = field(default_factory=ThermalZone)

    def __post_init__(self) -> None:
        if not self.id or not self.feeds or len(set(self.feeds)) != len(self.feeds):
            raise ValueError("rack needs an id and unique preferred feeds")
        for name in ("demand_kw", "transfer_delay_s", "hold_up_s"):
            finite(name, getattr(self, name))
        finite("initial_temperature_c", self.initial_temperature_c, -50)


@dataclass(frozen=True)
class CoolingUnit:
    id: str
    feed: str
    capacity_kw: float
    electric_kw: float
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.feed:
            raise ValueError("cooling unit needs id and feed")
        finite("capacity_kw", self.capacity_kw, strict=True)
        finite("electric_kw", self.electric_kw)


@dataclass
class ResilienceResult:
    timeline: pd.DataFrame
    racks: pd.DataFrame
    feeds: pd.DataFrame
    summary: dict[str, float]


def simulate_contingencies(
    feeds: list[PowerFeed],
    racks: list[CriticalRack],
    cooling: list[CoolingUnit],
    events: list[FailureEvent],
    *,
    duration_s: float,
    step_s: float = 1,
    ambient_c: float = 30,
    setpoint_c: float = 24,
) -> ResilienceResult:
    """Capacity/transfer study with exact event boundaries and well-mixed rack zones.

    Cooling gets electrical priority; racks then use input list priority. Feed B
    is selected when A is unavailable, without automatic failback. Hold-up bridges
    only transfer gaps and is reported separately as stored energy. No reliability
    probability, breaker selectivity or voltage transient is inferred.
    """
    finite("duration_s", duration_s, strict=True)
    finite("step_s", step_s, strict=True)
    finite("ambient_c", ambient_c, -50)
    finite("setpoint_c", setpoint_c, -50)
    feedmap = {f.id: f for f in feeds}
    if (
        not feeds
        or not racks
        or len(feedmap) != len(feeds)
        or len({r.id for r in racks}) != len(racks)
    ):
        raise ValueError("nonempty feeds/racks need unique ids")
    if len({c.id for c in cooling}) != len(cooling):
        raise ValueError("cooling ids must be unique")
    for rack in racks:
        if set(rack.feeds) - set(feedmap):
            raise ValueError("unknown rack feed")
    if any(c.feed not in feedmap for c in cooling):
        raise ValueError("unknown cooling feed")
    known = set(feedmap) | {r.id for r in racks} | {c.id for c in cooling}
    for f in feeds:
        known.update(f.modules_kw)
        known.update(f.dependencies)
    for c in cooling:
        known.update(c.dependencies)
    if any(e.component not in known for e in events):
        raise ValueError("unknown failed component")
    boundaries = sorted(
        {0.0, duration_s}
        | {v for e in events for v in (e.start_s, e.end_s) if 0 <= v <= duration_s}
    )
    active = {r.id: r.feeds[0] for r in racks}
    ready = dict.fromkeys(active, 0.0)
    hold_until = dict.fromkeys(active, 0.0)
    temperature = {r.id: r.initial_temperature_c for r in racks}
    t = 0.0
    rows, rack_rows, feed_rows = [], [], []
    while t < duration_s - 1e-9:
        failed = {e.component for e in events if e.start_s <= t < e.end_s}
        capacity = {f.id: f.available_kw(failed) for f in feeds}
        for r in racks:
            if capacity.get(active[r.id], 0) <= 0:
                selected = next((name for name in r.feeds if capacity[name] > 0), "")
                if selected != active[r.id]:
                    # Hold-up starts when a live supply is lost, not on restoration.
                    if active[r.id]:
                        hold_until[r.id] = t + r.hold_up_s
                    active[r.id] = selected
                    ready[r.id] = t + r.transfer_delay_s if selected else float("inf")
        next_points = [v for v in boundaries if v > t + 1e-9]
        next_points += [
            v for v in (*ready.values(), *hold_until.values()) if t + 1e-9 < v < duration_s
        ]
        dt = min(step_s, min(next_points) - t, duration_s - t)
        available = dict(capacity)
        cooling_kw = cooling_electric = 0.0
        for c in cooling:
            if c.id in failed or failed.intersection(c.dependencies):
                continue
            if available[c.feed] >= c.electric_kw:
                available[c.feed] -= c.electric_kw
                cooling_kw += c.capacity_kw
                cooling_electric += c.electric_kw
        supply, hold = {}, {}
        for r in racks:
            from_feed = 0.0
            if r.id not in failed and active[r.id] and t >= ready[r.id]:
                from_feed = min(r.demand_kw, available[active[r.id]])
                available[active[r.id]] -= from_feed
            hold[r.id] = (
                r.demand_kw
                if (
                    r.id not in failed
                    and t < hold_until[r.id]
                    and (not active[r.id] or t < ready[r.id])
                )
                else 0.0
            )
            supply[r.id] = from_feed + hold[r.id]
        requests = {
            r.id: max(
                0.0,
                supply[r.id]
                + r.zone.conductance_kw_k * (ambient_c - setpoint_c)
                + (temperature[r.id] - setpoint_c) * r.zone.capacitance_kj_k / dt,
            )
            for r in racks
        }
        total_request = sum(requests.values())
        for r in racks:
            removal = requests[r.id] * min(1, cooling_kw / total_request) if total_request else 0
            before = temperature[r.id]
            temperature[r.id] = r.zone.advance(before, ambient_c, supply[r.id], removal, dt / 3600)
            rack_rows.append(
                {
                    "time_s": t,
                    "duration_s": dt,
                    "equipment_id": r.id,
                    "feed": active[r.id],
                    "demand_kw": r.demand_kw,
                    "served_kw": supply[r.id],
                    "hold_up_kw": hold[r.id],
                    "unserved_kw": r.demand_kw - supply[r.id],
                    "removed_heat_kw": removal,
                    "temperature_start_c": before,
                    "temperature_c": temperature[r.id],
                }
            )
        for name, cap in capacity.items():
            feed_rows.append(
                {
                    "time_s": t,
                    "duration_s": dt,
                    "feed": name,
                    "available_kw": cap,
                    "delivered_kw": cap - available[name],
                }
            )
        rows.append(
            {
                "time_s": t,
                "duration_s": dt,
                "served_kw": sum(supply.values()),
                "unserved_kw": sum(r.demand_kw for r in racks) - sum(supply.values()),
                "cooling_capacity_kw": cooling_kw,
                "cooling_electric_kw": cooling_electric,
                "hold_up_kw": sum(hold.values()),
                "failed": tuple(sorted(failed)),
            }
        )
        t += dt
    frame, rack_frame = pd.DataFrame(rows), pd.DataFrame(rack_rows)
    return ResilienceResult(
        frame,
        rack_frame,
        pd.DataFrame(feed_rows),
        {
            "unserved_kwh": float((frame.unserved_kw * frame.duration_s).sum() / 3600),
            "interruption_s": float(frame.loc[frame.unserved_kw > 1e-8, "duration_s"].sum()),
            "hold_up_kwh": float((frame.hold_up_kw * frame.duration_s).sum() / 3600),
            "peak_temperature_c": float(rack_frame.temperature_c.max()),
        },
    )
