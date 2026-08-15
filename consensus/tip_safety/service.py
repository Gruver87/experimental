"""Application service for tip-safety evaluation and finality advance.

Pure domain orchestration: no DB, no P2P, no HTTP. Persistence adapters are
wired in a later stage; this service only mutates in-memory ``TipState``.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from consensus.tip_safety.ancestry_window import AncestryWindow
from consensus.tip_safety.errors import TipSafetyError, TipValidationError
from consensus.tip_safety.fork_choice import ForkChoice
from consensus.tip_safety.reorg_policy import ReorgPolicy
from consensus.tip_safety.tip_state import TipState
from consensus.tip_safety.types import ApplyDecision, ApplyOutcome, BlockRef

_LOG = logging.getLogger("abs.tip_safety")


class TipSafetyService:
    """Evaluate tip candidates and advance finality against a ``TipState``.

    Args:
        state: Mutable tip holder (thread-safe).
        reorg_policy: Policy used for single-candidate evaluation.
        fork_choice: Ranker for multi-candidate selection.
        ancestry: Bounded tip ancestry window (stage-1.5). When omitted and
            ``reorg_policy`` has no window, a default window is created and
            shared with a new ``ReorgPolicy``.
        ancestry_max_blocks: Capacity when constructing the default window.
        ws_service: Optional ADR 0017 weak-subjectivity gate (FEATURE_LONG_RANGE).
            When set, accepted tip candidates must also pass WS policy.
    """

    def __init__(
        self,
        state: TipState,
        reorg_policy: Optional[ReorgPolicy] = None,
        fork_choice: Optional[ForkChoice] = None,
        ancestry: Optional[AncestryWindow] = None,
        ancestry_max_blocks: int = 256,
        ws_service: Optional[object] = None,
    ) -> None:
        if not isinstance(state, TipState):
            raise TipValidationError(
                f"state must be TipState, got {type(state).__name__}"
            )
        self._state = state
        if ancestry is not None and not isinstance(ancestry, AncestryWindow):
            raise TipValidationError("ancestry must be AncestryWindow")
        if reorg_policy is not None and not isinstance(reorg_policy, ReorgPolicy):
            raise TipValidationError("reorg_policy must be ReorgPolicy")
        if ancestry is None and reorg_policy is not None:
            ancestry = reorg_policy.ancestry
        if ancestry is None:
            ancestry = AncestryWindow(max_blocks=int(ancestry_max_blocks) or 256)
        self._ancestry = ancestry
        if reorg_policy is None:
            self._reorg = ReorgPolicy(ancestry=self._ancestry)
        elif reorg_policy.ancestry is None:
            self._reorg = ReorgPolicy(ancestry=self._ancestry)
        else:
            self._reorg = reorg_policy
            self._ancestry = reorg_policy.ancestry
        self._fork = fork_choice if fork_choice is not None else ForkChoice()
        if not isinstance(self._fork, ForkChoice):
            raise TipValidationError("fork_choice must be ForkChoice")
        self._ws = ws_service
        # Seed window with current tip (and finalized if present).
        snap = self._state.snapshot()
        self._ancestry.record(snap.head)
        if snap.finalized is not None:
            self._ancestry.record(snap.finalized)

    @property
    def state(self) -> TipState:
        """Underlying tip state (same instance passed at construction)."""
        return self._state

    @property
    def ancestry(self) -> AncestryWindow:
        """Bounded ancestry window shared with reorg policy."""
        return self._ancestry

    def evaluate_candidate(self, candidate: BlockRef) -> ApplyDecision:
        """Evaluate a candidate without mutating state.

        Args:
            candidate: Proposed tip block.

        Returns:
            Decision with ``accepted`` True/False. On policy rejection the
            decision uses ``ApplyOutcome.REJECT`` and does not raise, so
            callers can record metrics without try/except. Structural type
            errors still raise ``TipValidationError``.
        """
        try:
            decision = self._reorg.evaluate(self._state, candidate)
        except TipSafetyError as exc:
            _LOG.info(
                "evaluate_candidate reject code=%s detail=%s",
                exc.code,
                exc.message,
            )
            return ApplyDecision(
                outcome=ApplyOutcome.REJECT,
                reason_code=exc.code,
                detail=exc.message,
                new_head=None,
            )
        if decision.accepted and self._ws is not None:
            try:
                from consensus.long_range.ancestry_bridge import evaluate_block_ref

                ws_dec = evaluate_block_ref(self._ws, self._ancestry, candidate)
                # FEATURE_LONG_RANGE attached: refuse including no_anchor.
                # Armed without a persisted checkpoint is not Long-Range protection.
                if not ws_dec.accept:
                    _LOG.info(
                        "evaluate_candidate WS refuse reason=%s height=%s",
                        ws_dec.reason,
                        candidate.height,
                    )
                    return ApplyDecision(
                        outcome=ApplyOutcome.REJECT,
                        reason_code=f"ws_{ws_dec.reason}",
                        detail=f"FEATURE_LONG_RANGE gate: {ws_dec.reason}",
                        new_head=None,
                    )
            except Exception as exc:
                _LOG.warning("WS tip gate error (fail-closed): %s", exc)
                return ApplyDecision(
                    outcome=ApplyOutcome.REJECT,
                    reason_code="ws_gate_error",
                    detail=str(exc),
                    new_head=None,
                )
        return decision

    def apply_candidate(self, candidate: BlockRef) -> ApplyDecision:
        """Evaluate and, if accepted, update tip state.

        Args:
            candidate: Proposed tip block.

        Returns:
            Decision after optional state update.
        """
        decision = self.evaluate_candidate(candidate)
        if not decision.accepted or decision.new_head is None:
            return decision
        try:
            self._state = self._state.with_head(decision.new_head)
        except TipSafetyError as exc:
            _LOG.warning(
                "apply_candidate state update failed code=%s detail=%s",
                exc.code,
                exc.message,
            )
            return ApplyDecision(
                outcome=ApplyOutcome.REJECT,
                reason_code=exc.code,
                detail=exc.message,
                new_head=None,
            )
        self._ancestry.record(decision.new_head)
        _LOG.info(
            "tip applied outcome=%s height=%s hash=%s",
            decision.outcome.value,
            decision.new_head.height,
            decision.new_head.short_hash(),
        )
        return decision

    def choose_and_apply(self, candidates: Sequence[BlockRef]) -> ApplyDecision:
        """Pick the best candidate via fork-choice, then apply it.

        Args:
            candidates: Competing tip candidates.

        Returns:
            Apply decision for the winning candidate (or reject if empty/invalid).
        """
        try:
            winner = self._fork.choose(candidates)
        except TipValidationError as exc:
            return ApplyDecision(
                outcome=ApplyOutcome.REJECT,
                reason_code=exc.code,
                detail=exc.message,
                new_head=None,
            )
        return self.apply_candidate(winner)

    def advance_finalized(self, checkpoint: BlockRef) -> TipState:
        """Advance the finalized checkpoint fail-closed.

        Args:
            checkpoint: New finalized block reference.

        Returns:
            Updated tip state.

        Raises:
            TipSafetyError: Validation or finality regress.
        """
        self._state = self._state.with_finalized(checkpoint)
        self._ancestry.record(checkpoint)
        _LOG.info(
            "finalized advanced height=%s hash=%s",
            checkpoint.height,
            checkpoint.short_hash(),
        )
        return self._state
