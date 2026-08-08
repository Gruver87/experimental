"""ADR 0018 wave-3: multiaddr + in-process swarm."""

from __future__ import annotations

import pytest

from network.transport.libp2p_adapter import (
    InProcessSwarm,
    Libp2pTransportAdapter,
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
