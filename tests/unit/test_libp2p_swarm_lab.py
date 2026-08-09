"""ADR 0018 wave-3: multiaddr + in-process swarm."""

from __future__ import annotations

import pytest

from network.transport.dual_stack import DualStackDialer
from network.transport.errors import TransportCapabilityError
from network.transport.libp2p_adapter import (
    DiscoveryRegistry,
    IdentifyService,
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


def test_parse_multiaddr_ipv6_roundtrip() -> None:
    ma = parse_multiaddr("/ip6/::1/tcp/4401/p2p/lab-w")
    assert ma.host == "::1"
    assert ma.port == 4401
    assert ma.peer_id == "lab-w"
    assert ma.to_string() == "/ip6/::1/tcp/4401/p2p/lab-w"


def test_parse_multiaddr_dns4_roundtrip() -> None:
    ma = parse_multiaddr("/dns4/localhost/tcp/4402/p2p/lab-y")
    assert ma.host == "localhost"
    assert ma.port == 4402
    assert ma.peer_id == "lab-y"
    assert ma.dns == "dns4"
    assert ma.to_string() == "/dns4/localhost/tcp/4402/p2p/lab-y"


def test_hostname_formats_as_dns4() -> None:
    from network.transport.libp2p_adapter.multiaddr import Multiaddr

    assert Multiaddr(host="example.com", port=9).to_string() == "/dns4/example.com/tcp/9"


def test_parse_multiaddr_quic_roundtrip() -> None:
    from network.transport.libp2p_adapter.multiaddr import Multiaddr, parse_multiaddr

    ma = parse_multiaddr("/ip4/127.0.0.1/udp/4403/quic-v1/p2p/lab-ab")
    assert ma.host == "127.0.0.1"
    assert ma.port == 4403
    assert ma.peer_id == "lab-ab"
    assert ma.transport == "quic-v1"
    assert ma.to_string() == "/ip4/127.0.0.1/udp/4403/quic-v1/p2p/lab-ab"
    assert (
        Multiaddr(host="127.0.0.1", port=9, transport="quic-v1").to_string()
        == "/ip4/127.0.0.1/udp/9/quic-v1"
    )


def test_parse_multiaddr_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_multiaddr("127.0.0.1:4001")


def test_adapter_connect_multiaddr() -> None:
    ad = Libp2pTransportAdapter(enabled=True)
    try:
        if ad.rust_backend:
            # ADR 0019: real swarm fail-closes when nothing listens.
            with pytest.raises(TransportCapabilityError):
                ad.connect(
                    PeerEndpoint(host="127.0.0.1", port=1),
                    multiaddr="/ip4/127.0.0.1/tcp/39998/p2p/peer-b",
                )
        else:
            h = ad.connect(
                PeerEndpoint(host="127.0.0.1", port=1),
                multiaddr="/ip4/10.0.0.2/tcp/4002/p2p/peer-b",
            )
            assert h["multiaddr"] == "/ip4/10.0.0.2/tcp/4002/p2p/peer-b"
            assert h["peer_id"] == "peer-b"
    finally:
        ad.close()


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


def test_identify_and_dial_discovered() -> None:
    swarm = InProcessSwarm()
    a = swarm.spawn("a", "/ip4/127.0.0.1/tcp/4501/p2p/a")
    b = swarm.spawn("b", "/ip4/127.0.0.1/tcp/4502/p2p/b")
    a.dial(b.listen.to_string())
    id_a = IdentifyService(a)
    IdentifyService(b)
    info = id_a.identify("b")
    assert info.peer_id == "b"
    reg = DiscoveryRegistry()
    reg.announce("b", b.listen.to_string())
    dialer = DualStackDialer(feature_libp2p=True)
    try:
        if dialer.libp2p.rust_backend:
            # In-process registry addr is not a real rust listener → fail-closed.
            with pytest.raises(TransportCapabilityError):
                dialer.dial_discovered(reg, "b")
        else:
            h = dialer.dial_discovered(reg, "b")
            assert h["kind"] == "libp2p"
            assert "4502" in h["handle"]["multiaddr"]
    finally:
        dialer.libp2p.close()


def test_discovery_announce_dial() -> None:
    reg = DiscoveryRegistry()
    swarm = InProcessSwarm()
    a = swarm.spawn("a", "/ip4/127.0.0.1/tcp/4401/p2p/a")
    b = swarm.spawn("b", "/ip4/127.0.0.1/tcp/4402/p2p/b")
    reg.announce("a", a.listen.to_string())
    reg.announce("b", b.listen.to_string())
    assert reg.lookup("b").endswith("/p2p/b")
    assert reg.find_and_dial(a, "b")["remote"] == "b"


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
