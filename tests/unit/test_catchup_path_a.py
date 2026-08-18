#!/usr/bin/env python3
"""Unit tests for CatchUpPathAService (ADR 0004 Step A)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sync.catchup import (
    CatchUpConfig,
    CatchUpPathAService,
    CatchUpPeerView,
    CatchUpStatus,
)
from tests.unit.fakes.fake_catchup_io import FakeCatchUpIO


def _blk(h: int, parent: str, digest: str) -> dict:
    return {
        "height": h,
        "parent_hash": parent,
        "hash": digest,
        "block_hash": digest,
    }


def _svc(io: FakeCatchUpIO) -> CatchUpPathAService:
    return CatchUpPathAService(chain=io, fetch=io, probe=io, side=io)


def test_refuse_catch_up_no_head() -> None:
    io = FakeCatchUpIO(height=1, head="aa" * 32)
    peer = CatchUpPeerView(peer_id="p1", height=5, head_hash="")
    out = _svc(io).run_ahead(peer, CatchUpConfig(require_head=True))
    assert out.status is CatchUpStatus.REFUSED
    assert out.reason_code == "catch_up_no_head"
    assert "catch_up_no_head" in io.refuses


def test_tip_probe_refuse_short_circuit() -> None:
    io = FakeCatchUpIO(
        height=2,
        head="aa" * 32,
        tip_probe_refuse="catch_up_tip_probe_failed",
    )
    peer = CatchUpPeerView(peer_id="p1", height=10, head_hash="bb" * 32)
    out = _svc(io).run_ahead(peer)
    assert out.status is CatchUpStatus.REFUSED
    assert out.reason_code == "catch_up_tip_probe_failed"
    assert io.fetch_calls == []


def test_peer_head_probe_refuse() -> None:
    io = FakeCatchUpIO(
        height=2,
        head="aa" * 32,
        peer_head_probe_refuse="catch_up_peer_head_probe_failed",
    )
    peer = CatchUpPeerView(peer_id="p1", height=10, head_hash="bb" * 32)
    out = _svc(io).run_ahead(peer)
    assert out.status is CatchUpStatus.REFUSED
    assert out.reason_code == "catch_up_peer_head_probe_failed"


def test_successful_multi_batch_import() -> None:
    tip = "aa" * 32
    b3 = _blk(3, tip, "b3" * 32)
    b4 = _blk(4, "b3" * 32, "b4" * 32)
    b5 = _blk(5, "b4" * 32, "b5" * 32)
    io = FakeCatchUpIO(
        height=2,
        head=tip,
        blocks_by_height={2: _blk(2, "00" * 32, tip)},
        batch_size=2,
        fetch_plan=[[b3, b4], [b5]],
    )
    peer = CatchUpPeerView(peer_id="peer-a", height=5, head_hash="b5" * 32)
    out = _svc(io).run_ahead(peer, CatchUpConfig(batch_size=2))
    assert out.status is CatchUpStatus.COMPLETE
    assert out.reached_target is True
    assert out.imported == 3
    assert io.height() == 5
    assert [b["height"] for b in io.imported] == [3, 4, 5]


def test_height_continuity_refuse_aborts_batch() -> None:
    tip = "aa" * 32
    # Body claims height 5 while cursor expects 3.
    bad = _blk(5, tip, "xx" * 32)
    io = FakeCatchUpIO(
        height=2,
        head=tip,
        blocks_by_height={2: _blk(2, "00" * 32, tip)},
        fetch_plan=[[bad]],
    )
    peer = CatchUpPeerView(peer_id="p1", height=5, head_hash="ff" * 32)
    out = _svc(io).run_ahead(peer)
    assert out.status is CatchUpStatus.INCOMPLETE
    assert "catch_up_height_continuity_mismatch" in io.refuses
    assert io.imported == []


def test_import_fail_extend_does_not_reorg() -> None:
    """Parent==tip is a failed extend, not a fork. Do not roll back."""
    tip2 = "aa" * 32
    h4 = "h4" * 32
    b5 = _blk(5, h4, "b5" * 32)
    io = FakeCatchUpIO(
        height=4,
        head=h4,
        blocks_by_height={
            2: _blk(2, "00" * 32, tip2),
            3: _blk(3, tip2, "h3" * 32),
            4: _blk(4, "h3" * 32, h4),
        },
        fail_import_heights=[5],
        ancestors={h4: 2},
        fetch_plan=[[b5], None],
    )
    peer = CatchUpPeerView(peer_id="p1", height=5, head_hash="b5" * 32)
    out = _svc(io).run_ahead(peer)
    assert "Fork resolved" not in " ".join(io.progress)
    assert io.height() == 4
    assert out.status in (CatchUpStatus.STALLED, CatchUpStatus.INCOMPLETE)


def test_duplicate_canonical_import_fail_does_not_reorg() -> None:
    """Concurrent PathA of an already-canonical #340 must not reorg to #339."""
    h339 = "a9" * 32
    h340 = "b0" * 32
    io = FakeCatchUpIO(
        height=340,
        head=h340,
        blocks_by_height={
            339: _blk(339, "a8" * 32, h339),
            340: _blk(340, h339, h340),
        },
        fail_import_heights=[340],
    )
    peer = CatchUpPeerView(peer_id="p1", height=342, head_hash="zz" * 32)
    cfg = CatchUpConfig(contiguous_parent_bind=False, tip_head_bind=False)
    out = _svc(io)._import_one(
        peer=peer,
        cfg=cfg,
        block_data=_blk(340, h339, h340),
        expected_height=340,
    )
    assert out == "fail"
    assert io.height() == 340
    assert "skip reorg" in " ".join(io.progress).lower() or "Duplicate" in " ".join(
        io.progress
    )


