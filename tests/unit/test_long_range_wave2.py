"""ADR 0017 wave-2: checkpoint + AncestryWindow bridge."""

from __future__ import annotations

from consensus.long_range import (
    CheckpointCertificate,
    CheckpointStore,
    WeakSubjectivityService,
    bind_persisted_ws,
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


def test_checkpoint_store_rotation() -> None:
    store = CheckpointStore(max_history=2)
    a = CheckpointCertificate.issue(height=1, block_hash="aa" * 32)
    b = CheckpointCertificate.issue(height=2, block_hash="bb" * 32)
    c = CheckpointCertificate.issue(height=3, block_hash="cc" * 32)
    store.push(a)
    store.push(b)
    store.push(c)
    assert len(store) == 2
    assert store.latest().digest == c.digest
    assert store.history()[0].digest == b.digest


def test_checkpoint_store_apply_latest() -> None:
    store = CheckpointStore()
    svc = WeakSubjectivityService()
    assert store.apply_latest(svc) is False
    store.push(CheckpointCertificate.issue(height=4, block_hash="dd" * 32))
    assert store.apply_latest(svc) is True
    assert svc.get_anchor() is not None
    assert svc.get_anchor().height == 4


def test_checkpoint_store_save_load(tmp_path) -> None:
    store = CheckpointStore(max_history=4)
    store.push(CheckpointCertificate.issue(height=1, block_hash="aa" * 32))
    store.push(CheckpointCertificate.issue(height=2, block_hash="bb" * 32))
    path = tmp_path / "ws.json"
    store.save(path)
    assert not path.with_name(path.name + ".tmp").exists()
    loaded = CheckpointStore.load(path)
    assert len(loaded) == 2
    assert loaded.latest().digest == store.latest().digest


def test_bind_persisted_ws_restart_loads_disk_not_env(tmp_path) -> None:
    path = tmp_path / "ws.json"
    store = CheckpointStore()
    store.push(CheckpointCertificate.issue(height=10, block_hash="aa" * 32))
    store.save(path)
    svc = bind_persisted_ws(
        path=path,
        env_height="1",
        env_hash="bb" * 32,
    )
    assert svc.get_anchor() is not None
    assert svc.get_anchor().height == 10
    assert svc.get_anchor().block_hash == "aa" * 32


def test_bind_persisted_ws_env_seeds_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "ws.json"
    first = bind_persisted_ws(
        path=path,
        env_height="7",
        env_hash="cc" * 32,
    )
    assert first.get_anchor() is not None
    assert first.get_anchor().height == 7
    assert path.is_file()
    restarted = bind_persisted_ws(path=path)
    assert restarted.get_anchor() is not None
    assert restarted.get_anchor().height == 7
    assert restarted.get_anchor().block_hash == "cc" * 32


def test_bind_persisted_ws_empty_store_is_no_anchor(tmp_path) -> None:
    path = tmp_path / "missing.json"
    svc = bind_persisted_ws(path=path)
    assert svc.get_anchor() is None
    d = svc.evaluate_stale_fork(
        candidate_height=1,
        candidate_hash="ee" * 32,
        shares_ancestor_with_anchor=True,
    )
    assert d.accept is False
    assert d.reason == "no_anchor"


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
