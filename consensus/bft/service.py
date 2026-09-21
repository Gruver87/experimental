"""Fail-closed BFT round state machine (ADR 0007). No P2P imports."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from consensus.bft.evidence import (
    ConsensusMaliciousError,
    build_evidence,
    is_malicious_reason,
    spam_threshold,
)
from consensus.bft.quorum import QuorumPolicy
from consensus.bft.types import (
    BlockRef,
    FinalityView,
    Proposal,
    QuorumCertificate,
    RoundId,
    RoundOutcome,
    RoundPhase,
    Vote,
    VoteType,
)
from consensus.ports import (
    ConsensusEvidencePort,
    ConsensusLockdownPort,
    ConsensusSideEffectPort,
    ValidatorRegistryPort,
)

logger = logging.getLogger("Consensus.RoundSM")


class RoundStateMachine:
    """Propose → Prevote → Precommit → Finalize, with Locked fail-closed."""

    def __init__(
        self,
        registry: ValidatorRegistryPort,
        evidence: ConsensusEvidencePort,
        lockdown: ConsensusLockdownPort,
        side: Optional[ConsensusSideEffectPort] = None,
        *,
        expected_proposer: Optional[str] = None,
        epoch_size: int = 32,
    ) -> None:
        self._registry = registry
        self._evidence = evidence
        self._lockdown = lockdown
        self._side = side
        self._policy = QuorumPolicy()
        self._expected_proposer = str(expected_proposer or "")
        self._epoch_size = max(1, int(epoch_size or 32))
        self._round = RoundId(epoch=0, height=0, round=0)
        self._phase = RoundPhase.PROPOSE
        self._proposal: Optional[Proposal] = None
        self._votes: List[Vote] = []
        # (validator_id, vote_type, round_key) -> block_hash
        self._seen: Dict[Tuple[str, str, Tuple[int, int, int]], str] = {}
        self._qc: Dict[Tuple[Tuple[int, int, int], str], QuorumCertificate] = {}
        self._finalized_hashes: set[str] = set()
        self._finalized_height: int = 0
        self._blocks: Dict[str, BlockRef] = {}
        self._head: Optional[BlockRef] = None
        self._attest_by_block: Dict[str, List[Vote]] = {}
        self._quorum_live_armed: bool = False

    # ── ConsensusPort surface ─────────────────────────────────────────────

    def current_round(self) -> RoundId:
        return self._round

    def round_phase(self, round_id: RoundId) -> RoundPhase:
        if round_id.key() != self._round.key():
            return RoundPhase.LOCKED if self._phase is RoundPhase.LOCKED else self._phase
        return self._phase

    def canonical_head(self) -> Optional[BlockRef]:
        return self._head

    def is_finalized(self, block_hash_or_height: str | int) -> bool:
        if isinstance(block_hash_or_height, int):
            return int(block_hash_or_height) <= int(self._finalized_height)
        hh = str(block_hash_or_height or "").strip().lower()
        return hh in self._finalized_hashes

    def finality_status(self) -> FinalityView:
        """Honest finality view.

        ``quorum_live`` stays False unless ``finality_quorum_live`` is armed on the
        host config *and* at least one QuorumCertificate has ``reached=True``.
        AncestryWindow / tip-safety is **not** Long-Range / weak-subjectivity proof.
        """
        votes_present = bool(self._votes)
        qc_live = any(
            bool(getattr(qc, "reached", False)) for qc in self._qc.values()
        )
        allow = bool(getattr(self, "_quorum_live_armed", False))
        live = bool(allow and qc_live)
        if live:
            detail = "quorum_certificate_reached"
        elif allow:
            detail = "quorum_armed_waiting_certificate"
        else:
            detail = "local_path_only"
        return FinalityView(
            finalized_height=int(self._finalized_height),
            justified_height=int(self._finalized_height),
            quorum_live=live,
            local_attestations_present=votes_present,
            detail=detail,
        )

    def arm_quorum_live(self, armed: bool = True) -> None:
        """Operator/ceremony arming for live quorum reporting (default off)."""
        self._quorum_live_armed = bool(armed)

    def quorum_certificate(
        self, round_id: RoundId, vote_type: VoteType
    ) -> Optional[QuorumCertificate]:
        return self._qc.get((round_id.key(), vote_type.value))

    def add_block(self, block_ref: BlockRef, parent_hash: str = "") -> None:
        parent = str(parent_hash or block_ref.parent_hash or "").lower()
        ref = BlockRef(
            height=block_ref.height,
            block_hash=block_ref.block_hash,
            parent_hash=parent,
        )
        self._blocks[ref.block_hash] = ref
        if self._head is None or ref.height >= self._head.height:
            self._head = ref
        # Align round height with tip when advancing.
        if ref.height > self._round.height or (
            ref.height == self._round.height and self._phase is RoundPhase.FINALIZE
        ):
            epoch = ref.height // self._epoch_size
            self._begin_round(RoundId(epoch=epoch, height=ref.height, round=0))

    def get_attestations_for_block(self, block_hash: str) -> List[Vote]:
        return list(self._attest_by_block.get(str(block_hash or "").lower(), []))

    def submit_proposal(self, proposal: Proposal) -> RoundOutcome:
        if self._phase is RoundPhase.LOCKED:
            return RoundOutcome.locked(
                "round_locked",
                round_id=self._round,
                detail="round already locked",
            )
        if proposal.round_id.key() != self._round.key():
            return RoundOutcome.refused(
                self._phase,
                "stale_round_vote",
                round_id=proposal.round_id,
                block_hash=proposal.block_hash,
            )
        if self._phase is not RoundPhase.PROPOSE:
            return RoundOutcome.refused(
                self._phase,
                "unexpected_proposal_phase",
                round_id=self._round,
                block_hash=proposal.block_hash,
            )
        snap = self._registry.snapshot()
        if not snap.is_active(proposal.proposer_id):
            return self._fail_closed(
                "unknown_validator_vote",
                validator_id=proposal.proposer_id,
                round_id=proposal.round_id,
                detail="proposer not in active set",
            )
        expected = self._expected_proposer or proposal.proposer_id
        if self._expected_proposer and proposal.proposer_id != expected:
            return self._fail_closed(
                "double_proposal",
                validator_id=proposal.proposer_id,
                round_id=proposal.round_id,
                detail=f"expected proposer {expected[:12]}",
            )
        if self._proposal is not None:
            if self._proposal.block_hash != proposal.block_hash:
                return self._fail_closed(
                    "double_proposal",
                    validator_id=proposal.proposer_id,
                    round_id=proposal.round_id,
                    conflicting_votes=(),
                    detail="conflicting proposal",
                )
            return RoundOutcome.accepted(
                RoundPhase.PREVOTE,
                round_id=self._round,
                block_hash=proposal.block_hash,
                reason_code="duplicate_proposal",
            )
        self._proposal = proposal
        self._phase = RoundPhase.PREVOTE
        self.add_block(
            BlockRef(
                height=proposal.round_id.height,
                block_hash=proposal.block_hash,
                parent_hash=proposal.parent_hash,
            )
        )
        return RoundOutcome.accepted(
            RoundPhase.PREVOTE,
            round_id=self._round,
            block_hash=proposal.block_hash,
        )

    def submit_vote(self, vote: Vote) -> RoundOutcome:
        if self._phase is RoundPhase.LOCKED:
            return RoundOutcome.locked(
                "round_locked",
                round_id=self._round,
            )
        if not vote.verified:
            return self._fail_closed(
                "fake_vote_unverified",
                validator_id=vote.validator_id,
                round_id=vote.round_id,
                conflicting_votes=(vote,),
            )
        if vote.round_id.key() != self._round.key():
            return RoundOutcome.refused(
                self._phase,
                "stale_round_vote",
                round_id=vote.round_id,
                block_hash=vote.block_hash,
            )
        snap = self._registry.snapshot()
        if not snap.is_active(vote.validator_id):
            return self._fail_closed(
                "unknown_validator_vote",
                validator_id=vote.validator_id,
                round_id=vote.round_id,
                conflicting_votes=(vote,),
            )

        key = (vote.validator_id, vote.vote_type.value, vote.round_id.key())
        prior = self._seen.get(key)
        if prior is not None and prior != vote.block_hash:
            prior_vote = Vote(
                validator_id=vote.validator_id,
                vote_type=vote.vote_type,
                round_id=vote.round_id,
                block_hash=prior,
                slot=vote.slot,
                verified=True,
            )
            return self._fail_closed(
                "double_vote",
                validator_id=vote.validator_id,
                round_id=vote.round_id,
                conflicting_votes=(prior_vote, vote),
            )
        if prior == vote.block_hash:
            return RoundOutcome.accepted(
                self._phase,
                round_id=self._round,
                block_hash=vote.block_hash,
                reason_code="duplicate_vote",
            )

        # Phase gates
        if vote.vote_type is VoteType.PREVOTE and self._phase not in (
            RoundPhase.PREVOTE,
            RoundPhase.PRECOMMIT,
            RoundPhase.FINALIZE,
        ):
            if self._phase is RoundPhase.PROPOSE and self._proposal is None:
                # Allow prevote without proposal for attestation-mapped path.
                self._phase = RoundPhase.PREVOTE
            elif self._phase is RoundPhase.PROPOSE:
                pass
            else:
                return RoundOutcome.refused(
                    self._phase,
                    "unexpected_prevote_phase",
                    round_id=self._round,
                    block_hash=vote.block_hash,
                )
        if vote.vote_type is VoteType.PRECOMMIT and self._phase not in (
            RoundPhase.PRECOMMIT,
            RoundPhase.FINALIZE,
            RoundPhase.PREVOTE,
        ):
            return RoundOutcome.refused(
                self._phase,
                "unexpected_precommit_phase",
                round_id=self._round,
                block_hash=vote.block_hash,
            )

        self._seen[key] = vote.block_hash
        self._votes.append(vote)
        self._attest_by_block.setdefault(vote.block_hash, []).append(vote)
        if self._side is not None:
            try:
                self._side.on_attestation(vote)
            except Exception:
                logger.exception("[RoundSM] side on_attestation failed")

        if vote.vote_type is VoteType.PREVOTE:
            return self._maybe_advance_prevote(snap, vote.block_hash)
        if vote.vote_type is VoteType.PRECOMMIT:
            return self._maybe_advance_precommit(snap, vote.block_hash)
        return RoundOutcome.accepted(
            self._phase,
            round_id=self._round,
            block_hash=vote.block_hash,
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _begin_round(self, round_id: RoundId) -> None:
        self._round = round_id
        self._phase = RoundPhase.PROPOSE
        self._proposal = None
        self._votes = []
        # Keep slash history in _seen across rounds for double-sign across
        # same round_key only; clear keys for new round_id.
        self._seen = {
            k: v for k, v in self._seen.items() if k[2] == round_id.key()
        }

    def open_round(
        self,
        height: int,
        *,
        epoch: Optional[int] = None,
        round_n: int = 0,
        expected_proposer: Optional[str] = None,
    ) -> RoundId:
        ep = int(epoch) if epoch is not None else int(height) // self._epoch_size
        rid = RoundId(epoch=ep, height=int(height), round=int(round_n or 0))
        if expected_proposer is not None:
            self._expected_proposer = str(expected_proposer or "")
        self._begin_round(rid)
        return rid

    def _maybe_advance_prevote(
        self, snap, block_hash: str
    ) -> RoundOutcome:
        cert = self._policy.certificate(
            snap,
            self._votes,
            round_id=self._round,
            vote_type=VoteType.PREVOTE,
            block_hash=block_hash,
        )
        self._qc[(self._round.key(), VoteType.PREVOTE.value)] = cert
        if not cert.reached:
            return RoundOutcome.accepted(
                RoundPhase.PREVOTE,
                round_id=self._round,
                block_hash=block_hash,
                reason_code="prevote_pending",
            )
        self._phase = RoundPhase.PRECOMMIT
        return RoundOutcome.accepted(
            RoundPhase.PRECOMMIT,
            round_id=self._round,
            block_hash=block_hash,
            reason_code="prevote_quorum",
        )

    def _maybe_advance_precommit(
        self, snap, block_hash: str
    ) -> RoundOutcome:
        prev = self._qc.get((self._round.key(), VoteType.PREVOTE.value))
        if prev is not None and prev.reached and prev.block_hash != block_hash:
            return self._fail_closed(
                "prevote_precommit_hash_mismatch",
                validator_id="",
                round_id=self._round,
                detail=f"prevote={prev.block_hash[:12]} precommit={block_hash[:12]}",
            )
        cert = self._policy.certificate(
            snap,
            self._votes,
            round_id=self._round,
            vote_type=VoteType.PRECOMMIT,
            block_hash=block_hash,
        )
        self._qc[(self._round.key(), VoteType.PRECOMMIT.value)] = cert
        if not cert.reached:
            if self._phase is RoundPhase.PREVOTE:
                self._phase = RoundPhase.PRECOMMIT
            return RoundOutcome.accepted(
                RoundPhase.PRECOMMIT,
                round_id=self._round,
                block_hash=block_hash,
                reason_code="precommit_pending",
            )
        return self._finalize(block_hash)

    def _finalize(self, block_hash: str) -> RoundOutcome:
        self._phase = RoundPhase.FINALIZE
        hh = str(block_hash or "").lower()
        self._finalized_hashes.add(hh)
        height = self._round.height
        ref = self._blocks.get(hh)
        if ref is not None:
            height = int(ref.height)
        self._finalized_height = max(int(self._finalized_height), int(height))
        if self._side is not None:
            try:
                self._side.on_finalized(hh, int(height))
            except Exception:
                logger.exception("[RoundSM] side on_finalized failed")
        return RoundOutcome.complete(round_id=self._round, block_hash=hh)

    def _fail_closed(
        self,
        reason: str,
        *,
        validator_id: str,
        round_id: Optional[RoundId],
        conflicting_votes: Tuple[Vote, ...] | tuple = (),
        detail: str = "",
    ) -> RoundOutcome:
        reason_code = str(reason or "refused")
        attempts = int(
            self._evidence.note_malicious_attempt(validator_id, reason_code) or 1
        )
        if attempts >= spam_threshold() and reason_code != "consensus_round_spam":
            reason_code = "consensus_round_spam"
            attempts = int(
                self._evidence.note_malicious_attempt(validator_id, reason_code)
                or attempts
            )
        evidence = build_evidence(
            reason_code=reason_code,
            validator_id=validator_id,
            round_id=round_id or self._round,
            conflicting_votes=conflicting_votes,
            attempt_count=attempts,
            detail=detail,
        )
        self._evidence.emit(evidence)
        try:
            self._registry.mark_slashed(validator_id, reason_code, evidence)
        except Exception:
            logger.exception("[RoundSM] mark_slashed failed")
            raise
        if is_malicious_reason(reason_code) or reason_code == "consensus_round_spam":
            lock_reason = (
                "consensus_double_sign"
                if reason_code in ("double_vote", "double_proposal", "consensus_double_sign")
                else reason_code
            )
            try:
                self._lockdown.request_lockdown(lock_reason)
            except Exception:
                logger.exception("[RoundSM] lockdown failed")
        self._phase = RoundPhase.LOCKED
        outcome = RoundOutcome.locked(
            reason_code,
            round_id=round_id or self._round,
            detail=detail,
        )
        raise ConsensusMaliciousError(outcome, evidence)