def test_competing_child_import_fail_does_reorg() -> None:
    """Different hash at the same height whose parent is below tip is a real fork."""
    h339 = "a9" * 32
    local340 = "b0" * 32
    peer340 = "c0" * 32
    io = FakeCatchUpIO(
        height=340,
        head=local340,
        blocks_by_height={
            339: _blk(339, "a8" * 32, h339),
            340: _blk(340, h339, local340),
        },
        fail_import_heights=[340],
    )
    peer = CatchUpPeerView(peer_id="p1", height=342, head_hash="zz" * 32)
    cfg = CatchUpConfig(contiguous_parent_bind=False, tip_head_bind=False)
    out = _svc(io)._import_one(
        peer=peer,
        cfg=cfg,
        block_data=_blk(340, h339, peer340),
        expected_height=340,
    )
    assert out == "reorg"
    assert io.height() == 339
    assert "Fork resolved" in " ".join(io.progress)


def test_stall_on_none_fetch() -> None:
    tip = "aa" * 32
    io = FakeCatchUpIO(
        height=1,
        head=tip,
        blocks_by_height={1: _blk(1, "00" * 32, tip)},
        fetch_plan=[None],
    )
    peer = CatchUpPeerView(peer_id="p1", height=4, head_hash="zz" * 32)
    out = _svc(io).run_ahead(peer)
    assert out.status is CatchUpStatus.STALLED
    assert out.reason_code == "fetch_stall"


def test_tip_head_mismatch_after_height_catch_up() -> None:
    tip = "aa" * 32
    b2 = _blk(2, tip, "b2" * 32)
    io = FakeCatchUpIO(
        height=1,
        head=tip,
        blocks_by_height={1: _blk(1, "00" * 32, tip)},
        fetch_plan=[[b2]],
    )
    # Peer claims head zz… but body hash is b2…
    peer = CatchUpPeerView(peer_id="p1", height=2, head_hash="zz" * 32)
    out = _svc(io).run_ahead(peer)
    # Import of height==peer.height refuses tip-head mismatch at import time.
    assert "catch_up_tip_head_mismatch" in io.refuses
    assert out.status is CatchUpStatus.INCOMPLETE


def test_skipped_when_not_ahead() -> None:
    io = FakeCatchUpIO(height=5, head="aa" * 32)
    peer = CatchUpPeerView(peer_id="p1", height=5, head_hash="aa" * 32)
    out = _svc(io).run_ahead(peer)
    assert out.status is CatchUpStatus.SKIPPED


def test_ahead_refuse_preserves_genesis_height_zero() -> None:
    from sync.catchup.policy import CatchUpPolicy

    p = CatchUpPolicy()
    reason = p.ahead_refuse_reason(
        local_height=-1,
        peer_height=5,
        peer_head="g0" * 32,
        local_block_for_head={"height": 0, "hash": "g0" * 32},
        require_head=True,
    )
    assert reason == "catch_up_head_height_mismatch"


def test_needs_genesis_store_error_at_empty_tip_still_imports() -> None:
    """Store error at height 0 must not skip genesis as not_ahead."""
    genesis = _blk(0, "0" * 64, "g0" * 32)

    class _BoomIO(FakeCatchUpIO):
        def needs_genesis(self):
            raise RuntimeError("store down")

    io = _BoomIO(height=0, head="", fetch_plan=[[genesis]])
    peer = CatchUpPeerView(peer_id="leader", height=0, head_hash="g0" * 32)
    out = _svc(io).run_ahead(peer, CatchUpConfig(batch_size=8, require_head=True))
    assert int(out.imported or 0) >= 1
    assert io.imported and int(io.imported[0]["height"]) == 0
    assert out.status is not CatchUpStatus.SKIPPED


def test_no_network_imports_in_path_a_domain() -> None:
    for rel in (
        "sync/catchup/path_a.py",
        "sync/catchup/types.py",
        "sync/ports.py",
    ):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "from network" not in src
        assert "import network" not in src
