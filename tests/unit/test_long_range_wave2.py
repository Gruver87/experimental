"""ADR 0017 wave-2: checkpoint + AncestryWindow bridge."""

from __future__ import annotations

from consensus.long_range import (
    CheckpointCertificate,
    WeakSubjectivityService,
    evaluate_with_window,
    shares_ancestor_with_anchor,
)
from consensus.tip_safety.ancestry_window import AncestryWindow
from consensus.tip_safety.types import BlockRef


def _chain() -> tuple[AncestryWindow, str, str, str]:
    g, mid, anchor, child = "11" * 32, "22" * 32, "aa" * 32, "bb" * 32
    w = AncestryWindow(max_blocks=32)
    w.record(BlockRef(height=0, block_hash=g, parent_hash=""))
    w.record(BlockRef(height=1, block_hash=mid, parent_hash=g))
    w.record(BlockRef(height=2, block_hash=anchor, parent_hash=mid))
    w.record(BlockRef(height=3, block_hash=child, parent_hash=anchor))
    return w, anchor, child, mid


def test_checkpoint_digest_stable() -> None:
    c = CheckpointCertificate.issue(height=2, block_hash="aa" * 32, issuer="x")
    assert c.verify_digest()
    assert len(c.digest) == 64


def test_checkpoint_json_roundtrip() -> None:
    c = CheckpointCertificate.issue(height=2, block_hash="aa" * 32, issuer="x", epoch=7)
    again = CheckpointCertificate.from_json(c.to_json())
    assert again.digest == c.digest
    assert again.anchor.epoch == 7
    assert again.verify_digest()


def test_checkpoint_from_dict_digest_mismatch() -> None:
    import pytest

    c = CheckpointCertificate.issue(height=1, block_hash="bb" * 32)
    bad = dict(c.to_dict())
    bad["digest"] = "00" * 32
    with pytest.raises(ValueError, match="digest mismatch"):
        CheckpointCertificate.from_dict(bad)


def test_shares_ancestor_walk() -> None:
    w, anchor, child, mid = _chain()
    assert shares_ancestor_with_anchor(w, candidate_hash=child, anchor_hash=anchor)
    assert not shares_ancestor_with_anchor(w, candidate_hash=mid, anchor_hash=anchor)


def test_evaluate_with_window_accept_child() -> None:
    w, anchor, child, _mid = _chain()
    svc = WeakSubjectivityService()
    svc.set_anchor(CheckpointCertificate.issue(height=2, block_hash=anchor).anchor)
    d = evaluate_with_window(svc, w, candidate_hash=child, candidate_height=3)
    assert d.accept is True


def test_evaluate_with_window_refuse_unlinked() -> None:
    w, anchor, _child, _mid = _chain()
    stale = "cc" * 32
    w.record(BlockRef(height=3, block_hash=stale, parent_hash="dd" * 32))
    svc = WeakSubjectivityService()
    svc.set_anchor(CheckpointCertificate.issue(height=2, block_hash=anchor).anchor)
    d = evaluate_with_window(svc, w, candidate_hash=stale, candidate_height=3)
    assert d.accept is False
    assert d.reason == "long_range_fork_below_anchor"
