#!/usr/bin/env python3
"""Long-Range / weak-subjectivity lab (ADR 0017).

Wave-2: checkpoint certificate + AncestryWindow walk.
Wave-4: JSON export/import round-trip of the WS checkpoint.
Wave-5: TipSafetyService WS tip-import gate (below-anchor refuse).
Wave-6: CheckpointStore rotation (bounded history).
Wave-7: CheckpointStore.apply_latest → WeakSubjectivityService.
Wave-8: CheckpointStore save/load JSON persistence.
Wave-9: persist height+hash, restart bind, tip-import HARD REFUSE below
        and when the store is empty (no_anchor).
Wave-10: checkpoint height is unique (wrong hash → anchor_hash_mismatch).
Wave-11: persist JSON without digest is refused (cannot rewrite height/hash).
Wave-12: existing empty persist file must not re-seed from leftover env.

Usage:
  python scripts/long_range_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.long_range import (
    CheckpointCertificate,
    CheckpointStore,
    WeakSubjectivityService,
    bind_persisted_ws,
    evaluate_with_window,
)
from consensus.long_range.ancestry_bridge import evaluate_block_ref
from consensus.tip_safety import TipSafetyService
from consensus.tip_safety.ancestry_window import AncestryWindow
from consensus.tip_safety.tip_state import TipState
from consensus.tip_safety.types import ApplyOutcome, BlockRef


def main() -> int:
    # Build a short chain: genesis -> ... -> anchor@2 -> child@3
    g = "11" * 32
    a1 = "22" * 32
    anchor_h = "aa" * 32
    child = "bb" * 32
    stale = "cc" * 32

    window = AncestryWindow(max_blocks=64)
    window.record(BlockRef(height=0, block_hash=g, parent_hash=""))
    window.record(BlockRef(height=1, block_hash=a1, parent_hash=g))
    window.record(BlockRef(height=2, block_hash=anchor_h, parent_hash=a1))
    window.record(BlockRef(height=3, block_hash=child, parent_hash=anchor_h))
    # Stale fork at height 3 with different parent (not in window linked to anchor)
    window.record(BlockRef(height=3, block_hash=stale, parent_hash="dd" * 32))

    cert = CheckpointCertificate.issue(
        height=2, block_hash=anchor_h, epoch=1, issuer="lab-node1"
    )
    if not cert.verify_digest():
        print("FAIL: checkpoint digest")
        return 1

    svc = WeakSubjectivityService()
    svc.set_anchor(cert.anchor)

    ok = evaluate_with_window(svc, window, candidate_hash=child, candidate_height=3)
    bad = evaluate_with_window(svc, window, candidate_hash=stale, candidate_height=3)
    below = evaluate_with_window(svc, window, candidate_hash=a1, candidate_height=1)

    # Wave-4: export/import checkpoint (lab peer handoff simulation)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ws_checkpoint.json"
        path.write_text(cert.to_json(), encoding="utf-8")
        restored = CheckpointCertificate.from_json(path.read_text(encoding="utf-8"))
    if restored.digest != cert.digest or not restored.verify_digest():
        print("FAIL: checkpoint export/import")
        return 1
    svc2 = WeakSubjectivityService()
    svc2.set_anchor(restored.anchor)
    ok2 = evaluate_with_window(svc2, window, candidate_hash=child, candidate_height=3)
    if not ok2.accept:
        print("FAIL: restored anchor rejected valid child")
        return 1

    # Wave-5: TipSafety tip-import gate with WS ahead of tip
    tip_w = AncestryWindow(max_blocks=64)
    tip_block = BlockRef(height=2, block_hash=anchor_h, parent_hash=a1)
    tip_w.record(BlockRef(height=0, block_hash=g, parent_hash=""))
    tip_w.record(BlockRef(height=1, block_hash=a1, parent_hash=g))
    tip_w.record(tip_block)
    ws_ahead = WeakSubjectivityService()
    ws_ahead.set_anchor(
        CheckpointCertificate.issue(height=10, block_hash="ff" * 32).anchor
    )
    tip_svc = TipSafetyService(
        TipState(head=tip_block), ancestry=tip_w, ws_service=ws_ahead
    )
    tip_child = BlockRef(height=3, block_hash=child, parent_hash=anchor_h)
    tip_dec = tip_svc.evaluate_candidate(tip_child)
    if tip_dec.outcome != ApplyOutcome.REJECT or tip_dec.reason_code != "ws_below_ws_anchor":
        print(
            f"FAIL: tip gate expected ws_below_ws_anchor got "
            f"{tip_dec.outcome}/{tip_dec.reason_code}"
        )
        return 1

    # Wave-6: rotate checkpoints in a bounded store
    store = CheckpointStore(max_history=3)
    store.push(cert)
    later = CheckpointCertificate.issue(
        height=3, block_hash=child, epoch=2, issuer="lab-node1"
    )
    store.push(later)
    if store.latest() is None or store.latest().digest != later.digest:
        print("FAIL: checkpoint store latest")
        return 1
    if len(store.history()) != 2:
        print("FAIL: checkpoint store history")
        return 1
    svc3 = WeakSubjectivityService()
    if not store.apply_latest(svc3):
        print("FAIL: apply_latest")
        return 1
    if svc3.get_anchor() is None or svc3.get_anchor().height != 3:
        print("FAIL: apply_latest anchor height")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "ws_store.json"
        store.save(store_path)
        loaded = CheckpointStore.load(store_path)
    if len(loaded) != len(store) or loaded.latest().digest != store.latest().digest:
        print("FAIL: checkpoint store save/load")
        return 1

    # Wave-9: disk persist survives a new service; below-anchor is HARD REFUSE.
    with tempfile.TemporaryDirectory() as tmp:
        persist = Path(tmp) / "ws_restart.json"
        seeded = bind_persisted_ws(
            path=persist, env_height="10", env_hash="ff" * 32
        )
        if seeded.get_anchor() is None or seeded.get_anchor().height != 10:
            print("FAIL: env seed did not persist anchor")
            return 1
        restarted = bind_persisted_ws(path=persist)
        if restarted.get_anchor() is None or restarted.get_anchor().height != 10:
            print("FAIL: restart did not load persisted height+hash")
            return 1
        restart_tip = TipSafetyService(
            TipState(head=tip_block), ancestry=tip_w, ws_service=restarted
        )
        restart_dec = restart_tip.evaluate_candidate(tip_child)
        if (
            restart_dec.outcome != ApplyOutcome.REJECT
            or restart_dec.reason_code != "ws_below_ws_anchor"
        ):
            print(
                f"FAIL: restart tip gate expected ws_below_ws_anchor got "
                f"{restart_dec.outcome}/{restart_dec.reason_code}"
            )
            return 1
        empty = bind_persisted_ws(path=Path(tmp) / "missing.json")
        empty_tip = TipSafetyService(
            TipState(head=tip_block), ancestry=tip_w, ws_service=empty
        )
        empty_dec = empty_tip.evaluate_candidate(tip_child)
        if (
            empty_dec.outcome != ApplyOutcome.REJECT
            or empty_dec.reason_code != "ws_no_anchor"
        ):
            print(
                f"FAIL: empty store expected ws_no_anchor got "
                f"{empty_dec.outcome}/{empty_dec.reason_code}"
            )
            return 1

    # Wave-10: checkpoint height is unique (wrong hash is not a descendant).
    mismatch = svc.evaluate_stale_fork(
        candidate_height=2,
        candidate_hash="ee" * 32,
        shares_ancestor_with_anchor=True,
    )
    if mismatch.accept or mismatch.reason != "anchor_hash_mismatch":
        print(
            f"FAIL: expected anchor_hash_mismatch got "
            f"accept={mismatch.accept} reason={mismatch.reason}"
        )
        return 1
    exact = svc.evaluate_stale_fork(
        candidate_height=2,
        candidate_hash=anchor_h,
        shares_ancestor_with_anchor=False,
    )
    if not exact.accept or exact.reason != "is_anchor":
        print(f"FAIL: expected is_anchor got accept={exact.accept} reason={exact.reason}")
        return 1

    lie = BlockRef(height=2, block_hash="ee" * 32, parent_hash=anchor_h)
    lie_dec = evaluate_block_ref(svc, window, lie)
    if lie_dec.accept or lie_dec.reason != "anchor_hash_mismatch":
        print(
            f"FAIL: evaluate_block_ref expected anchor_hash_mismatch got "
            f"accept={lie_dec.accept} reason={lie_dec.reason}"
        )
        return 1

    # Wave-11: missing digest cannot rewrite height/hash into a loaded anchor.
    with tempfile.TemporaryDirectory() as tmp:
        bad_path = Path(tmp) / "no_digest.json"
        bad_path.write_text(
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
        try:
            bind_persisted_ws(path=bad_path)
            print("FAIL: missing digest loaded as WS anchor")
            return 1
        except ValueError as exc:
            if "digest" not in str(exc).lower():
                print(f"FAIL: expected digest error got {exc}")
                return 1

    # Wave-12: wiped items + leftover env must not lower the checkpoint.
    with tempfile.TemporaryDirectory() as tmp:
        wiped = Path(tmp) / "empty_items.json"
        wiped.write_text(json.dumps({"max_history": 8, "items": []}), encoding="utf-8")
        wiped_svc = bind_persisted_ws(
            path=wiped, env_height="1", env_hash="bb" * 32
        )
        if wiped_svc.get_anchor() is not None:
            print(
                "FAIL: empty persist re-seeded from env "
                f"height={wiped_svc.get_anchor().height}"
            )
            return 1

    print("Long-Range lab wave-12 (empty persist does not re-seed env)")
    print(f"  cert digest: {cert.digest[:16]}... verify={cert.verify_digest()}")
    print(f"  WS child:   accept={ok.accept} reason={ok.reason}")
    print(f"  stale fork: accept={bad.accept} reason={bad.reason}")
    print(f"  below:      accept={below.accept} reason={below.reason}")
    print(f"  import:     digest_match={restored.digest == cert.digest}")
    print(f"  tip gate:   reject={tip_dec.reason_code}")
    print(f"  restart:    reject={restart_dec.reason_code}")
    print(f"  no_anchor:  reject={empty_dec.reason_code}")
    print(f"  mismatch:   reject={mismatch.reason}")
    print(f"  is_anchor:  accept={exact.reason}")
    print("  no_digest:  refused")
    print("  empty_env:  no re-seed")
    print(f"  store:      history={len(store)} latest_h={store.latest().anchor.height}")

    if not ok.accept or bad.accept or below.accept:
        print("FAIL: unexpected policy outcomes")
        return 1
    if bad.reason != "long_range_fork_below_anchor":
        # parent not found / not linked → long_range_fork
        if bad.reason not in ("long_range_fork_below_anchor",):
            print(f"FAIL: unexpected stale reason {bad.reason}")
            return 1
    if below.reason != "below_ws_anchor":
        print(f"FAIL: expected below_ws_anchor got {below.reason}")
        return 1
    print("OK: long_range_lab PASS (research only; persist+refuse; not tip proof)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
