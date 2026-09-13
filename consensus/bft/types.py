"""Consensus domain value types (ADR 0007). No P2P / DB imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Tuple


class VoteType(str, Enum):
    PROPOSE = "propose"
    PREVOTE = "prevote"
    PRECOMMIT = "precommit"


class RoundPhase(str, Enum):
    PROPOSE = "propose"
    PREVOTE = "prevote"
    PRECOMMIT = "precommit"
    FINALIZE = "finalize"
    LOCKED = "locked"


class RoundStatus(str, Enum):
    OK = "ok"
    REFUSED = "refused"
    COMPLETE = "complete"
    LOCKED = "locked"


@dataclass(frozen=True)
class RoundId:
    epoch: int
    height: int
    round: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch", int(self.epoch or 0))
        object.__setattr__(self, "height", int(self.height or 0))
        object.__setattr__(self, "round", int(self.round or 0))

    def key(self) -> Tuple[int, int, int]:
        return (self.epoch, self.height, self.round)


@dataclass(frozen=True)
class ValidatorInfo:
    validator_id: str
    stake: int = 0  # Wave M: integer satoshi (not float ABS)
    pubkey: str = ""
    active: bool = True
    slashed: bool = False

    def __post_init__(self) -> None:
        from runtime.amount import to_satoshi

        object.__setattr__(self, "validator_id", str(self.validator_id or "").strip())
        try:
            stake_sat = int(to_satoshi(self.stake or 0))
        except (TypeError, ValueError):
            stake_sat = 0
        object.__setattr__(self, "stake", max(0, stake_sat))
        object.__setattr__(self, "pubkey", str(self.pubkey or ""))
        object.__setattr__(self, "active", bool(self.active))
        object.__setattr__(self, "slashed", bool(self.slashed))


@dataclass(frozen=True)
class ValidatorSetSnapshot:
    """Immutable validator set for one round (no live DB)."""

    validators: Tuple[ValidatorInfo, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "validators", tuple(self.validators or ()))

    def get(self, validator_id: str) -> Optional[ValidatorInfo]:
        want = str(validator_id or "").strip()
        for v in self.validators:
            if v.validator_id == want:
                return v
        return None

    def total_active_stake(self) -> int:
        return int(
            sum(
                int(v.stake)
                for v in self.validators
                if v.active and not v.slashed and int(v.stake) > 0
            )
        )

    def is_active(self, validator_id: str) -> bool:
        v = self.get(validator_id)
        return bool(v and v.active and not v.slashed)


@dataclass(frozen=True)
class BlockRef:
    height: int
    block_hash: str
    parent_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "height", int(self.height or 0))
        object.__setattr__(
            self, "block_hash", str(self.block_hash or "").strip().lower()
        )
        object.__setattr__(
            self, "parent_hash", str(self.parent_hash or "").strip().lower()
        )


@dataclass(frozen=True)
class Vote:
    validator_id: str
    vote_type: VoteType
    round_id: RoundId
    block_hash: str
    slot: int = 0
    signature_ref: str = ""
    verified: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "validator_id", str(self.validator_id or "").strip())
        vt = self.vote_type
        if not isinstance(vt, VoteType):
            vt = VoteType(str(vt))
        object.__setattr__(self, "vote_type", vt)
        object.__setattr__(
            self, "block_hash", str(self.block_hash or "").strip().lower()
        )
        object.__setattr__(self, "slot", int(self.slot or 0))
        object.__setattr__(self, "signature_ref", str(self.signature_ref or ""))
        object.__setattr__(self, "verified", bool(self.verified))


@dataclass(frozen=True)
class Proposal:
    proposer_id: str
    round_id: RoundId
    block_hash: str
    parent_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposer_id", str(self.proposer_id or "").strip())
        object.__setattr__(
            self, "block_hash", str(self.block_hash or "").strip().lower()
        )
        object.__setattr__(
            self, "parent_hash", str(self.parent_hash or "").strip().lower()
        )


@dataclass(frozen=True)
class QuorumCertificate:
    round_id: RoundId
    vote_type: VoteType
    block_hash: str
    stake_voted: int
    stake_total: int
    reached: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "block_hash", str(self.block_hash or "").strip().lower()
        )
        object.__setattr__(self, "stake_voted", int(self.stake_voted or 0))
        object.__setattr__(self, "stake_total", int(self.stake_total or 0))
        object.__setattr__(self, "reached", bool(self.reached))


@dataclass(frozen=True)
class FinalityView:
    """Honest finality status — quorum_live stays False in Waves A–C."""

    finalized_height: int = 0
    justified_height: int = 0
    quorum_live: bool = False
    local_attestations_present: bool = False
    detail: str = "local_path_only"


@dataclass(frozen=True)
class RoundOutcome:
    status: RoundStatus
    phase: RoundPhase
    reason_code: str = ""
    round_id: Optional[RoundId] = None
    block_hash: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (RoundStatus.OK, RoundStatus.COMPLETE)

    @classmethod
    def accepted(
        cls,
        phase: RoundPhase,
        *,
        round_id: Optional[RoundId] = None,
        block_hash: str = "",
        reason_code: str = "accepted",
    ) -> "RoundOutcome":
        return cls(
            status=RoundStatus.OK,
            phase=phase,
            reason_code=reason_code,
            round_id=round_id,
            block_hash=str(block_hash or ""),
        )

    @classmethod
    def complete(
        cls,
        *,
        round_id: Optional[RoundId] = None,
        block_hash: str = "",
    ) -> "RoundOutcome":
        return cls(
            status=RoundStatus.COMPLETE,
            phase=RoundPhase.FINALIZE,
            reason_code="finalized",
            round_id=round_id,
            block_hash=str(block_hash or ""),
        )

    @classmethod
    def refused(
        cls,
        phase: RoundPhase,
        reason_code: str,
        *,
        round_id: Optional[RoundId] = None,
        block_hash: str = "",
        detail: str = "",
    ) -> "RoundOutcome":
        return cls(
            status=RoundStatus.REFUSED,
            phase=phase,
            reason_code=str(reason_code or "refused"),
            round_id=round_id,
            block_hash=str(block_hash or ""),
            detail=str(detail or ""),
        )

    @classmethod
    def locked(
        cls,
        reason_code: str,
        *,
        round_id: Optional[RoundId] = None,
        block_hash: str = "",
        detail: str = "",
    ) -> "RoundOutcome":
        return cls(
            status=RoundStatus.LOCKED,
            phase=RoundPhase.LOCKED,
            reason_code=str(reason_code or "locked"),
            round_id=round_id,
            block_hash=str(block_hash or ""),
            detail=str(detail or ""),
        )


@dataclass(frozen=True)
class ConsensusSecurityEvidence:
    reason_code: str
    validator_id: str
    round_id: Optional[RoundId] = None
    conflicting_votes: Tuple[Vote, ...] = ()
    attempt_count: int = 1
    detail: str = ""
    kind: str = "consensus_malicious"

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_code", str(self.reason_code or "refused"))
        object.__setattr__(self, "validator_id", str(self.validator_id or ""))
        object.__setattr__(self, "conflicting_votes", tuple(self.conflicting_votes or ()))
        object.__setattr__(self, "attempt_count", max(1, int(self.attempt_count or 1)))
        object.__setattr__(self, "detail", str(self.detail or ""))

    def to_bus_payload(self) -> dict:
        rid = self.round_id
        return {
            "kind": self.kind,
            "reason_code": self.reason_code,
            "validator_id": self.validator_id,
            "epoch": int(rid.epoch) if rid else 0,
            "height": int(rid.height) if rid else 0,
            "round": int(rid.round) if rid else 0,
            "attempt_count": int(self.attempt_count),
            "detail": self.detail,
            "fail_closed": True,
            "conflicting_vote_count": len(self.conflicting_votes),
        }
