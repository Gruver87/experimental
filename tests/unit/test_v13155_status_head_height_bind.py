#!/usr/bin/env python3
"""v1.3.155: STATUS/handshake known-head height bind."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import P2PNode, PeerConnection
from runtime.config import Config

DIGEST = "ab" * 32


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


def _node() -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.bootstrap_peers = []
    cfg.p2p_status_head_height_bind = True
    chain = MagicMock()
    chain.get_height.return_value = 10
    chain.get_state_root.return_value = "aa" * 32
    chain.get_block_by_hash = MagicMock(return_value=None)
    return P2PNode(cfg, chain, MagicMock())


def test_needles_v13155():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "status_head_height_mismatch" in p2p
    assert "handshake_head_height_mismatch" in p2p
    assert "_status_head_height_refuse_reason" in p2p
    assert "_local_known_head_height_mismatch" in p2p
    assert "native_status_head_height_bind" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_status_head_height_bind" in cfg
    assert "P2P_STATUS_HEAD_HEIGHT_BIND" in cfg
    notes = (ROOT / "RELEASE_NOTES_v1.3.155.md").read_text(encoding="utf-8")
    assert "1.3.155-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_status_head_height_bind" in metrics
    assert "abs_p2p_status_head_height_mismatch_total" in metrics


def test_status_head_height_mismatch_refuse():
    node = _node()
    node.get_block = MagicMock(  # type: ignore[method-assign]
        return_value={"hash": DIGEST, "height": 50}
    )
    assert (
        node._status_head_height_refuse_reason(DIGEST, 110)
        == "status_head_height_mismatch"
    )
    assert node._status_head_height_refuse_reason(DIGEST, 50) == ""
    assert (
        node._status_head_height_refuse_reason(
            DIGEST, 110, reason="handshake_head_height_mismatch"
        )
        == "handshake_head_height_mismatch"
    )
    node.get_block = MagicMock(return_value=None)  # type: ignore[method-assign]
    assert node._status_head_height_refuse_reason("ff" * 32, 9) == ""
    st = node.get_p2p_security_status()
    assert st.get("native_status_head_height_bind") is True


def test_new_block_bind_still_uses_shared_helper():
    node = _node()
    node.get_block = MagicMock(  # type: ignore[method-assign]
        return_value={"hash": DIGEST, "height": 7}
    )
    assert (
        node._new_block_head_height_refuse_reason(DIGEST, 99)
        == "new_block_head_height_mismatch"
    )
    assert node._local_known_head_height_mismatch(DIGEST, 99) is True
    assert node._local_known_head_height_mismatch(DIGEST, 7) is False


def test_head_height_store_error_is_mismatch_not_agree():
    node = _node()
    node.get_block = MagicMock(side_effect=RuntimeError("store down"))  # type: ignore[method-assign]
    assert node._local_known_head_height_mismatch(DIGEST, 7) is True
    assert (
        node._new_block_head_height_refuse_reason(DIGEST, 7)
        == "new_block_head_height_mismatch"
    )
