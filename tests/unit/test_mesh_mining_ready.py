#!/usr/bin/env python3
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from runtime.mesh_mining import mesh_ready_for_mining


def test_mesh_ready_requires_connections():
    assert not mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=1,
        wire_roots=[],
        local_height=1,
        local_root="aa" * 32,
    )


def test_mesh_ready_partial_wire_when_consistent():
    root = "ab" * 32
    assert mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[
            {"height": 1, "state_root": root},
            {"height": 1, "state_root": root},
        ],
        local_height=1,
        local_root=root,
        state_consistent=True,
    )


def test_mesh_ready_rejects_root_mismatch():
    assert not mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[{"height": 1, "state_root": "cc" * 32}],
        local_height=1,
        local_root="ab" * 32,
        state_consistent=True,
        peer_heights=[1, 1],
    )


def test_mesh_ready_ignores_stale_wire_height():
    """Stale wire h=1 must not block hub at h=2 when STATUS peers are aligned + consistent."""
    root = "ab" * 32
    assert mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[{"height": 1, "state_root": root}],
        local_height=2,
        local_root=root,
        state_consistent=True,
        peer_heights=[2, 2],
    )


def test_mesh_ready_empty_wire_not_consistent():
    assert not mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[],
        local_height=1,
        local_root="ab" * 32,
        state_consistent=False,
    )


def test_mesh_ready_peer_heights_require_state_consistent():
    """STATUS height alignment alone must not forge while state is inconsistent."""
    assert not mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[],
        local_height=2,
        local_root="ab" * 32,
        state_consistent=False,
        peer_heights=[2, 2],
    )


def test_mesh_ready_wire_soft_fail_allows_unanimous_status():
    """Wire solicit timeout + unanimous STATUS tip may forge (LR tip plateau heal)."""
    assert mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[],
        local_height=2,
        local_root="ab" * 32,
        state_consistent=False,
        peer_heights=[2, 2],
        wire_soft_fail=True,
    )


def test_mesh_ready_wire_soft_fail_still_refuses_behind_peer():
    assert not mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[],
        local_height=10,
        local_root="ab" * 32,
        state_consistent=False,
        peer_heights=[10, 8],
        wire_soft_fail=True,
    )


def test_mesh_ready_wire_soft_fail_refuses_mismatch_wire():
    assert not mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[{"height": 2, "state_root": "cc" * 32}],
        local_height=2,
        local_root="ab" * 32,
        state_consistent=False,
        peer_heights=[2, 2],
        wire_soft_fail=True,
    )


def test_mesh_ready_peer_heights_when_consistent():
    """Hub may forge when STATUS heights align and sync consistency is already True."""
    assert mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[],
        local_height=2,
        local_root="ab" * 32,
        state_consistent=True,
        peer_heights=[2, 2],
    )


def test_mesh_ready_refuses_when_any_peer_behind():
    """Do not forge while a connected follower reports lower STATUS height."""
    assert not mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[],
        local_height=10,
        local_root="ab" * 32,
        state_consistent=True,
        peer_heights=[10, 8],
    )


def test_lab_json_requires_full_mesh_before_mine():
    """LR lab miner must require both peers (lr48fail1 solo-window amplifier)."""
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(ROOT) / "node.long_range.lab.json").read_text(encoding="utf-8")
    )
    assert int(raw.get("mesh_min_peers_before_mine") or 0) >= 2
    assert int(raw.get("testnet_expected_peers") or 0) >= 2


def test_mesh_ready_stale_peer_heights_wire_proves_alignment():
    """Stale P2P STATUS cache must not block when wire roots prove mesh alignment."""
    root = "ab" * 32
    assert mesh_ready_for_mining(
        min_mesh_peers=2,
        connected_peers=2,
        wire_roots=[
            {"height": 2, "state_root": root},
            {"height": 2, "state_root": root},
        ],
        local_height=2,
        local_root=root,
        state_consistent=False,
        peer_heights=[17, 17],
    )
