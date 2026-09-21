"""Unit tests for prod-mesh tip alignment helpers (BehindOpen tip+1 guard)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_p2p_ci import _mesh_tips_aligned  # noqa: E402


def test_mesh_tips_aligned_equal_tip() -> None:
    assert _mesh_tips_aligned(
        [7, 7, 7],
        ["abcd", "abcd", "abcd"],
        ["root1", "root1", "root1"],
        max_spread=0,
    )


def test_mesh_tips_aligned_rejects_tip_plus_one_trap() -> None:
    # Classic industrial stall: leader at N+1, followers at N, divergent roots.
    assert not _mesh_tips_aligned(
        [7, 6, 6],
        ["aaaa", "bbbb", "bbbb"],
        ["0cd7", "48be", "48be"],
        max_spread=0,
    )


def test_mesh_tips_aligned_allows_spread_one_when_configured() -> None:
    assert _mesh_tips_aligned(
        [7, 6, 6],
        ["aaaa", "aaaa", "aaaa"],
        ["root", "root", "root"],
        max_spread=1,
    )
