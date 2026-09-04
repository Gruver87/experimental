"""Weak-subjectivity checkpoint certificates (ADR 0017 research)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence

from consensus.long_range.committee import (
    CommitteeConfig,
    CommitteeSignature,
    committee_required,
    verify_committee_quorum,
)
from consensus.long_range.ports import WeakSubjectivityAnchor


@dataclass(frozen=True)
class CheckpointCertificate:
    """Lab WS certificate binding an anchor.

    Always carries a deterministic digest. Optional Ed25519 committee signatures
    (ADR 0017 lab-industrial) — not BLS aggregate.
    """

    anchor: WeakSubjectivityAnchor
    issuer: str
    issued_at_height: int
    digest: str
    signatures: tuple[CommitteeSignature, ...] = field(default_factory=tuple)

    @staticmethod
    def issue(
        *,
        height: int,
        block_hash: str,
        epoch: int = 0,
        issuer: str = "lab",
        issued_at_height: int | None = None,
        signatures: Sequence[CommitteeSignature | Mapping[str, Any]] | None = None,
    ) -> "CheckpointCertificate":
        anchor = WeakSubjectivityAnchor(
            height=int(height),
            block_hash=str(block_hash).lower().replace("0x", ""),
            epoch=int(epoch),
        )
        at_h = int(issued_at_height if issued_at_height is not None else height)
        payload = {
            "h": anchor.height,
            "hash": anchor.block_hash,
            "epoch": anchor.epoch,
            "issuer": str(issuer),
            "at": at_h,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        sigs: List[CommitteeSignature] = []
        for item in signatures or ():
            if isinstance(item, CommitteeSignature):
                sigs.append(item)
            else:
                sigs.append(CommitteeSignature.from_dict(item))
        return CheckpointCertificate(
            anchor=anchor,
            issuer=str(issuer),
            issued_at_height=at_h,
            digest=digest,
            signatures=tuple(sigs),
        )

    def with_signatures(
        self, signatures: Sequence[CommitteeSignature | Mapping[str, Any]]
    ) -> "CheckpointCertificate":
        return CheckpointCertificate.issue(
            height=self.anchor.height,
            block_hash=self.anchor.block_hash,
            epoch=self.anchor.epoch,
            issuer=self.issuer,
            issued_at_height=self.issued_at_height,
            signatures=signatures,
        )

    def verify_digest(self) -> bool:
        again = CheckpointCertificate.issue(
            height=self.anchor.height,
            block_hash=self.anchor.block_hash,
            epoch=self.anchor.epoch,
            issuer=self.issuer,
            issued_at_height=self.issued_at_height,
        )
        return again.digest == self.digest

    def verify_committee(self, committee: Optional[CommitteeConfig] = None) -> bool:
        """Verify Ed25519 quorum when committee configured.

        - No committee env and not required → True (digest-only mode).
        - Committee configured → need valid 2/3 (or threshold) signatures.
        - ``ABS_WS_COMMITTEE_REQUIRED`` without pubkeys → False.
        """
        cfg = committee
        if cfg is None:
            try:
                cfg = CommitteeConfig.from_env()
            except ValueError:
                return False
        if cfg is None:
            return not committee_required()
        return verify_committee_quorum(
            digest=self.digest,
            signatures=self.signatures,
            committee=cfg,
        )

    def to_dict(self) -> Mapping[str, Any]:
        out: dict[str, Any] = {
            "height": self.anchor.height,
            "block_hash": self.anchor.block_hash,
            "epoch": self.anchor.epoch,
            "issuer": self.issuer,
            "issued_at_height": self.issued_at_height,
            "digest": self.digest,
        }
        if self.signatures:
            out["signatures"] = [s.to_dict() for s in self.signatures]
        return out

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "CheckpointCertificate":
        """Rehydrate a certificate and require a matching digest (fail-closed)."""
        if not isinstance(data, Mapping):
            raise ValueError("checkpoint must be a mapping")
        raw_sigs = data.get("signatures") or ()
        sigs = [
            CommitteeSignature.from_dict(s) if isinstance(s, Mapping) else s
            for s in raw_sigs
        ]
        cert = CheckpointCertificate.issue(
            height=int(data["height"]),
            block_hash=str(data["block_hash"]),
            epoch=int(data.get("epoch") or 0),
            issuer=str(data.get("issuer") or "lab"),
            issued_at_height=int(
                data["issued_at_height"]
                if data.get("issued_at_height") is not None
                else data["height"]
            ),
            signatures=sigs,
        )
        expected = str(data.get("digest") or "").strip().lower()
        if not expected:
            raise ValueError("checkpoint digest missing")
        if expected != cert.digest:
            raise ValueError("checkpoint digest mismatch")
        if not cert.verify_digest():
            raise ValueError("checkpoint digest invalid")
        return cert

    def to_json(self) -> str:
        return json.dumps(dict(self.to_dict()), sort_keys=True)

    @staticmethod
    def from_json(raw: str) -> "CheckpointCertificate":
        return CheckpointCertificate.from_dict(json.loads(raw))
