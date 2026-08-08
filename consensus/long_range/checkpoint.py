"""Weak-subjectivity checkpoint certificates (ADR 0017 research)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from consensus.long_range.ports import WeakSubjectivityAnchor


@dataclass(frozen=True)
class CheckpointCertificate:
    """Signed-ish lab certificate binding a WS anchor.

    Phase-1 uses a deterministic digest (not BLS aggregate). Honesty: lab only.
    """

    anchor: WeakSubjectivityAnchor
    issuer: str
    issued_at_height: int
    digest: str

    @staticmethod
    def issue(
        *,
        height: int,
        block_hash: str,
        epoch: int = 0,
        issuer: str = "lab",
        issued_at_height: int | None = None,
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
        return CheckpointCertificate(
            anchor=anchor,
            issuer=str(issuer),
            issued_at_height=at_h,
            digest=digest,
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

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "height": self.anchor.height,
            "block_hash": self.anchor.block_hash,
            "epoch": self.anchor.epoch,
            "issuer": self.issuer,
            "issued_at_height": self.issued_at_height,
            "digest": self.digest,
        }
