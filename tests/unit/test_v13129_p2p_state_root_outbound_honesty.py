#!/usr/bin/env python3
"""v1.3.129: outbound state_root_response height honesty + no height inflation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import P2PNode
from runtime.config import Config


class _Chain:
    def __init__(self):
        self._height = 3
        self._tip_root = "tt" * 32
        self._tip_head = "hh" * 32
        self._blocks = {
            1: {"height": 1, "state_root": "11" * 32, "hash": "a1" * 32},
            2: {"height": 2, "state_root": "22" * 32, "hash": "a2" * 32},
            3: {"height": 3, "state_root": "33" * 32, "hash": "a3" * 32},
        }

    def get_height(self):
        return self._height

    def get_state_root(self):
        return self._tip_root

    def get_block(self, height: int):
        return self._blocks.get(int(height))


def _node() -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.bootstrap_peers = []
    node = P2PNode(cfg, _Chain(), MagicMock())
    node.head = lambda: node.blockchain._tip_head  # type: ignore[method-assign]
    return node


def test_needles_v13129():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "_state_root_response_for_height" in p2p
    assert "state_root_outbound_refuse_total" in p2p
    # Wording evolved with later waves; keep the honesty intent.
    assert (
        "never label tip root/head as a non-tip height" in p2p
        or "never mislabel tip" in p2p
    )
    assert (
        "must not inflate peer.height" in p2p
        or "must not inflate peer tip" in p2p
    )
    notes = (ROOT / "RELEASE_NOTES_v1.3.129.md").read_text(encoding="utf-8")
    assert "1.3.129-industrial" in notes
    # Live Config().node_version advances with later waves; pin notes not config.
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_state_root_outbound_honesty" in metrics
    assert "abs_p2p_state_root_outbound_refuse_total" in metrics


def test_tip_uses_live_root_and_head():
    node = _node()
    payload = node._state_root_response_for_height(3)
    assert payload == {
        "height": 3,
        "state_root": "tt" * 32,
        "head_hash": "hh" * 32,
    }
    assert node._state_root_response_for_height(0) == payload


def test_historical_uses_block_header():
    node = _node()
    payload = node._state_root_response_for_height(1)
    assert payload == {
        "height": 1,
        "state_root": "11" * 32,
        "head_hash": "a1" * 32,
    }
    # Must not leak tip root under historical height.
    assert payload["state_root"] != node.blockchain.get_state_root()


def test_ahead_of_tip_refuses():
    node = _node()
    assert node._state_root_response_for_height(9) is None


def test_missing_incomplete_header_refuses():
    node = _node()
    node.blockchain._blocks[2] = {"height": 2, "state_root": "", "hash": "a2" * 32}
    assert node._state_root_response_for_height(2) is None


def test_get_last_block_error_refuses_tip_root(caplog):
    import logging

    node = _node()

    def _boom():
        raise RuntimeError("last missing")

    node.blockchain.get_last_block = _boom  # type: ignore[attr-defined]
    with caplog.at_level(logging.WARNING, logger="P2P"):
        assert node._state_root_response_for_height(3) is None
        assert node._state_root_response_for_height(0) is None
    assert "get_last_block failed in state_root_response" in caplog.text


def test_empty_follower_get_last_none_refuses():
    node = _node()
    node.blockchain.get_last_block = lambda: None  # type: ignore[attr-defined]
    assert node._state_root_response_for_height(3) is None


def test_peer_close_logs_queue_wake_failure(caplog):
    import logging
    from network.p2p_node import PeerConnection

    class _BoomQ:
        def put_nowait(self, _item):
            raise RuntimeError("q full")

    peer = PeerConnection(None, None)
    peer._send_q = _BoomQ()
    with caplog.at_level(logging.DEBUG, logger="P2P"):
        peer.close()
    assert "close send_q wake failed" in caplog.text


def test_security_status_exposes_outbound_honesty():
    node = _node()
    st = node.get_p2p_security_status()
    assert st.get("native_state_root_outbound_honesty") is True
    assert "state_root_outbound_refuse_total" in st
