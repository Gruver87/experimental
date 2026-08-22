"""ADR 0020 Experimental industrial libp2p mesh — fail-closed unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from network.transport.errors import TransportValidationError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.p2p_node import P2PNode
from runtime.config import Config


def _node(cfg: Config) -> P2PNode:
    chain = MagicMock()
    chain.height = 0
    chain.get_height = MagicMock(return_value=0)
    chain.get_tip_hash = MagicMock(return_value="")
    return P2PNode(cfg, chain, MagicMock())


def test_prod_json_mesh_libp2p_on_does_not_start_native_listener() -> None:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.feature_libp2p = True
    cfg.p2p_native_transport = True
    node = _node(cfg)
    assert node._use_libp2p_transport is True
    assert node._use_native_transport is False
    assert node._native_listener is None


@pytest.mark.asyncio
async def test_flag_on_without_native_swarm_refuses_start() -> None:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.feature_libp2p = True
    node = _node(cfg)
    with patch(
        "network.transport.libp2p_adapter.adapter.native_libp2p_available",
        return_value=False,
    ):
        node._dual_stack.libp2p._native_capable = False
        await node.start()
    assert node._running is False
    assert node._native_listener is None
    assert node._libp2p_listening is False


def test_prepare_fail_does_not_call_send_wire() -> None:
    ad = Libp2pTransportAdapter(enabled=True)
    sent: list = []

    def _boom(*_a, **_k):
        sent.append(True)
        return b"nope"

    ad.send_wire = _boom  # type: ignore[method-assign]
    with pytest.raises(TransportValidationError):
        ad.send_abs_wire("peer-a", "   ", {"lab": True})
    assert sent == []


def test_inbound_garbage_is_refuse_not_dispatch() -> None:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    out = node._libp2p_admit_raw_frame("peer-a", b"%%%not-abs-wire%%%\n")
    assert out is None
    assert int(node._libp2p_wire_refuse_total) >= 1


def test_libp2p_session_reused_for_same_peer_id() -> None:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    a = node._new_libp2p_peer("node2", 5000, "QmABC")
    b = node._new_libp2p_peer("node2", 5000, "QmABC")
    assert a is b
    assert node._libp2p_sessions["QmABC"] is a


def test_status_honesty_lab_until_listening() -> None:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    st = node.get_p2p_security_status()
    assert st["libp2p"]["active"] is False
    assert "ADR0019" in st["libp2p"]["honesty"]
    node._libp2p_listening = True
    st2 = node.get_p2p_security_status()
    assert st2["libp2p"]["active"] is True
    assert st2["libp2p"]["honesty"] == "ADR0020_experimental_libp2p_industrial_mesh"
    assert "lab_not_prod_mesh" not in st2["libp2p"]["honesty"]


def test_health_ready_p2p_running_accepts_libp2p_listen() -> None:
    from api.http import _p2p_listener_bound

    class _P2P:
        _server = None
        _native_listener = None
        _libp2p_listening = False

    p = _P2P()
    assert _p2p_listener_bound(p) is False
    p._libp2p_listening = True
    assert _p2p_listener_bound(p) is True
    p._libp2p_listening = False
    p._native_listener = object()
    assert _p2p_listener_bound(p) is True


def test_connect_peer_refuses_peer_id_as_dns_host() -> None:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    assert node._host_looks_like_libp2p_peer_id(
        "12D3KooWAbCdEfGhIjKlMnOpQrStUvWxYz"
    )
    assert not node._host_looks_like_libp2p_peer_id("docker-prod-mesh-2")
    assert not node._host_looks_like_libp2p_peer_id("172.20.0.12")
