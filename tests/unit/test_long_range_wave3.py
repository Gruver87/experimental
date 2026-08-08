"""ADR 0017 wave-3: tip-import WS gate + evaluate_block_ref."""

from __future__ import annotations

from consensus.long_range import CheckpointCertificate, WeakSubjectivityService
from consensus.long_range.ancestry_bridge import evaluate_block_ref
from consensus.tip_safety import TipSafetyService
from consensus.tip_safety.ancestry_window import AncestryWindow
from consensus.tip_safety.tip_state import TipState
from consensus.tip_safety.types import ApplyOutcome, BlockRef


def _seed() -> tuple[AncestryWindow, BlockRef, BlockRef]:
    g = BlockRef(height=0, block_hash="11" * 32, parent_hash="")
    mid = BlockRef(height=1, block_hash="22" * 32, parent_hash=g.block_hash)
    anchor = BlockRef(height=2, block_hash="aa" * 32, parent_hash=mid.block_hash)
    w = AncestryWindow(max_blocks=32)
    for b in (g, mid, anchor):
        w.record(b)
    return w, mid, anchor


def test_evaluate_block_ref_unrecorded_child() -> None:
    w, _mid, anchor = _seed()
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=anchor.block_hash)
    svc = WeakSubjectivityService()
    svc.set_anchor(CheckpointCertificate.issue(height=2, block_hash=anchor.block_hash).anchor)
    d = evaluate_block_ref(svc, w, child)
    assert d.accept is True


def test_tip_safety_ws_gate_refuses_below_anchor() -> None:
    w, _mid, tip_block = _seed()
    ws = WeakSubjectivityService()
    # Anchor ahead of live tip → any extend is below WS (classic refuse).
    ws.set_anchor(
        CheckpointCertificate.issue(height=10, block_hash="ff" * 32).anchor
    )
    tip = TipSafetyService(TipState(head=tip_block), ancestry=w, ws_service=ws)
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=tip_block.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_below_ws_anchor"


def test_tip_safety_no_anchor_does_not_block() -> None:
    w, _mid, anchor = _seed()
    tip = TipSafetyService(
        TipState(head=anchor),
        ancestry=w,
        ws_service=WeakSubjectivityService(),
    )
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=anchor.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.accepted is True
