"""Tip-safety evidence bridge for the dispatcher (DI; no p2p_node import).

Uses ``consensus.tip_safety`` domain types directly. Optional shadow observer is
injected for enforce/enabled flags only — evaluate itself does not mutate
shadow counters (import path remains the observe/enforce source of truth for
metrics). Dispatcher uses this to refuse NEW_BLOCK under enforce before the
domain handler runs.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from network.p2p_dispatch.types import TipEvidenceDecision

logger = logging.getLogger("P2P.TipEvidence")

ShadowProvider = Callable[[], Any]


class TipSafetyEvidenceBridge:
    """Adapt tip-safety domain (+ optional shadow flags) to ``TipEvidencePort``."""

    __slots__ = ("_shadow_provider", "_reorg")

    def __init__(
        self,
        *,
        shadow_provider: Optional[ShadowProvider] = None,
        reorg_policy: Any = None,
    ) -> None:
        self._shadow_provider = shadow_provider
        if reorg_policy is None:
            from consensus.tip_safety import ReorgPolicy

            reorg_policy = ReorgPolicy()
        self._reorg = reorg_policy

    def _shadow(self) -> Any:
        if self._shadow_provider is None:
            return None
        try:
            return self._shadow_provider()
        except Exception as exc:
            logger.warning("tip-safety shadow provider failed: %s", exc)
            return None

    @property
    def enabled(self) -> bool:
        shadow = self._shadow()
        if shadow is None:
            return False
        return bool(getattr(shadow, "enabled", False))

    @property
    def enforce(self) -> bool:
        shadow = self._shadow()
        if shadow is None:
            return False
        return bool(getattr(shadow, "enforce", False))

    def evaluate_block_candidate(
        self,
        data: Mapping[str, Any],
        chain: Any,
    ) -> TipEvidenceDecision:
        """Policy-evaluate a block announce / body without shadow counter side effects.

        When tip-safety is disabled or unset → allow.
        When enabled → run ``ReorgPolicy.evaluate`` against chain tip (read-only).
        ``enforce_refuse`` is set only when shadow.enforce and policy rejects.
        """
        shadow = self._shadow()
        if shadow is not None and not bool(getattr(shadow, "enabled", False)):
            return TipEvidenceDecision(ok=True, reason_code="tip_evidence_disabled")
        # No shadow wired → allow (import path may still observe later).
        if shadow is None:
            return TipEvidenceDecision(ok=True, reason_code="tip_evidence_unbound")
        if chain is None:
            if self.enforce:
                return TipEvidenceDecision(
                    ok=False,
                    reason_code="tip_evidence_no_chain",
                    detail="blockchain missing",
                    enforce_refuse=True,
                )
            return TipEvidenceDecision(ok=True, reason_code="tip_evidence_no_chain")

        try:
            cand_h = int((data or {}).get("height") or (data or {}).get("number") or 0)
        except (TypeError, ValueError):
            cand_h = 0
        try:
            last_forge = int(getattr(shadow, "last_local_forge_height", 0) or 0)
        except (TypeError, ValueError):
            last_forge = 0
        if last_forge > 0 and cand_h in (last_forge, last_forge + 1):
            return TipEvidenceDecision(
                ok=True,
                reason_code="own_forge_echo",
                detail=f"candidate {cand_h} within local forge {last_forge}",
            )

        try:
            from consensus.tip_safety.shadow import (
                TipSafetyShadowObserver,
                block_ref_from_mapping,
                tip_state_from_chain,
            )
            from consensus.tip_safety import TipSafetyService

            # Live chain tip only. Preferring stale ``svc.state`` made the
            # miner refuse its own NEW_BLOCK echo as tip_unknown_parent
            # (candidate=N head=N-2) after KeepVolumes restart.
            if isinstance(shadow, TipSafetyShadowObserver):
                shadow.sync_from_chain(chain)
            tip = tip_state_from_chain(chain)
            svc = getattr(shadow, "_service", None)
            candidate = block_ref_from_mapping(data)
            if (
                isinstance(shadow, TipSafetyShadowObserver)
                and svc is not None
                and hasattr(svc, "evaluate_candidate")
            ):
                service = svc
            else:
                service = TipSafetyService(state=tip, reorg_policy=self._reorg)
            decision = service.evaluate_candidate(candidate)
        except Exception as exc:
            if self.enforce:
                return TipEvidenceDecision(
                    ok=False,
                    reason_code="tip_evidence_error",
                    detail=str(exc),
                    enforce_refuse=True,
                )
            return TipEvidenceDecision(
                ok=True,
                reason_code="tip_evidence_error_soft",
                detail=str(exc),
            )

        if decision.accepted:
            return TipEvidenceDecision(ok=True, reason_code="ok")
        reason = str(getattr(decision, "reason_code", "") or "tip_reject")
        refuse = bool(self.enforce)
        return TipEvidenceDecision(
            ok=not refuse,
            reason_code=reason,
            detail=str(getattr(decision, "detail", "") or ""),
            enforce_refuse=refuse,
        )

    def evaluate_status_claim(
        self,
        *,
        height: int,
        head_hash: str,
        local_height: int,
        local_head: str,
    ) -> TipEvidenceDecision:
        """Soft STATUS claim check vs local tip (not Long-Range / tip proof).

        Refuses under enforce only when the claimed head equals the local tip
        head but the claimed height disagrees.
        """
        if not self.enabled:
            return TipEvidenceDecision(ok=True, reason_code="tip_evidence_disabled")
        h = int(height or 0)
        local_h = int(local_height or 0)
        claim_head = str(head_hash or "").strip().lower()
        tip_head = str(local_head or "").strip().lower()
        if not claim_head:
            return TipEvidenceDecision(ok=True, reason_code="ok")
        if tip_head and claim_head == tip_head and h != local_h and local_h > 0:
            refuse = bool(self.enforce)
            return TipEvidenceDecision(
                ok=not refuse,
                reason_code="tip_status_head_height_mismatch",
                detail=f"head matches tip but height {h} != local {local_h}",
                enforce_refuse=refuse,
            )
        return TipEvidenceDecision(ok=True, reason_code="ok")
