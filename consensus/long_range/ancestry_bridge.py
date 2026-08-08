"""Bridge WeakSubjectivityService <-> AncestryWindow (ADR 0017)."""

from __future__ import annotations

from typing import Optional

from consensus.long_range.ports import StaleForkDecision
from consensus.long_range.service import WeakSubjectivityService
from consensus.tip_safety.ancestry_window import AncestryWindow
from consensus.tip_safety.types import BlockRef, normalize_block_hash


def shares_ancestor_with_anchor(
    window: AncestryWindow,
    *,
    candidate_hash: str,
    anchor_hash: str,
    max_walk: int = 4096,
) -> bool:
    """Walk candidate parents inside ``window`` looking for ``anchor_hash``."""
    try:
        target = normalize_block_hash(anchor_hash)
        cur = normalize_block_hash(candidate_hash)
    except Exception:
        return False
    if cur == target:
        return True
    seen: set[str] = set()
    for _ in range(int(max_walk)):
        if cur in seen:
            return False
        seen.add(cur)
        ref: Optional[BlockRef] = window.get(cur)
        if ref is None:
            return False
        parent = str(ref.parent_hash or "")
        if not parent:
            return False
        if parent == target:
            return True
        cur = parent
    return False


def evaluate_block_ref(
    svc: WeakSubjectivityService,
    window: AncestryWindow,
    candidate: BlockRef,
) -> StaleForkDecision:
    """Evaluate a tip candidate that may not yet be recorded in ``window``."""
    anchor = svc.get_anchor()
    if anchor is None:
        return svc.evaluate_stale_fork(
            candidate_height=int(candidate.height),
            candidate_hash=str(candidate.block_hash),
            shares_ancestor_with_anchor=False,
        )
    if window.contains(candidate.block_hash):
        return evaluate_with_window(
            svc,
            window,
            candidate_hash=candidate.block_hash,
            candidate_height=candidate.height,
        )
    parent = str(candidate.parent_hash or "")
    if not parent:
        linked = int(candidate.height) == 0 and candidate.block_hash == anchor.block_hash
    else:
        try:
            ph = normalize_block_hash(parent)
        except Exception:
            ph = ""
        linked = bool(ph) and (
            ph == normalize_block_hash(anchor.block_hash)
            or shares_ancestor_with_anchor(
                window, candidate_hash=ph, anchor_hash=anchor.block_hash
            )
        )
    return svc.evaluate_stale_fork(
        candidate_height=int(candidate.height),
        candidate_hash=str(candidate.block_hash),
        shares_ancestor_with_anchor=linked,
    )


def evaluate_with_window(
    svc: WeakSubjectivityService,
    window: AncestryWindow,
    *,
    candidate_hash: str,
    candidate_height: int | None = None,
) -> StaleForkDecision:
    """Policy decision using ancestry walk when an anchor is set."""
    anchor = svc.get_anchor()
    try:
        cand = normalize_block_hash(candidate_hash)
    except Exception:
        return StaleForkDecision(
            accept=False,
            reason="bad_candidate_hash",
            anchor_height=int(anchor.height) if anchor else -1,
            candidate_height=int(candidate_height or -1),
        )
    ref = window.get(cand)
    height = int(candidate_height if candidate_height is not None else (ref.height if ref else -1))
    if anchor is None:
        return svc.evaluate_stale_fork(
            candidate_height=height,
            candidate_hash=cand,
            shares_ancestor_with_anchor=False,
        )
    linked = shares_ancestor_with_anchor(
        window, candidate_hash=cand, anchor_hash=anchor.block_hash
    )
    return svc.evaluate_stale_fork(
        candidate_height=height if height >= 0 else int(anchor.height),
        candidate_hash=cand,
        shares_ancestor_with_anchor=linked,
    )
