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

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "CheckpointCertificate":
        """Rehydrate a certificate and re-verify digest (fail-closed)."""
        if not isinstance(data, Mapping):
            raise ValueError("checkpoint must be a mapping")
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
        )
        expected = str(data.get("digest") or "").lower()
        if expected and expected != cert.digest:
            raise ValueError("checkpoint digest mismatch")
        if not cert.verify_digest():
            raise ValueError("checkpoint digest invalid")
        return cert

    def to_json(self) -> str:
        return json.dumps(dict(self.to_dict()), sort_keys=True)

    @staticmethod
    def from_json(raw: str) -> "CheckpointCertificate":
        return CheckpointCertificate.from_dict(json.loads(raw))
