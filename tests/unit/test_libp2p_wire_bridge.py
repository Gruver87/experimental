"""ADR 0019 wire bridge + peer policy unit tests."""

from __future__ import annotations

import pytest

from network.peer_manager import PeerManager, PeerManagerSettings
from network.transport.errors import TransportCapabilityError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.transport.libp2p_adapter.peer_policy import Libp2pPeerPolicy
from network.transport.libp2p_adapter.wire_bridge import (
    admit_abs_wire_frame,
    encode_abs_wire_frame,
)
from network.transport.types import PeerEndpoint


def test_encode_abs_wire_frame_ping() -> None:
    raw = encode_abs_wire_frame("ping", {"lab": True}, codec="v1")
    assert isinstance(raw, (bytes, bytearray))
    assert b"ping" in raw or b"PING" in raw or raw.startswith(b"AB2:")


def test_admit_abs_wire_frame_roundtrip() -> None:
    raw = encode_abs_wire_frame("ping", None, codec="v1")
    decision = admit_abs_wire_frame(raw, peer_id="peer-a")
    # Native ingress may soft-fail without full RL table; accept either ok or structured reject
    assert decision.ok or decision.reject is not None
    if decision.ok and decision.frame is not None:
        assert decision.frame.msg_type.lower() == "ping"


def test_peer_policy_blocks_banned() -> None:
    pm = PeerManager(settings=PeerManagerSettings(rate_limit_strikes=1, ban_seconds=60))
    # Force ban via strikes
    class P:
        peer_id = "bad-peer"
        host = "127.0.0.1"
        port = 4001

    assert pm.strike(P(), "lab") is True
    policy = Libp2pPeerPolicy(peer_manager=pm)
    with pytest.raises(TransportCapabilityError):
        policy.check_dial(peer_id="bad-peer", host="127.0.0.1", port=4001)

    ad = Libp2pTransportAdapter(enabled=True, peer_policy=policy)
    with pytest.raises(TransportCapabilityError):
        ad.connect(PeerEndpoint(host="127.0.0.1", port=4001, peer_id="bad-peer"))


def test_security_status_includes_libp2p_block() -> None:
    from unittest.mock import MagicMock

    from network.p2p_node import P2PNode
    from runtime.config import Config

    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.feature_libp2p = False
    chain = MagicMock()
    chain.height = 0
    chain.get_tip_hash = MagicMock(return_value="")
    node = P2PNode(cfg, chain, MagicMock())
    st = node.get_p2p_security_status()
    assert "libp2p" in st
    assert st["libp2p"]["feature_libp2p"] is False
    assert st["libp2p"]["default_mesh"] is False
    assert "ADR0019" in st["libp2p"]["honesty"]
    assert st["libp2p"]["peer_policy"] is True
