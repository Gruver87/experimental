#!/usr/bin/env python3
"""libp2p mid-session Absolute handshake must soft-refuse (no 300s mesh ban)."""

from __future__ import annotations

import pytest

from network.p2p_node import MSG_HANDSHAKE, MSG_HANDSHAKE_ACK, P2PNode, PeerConnection
from runtime.config import Config


class _FakeWriter:
    def write(self, _data):
        return None

    def drain(self):
        return None

    def get_extra_info(self, name, default=None):
        if name == "peername":
            return ("127.0.0.1", 5000)
        return default

    def close(self):
        return None

    def is_closing(self):
        return False


class _FakeReader:
    def __init__(self, data: bytes = b""):
        self._buf = bytes(data)
        self._pos = 0

    async def read(self, n: int = -1):
        if self._pos >= len(self._buf):
            return b""
        if n is None or n < 0:
            chunk = self._buf[self._pos :]
            self._pos = len(self._buf)
            return chunk
        chunk = self._buf[self._pos : self._pos + int(n)]
        self._pos += len(chunk)
        return chunk

    async def readline(self):
        if self._pos >= len(self._buf):
            return b""
        nl = self._buf.find(b"\n", self._pos)
        if nl < 0:
            chunk = self._buf[self._pos :]
            self._pos = len(self._buf)
            return chunk
        chunk = self._buf[self._pos : nl + 1]
        self._pos = nl + 1
        return chunk


@pytest.mark.asyncio
async def test_libp2p_mid_session_handshake_soft_refuse_no_ban():
    cfg = Config()
    cfg.feature_libp2p = True
    cfg.p2p_rate_limit_strikes = 1
    cfg.p2p_ban_seconds = 300
    p2p = P2PNode(cfg, None, None)
    assert p2p._use_libp2p_transport is True

    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "libp2p-mid"
    p2p.peers[peer.peer_id] = peer
    removed = []
    p2p._remove_peer = lambda pid, p: removed.append(pid)

    await p2p._handle_message(peer, {"type": MSG_HANDSHAKE, "data": {"node_id": "x"}})
    assert removed == [], "libp2p mid-session HS must not remove/ban mesh peer"
    assert peer.peer_id in p2p.peers
    sec = p2p.get_p2p_security_status()
    assert sec["handshake_rejects"] >= 1
    shapes = sec.get("shape_rejects") or {}
    assert int(shapes.get("mid_session_handshake_libp2p", 0) or 0) >= 1
    assert int(shapes.get("mid_session_handshake", 0) or 0) == 0

    await p2p._handle_message(
        peer, {"type": MSG_HANDSHAKE_ACK, "data": {"accepted": True}}
    )
    assert removed == []
    assert int(
        p2p.get_p2p_security_status()["shape_rejects"].get(
            "mid_session_handshake_libp2p", 0
        )
        or 0
    ) >= 2


@pytest.mark.asyncio
async def test_tcp_mid_session_handshake_still_hard_bans():
    """TCP+TLS path must keep hard mid_session_handshake ban (v1.3.103)."""
    cfg = Config()
    cfg.feature_libp2p = False
    cfg.p2p_rate_limit_strikes = 1
    p2p = P2PNode(cfg, None, None)
    assert p2p._use_libp2p_transport is False

    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "tcp-mid"
    p2p.peers[peer.peer_id] = peer
    removed = []
    p2p._remove_peer = lambda pid, p: removed.append(pid)

    await p2p._handle_message(peer, {"type": MSG_HANDSHAKE, "data": {"node_id": "x"}})
    assert removed == ["tcp-mid"]
    shapes = p2p.get_p2p_security_status().get("shape_rejects") or {}
    assert int(shapes.get("mid_session_handshake", 0) or 0) >= 1
