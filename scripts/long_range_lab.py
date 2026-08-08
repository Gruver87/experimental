#!/usr/bin/env python3
"""Long-Range / weak-subjectivity lab (ADR 0017).

Wave-2: checkpoint certificate + AncestryWindow walk.

Usage:
  python scripts/long_range_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.long_range import (
    CheckpointCertificate,
    WeakSubjectivityService,
    evaluate_with_window,
)
from consensus.tip_safety.ancestry_window import AncestryWindow
from consensus.tip_safety.types import BlockRef


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

    print("Long-Range lab wave-2 (checkpoint + AncestryWindow)")
    print(f"  cert digest: {cert.digest[:16]}… verify={cert.verify_digest()}")
    print(f"  WS child:   accept={ok.accept} reason={ok.reason}")
    print(f"  stale fork: accept={bad.accept} reason={bad.reason}")
    print(f"  below:      accept={below.accept} reason={below.reason}")

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
    print("OK: long_range_lab PASS (research only; not tip proof)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
