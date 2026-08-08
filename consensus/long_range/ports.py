"""Ports for Long-Range / weak-subjectivity research (ADR 0017)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class WeakSubjectivityAnchor:
    """Checkpoint a node trusts as the floor for accepting history."""

    height: int
    block_hash: str
    epoch: int = 0


@dataclass(frozen=True)
class StaleForkDecision:
    """Policy outcome for a competing tip relative to the WS anchor."""

    accept: bool
    reason: str
    anchor_height: int
    candidate_height: int


@runtime_checkable
class WeakSubjectivityPort(Protocol):
    def set_anchor(self, anchor: WeakSubjectivityAnchor) -> None: ...

    def get_anchor(self) -> Optional[WeakSubjectivityAnchor]: ...

    def evaluate_stale_fork(
        self,
        *,
        candidate_height: int,
        candidate_hash: str,
        shares_ancestor_with_anchor: bool,
    ) -> StaleForkDecision: ...
