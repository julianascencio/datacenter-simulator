import pytest

from datacenter_simulator.methods.communications import CommunicationNetwork, Link, Traffic


def topology() -> CommunicationNetwork:
    return CommunicationNetwork(
        ["a", "b", "c"],
        [Link("ab", "a", "b", 10, 1), Link("ac", "a", "c", 10, 2), Link("cb", "c", "b", 10, 2)],
    )


def test_full_duplex_counts_each_direction_separately() -> None:
    r = topology().evaluate([Traffic("a", "b", 8), Traffic("b", "a", 8)])
    assert r.links[r.links.link == "ab"].utilization.tolist() == [0.8, 0.8]
    assert not r.warnings
    assert r.flows.iloc[0].latency_lower_bound_ms == pytest.approx(1.0012)


def test_overload_and_failure_reroute() -> None:
    network = topology()
    assert network.evaluate([Traffic("a", "b", 11)]).warnings
    rerouted = network.evaluate([Traffic("a", "b", 8)], failed_links=frozenset({"ab"}))
    assert rerouted.flows.iloc[0].path == ("ac", "cb")
    disconnected = network.evaluate([Traffic("a", "b", 8)], failed_nodes=frozenset({"b"}))
    assert not disconnected.flows.iloc[0].reachable
    assert disconnected.warnings


def test_unknown_failure_rejected() -> None:
    with pytest.raises(ValueError):
        topology().evaluate([], failed_links=frozenset({"typo"}))
