#!/usr/bin/env python3
"""v1.3.137: attestation local-head consistency + solicit-only block responses."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import MSG_BLOCK, MSG_BLOCKS, P2PNode, PeerConnection
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


DIGEST = "ab" * 32


def _node() -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.bootstrap_peers = []
    cfg.p2p_max_attestation_slot_ahead = 100_000
    chain = MagicMock()
    chain.get_height.return_value = 10
    chain.get_state_root.return_value = "aa" * 32
    chain.get_block_by_hash.side_effect = lambda h: (
        {"hash": DIGEST, "height": 7, "number": 7}
        if str(h).lower() == DIGEST
        else None
    )
    node = P2PNode(cfg, chain, MagicMock())
    vkeys = MagicMock()
    vkeys.verify_attestation.return_value = True
    node.validator_keys = vkeys
    consensus = MagicMock()
    consensus.engine = MagicMock()
    consensus.engine.current_slot = 10
    consensus.attest = MagicMock(return_value=True)
    node._consensus = consensus
    return node


def test_needles_v13137():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    solicit = (ROOT / "sync" / "solicit.py").read_text(encoding="utf-8")
    handlers = (ROOT / "network" / "p2p_dispatch" / "handlers.py").read_text(
        encoding="utf-8"
    )
    surface = p2p + "\n" + solicit + "\n" + handlers
    assert "_attestation_local_head_reject_reason" in p2p
    assert "attestation_local_height_mismatch" in p2p
    assert "unsolicited_blocks" in surface
    assert "native_block_solicit_only" in p2p
    notes = (ROOT / "RELEASE_NOTES_v1.3.137.md").read_text(encoding="utf-8")
    assert "1.3.137-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_attestation_local_head" in metrics
    assert "abs_p2p_unsolicited_block_rejects_total" in metrics
    assert "abs_p2p_native_block_solicit_only" in metrics


def test_local_head_mismatch_and_unknown():
    node = _node()
    assert (
        node._attestation_local_head_reject_reason(
            {"target_hash": DIGEST, "target_height": 99}
        )
        == "attestation_local_height_mismatch"
    )
    assert (
        node._attestation_local_head_reject_reason(
            {"target_hash": DIGEST, "target_height": 7}
        )
        == ""
    )
    assert (
        node._attestation_local_head_reject_reason(
            {"target_hash": "ff" * 32, "target_height": 7}
        )
        == ""
    )


@pytest.mark.asyncio
async def test_local_mismatch_not_applied(monkeypatch):
    node = _node()
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "att"
    node.peers[peer.peer_id] = peer
    node._relay_attestation = AsyncMock()
    monkeypatch.setattr(
        "network.p2p_node.native.validate_p2p_attestation_payload",
        lambda _d: True,
    )
    await node._handle_attestation(
        peer,
        {
            "validator": "0x" + ("11" * 20),
            "target_hash": DIGEST,
            "target_height": 99,
            "slot": 7,
            "signature": "cd" * 32,
            "public_key": "ef" * 33,
        },
    )
    node._consensus.attest.assert_not_called()
    node._relay_attestation.assert_not_called()
    assert node._attestation_local_head_rejects_total >= 1


@pytest.mark.asyncio
async def test_own_attestation_echo_is_not_reapplied():
    node = _node()
    our = "0x" + ("11" * 20)
    node.validator_keys.get_address.return_value = our
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "echo"
    node.peers[peer.peer_id] = peer
    node._relay_attestation = AsyncMock()
    payload = {
        "validator": our,
        "target_hash": DIGEST,
        "target_height": 7,
        "slot": 7,
        "signature": "cd" * 32,
        "public_key": "ef" * 33,
    }
    await node._handle_attestation(peer, payload)
    node._consensus.attest.assert_not_called()
    node._relay_attestation.assert_not_called()
    assert node._attestation_echo_drops_total >= 1


@pytest.mark.asyncio
async def test_duplicate_attestation_is_not_relayed_twice(monkeypatch):
    node = _node()
    node.validator_keys.get_address.return_value = "0x" + ("22" * 20)
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "att"
    node.peers[peer.peer_id] = peer
    node._relay_attestation = AsyncMock()
    monkeypatch.setattr(
        "network.p2p_node.native.validate_p2p_attestation_payload",
        lambda _d: True,
    )
    payload = {
        "validator": "0x" + ("11" * 20),
        "target_hash": DIGEST,
        "target_height": 7,
        "slot": 7,
        "signature": "cd" * 32,
        "public_key": "ef" * 33,
    }
    await node._handle_attestation(peer, payload)
    await node._handle_attestation(peer, payload)
    assert node._consensus.attest.call_count == 1
    assert node._relay_attestation.await_count == 1
    assert node._attestation_dup_drops_total >= 1


def test_on_consensus_attestation_binds_header_height_not_live_tip():
    node = _node()
    our = "0xabc"
    node.validator_keys.get_address.return_value = our
    signed = {}

    def _sign(block_data, slot):
        signed["block"] = dict(block_data)
        signed["slot"] = slot
        return {"ok": True, **block_data, "slot": slot}

    node.validator_keys.sign_attestation.side_effect = _sign
    node._loop = None
    node._running = True
    node.blockchain.get_height.return_value = 99
    node.blockchain.get_last_block.return_value = {"hash": "ff" * 32, "height": 99}
    node._on_consensus_attestation(
        {"validator": our, "block_hash": DIGEST, "slot": 7}
    )
    assert signed["block"]["number"] == 7
    assert signed["block"]["hash"] == DIGEST


@pytest.mark.asyncio
async def test_unsolicited_blocks_struck():
    node = _node()
    peer = PeerConnection(_FakeReader(), _FakeWriter())
    peer.peer_id = "blk"
    node.peers[peer.peer_id] = peer
    await node._handle_message(peer, {"type": MSG_BLOCKS, "data": []})
    assert node._unsolicited_block_rejects_total >= 1
    await node._handle_message(peer, {"type": MSG_BLOCK, "data": None})
    assert node._unsolicited_block_rejects_total >= 2
    st = node.get_p2p_security_status()
    assert st.get("native_block_solicit_only") is True
    assert st.get("native_attestation_local_head") is True
