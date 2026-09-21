#!/usr/bin/env python3
"""v1.3.178: GET_MEMPOOL served only when peer tip is near local tip."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import P2PNode, PeerConnection
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
    async def read(self, _n):
        await asyncio.sleep(0)
        return b""


def _node(*, local_h: int = 10) -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_mempool_require_wire_satoshi = False
    cfg.bootstrap_peers = []
    cfg.p2p_mempool_serve_tip_align = True
    cfg.p2p_mempool_serve_max_height_delta = 2
    chain = MagicMock()
    chain.get_height.return_value = local_h
    chain.get_state_root.return_value = "ee" * 32
    mp = MagicMock()
    mp.get = MagicMock(return_value=[MagicMock()])
    node = P2PNode(cfg, chain, mp)
    return node


def test_needles_v13178():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "get_mempool_tip_misaligned" in p2p
    assert "_get_mempool_tip_align_refuse_reason" in p2p
    assert "native_mempool_serve_tip_align" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_mempool_serve_tip_align" in cfg
    assert "P2P_MEMPOOL_SERVE_TIP_ALIGN" in cfg
    notes = (ROOT / "RELEASE_NOTES_v1.3.178.md").read_text(encoding="utf-8")
    assert "1.3.178-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_serve_tip_align" in metrics
    assert "abs_p2p_get_mempool_tip_misaligned_total" in metrics


def test_refuse_far_peer():
    node = _node(local_h=10)
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.height = 20
    assert (
        node._get_mempool_tip_align_refuse_reason(peer)
        == "get_mempool_tip_misaligned"
    )


def test_ok_near_peer():
    node = _node(local_h=10)
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.height = 11
    assert node._get_mempool_tip_align_refuse_reason(peer) == ""


@pytest.mark.asyncio
async def test_handle_sends_empty_on_misalign():
    node = _node(local_h=10)
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "p1"
    peer.height = 99
    peer.send = AsyncMock(return_value=True)  # type: ignore
    await node._handle_get_mempool(peer)
    peer.send.assert_called()
    args = peer.send.call_args[0]
    assert args[0] == "mempool"
    assert args[1].get("count") == 0
    assert node._get_mempool_tip_misaligned_total >= 1
    node.mempool.get.assert_not_called()
    st = node.get_p2p_security_status()
    assert st.get("native_mempool_serve_tip_align") is True
