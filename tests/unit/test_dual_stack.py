"""ADR 0018 dual-stack selector tests."""

from __future__ import annotations

from network.transport.dual_stack import DualStackDialer
from network.transport.types import PeerEndpoint
from runtime.config import Config


def test_default_active_native() -> None:
    d = DualStackDialer.from_config(Config())
    assert d.active_kind == "native_tcp_tls"
    out = d.dial(PeerEndpoint(host="127.0.0.1", port=5000))
    assert out["kind"] == "native_tcp_tls"


def test_feature_selects_libp2p() -> None:
    d = DualStackDialer(feature_libp2p=True)
    assert d.active_kind == "libp2p"
    out = d.dial(PeerEndpoint(host="127.0.0.1", port=4001))
    assert out["kind"] == "libp2p"
    assert out["handle"]["phase"] == 1
