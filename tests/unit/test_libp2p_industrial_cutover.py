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


def test_stale_outbound_libp2p_session_is_cleared_for_retry() -> None:
    """Failed handshake must not pin role=outbound on the reused rust session."""
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    peer = node._new_libp2p_peer("node2", 5000, "12D3KooWstale")
    peer._libp2p_role = "outbound"
    peer._libp2p_inbound_handler = True
    peer.peer_id = ""
    assert peer.peer_id not in node.peers
    node._release_libp2p_session(peer)
    assert str(getattr(peer, "_libp2p_role", "") or "") == ""
    assert getattr(peer, "_libp2p_inbound_handler", False) is False
    assert "12D3KooWstale" not in node._libp2p_sessions


@pytest.mark.asyncio
async def test_libp2p_write_does_not_wait_rr_ack() -> None:
    """send_wire ACK must not HOL the peer send loop (state_root probe)."""
    import asyncio
    import time

    from network.p2p_node import PeerConnection, _ensure_libp2p_io_pools

    started = time.monotonic()
    blocked = asyncio.Event()

    class _Ad:
        def send_wire(self, *_a, **_k):
            blocked.set()
            time.sleep(2.0)
            return b"OK:"

    peer = PeerConnection(None, None, libp2p_adapter=_Ad(), libp2p_peer_id="12D3KooWtest")
    with patch(
        "network.transport.libp2p_adapter.wire_bridge.prepare_abs_wire_frame",
        return_value=(MagicMock(ok=True), b'{"type":"ping"}\n'),
    ):
        ok = await asyncio.wait_for(peer._write_message("ping", {}), timeout=0.5)
    assert ok is True
    assert time.monotonic() - started < 1.0
    await asyncio.wait_for(blocked.wait(), timeout=2.0)
    send_pool, inbox_pool = _ensure_libp2p_io_pools()
    assert send_pool is not inbox_pool


@pytest.mark.asyncio
async def test_libp2p_state_root_bypasses_inbound_queue() -> None:
    """state_root must not sit behind NEW_BLOCK on the per-peer queue."""
    import asyncio

    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    peer = node._new_libp2p_peer("node2", 5000, "12D3KooWtest")
    peer.peer_id = "mesh-2"
    node.peers = {peer.peer_id: peer}
    await peer._libp2p_inbound.put({"type": "new_block", "data": {}})
    handled: list = []

    async def _hm(_peer, msg):
        handled.append(msg)

    node._handle_message = _hm  # type: ignore[method-assign]
    node._libp2p_admit_raw_frame = lambda *_a, **_k: {  # type: ignore[method-assign]
        "type": "state_root_response",
        "data": {"height": 1, "state_root": "aa" * 32},
    }
    await node._libp2p_on_raw_frame("12D3KooWtest", b"ignored")
    assert len(handled) == 1
    assert handled[0]["type"] == "state_root_response"
    assert peer._libp2p_inbound.qsize() == 1


@pytest.mark.asyncio
async def test_libp2p_passive_spawns_inbound_handler() -> None:
    """Lex-smaller initiator's HANDSHAKE must start the responder (role=passive)."""
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    peer = node._new_libp2p_peer("node1", 5000, "12D3KooWpassive")
    peer._libp2p_role = "passive"
    node._libp2p_admit_raw_frame = lambda *_a, **_k: {  # type: ignore[method-assign]
        "type": "handshake",
        "data": {},
    }

    async def _noop(_peer):
        return None

    node._handle_libp2p_incoming = _noop  # type: ignore[method-assign]
    await node._libp2p_on_raw_frame("12D3KooWpassive", b"ignored")
    assert getattr(peer, "_libp2p_inbound_handler", False) is True
    assert peer._libp2p_inbound.qsize() == 1


@pytest.mark.asyncio
async def test_libp2p_outbound_does_not_spawn_second_handler() -> None:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.feature_libp2p = True
    node = _node(cfg)
    peer = node._new_libp2p_peer("node2", 5000, "12D3KooWtest")
    peer.peer_id = "mesh-2"
    peer._libp2p_role = "outbound"
    node.peers = {peer.peer_id: peer}
    node._libp2p_admit_raw_frame = lambda *_a, **_k: {  # type: ignore[method-assign]
        "type": "ping",
        "data": {},
    }
    await node._libp2p_on_raw_frame("12D3KooWtest", b"ignored")
    assert getattr(peer, "_libp2p_inbound_handler", False) is False
    assert peer._libp2p_inbound.qsize() == 1
