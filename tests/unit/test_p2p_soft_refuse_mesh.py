#!/usr/bin/env python3
"""Mesh must not ban peers for soft-refuse solicit races / disabled register."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_soft_refuse_does_not_ban():
    from network.p2p_node import P2PNode

    cfg = SimpleNamespace(
        deployment_mode="prod",
        require_native_crypto=True,
        p2p_port=5000,
        p2p_rate_limit_strikes=5,
        p2p_ban_seconds=300,
    )
    node = object.__new__(P2PNode)
    node.config = cfg
    node._soft_refuse_total = 0
    pm = MagicMock()
    pm.strike.return_value = True
    node.peer_manager = pm
    peer = SimpleNamespace(peer_id="docker-prod-mesh-1")

    banned = node._strike_peer_sync(peer, "validator_register_disabled")
    assert banned is False
    pm.strike.assert_not_called()
    assert node._soft_refuse_total == 1

    for reason in (
        "unsolicited_mempool",
        "unsolicited_block",
        "unsolicited_blocks",
        "unsolicited_peers",
        "tip_duplicate",
        "attestation_local_height_mismatch",
        "rate_limit_exceeded",
        "exempt_rate_exceeded",
        "bandwidth_exceeded",
        "rate_limited",
        "tip_unknown_parent",
        "handshake_head_height_mismatch",
        "status_head_height_mismatch",
        "recv_error",
        "bad_state_root_response_local_root",
        "bad_state_root_response_head",
    ):
        assert node._strike_peer_sync(peer, reason) is False
    pm.strike.assert_not_called()
    assert node._soft_refuse_total == 17


def test_announce_validator_noop_in_prod():
    from network.p2p_node import P2PNode

    node = object.__new__(P2PNode)
    node.config = SimpleNamespace(
        deployment_mode="prod",
        require_native_crypto=True,
        p2p_port=5000,
    )
    node._loop = object()
    node._running = True
    node._relay_validator_register = MagicMock()
    node.announce_validator("0xabc", 1.0)
    # no coroutine scheduled — method returns before run_coroutine_threadsafe
