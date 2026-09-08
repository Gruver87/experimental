"""ADR 0017 wave-3: tip-import WS gate + evaluate_block_ref."""

from __future__ import annotations

from consensus.long_range import CheckpointCertificate, WeakSubjectivityService, bind_persisted_ws
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


def test_evaluate_block_ref_same_height_wrong_hash_refuses() -> None:
    """parent_hash = anchor at the checkpoint height is not a descendant."""
    w, _mid, anchor = _seed()
    sibling = BlockRef(
        height=anchor.height,
        block_hash="ee" * 32,
        parent_hash=anchor.block_hash,
    )
    svc = WeakSubjectivityService()
    svc.set_anchor(CheckpointCertificate.issue(height=2, block_hash=anchor.block_hash).anchor)
    d = evaluate_block_ref(svc, w, sibling)
    assert d.accept is False
    assert d.reason == "anchor_hash_mismatch"


def test_tip_safety_ws_gate_refuses_competing_hash_at_anchor() -> None:
    """Same-height reorg at the checkpoint must not replace the pinned hash."""
    w, mid, anchor = _seed()
    ws = WeakSubjectivityService()
    ws.set_anchor(
        CheckpointCertificate.issue(height=2, block_hash=anchor.block_hash).anchor
    )
    tip = TipSafetyService(TipState(head=anchor), ancestry=w, ws_service=ws)
    rival = BlockRef(height=2, block_hash="ee" * 32, parent_hash=mid.block_hash)
    d = tip.evaluate_candidate(rival)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_anchor_hash_mismatch"


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


def test_tip_safety_no_anchor_refuses() -> None:
    w, _mid, anchor = _seed()
    tip = TipSafetyService(
        TipState(head=anchor),
        ancestry=w,
        ws_service=WeakSubjectivityService(),
    )
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=anchor.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_no_anchor"


def test_tip_safety_without_ws_still_accepts() -> None:
    w, _mid, anchor = _seed()
    tip = TipSafetyService(TipState(head=anchor), ancestry=w)
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=anchor.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.accepted is True


def test_tip_safety_restart_from_disk_refuses_below_anchor(tmp_path) -> None:
    w, _mid, tip_block = _seed()
    path = tmp_path / "ws.json"
    store_ws = bind_persisted_ws(
        path=path,
        env_height="10",
        env_hash="ff" * 32,
    )
    assert store_ws.get_anchor() is not None
    restarted = bind_persisted_ws(path=path)
    tip = TipSafetyService(
        TipState(head=tip_block), ancestry=w, ws_service=restarted
    )
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=tip_block.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_below_ws_anchor"


def test_optional_ws_flag_off_detached(monkeypatch) -> None:
    from consensus.tip_safety.shadow import _optional_ws_service

    monkeypatch.setenv("FEATURE_LONG_RANGE", "false")
    assert _optional_ws_service() is None


