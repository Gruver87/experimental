#!/usr/bin/env python3
"""v1.3.131: solicit-only mempool + status peer.height ahead cap."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import MSG_MEMPOOL, MSG_STATUS, P2PNode, PeerConnection
from runtime.config import Config


class _FakeWriter:
    def write(self, _data):
        return None

    async def drain(self):
        return None

    def close(self):
        return None

    def get_extra_info(self, _name, default=None):
        return default

    def is_closing(self):
        return False


class _FakeReader:
    def __init__(self):
        self._buf = b""

    async def read(self, _n):
        await asyncio.sleep(0)
        return b""


def _node() -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_mempool_require_wire_satoshi = False
    cfg.bootstrap_peers = []
    cfg.p2p_max_peer_height_ahead = 100
    chain = MagicMock()
    chain.get_height.return_value = 10
    chain.get_state_root.return_value = "aa" * 32
    mempool = MagicMock()
    node = P2PNode(cfg, chain, mempool)
    return node


def test_needles_v13131():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert 'kind": "mempool"' in p2p
    assert "unsolicited_mempool" in p2p
    assert "p2p_max_peer_height_ahead" in p2p
    assert "status_height_cap_total" in p2p
    assert "p2p_max_peer_height_ahead" in (
        ROOT / "runtime" / "config.py"
    ).read_text(encoding="utf-8")
    notes = (ROOT / "RELEASE_NOTES_v1.3.131.md").read_text(encoding="utf-8")
    assert "1.3.131-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_solicit_only" in metrics
    assert "abs_p2p_unsolicited_mempool_rejects_total" in metrics
    assert "abs_p2p_status_height_cap_total" in metrics


@pytest.mark.asyncio
async def test_unsolicited_mempool_struck_not_ingested():
    node = _node()
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "mp-peer"
    node.peers[peer.peer_id] = peer
    node._handle_mempool_batch = AsyncMock()
    await node._handle_message(
        peer, {"type": MSG_MEMPOOL, "data": {"transactions": []}}
    )
    node._handle_mempool_batch.assert_not_called()
    assert node._unsolicited_mempool_rejects_total >= 1
    st = node.get_p2p_security_status()
    assert st.get("native_mempool_solicit_only") is True


@pytest.mark.asyncio
async def test_status_height_capped_above_local():
    node = _node()
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "st-peer"
    peer.height = 5
    node.peers[peer.peer_id] = peer
    digest = "bb" * 32
    await node._handle_message(
        peer,
        {"type": MSG_STATUS, "data": {"height": 10_000_000, "head_hash": digest}},
    )
    # local=10, max_ahead=100 → capped at 110
    assert peer.height == 110
    assert node._status_height_cap_total >= 1
