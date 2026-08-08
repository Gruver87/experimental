"""ADR 0018 wave-3: multiaddr + in-process swarm."""

from __future__ import annotations

import pytest

from network.transport.libp2p_adapter import (
    InProcessSwarm,
    Libp2pTransportAdapter,
    RequestResponseService,
    parse_multiaddr,
)
from network.transport.types import PeerEndpoint


def test_parse_multiaddr_roundtrip() -> None:
    ma = parse_multiaddr("/ip4/127.0.0.1/tcp/4001/p2p/lab-a")
    assert ma.host == "127.0.0.1"
    assert ma.port == 4001
    assert ma.peer_id == "lab-a"
    assert ma.to_string() == "/ip4/127.0.0.1/tcp/4001/p2p/lab-a"


def test_parse_multiaddr_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_multiaddr("127.0.0.1:4001")


def test_adapter_connect_multiaddr() -> None:
    ad = Libp2pTransportAdapter(enabled=True)
    h = ad.connect(
        PeerEndpoint(host="127.0.0.1", port=1),
        multiaddr="/ip4/10.0.0.2/tcp/4002/p2p/peer-b",
    )
    assert h["multiaddr"] == "/ip4/10.0.0.2/tcp/4002/p2p/peer-b"
    assert h["peer_id"] == "peer-b"


def test_in_process_swarm_dial_and_publish() -> None:
    swarm = InProcessSwarm()
    a = swarm.spawn("a", "/ip4/127.0.0.1/tcp/4001/p2p/a")
    b = swarm.spawn("b", "/ip4/127.0.0.1/tcp/4002/p2p/b")
    got: list[bytes] = []
    b.subscribe("t", lambda _p, data: got.append(data))
    assert a.dial(b.listen.to_string())["connected"]
    assert a.publish("t", b"ping") == 1
    assert got == [b"ping"]


def test_request_response_echo() -> None:
    swarm = InProcessSwarm()
    a = swarm.spawn("a", "/ip4/127.0.0.1/tcp/4201/p2p/a")
    b = swarm.spawn("b", "/ip4/127.0.0.1/tcp/4202/p2p/b")
    a.dial(b.listen.to_string())
    rr_a = RequestResponseService(a)
    rr_b = RequestResponseService(b)
    rr_b.set_handler(lambda _p, data: data.upper())
    assert rr_a.request("b", b"hi") == b"HI"


def test_relay_line_topology() -> None:
    swarm = InProcessSwarm()
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4301/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4302/p2p/n2")
    c = swarm.spawn("n3", "/ip4/127.0.0.1/tcp/4303/p2p/n3")
    a.dial(b.listen.to_string())
    b.dial(c.listen.to_string())
    got: list[bytes] = []
    c.subscribe("t", lambda _p, d: got.append(d))
    assert a.publish("t", b"x") == 1
    assert got == []
    assert a.publish_relay("t", b"y", ttl=2) >= 2
    assert got == [b"y"]


def test_three_node_mesh_fanout() -> None:
    swarm = InProcessSwarm()
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4101/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4102/p2p/n2")
    c = swarm.spawn("n3", "/ip4/127.0.0.1/tcp/4103/p2p/n3")
    a.dial(b.listen.to_string())
    a.dial(c.listen.to_string())
    b.dial(c.listen.to_string())
    got_b: list[bytes] = []
    got_c: list[bytes] = []
    b.subscribe("blocks", lambda _p, d: got_b.append(d))
    c.subscribe("blocks", lambda _p, d: got_c.append(d))
    assert a.publish("blocks", b"x") == 2
    assert got_b == [b"x"] and got_c == [b"x"]