def test_optional_ws_flag_on_empty_attaches_and_refuses(monkeypatch) -> None:
    from consensus.tip_safety.shadow import _optional_ws_service

    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.delenv("ABS_WS_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("ABS_WS_ANCHOR_HEIGHT", raising=False)
    monkeypatch.delenv("ABS_WS_ANCHOR_HASH", raising=False)
    svc = _optional_ws_service(None)
    assert svc is not None
    assert svc.get_anchor() is None
    w, _mid, anchor = _seed()
    tip = TipSafetyService(TipState(head=anchor), ancestry=w, ws_service=svc)
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=anchor.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_no_anchor"


def test_optional_ws_restart_from_checkpoint_path(monkeypatch, tmp_path) -> None:
    from consensus.tip_safety.shadow import _optional_ws_service

    path = tmp_path / "ws.json"
    bind_persisted_ws(path=path, env_height="10", env_hash="ff" * 32)
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.delenv("ABS_WS_ANCHOR_HEIGHT", raising=False)
    monkeypatch.delenv("ABS_WS_ANCHOR_HASH", raising=False)
    svc = _optional_ws_service()
    assert svc is not None
    assert svc.get_anchor() is not None
    assert svc.get_anchor().height == 10
    w, _mid, tip_block = _seed()
    tip = TipSafetyService(TipState(head=tip_block), ancestry=w, ws_service=svc)
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=tip_block.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_below_ws_anchor"


def test_optional_ws_missing_digest_file_fail_closed_empty(monkeypatch, tmp_path) -> None:
    """Corrupt persist (no digest) must not drop the WS gate or load a lowered height."""
    import json

    from consensus.tip_safety.shadow import _optional_ws_service

    path = tmp_path / "ws.json"
    path.write_text(
        json.dumps(
            {
                "max_history": 8,
                "items": [
                    {
                        "height": 1,
                        "block_hash": "aa" * 32,
                        "epoch": 0,
                        "issuer": "lab",
                        "issued_at_height": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.delenv("ABS_WS_ANCHOR_HEIGHT", raising=False)
    monkeypatch.delenv("ABS_WS_ANCHOR_HASH", raising=False)
    svc = _optional_ws_service()
    assert svc is not None
    assert svc.get_anchor() is None
    w, _mid, anchor = _seed()
    tip = TipSafetyService(TipState(head=anchor), ancestry=w, ws_service=svc)
    child = BlockRef(height=3, block_hash="bb" * 32, parent_hash=anchor.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_no_anchor"


def test_optional_ws_empty_items_file_ignores_leftover_env(monkeypatch, tmp_path) -> None:
    """Existing persist with empty items + leftover env must not lower the anchor."""
    import json

    from consensus.tip_safety.shadow import _optional_ws_service

    path = tmp_path / "ws.json"
    path.write_text(json.dumps({"max_history": 8, "items": []}), encoding="utf-8")
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.setenv("ABS_WS_ANCHOR_HEIGHT", "1")
    monkeypatch.setenv("ABS_WS_ANCHOR_HASH", "bb" * 32)
    svc = _optional_ws_service()
    assert svc is not None
    assert svc.get_anchor() is None
    w, _mid, anchor = _seed()
    tip = TipSafetyService(TipState(head=anchor), ancestry=w, ws_service=svc)
    child = BlockRef(height=3, block_hash="cc" * 32, parent_hash=anchor.block_hash)
    d = tip.evaluate_candidate(child)
    assert d.outcome == ApplyOutcome.REJECT
    assert d.reason_code == "ws_no_anchor"


class _FakeChain:
    """Minimal chain for ancestry backfill + shadow sync tests."""

    def __init__(self, blocks: list[dict]) -> None:
        self._by_h = {int(b["height"]): b for b in blocks}
        self._by_hash = {str(b["hash"]): b for b in blocks}
        self.GENESIS_HASH = "00" * 32

    def get_height(self) -> int:
        return max(self._by_h)

    def get_block(self, height: int):
        return self._by_h.get(int(height))

    def get_block_by_hash(self, block_hash: str):
        return self._by_hash.get(str(block_hash))


def _lab_stall_chain() -> tuple[_FakeChain, str, BlockRef]:
    """Reproduce LR lab stall: tip at 15, WS anchor at 13, child 16 contiguous."""
    blocks = []
    parent = "00" * 32
    for h in range(0, 16):
        bh = f"{h:02x}" * 32
        blocks.append({"height": h, "hash": bh, "parent_hash": parent if h else ""})
        parent = bh
    chain = _FakeChain(blocks)
    anchor_hash = blocks[13]["hash"]
    tip15 = BlockRef(
        height=15,
        block_hash=blocks[15]["hash"],
        parent_hash=blocks[14]["hash"],
    )
    return chain, anchor_hash, tip15


def test_backfill_ancestry_reaches_ws_anchor() -> None:
    from consensus.tip_safety.shadow import backfill_ancestry_from_chain

    chain, anchor_hash, tip15 = _lab_stall_chain()
    w = AncestryWindow(max_blocks=64)
    w.record(tip15)  # tip-only, like TipSafetyService init
    n = backfill_ancestry_from_chain(w, chain, stop_hash=anchor_hash)
    assert n >= 3
    assert w.contains(anchor_hash)
    child = BlockRef(
        height=16,
        block_hash="ff" * 32,
        parent_hash=tip15.block_hash,
    )
    ws = WeakSubjectivityService()
    ws.set_anchor(
        CheckpointCertificate.issue(height=13, block_hash=anchor_hash).anchor
    )
    d = evaluate_block_ref(ws, w, child)
    assert d.accept is True
    assert d.reason == "descendant_of_ws_anchor"


def test_shadow_sync_backfill_allows_tip_plus_one(monkeypatch, tmp_path) -> None:
    """After sync_from_chain (tip-only seed), contiguous tip+1 must pass WS."""
    from consensus.tip_safety.shadow import TipSafetyShadowObserver

    chain, anchor_hash, _tip15 = _lab_stall_chain()
    path = tmp_path / "ws.json"
    bind_persisted_ws(path=path, env_height="13", env_hash=anchor_hash)
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.delenv("ABS_WS_ANCHOR_HEIGHT", raising=False)
    monkeypatch.delenv("ABS_WS_ANCHOR_HASH", raising=False)

    class _Cfg:
        feature_long_range = True

    obs = TipSafetyShadowObserver(enabled=True, enforce=True, config=_Cfg())
    assert obs.sync_from_chain(chain) is True
    child = {
        "height": 16,
        "hash": "ff" * 32,
        "parent_hash": chain.get_block(15)["hash"],
    }
    d = obs.observe_before_import(child, chain)
    assert d is not None
    assert d.accepted is True


def test_contiguous_tip_plus_one_survives_lru_eviction() -> None:
    """Past-anchor tip+1 must accept even when window lost tip→anchor path."""
    chain, anchor_hash, tip15 = _lab_stall_chain()
    # Tiny window: only tip survives — simulates 48h LRU past 256 blocks.
    w = AncestryWindow(max_blocks=2)
    w.record(tip15)
    assert not w.contains(anchor_hash)
    child = BlockRef(height=16, block_hash="ff" * 32, parent_hash=tip15.block_hash)
    ws = WeakSubjectivityService()
    ws.set_anchor(
        CheckpointCertificate.issue(height=13, block_hash=anchor_hash).anchor
    )
    d = evaluate_block_ref(ws, w, child, local_tip=tip15)
    assert d.accept is True
    assert d.reason == "descendant_of_ws_anchor"
