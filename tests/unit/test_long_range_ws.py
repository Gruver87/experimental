"""ADR 0017 weak-subjectivity / Long-Range research unit tests."""

from __future__ import annotations

from consensus.long_range import WeakSubjectivityService
from consensus.long_range.ports import WeakSubjectivityAnchor


def test_refuse_below_anchor() -> None:
    svc = WeakSubjectivityService()
    svc.set_anchor(WeakSubjectivityAnchor(height=10, block_hash="aa" * 32))
    d = svc.evaluate_stale_fork(
        candidate_height=5,
        candidate_hash="bb" * 32,
        shares_ancestor_with_anchor=True,
    )
    assert d.accept is False
    assert d.reason == "below_ws_anchor"


def test_refuse_long_range_fork() -> None:
    svc = WeakSubjectivityService()
    svc.set_anchor(WeakSubjectivityAnchor(height=10, block_hash="aa" * 32))
    d = svc.evaluate_stale_fork(
        candidate_height=20,
        candidate_hash="cc" * 32,
        shares_ancestor_with_anchor=False,
    )
    assert d.accept is False
    assert d.reason == "long_range_fork_below_anchor"


def test_accept_descendant() -> None:
    svc = WeakSubjectivityService()
    svc.set_anchor(WeakSubjectivityAnchor(height=10, block_hash="aa" * 32))
    d = svc.evaluate_stale_fork(
        candidate_height=20,
        candidate_hash="dd" * 32,
        shares_ancestor_with_anchor=True,
    )
    assert d.accept is True
    assert d.reason == "descendant_of_ws_anchor"


def test_no_anchor_fail_closed() -> None:
    svc = WeakSubjectivityService()
    d = svc.evaluate_stale_fork(
        candidate_height=1,
        candidate_hash="ee" * 32,
        shares_ancestor_with_anchor=True,
    )
    assert d.accept is False
    assert d.reason == "no_anchor"
