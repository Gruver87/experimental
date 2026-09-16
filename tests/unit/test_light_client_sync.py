#!/usr/bin/env python3
"""Light client local chain header bootstrap."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from core.blockchain import Block
from light.light_client import LightClient


class _FakeChain:
    def __init__(self, blocks):
        self._blocks = {int(b["height"]): b for b in blocks}

    def get_height(self):
        return max(self._blocks)

    def get_block(self, height):
        return self._blocks.get(int(height))


def test_sync_from_blockchain_loads_all_local_headers():
    blocks = []
    prev = "0" * 64
    for h in range(3):
        block = Block(
            height=h,
            parent_hash=prev,
            miner="0x" + "1" * 40,
            transactions=[],
            timestamp=1_700_000_000 + h,
            state_root="a" * 64,
        )
        data = block.to_dict()
        blocks.append(data)
        prev = data["hash"]

    lc = LightClient()
    added = lc.sync_from_blockchain(_FakeChain(blocks))
    assert added == 3
    assert lc.get_header_count() == 3
    assert lc.get_chain_height() == 2


def test_derive_p2p_sync_status_helpers():
    from api.http import _derive_p2p_sync_status

    assert _derive_p2p_sync_status(
        peer_count=0, peer_gap=0, state_consistent=True,
        deployment_mode="dev", mesh_min_peers=2,
    ) == "solo"
    assert _derive_p2p_sync_status(
        peer_count=1, peer_gap=91, state_consistent=False,
        deployment_mode="dev", mesh_min_peers=2,
    ) == "single_peer_stale"
    assert _derive_p2p_sync_status(
        peer_count=3, peer_gap=0, state_consistent=True,
        deployment_mode="prod", mesh_min_peers=2,
    ) == "aligned"
    # tip-v2 mine window: gap 1–2 + consistent → tip_skew, not inconsistent
    assert _derive_p2p_sync_status(
        peer_count=2, peer_gap=1, state_consistent=True,
        deployment_mode="prod", mesh_min_peers=2,
    ) == "tip_skew"
    assert _derive_p2p_sync_status(
        peer_count=2, peer_gap=2, state_consistent=True,
        deployment_mode="prod", mesh_min_peers=2,
    ) == "tip_skew"
    assert _derive_p2p_sync_status(
        peer_count=2, peer_gap=5, state_consistent=True,
        deployment_mode="prod", mesh_min_peers=2,
    ) == "tip_lagging"
    # Real fork / root mismatch keeps inconsistent
    assert _derive_p2p_sync_status(
        peer_count=2, peer_gap=0, state_consistent=False,
        deployment_mode="prod", mesh_min_peers=2,
    ) == "inconsistent"
    assert _derive_p2p_sync_status(
        peer_count=2, peer_gap=1, state_consistent=False,
        deployment_mode="prod", mesh_min_peers=2,
    ) == "inconsistent"


def test_bridge_disabled_reason_mainnet_v1(monkeypatch):
    from types import SimpleNamespace
    from api.http import _bridge_disabled_reason

    monkeypatch.delenv("BRIDGE_ENABLED", raising=False)
    cfg = SimpleNamespace(bridge_enabled=False, chain_id=778888, deployment_mode="prod")
    reason = _bridge_disabled_reason(cfg)
    assert "mainnet-v1" in reason

    cfg_on = SimpleNamespace(bridge_enabled=True, chain_id=778888, deployment_mode="prod")
    assert _bridge_disabled_reason(cfg_on) == ""

    monkeypatch.setenv("BRIDGE_ENABLED", "false")
    assert "BRIDGE_ENABLED=false" in _bridge_disabled_reason(cfg)
