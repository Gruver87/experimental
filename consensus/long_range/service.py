"""Weak-subjectivity policy service (ADR 0017) — research, not tip proof."""

from __future__ import annotations

from typing import Optional

from consensus.long_range.ports import (
    StaleForkDecision,
    WeakSubjectivityAnchor,
)


class WeakSubjectivityService:
    """Refuse histories that fork below the WS anchor (classic Long-Range refuse).

    When no anchor is set, ``evaluate_stale_fork`` returns accept=False /
    ``no_anchor``. Tip-import with this service attached must refuse that
    reason (armed Long-Range without a checkpoint is not protection).
    """

    def __init__(self) -> None:
        self._anchor: Optional[WeakSubjectivityAnchor] = None

    def set_anchor(self, anchor: WeakSubjectivityAnchor) -> None:
        if int(anchor.height) < 0:
            raise ValueError("anchor.height must be >= 0")
        if not str(anchor.block_hash or "").strip():
            raise ValueError("anchor.block_hash required")
        self._anchor = WeakSubjectivityAnchor(
            height=int(anchor.height),
            block_hash=str(anchor.block_hash).lower(),
            epoch=int(anchor.epoch or 0),
        )

    def get_anchor(self) -> Optional[WeakSubjectivityAnchor]:
        return self._anchor

    def evaluate_stale_fork(
        self,
        *,
        candidate_height: int,
        candidate_hash: str,
        shares_ancestor_with_anchor: bool,
    ) -> StaleForkDecision:
        cand_h = int(candidate_height)
        cand_hash = str(candidate_hash or "").lower()
        if self._anchor is None:
            return StaleForkDecision(
                accept=False,
                reason="no_anchor",
                anchor_height=-1,
                candidate_height=cand_h,
            )
        ah = int(self._anchor.height)
        if cand_h < ah:
            return StaleForkDecision(
                accept=False,
                reason="below_ws_anchor",
                anchor_height=ah,
                candidate_height=cand_h,
            )
        if not shares_ancestor_with_anchor:
            return StaleForkDecision(
                accept=False,
                reason="long_range_fork_below_anchor",
                anchor_height=ah,
                candidate_height=cand_h,
            )
        if cand_hash == self._anchor.block_hash and cand_h == ah:
            return StaleForkDecision(
                accept=True,
                reason="is_anchor",
                anchor_height=ah,
                candidate_height=cand_h,
            )
        return StaleForkDecision(
            accept=True,
            reason="descendant_of_ws_anchor",
            anchor_height=ah,
            candidate_height=cand_h,
        )
