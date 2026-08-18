#!/usr/bin/env python3
"""v1.3.167: tip-height attestation must cite local tip hash."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import P2PNode, PeerConnection
from runtime.config import Config

TIP = "aa" * 32
OTHER = "bb" * 32


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
    cfg.bootstrap_peers = []
    cfg.p2p_attestation_target_head_bind = True
    chain = MagicMock()
    chain.get_height.return_value = local_h
    chain.get_state_root.return_value = "ee" * 32
    chain.get_block_by_hash = MagicMock(return_value=None)
    node = P2PNode(cfg, chain, MagicMock())
    node.head = MagicMock(return_value=TIP)  # type: ignore[method-assign]
    return node


def test_needles_v13167():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "attestation_target_head_mismatch" in p2p
    assert "_attestation_target_head_refuse_reason" in p2p
    assert "native_attestation_target_head_bind" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_attestation_target_head_bind" in cfg
    assert "P2P_ATTESTATION_TARGET_HEAD_BIND" in cfg
    notes = (ROOT / "RELEASE_NOTES_v1.3.167.md").read_text(encoding="utf-8")
    assert "1.3.167-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_attestation_target_head_bind" in metrics
    assert "abs_p2p_attestation_target_head_rejects_total" in metrics


def test_refuse_wrong_tip_hash():
    node = _node(local_h=10)
    assert (
        node._attestation_target_head_refuse_reason(
            {"target_hash": OTHER, "target_height": 10}
        )
        == "attestation_target_head_mismatch"
    )


def test_ok_tip_hash():
    node = _node(local_h=10)
    assert (
        node._attestation_target_head_refuse_reason(
            {"target_hash": TIP, "target_height": 10}
        )
        == ""
    )


def test_refuse_when_head_unreadable():
    node = _node(local_h=10)
    node.head = MagicMock(side_effect=RuntimeError("head boom"))  # type: ignore[method-assign]
    assert (
        node._attestation_target_head_refuse_reason(
            {"target_hash": TIP, "target_height": 10}
        )
        == "local_tip_unreadable"
    )


def test_empty_head_soft_skips_attestation_bind():
    node = _node(local_h=10)
    node.head = MagicMock(return_value=None)  # type: ignore[method-assign]
    assert (
        node._attestation_target_head_refuse_reason(
            {"target_hash": TIP, "target_height": 10}
        )
        == ""
    )


def test_non_tip_height_skips():
    node = _node(local_h=10)
    assert (
        node._attestation_target_head_refuse_reason(
            {"target_hash": OTHER, "target_height": 11}
        )
        == ""
    )


@pytest.mark.asyncio
async def test_handle_attestation_strikes_mismatch(monkeypatch):
    node = _node(local_h=10)
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "a1"
    node.peers[peer.peer_id] = peer
    strikes: list[str] = []
    node._strike_peer_sync = lambda p, r: strikes.append(r)  # type: ignore

    class _Native:
        @staticmethod
        def validate_p2p_attestation_payload(data):
            return True

    class _Keys:
        @staticmethod
        def verify_attestation(_data):
            return True

        @staticmethod
        def get_address():
            return "0x" + "aa" * 20

    monkeypatch.setattr("network.p2p_node.native", _Native)
    node.validator_keys = _Keys()
    await node._handle_attestation(
        peer,
        {
            "validator": "0x" + "11" * 20,
            "target_hash": OTHER,
            "target_height": 10,
            "slot": 9,
        },
    )
    assert "attestation_target_head_mismatch" in strikes
    assert node._attestation_target_head_rejects_total >= 1
    st = node.get_p2p_security_status()
    assert st.get("native_attestation_target_head_bind") is True
