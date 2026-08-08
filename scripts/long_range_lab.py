#!/usr/bin/env python3
"""Long-Range / weak-subjectivity lab (ADR 0017).

Simulates a stale competing history forking below a WS anchor and asserts
the refuse policy. Does **not** claim mainnet Long-Range proof.

Usage:
  python scripts/long_range_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.long_range import WeakSubjectivityService
from consensus.long_range.ports import WeakSubjectivityAnchor


def main() -> int:
    svc = WeakSubjectivityService()
    anchor = WeakSubjectivityAnchor(height=100, block_hash="aa" * 32, epoch=1)
    svc.set_anchor(anchor)

    stale = svc.evaluate_stale_fork(
        candidate_height=50,
        candidate_hash="bb" * 32,
        shares_ancestor_with_anchor=False,
    )
    long_range = svc.evaluate_stale_fork(
        candidate_height=200,
        candidate_hash="cc" * 32,
        shares_ancestor_with_anchor=False,
    )
    ok_desc = svc.evaluate_stale_fork(
        candidate_height=150,
        candidate_hash="dd" * 32,
        shares_ancestor_with_anchor=True,
    )

    print("Long-Range lab (FEATURE_LONG_RANGE research)")
    print(f"  stale below anchor: accept={stale.accept} reason={stale.reason}")
    print(f"  long-range fork:    accept={long_range.accept} reason={long_range.reason}")
    print(f"  WS descendant:      accept={ok_desc.accept} reason={ok_desc.reason}")

    if stale.accept or long_range.accept or not ok_desc.accept:
        print("FAIL: unexpected policy outcomes")
        return 1
    if stale.reason != "below_ws_anchor":
        print(f"FAIL: expected below_ws_anchor got {stale.reason}")
        return 1
    if long_range.reason != "long_range_fork_below_anchor":
        print(f"FAIL: expected long_range_fork_below_anchor got {long_range.reason}")
        return 1
    print("OK: long_range_lab PASS (research only; not tip proof)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
