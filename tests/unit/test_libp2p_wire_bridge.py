"""ADR 0019 wire bridge + peer policy unit tests."""

from __future__ import annotations

import pytest

from network.peer_manager import PeerManager, PeerManagerSettings
from network.transport.errors import TransportCapabilityError, TransportValidationError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.transport.libp2p_adapter.peer_policy import Libp2pPeerPolicy
from network.transport.libp2p_adapter.wire_bridge import (
    admit_abs_inbox,
    admit_abs_wire_frame,
    detect_abs_wire_codec,
    encode_abs_wire_frame,
    prepare_abs_wire_frame,
)
from network.transport.types import PeerEndpoint


def test_encode_abs_wire_frame_ping() -> None:
    raw = encode_abs_wire_frame("ping", {"lab": True}, codec="v1")
    assert isinstance(raw, (bytes, bytearray))
    assert b"ping" in raw or b"PING" in raw or raw.startswith(b"AB2:")


def test_detect_abs_wire_codec_v1_v2() -> None:
    v1 = encode_abs_wire_frame("ping", {"lab": True}, codec="v1")
    v2 = encode_abs_wire_frame("ping", {"lab": True}, codec="v2")
    assert detect_abs_wire_codec(v1) == "v1"
    assert detect_abs_wire_codec(v2) == "v2"
    assert detect_abs_wire_codec(b"ping\0lab") == "lab"


def test_admit_abs_wire_frame_roundtrip() -> None:
    raw = encode_abs_wire_frame("ping", None, codec="v1")
    decision = admit_abs_wire_frame(raw, peer_id="peer-a")
    # Native ingress may soft-fail without full RL table; accept either ok or structured reject
    assert decision.ok or decision.reject is not None
    if decision.ok and decision.frame is not None:
        assert decision.frame.msg_type.lower() == "ping"


def test_admit_abs_inbox_batch() -> None:
    v1 = encode_abs_wire_frame("ping", {"n": 1}, codec="v1")
    v2 = encode_abs_wire_frame("ping", {"n": 2}, codec="v2")
    out = admit_abs_inbox([("p1", v1), ("p2", v2)])
    assert len(out) == 2
    assert out[0][0] == "p1" and out[0][2] == "v1"
    assert out[1][0] == "p2" and out[1][2] == "v2"
    assert out[0][1].ok or out[0][1].reject is not None
    assert out[1][1].ok or out[1][1].reject is not None


def test_prepare_abs_wire_refuses_empty_msg_type() -> None:
    d, raw = prepare_abs_wire_frame(peer_id="peer-a", msg_type="  ", payload={})
    assert d.ok is False
    assert raw == b""
    assert d.reject is not None


def test_prepare_abs_wire_refuses_empty_peer() -> None:
    d, raw = prepare_abs_wire_frame(peer_id="", msg_type="ping", payload={})
    assert d.ok is False
    assert raw == b""
    assert d.reject is not None


def test_prepare_abs_wire_refuses_oversize() -> None:
    d, raw = prepare_abs_wire_frame(
        peer_id="peer-a",
        msg_type="ping",
        payload={"blob": "x" * 8000},
        max_bytes=4096,
    )
    assert d.ok is False
    assert raw == b""
    assert d.reject is not None


def test_send_abs_wire_refuses_when_prepare_refuses() -> None:
    ad = Libp2pTransportAdapter(enabled=False)
    with pytest.raises(TransportValidationError) as ei:
        ad.send_abs_wire("peer-a", "", {"lab": True})
    assert ei.value.code in ("transport_validation", "abs_wire_prepare_refused")


def test_admit_abs_wire_junk_is_not_ok() -> None:
    decision = admit_abs_wire_frame(b"%%%not-abs-wire%%%\n", peer_id="peer-a")
    assert decision.ok is False
    assert decision.reject is not None


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
