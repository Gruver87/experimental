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
    max_walk: int | None = None,
) -> bool:
    """Walk candidate parents inside ``window`` looking for ``anchor_hash``."""
    if max_walk is None:
        try:
            import os

            max_walk = int(os.environ.get("TIP_ANCESTRY_WINDOW_MAX", "4096") or 4096)
        except (TypeError, ValueError):
            max_walk = 4096
        max_walk = max(int(window.max_blocks), int(max_walk))
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
        try:
            parent_n = normalize_block_hash(parent)
        except Exception:
            parent_n = parent
        if parent_n == target:
            return True
        cur = parent_n
    return False


def evaluate_block_ref(
    svc: WeakSubjectivityService,
    window: AncestryWindow,
    candidate: BlockRef,
    local_tip: Optional[BlockRef] = None,
) -> StaleForkDecision:
    """Evaluate a tip candidate that may not yet be recorded in ``window``.

    ``local_tip`` (optional): current canonical tip. Contiguous ``tip+1`` past a
    WS anchor must not false-refuse when the bounded ancestry window has LRU-
    evicted the path tip→anchor (lab 48h stall after ~256 blocks).
    """
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
            local_tip=local_tip,
        )
    parent = str(candidate.parent_hash or "")
    if not parent:
        linked = int(candidate.height) == 0 and candidate.block_hash == anchor.block_hash
    else:
        try:
            ph = normalize_block_hash(parent)
            ah = normalize_block_hash(anchor.block_hash)
        except Exception:
            ph, ah = "", ""
        linked = bool(ph) and (
            ph == ah
            or shares_ancestor_with_anchor(
                window, candidate_hash=ph, anchor_hash=anchor.block_hash
            )
        )
        # Contiguous extend on local tip already past WS floor.
        if (
            not linked
            and local_tip is not None
            and ph
            and int(candidate.height) == int(local_tip.height) + 1
        ):
            try:
                tip_hash = normalize_block_hash(local_tip.block_hash)
                tip_h = int(local_tip.height)
                anch_h = int(anchor.height)
            except Exception:
                tip_hash, tip_h, anch_h = "", -1, -1
            if tip_hash and ph == tip_hash and tip_h >= anch_h:
                if tip_h == anch_h:
                    linked = tip_hash == ah
                else:
                    linked = True
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
    local_tip: Optional[BlockRef] = None,
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
    if (
        not linked
        and local_tip is not None
        and ref is not None
        and int(height) == int(local_tip.height) + 1
    ):
        try:
            tip_hash = normalize_block_hash(local_tip.block_hash)
            parent = normalize_block_hash(str(ref.parent_hash or ""))
            ah = normalize_block_hash(anchor.block_hash)
            tip_h = int(local_tip.height)
            anch_h = int(anchor.height)
        except Exception:
            tip_hash, parent, ah, tip_h, anch_h = "", "", "", -1, -1
        if tip_hash and parent == tip_hash and tip_h >= anch_h:
            linked = tip_hash == ah if tip_h == anch_h else True
    return svc.evaluate_stale_fork(
        candidate_height=height if height >= 0 else int(anchor.height),
        candidate_hash=cand,
        shares_ancestor_with_anchor=linked,
    )
